"""
Application settings loaded from the .env file (or environment variables).

Usage:
    from documind_core.config import get_settings

    s = get_settings()
    print(s.ollama_base_url)
"""

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from documind_core.paths import REPO_ROOT


class Settings(BaseSettings):
    """
    All values can be overridden by environment variables or the .env file.
    Variable names are case-insensitive.
    """

    model_config = SettingsConfigDict(
        # Walk up to repo root to find .env regardless of CWD
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # silently ignore unknown env vars
    )

    # ─── Ollama ───────────────────────────────────────────
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL of the running Ollama instance.",
    )
    ollama_llm_model: str = Field(
        default="llama3.1:8b",
        description="Ollama model tag used for generation.",
    )
    ollama_embed_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model tag used for embeddings.",
    )

    # ─── Qdrant ───────────────────────────────────────────
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="HTTP URL of the Qdrant instance.",
    )
    qdrant_collection: str = Field(
        default="documind",
        description="Qdrant collection name.",
    )

    # ─── Reranker ─────────────────────────────────────────
    reranker_model: str = Field(
        default="BAAI/bge-reranker-base",
        description="HuggingFace model ID for cross-encoder reranking.",
    )

    # ─── SQLite ───────────────────────────────────────────
    sqlite_url: str = Field(
        default="sqlite:///./data/documind.db",
        description="SQLAlchemy connection string for the SQLite database.",
    )

    # ─── Langfuse ─────────────────────────────────────────
    langfuse_host: str = Field(
        default="http://localhost:3000",
        description="URL of the Langfuse observability server.",
    )
    langfuse_public_key: str = Field(
        default="",
        description="Langfuse project public key.",
    )
    langfuse_secret_key: str = Field(
        default="",
        description="Langfuse project secret key.",
    )

    # ─── Retrieval Knobs ──────────────────────────────────
    max_critic_loops: int = Field(
        default=2,
        description="Maximum self-critique iterations the agent may run.",
    )
    retrieve_top_k: int = Field(
        default=40,
        description="Number of candidates to fetch from the vector store.",
    )
    rerank_top_n: int = Field(
        default=8,
        description="Number of candidates to keep after reranking.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.

    The cache is process-scoped; call get_settings.cache_clear() in
    tests if you need a fresh load after patching env vars.
    """
    return Settings()
