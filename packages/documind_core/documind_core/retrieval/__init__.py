"""Retrieval: hybrid dense+sparse search with RRF fusion."""

from documind_core.retrieval.fusion import rrf
from documind_core.retrieval.hybrid import hybrid_search, RetrievedChunk

__all__ = ["rrf", "hybrid_search", "RetrievedChunk"]
