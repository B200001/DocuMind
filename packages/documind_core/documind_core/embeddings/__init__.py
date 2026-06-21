"""Embedding model wrappers."""

from documind_core.embeddings.ollama_embedder import (
    OllamaEmbedder,
    OllamaUnavailableError,
    OllamaModelNotFoundError,
    EmbeddingDimensionMismatchError,
)

__all__ = [
    "OllamaEmbedder",
    "OllamaUnavailableError",
    "OllamaModelNotFoundError",
    "EmbeddingDimensionMismatchError",
]
