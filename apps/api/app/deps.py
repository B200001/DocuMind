"""
Dependency injection singletons for FastAPI.

All expensive objects (embedder, vector store) are created once during
lifespan startup and reused across every request via Depends().
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Populated during lifespan startup, read-only after that
_singletons: dict = {}


def init_singletons() -> None:
    """Initialise all singletons. Called once from lifespan."""
    from documind_core.embeddings.ollama_embedder import OllamaEmbedder
    from documind_core.vectorstore.qdrant_store import QdrantStore

    logger.info("[deps] Initialising singletons...")
    _singletons["embedder"] = OllamaEmbedder()
    logger.info("[deps] OllamaEmbedder ready.")
    _singletons["store"] = QdrantStore()
    logger.info("[deps] QdrantStore ready.")
    logger.info("[deps] All singletons initialised.")


def teardown_singletons() -> None:
    """Clean up on shutdown."""
    _singletons.clear()
    logger.info("[deps] Singletons cleared.")


def get_embedder():
    """Return the shared OllamaEmbedder instance."""
    return _singletons["embedder"]


def get_store():
    """Return the shared QdrantStore instance."""
    return _singletons["store"]
