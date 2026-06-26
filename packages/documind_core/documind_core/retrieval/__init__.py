"""Retrieval: hybrid dense+sparse search, RRF fusion, and cross-encoder reranking."""

from documind_core.retrieval.fusion import rrf
from documind_core.retrieval.hybrid import hybrid_search, RetrievedChunk
from documind_core.retrieval.rerank import rerank, retrieve_and_rerank

__all__ = [
    "rrf",
    "hybrid_search",
    "RetrievedChunk",
    "rerank",
    "retrieve_and_rerank",
]
