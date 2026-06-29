"""
Reranker using BAAI/bge-reranker-base cross-encoder.

WHY A RERANKER?
----------------
Hybrid search (dense + sparse + RRF) retrieves a broad candidate set
(top-40 by default). It is fast but imprecise — it ranks by vector
similarity and keyword overlap, which misses subtle relevance signals.

A cross-encoder reranker fixes this: it looks at the (query, chunk) pair
TOGETHER through a transformer, scoring their relevance as a unit rather
than comparing them independently. This is much slower (no pre-computed
embeddings), but the quality jump is significant. The pattern is:

    hybrid_search(query, top_k=40)  <- broad, fast, imprecise
            |
       rerank(query, chunks)        <- narrow, slow, precise
            |
        top_n=8 results             <- what the agent actually reads

SINGLETON LOADING
-----------------
The cross-encoder is large (~280MB). Loading it on every call would make
the first request in each process take 5-10s. Instead, we load it once at
module level into a process-wide singleton (_reranker_instance), so the
first call to rerank() loads the model and all subsequent calls reuse it
instantly. The load itself is deferred to first use (lazy) so importing
this module at startup doesn't block until the model is actually needed.

FlagEmbedding vs sentence-transformers
---------------------------------------
Both can load BAAI/bge-reranker-base. FlagEmbedding's FlagReranker is
tried first (it has BGE-specific optimisations); if unavailable we fall
back to sentence_transformers.CrossEncoder (same model, same scores, just
a different Python wrapper). This makes the module resilient to either
package being missing or broken in a given environment.

Usage
-----
    from documind_core.retrieval.rerank import rerank, retrieve_and_rerank

    # Use reranker standalone:
    chunks = hybrid_search(query, top_k=40)
    top8   = rerank(query, chunks, top_n=8)

    # Or use the convenience one-liner:
    top8 = retrieve_and_rerank("what is the refund policy?")
"""

from __future__ import annotations

import logging
from typing import Optional

from documind_core.config import get_settings
from documind_core.retrieval.hybrid import RetrievedChunk, hybrid_search
from documind_core.embeddings.ollama_embedder import OllamaEmbedder
from documind_core.vectorstore.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


# ─── Singleton model handle ────────────────────────────────────────────────────

# _reranker_instance holds the loaded cross-encoder after first use.
# None means "not loaded yet" (lazy init, not "failed to load").
_reranker_instance = None


def _get_reranker():
    """
    Return the process-wide cross-encoder singleton, loading it on first call.

    We try FlagEmbedding first (BGE-optimised), then fall back to
    sentence-transformers CrossEncoder. Both produce identical scores for
    BAAI/bge-reranker-base — the wrapper differences are internal only.

    Raises
    ------
    ImportError
        If neither FlagEmbedding nor sentence-transformers is installed.
    """
    global _reranker_instance

    if _reranker_instance is not None:
        return _reranker_instance

    model_name = get_settings().reranker_model  # default: BAAI/bge-reranker-base
    logger.info("Loading reranker model '%s' (first call — this may take a moment)...", model_name)

    # Attempt 1: FlagEmbedding (preferred for BGE models)
    try:
        from FlagEmbedding import FlagReranker
        _reranker_instance = FlagReranker(model_name, use_fp16=True)
        # Smoke-test: XLMRobertaTokenizer dropped prepare_for_model in newer
        # transformers; catch it here so we fall back instead of dying at query time.
        _reranker_instance.compute_score([["test", "test"]], normalize=True)
        logger.info("Reranker loaded via FlagEmbedding.")
        return _reranker_instance
    except ImportError:
        logger.debug("FlagEmbedding not available, trying sentence-transformers.")
    except Exception as exc:
        logger.warning("FlagEmbedding failed to load reranker: %s. Trying sentence-transformers.", exc)
        _reranker_instance = None
    # Attempt 2: sentence-transformers CrossEncoder (universal fallback)
    try:
        from sentence_transformers import CrossEncoder
        _reranker_instance = CrossEncoder(model_name)
        logger.info("Reranker loaded via sentence-transformers CrossEncoder.")
        return _reranker_instance
    except ImportError as exc:
        raise ImportError(
            "Neither FlagEmbedding nor sentence-transformers is installed. "
            "Install at least one:\n"
            "  pip install FlagEmbedding\n"
            "  pip install sentence-transformers"
        ) from exc


def _compute_scores(reranker, query: str, texts: list[str]) -> list[float]:
    """
    Score (query, text) pairs using whichever reranker backend was loaded.

    FlagReranker and CrossEncoder have slightly different call conventions:
      - FlagReranker.compute_score([[query, text], ...])  -> list[float]
      - CrossEncoder.predict([(query, text), ...])         -> ndarray

    This function hides that difference so rerank() doesn't need to know
    which backend it's using.
    """
    pairs = [[query, t] for t in texts]

    # FlagReranker
    if hasattr(reranker, "compute_score"):
        scores = reranker.compute_score(pairs, normalize=True)
        # compute_score returns a plain float when len(pairs)==1
        if isinstance(scores, float):
            scores = [scores]
        return list(scores)

    # CrossEncoder (sentence-transformers)
    if hasattr(reranker, "predict"):
        import numpy as np
        scores = reranker.predict(pairs)
        # predict() returns an ndarray; normalise to [0,1] via sigmoid
        # so scores are comparable regardless of raw logit range.
        scores = 1.0 / (1.0 + np.exp(-scores))
        return scores.tolist()

    raise RuntimeError(
        f"Loaded reranker {type(reranker)} has neither compute_score nor predict. "
        "This is an unsupported backend."
    )


# ─── Public API ────────────────────────────────────────────────────────────────

def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: Optional[int] = None,
) -> list[RetrievedChunk]:
    """
    Score (query, chunk) pairs with a cross-encoder and return the top-N.

    Parameters
    ----------
    query:
        The original search query. The same string used in hybrid_search().
    chunks:
        Candidate chunks to rerank — typically the output of hybrid_search().
        Order doesn't matter; all are scored and re-sorted.
    top_n:
        How many to return after reranking. Defaults to settings.rerank_top_n
        (8 by default). Pass an explicit value to override per-call.

    Returns
    -------
    list[RetrievedChunk]
        The top_n highest-scoring chunks, sorted by cross-encoder score
        descending. Each chunk is a new frozen dataclass with the
        ``rrf_score`` field replaced by the cross-encoder relevance score
        (so callers always read from ``.rrf_score`` regardless of stage).

    Notes
    -----
    - If ``chunks`` is empty, returns [] immediately (no model load).
    - If ``top_n`` >= len(chunks), all chunks are returned (re-ordered).
    - The cross-encoder model is loaded lazily on first call and then
      reused for the lifetime of the process.
    """
    if not chunks:
        return []

    settings = get_settings()
    effective_top_n = top_n if top_n is not None else settings.rerank_top_n

    # Load (or reuse) the singleton cross-encoder
    reranker = _get_reranker()

    # Score all (query, chunk_text) pairs in a single batched forward pass.
    # Batching is important: it allows the model to process pairs in parallel
    # on GPU/MPS, or at least avoid Python-level loop overhead on CPU.
    texts = [c.text for c in chunks]
    scores = _compute_scores(reranker, query, texts)

    logger.debug(
        "rerank: scored %d chunks for query %r, keeping top %d",
        len(chunks), query[:50], effective_top_n,
    )

    # Pair each chunk with its score, sort descending, take top_n
    scored = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
    top = scored[:effective_top_n]

    # Return new RetrievedChunk objects with rrf_score replaced by the
    # cross-encoder score, so the caller always reads from .rrf_score
    # and never needs to know which stage produced which score.
    return [
        RetrievedChunk(
            chunk_id=c.chunk_id,
            doc_id=c.doc_id,
            rrf_score=float(score),   # cross-encoder score replaces RRF score
            text=c.text,
            page=c.page,
            section=c.section,
            source_ref=c.source_ref,
        )
        for score, c in top
    ]


def retrieve_and_rerank(query: str, top_n: Optional[int] = None, filter=None,
                         doc_id: Optional[str] = None, embedder=None, store=None) -> list[RetrievedChunk]:
    from documind_core.observability.langfuse_client import observe_retrieval, update_span
    from documind_core.config import get_settings
    settings = get_settings()
    effective_top_n = top_n if top_n is not None else settings.rerank_top_n

    with observe_retrieval(query, top_k=settings.retrieve_top_k):
        candidates = hybrid_search(query=query, filter=filter, doc_id=doc_id, embedder=embedder, store=store)
        results = rerank(query=query, chunks=candidates, top_n=effective_top_n)
        update_span(output={
            "candidates": len(candidates),
            "returned": len(results),
            "top_score": round(results[0].rrf_score, 4) if results else None,
        })
    return results

    # Step 2: precise reranking — narrows to rerank_top_n (default 8)
    return rerank(query=query, chunks=candidates, top_n=top_n)
