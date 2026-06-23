"""
hybrid_search(query, ...) — runs dense + sparse search in parallel,
then fuses the results with RRF into a single ranked list.

HOW HYBRID SEARCH WORKS
--------------------------
A query like "what is the refund policy?" is answered better by combining
two complementary retrieval strategies:

  1. DENSE search (semantic/embedding):
       "returns within 30 days" will match "refund policy" even though it
       uses different words — because the embedding captures MEANING.
       Good at: paraphrase matching, synonyms, conceptual similarity.
       Bad at: rare proper nouns, exact codes, very specific terms.

  2. SPARSE search (BM25 keyword):
       "refund" in the query will strongly match chunks that literally
       contain the word "refund". Good at: exact term matching, rare
       words, technical jargon.
       Bad at: vocabulary mismatch (query says "reimburse", doc says
       "refund").

Neither alone is best. Hybrid = run both in parallel, fuse with RRF.
The fusion step rewards chunks that score well in BOTH systems
(they're almost certainly relevant) while still surfacing strong
single-system matches.

PARALLELISM
-----------
Dense embedding (one Ollama call) and both Qdrant searches run with
ThreadPoolExecutor. The embedding call must finish first (we need the
vector before we can search), but the two Qdrant searches run in
parallel — halving this leg of latency vs. running them serially.

         embed_query()          <- must finish first (blocking)
              |
    ┌─────────┴─────────┐
    search_dense()   search_sparse()   <- run in parallel
    └─────────┬─────────┘
              |
            rrf()               <- fuse and re-rank
              |
        RetrievedChunk[]        <- returned to caller


USAGE
-----
    from documind_core.retrieval.hybrid import hybrid_search

    chunks = hybrid_search("what is the refund policy?", top_k=8)
    for c in chunks:
        print(c.score, c.chunk_id, c.text[:80])

    # With a doc_id filter (useful during evaluation or re-ranking):
    chunks = hybrid_search("refund", top_k=8, doc_id="abc123")
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

from qdrant_client import models as qdrant_models

from documind_core.config import get_settings
from documind_core.embeddings.ollama_embedder import OllamaEmbedder
from documind_core.ingestion.sparse_vectorizer import text_to_sparse_vector
from documind_core.retrieval.fusion import rrf
from documind_core.vectorstore.qdrant_store import QdrantStore, SearchHit

logger = logging.getLogger(__name__)


# ─── Output shape ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RetrievedChunk:
    """
    A single chunk returned by hybrid_search(), with its fused RRF score
    and all payload fields unpacked for direct use by the agent/eval layer.

    The ``rrf_score`` is NOT a probability or similarity percentage — it is
    the accumulated Reciprocal Rank Fusion score (roughly 0.01–0.05 range
    for top results). Higher = more relevant, but the absolute value is
    not meaningful on its own.

    The ``source_ref`` is a human-readable citation string the agent can
    include in its response, e.g. "handbook.pdf p.3 § Refund Policy".
    """

    chunk_id: str           # e.g. "abc123:7" — stable, deterministic
    doc_id: str
    rrf_score: float        # fused score from RRF (higher = more relevant)
    text: str               # raw chunk text — no DB join needed
    page: Optional[int]     # page number within the source document (if known)
    section: Optional[str]  # heading/section the chunk came from (if known)
    source_ref: str         # citation string: "doc_id p.N § Section"


# ─── Internal helpers ──────────────────────────────────────────────────────────

def _make_source_ref(hit: SearchHit) -> str:
    """
    Build a human-readable citation string from a SearchHit's payload.

    The agent layer includes this in its answer so users know where the
    information came from, without needing to look anything up separately.

    Examples:
        doc_id="abc123", page=3, section="Refund Policy"
            -> "abc123 p.3 § Refund Policy"
        doc_id="abc123", page=None, section=None
            -> "abc123"
    """
    ref = hit.doc_id
    if hit.page is not None:
        ref += f" p.{hit.page}"
    if hit.section:
        ref += f" § {hit.section}"
    return ref


def _hit_to_retrieved_chunk(hit: SearchHit, rrf_score: float) -> RetrievedChunk:
    """Map a raw SearchHit (from QdrantStore) to the public RetrievedChunk shape."""
    return RetrievedChunk(
        chunk_id=hit.chunk_id,
        doc_id=hit.doc_id,
        rrf_score=rrf_score,
        text=hit.text,
        page=hit.page,
        section=hit.section,
        source_ref=_make_source_ref(hit),
    )


# ─── Main entry point ──────────────────────────────────────────────────────────

def hybrid_search(
    query: str,
    top_k: Optional[int] = None,
    filter: Optional[qdrant_models.Filter] = None,
    doc_id: Optional[str] = None,
    rrf_k: int = 60,
    embedder: Optional[OllamaEmbedder] = None,
    store: Optional[QdrantStore] = None,
) -> list[RetrievedChunk]:
    """
    Dense + sparse hybrid search, fused with Reciprocal Rank Fusion.

    Parameters
    ----------
    query:
        The user's natural-language question or search string.
    top_k:
        Number of results to return after fusion. Defaults to
        ``settings.retrieve_top_k`` (40 by default). Each individual
        search (dense and sparse) retrieves this many candidates before
        fusion, so the fused output has at most this many results
        (but usually fewer if the two lists overlap heavily).
    filter:
        Optional pre-built Qdrant filter for advanced filtering (e.g.
        filtering by multiple doc_ids, by date range, etc.).
        If provided, ``doc_id`` is ignored.
    doc_id:
        Convenience shortcut: filter results to a single document.
        Ignored if ``filter`` is provided. Useful during evaluation
        (test retrieval against a specific document) or in agent steps
        where the document is already known.
    rrf_k:
        The RRF smoothing constant. Default 60 (from the original paper).
        You almost never need to change this.
    embedder:
        Optional OllamaEmbedder instance. Defaults to a new one using
        get_settings(). Pass your own for dependency injection in tests
        or if you want to reuse an already-warm embedder instance.
    store:
        Optional QdrantStore instance. Same rationale as ``embedder``.

    Returns
    -------
    list[RetrievedChunk]
        Chunks ranked by fused RRF score, best-first. Contains at most
        ``top_k`` results. May contain fewer if the collection has fewer
        matching chunks. Each chunk has its full text and metadata
        included — no further DB lookups needed by the caller.

    Raises
    ------
    ValueError
        If ``query`` is empty or whitespace-only.
    documind_core.embeddings.ollama_embedder.OllamaUnavailableError
        If Ollama is not running (propagated from OllamaEmbedder).
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty.")

    settings = get_settings()
    effective_top_k = top_k if top_k is not None else settings.retrieve_top_k

    # Lazily create dependencies (real by default, injectable for tests).
    embedder = embedder or OllamaEmbedder()
    store = store or QdrantStore()

    # ── Step 1: build both query vector forms ─────────────────────────────────
    # Dense embedding requires a network call (Ollama), done first,
    # synchronously. Sparse vectorization is pure local computation.
    logger.debug("hybrid_search: embedding query (%d chars)", len(query))
    dense_vector = embedder.embed_query(query)
    sparse_vector = text_to_sparse_vector(query)

    # ── Step 2: run dense and sparse searches in parallel ─────────────────────
    # Both searches hit Qdrant (network calls), so running them concurrently
    # with ThreadPoolExecutor halves this leg of latency.
    # QdrantClient is thread-safe (confirmed via concurrent testing).
    logger.debug("hybrid_search: searching dense + sparse in parallel (top_k=%d)", effective_top_k)

    def _dense():
        return store.search_dense(
            vector=dense_vector,
            k=effective_top_k,
            filter=filter,
            doc_id=doc_id,
        )

    def _sparse():
        return store.search_sparse(
            sparse=sparse_vector,
            k=effective_top_k,
            filter=filter,
            doc_id=doc_id,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_dense  = pool.submit(_dense)
        future_sparse = pool.submit(_sparse)

        # Collect errors without swallowing them
        search_errors: list[Exception] = []
        for future in as_completed([future_dense, future_sparse]):
            exc = future.exception()
            if exc is not None:
                search_errors.append(exc)

    if search_errors:
        raise search_errors[0]

    dense_hits  = future_dense.result()
    sparse_hits = future_sparse.result()

    logger.debug(
        "hybrid_search: dense=%d hits, sparse=%d hits",
        len(dense_hits), len(sparse_hits),
    )

    # ── Step 3: fuse with RRF ─────────────────────────────────────────────────
    # rrf() returns (chunk_id, score) pairs, best-first.
    fused: list[tuple[str, float]] = rrf(
        [dense_hits, sparse_hits],
        k=rrf_k,
    )

    # ── Step 4: build chunk_id -> SearchHit lookup for payload recovery ────────
    # RRF only keeps chunk_ids and scores — we need the original payload
    # (text, page, section). Both search results carry identical payloads
    # (stored once in Qdrant), so either is fine as a source. Dense hits
    # overwrite sparse hits for the same chunk_id as a minor tie-breaker.
    hit_by_chunk_id: dict[str, SearchHit] = {}
    for hit in sparse_hits:
        hit_by_chunk_id[hit.chunk_id] = hit
    for hit in dense_hits:
        hit_by_chunk_id[hit.chunk_id] = hit  # dense preferred as tie-breaker

    # ── Step 5: build RetrievedChunk list, capped at top_k ───────────────────
    results: list[RetrievedChunk] = []
    for chunk_id, score in fused[:effective_top_k]:
        hit = hit_by_chunk_id.get(chunk_id)
        if hit is None:
            # Defensive guard: should never happen since RRF only assigns
            # IDs it received from the search results.
            logger.warning(
                "hybrid_search: chunk_id '%s' in RRF output but not in hits — skipping",
                chunk_id,
            )
            continue
        results.append(_hit_to_retrieved_chunk(hit, rrf_score=score))

    logger.debug("hybrid_search: returning %d fused results", len(results))
    return results
