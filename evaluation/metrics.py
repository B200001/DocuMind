"""
Pure information-retrieval metric functions: hit@k, MRR, nDCG@k.

Kept separate from retrieval_eval.py's I/O (loading data, calling the
retriever, querying the DB) so the math itself can be tested in isolation
with plain lists — no live Qdrant/Ollama/SQLite needed to verify these
are computed correctly.
"""

from __future__ import annotations

import math


def hit_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    1.0 if any relevant chunk appears in the top-k ranked results, else 0.0.

    Parameters
    ----------
    ranked_ids:
        Chunk IDs in ranked order, best first (e.g. from retrieve_and_rerank).
    relevant_ids:
        The set of chunk IDs considered ground-truth-correct for this query.
    k:
        Cutoff rank to consider.
    """
    if not relevant_ids:
        return 0.0
    top_k = set(ranked_ids[:k])
    return 1.0 if top_k & relevant_ids else 0.0


def reciprocal_rank(ranked_ids: list[str], relevant_ids: set[str]) -> float:
    """
    1 / rank of the FIRST relevant chunk in the ranked list (1-based rank).
    0.0 if no relevant chunk appears anywhere in the ranked list.

    This is the per-query value that gets averaged into Mean Reciprocal
    Rank (MRR) across the whole eval set.
    """
    if not relevant_ids:
        return 0.0
    for rank, chunk_id in enumerate(ranked_ids, start=1):
        if chunk_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain at rank k.

    Uses binary relevance (1.0 if a chunk_id is in relevant_ids, else 0.0).
    DCG@k   = sum_{i=1}^{k} rel_i / log2(i + 1)
    IDCG@k  = DCG@k of the ideal ranking (all relevant chunks first)
    nDCG@k  = DCG@k / IDCG@k   (0.0 if IDCG@k is 0, i.e. no relevant chunks)
    """
    if not relevant_ids:
        return 0.0

    dcg = 0.0
    for i, chunk_id in enumerate(ranked_ids[:k], start=1):
        relevance = 1.0 if chunk_id in relevant_ids else 0.0
        if relevance > 0:
            dcg += relevance / math.log2(i + 1)

    num_relevant_in_ideal = min(len(relevant_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, num_relevant_in_ideal + 1))

    if idcg == 0.0:
        return 0.0
    return dcg / idcg
