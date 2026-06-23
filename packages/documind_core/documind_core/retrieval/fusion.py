"""
Reciprocal Rank Fusion (RRF) — fuses multiple ranked result lists into one.

WHAT IS RRF AND WHY DO WE NEED IT?
-------------------------------------
When you run a hybrid search (dense vector search + sparse keyword search),
you end up with TWO separate ranked lists of results. The problem: a chunk
that ranks #1 in the sparse list might rank #15 in the dense list. How do
you combine them fairly into a single ordered list?

Naive approaches fail:
  - Adding raw scores directly is unfair because dense scores (cosine,
    range 0-1) and sparse scores (BM25-style, unbounded) live on totally
    different scales.
  - Just concatenating and deduplicating loses ranking information.

RRF solves this cleanly:
  - Each result's RANK in each list (1st place, 2nd place, ...) is turned
    into a contribution score using: 1 / (k + rank)
  - A result that shows up in BOTH lists accumulates contributions from both.
  - A result that only shows up in one list only gets one contribution.
  - Results that show up near the top of multiple lists naturally float
    to the top of the fused list.

The k parameter (typically 60) is a smoothing constant that prevents results
ranked #1 from dominating too heavily. At k=60, rank 1 gives 1/61 ≈ 0.016,
rank 10 gives 1/70 ≈ 0.014 — so top-ranked results still matter, but not
overwhelmingly so.

WHY k=60?
---------
This is the value from the original RRF paper (Cormack et al., 2009). It
was empirically derived across many retrieval benchmarks and has remained
the standard default. Nothing magic about it — it just works well in practice.

USAGE
-----
    from documind_core.retrieval.fusion import rrf

    dense_hits = store.search_dense(vector, k=40)   # list of SearchHit
    sparse_hits = store.search_sparse(sparse, k=40) # list of SearchHit

    fused = rrf([dense_hits, sparse_hits], k=60)
    # Returns list of (chunk_id, rrf_score) tuples, best-first.
"""

from __future__ import annotations


def rrf(
    result_lists: list[list],
    k: int = 60,
    id_fn=None,
) -> list[tuple[str, float]]:
    """
    Reciprocal Rank Fusion across any number of ranked result lists.

    Parameters
    ----------
    result_lists:
        A list of ranked lists. Each inner list contains objects that
        have a ``chunk_id`` attribute (e.g. SearchHit from qdrant_store),
        OR arbitrary objects if you supply ``id_fn``. Order within each
        inner list matters — first item = rank 1, second = rank 2, etc.
        Lists can overlap (same chunk_id appearing in multiple lists) or
        have different lengths. Empty lists are skipped harmlessly.

    k:
        The RRF smoothing constant. The original paper recommends 60.
        Larger values flatten the score distribution (make ranking less
        decisive); smaller values make top-ranked items more dominant.

    id_fn:
        Optional callable: id_fn(item) -> str, used to extract the
        unique identifier from each result object. Defaults to accessing
        ``item.chunk_id``. Pass a custom lambda if your result objects
        use a different field name (useful in tests and eval scripts).

    Returns
    -------
    list[tuple[str, float]]
        ``[(chunk_id, rrf_score), ...]`` sorted by rrf_score descending.
        A chunk_id that appeared in multiple input lists accumulates
        contributions from each, so cross-list consensus floats to the top.

    Examples
    --------
    Fusing two lists where "C" appears in both:

        list1 = [hit("A", 0.9), hit("C", 0.7), hit("B", 0.5)]
        list2 = [hit("C", 1.1), hit("D", 0.8), hit("E", 0.3)]

        rrf([list1, list2], k=60)
        # "C" rank 2 in list1 (1/62) + rank 1 in list2 (1/61) = 0.0325
        # "A" rank 1 in list1 only (1/61)                      = 0.0164
        # "D" rank 2 in list2 only (1/62)                      = 0.0161
        # -> [("C", 0.0325), ("A", 0.0164), ("D", 0.0161), ...]
    """
    # Default: extract chunk_id attribute from SearchHit-style objects
    if id_fn is None:
        id_fn = lambda item: item.chunk_id  # noqa: E731

    # Accumulate RRF contributions.
    # Key: chunk_id string. Value: running sum of 1/(k+rank) across all lists.
    scores: dict[str, float] = {}

    for ranked_list in result_lists:
        for rank_zero_based, item in enumerate(ranked_list):
            chunk_id = id_fn(item)
            rank = rank_zero_based + 1           # RRF uses 1-based rank
            contribution = 1.0 / (k + rank)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + contribution

    # Sort by accumulated score, best first
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
