"""
OllamaEmbedder — wraps the Ollama embeddings endpoint for nomic-embed-text
(768-dim) with batching, retry, and a clear health check.

Usage
-----
    from documind_core.embeddings.ollama_embedder import OllamaEmbedder

    embedder = OllamaEmbedder()
    embedder.health_check()                       # raises if Ollama isn't up

    doc_vectors = embedder.embed_documents(["chunk 1 text", "chunk 2 text"])
    query_vector = embedder.embed_query("what is the refund policy?")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import ollama

from documind_core.config import get_settings

logger = logging.getLogger(__name__)

# nomic-embed-text always produces 768-dim vectors; used to validate
# responses and to fail fast if a different model is misconfigured.
EXPECTED_EMBED_DIM = 768

DEFAULT_BATCH_SIZE = 32
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0


# ─── Exceptions ────────────────────────────────────────────────────────────────

class OllamaUnavailableError(RuntimeError):
    """
    Raised when Ollama cannot be reached at all (connection refused/timeout).

    This is distinct from a model-not-found error: the server itself is
    down or unreachable at the configured base URL.
    """


class OllamaModelNotFoundError(RuntimeError):
    """
    Raised when Ollama is reachable but the configured embedding model
    has not been pulled (e.g. `ollama pull nomic-embed-text` was never run).
    """


class EmbeddingDimensionMismatchError(RuntimeError):
    """
    Raised when the embedding model returns vectors of an unexpected
    dimensionality — usually means OLLAMA_EMBED_MODEL was changed to a
    model that isn't actually nomic-embed-text (768-dim).
    """


# ─── Embedder ──────────────────────────────────────────────────────────────────

@dataclass
class OllamaEmbedder:
    """
    Thin, retrying wrapper around Ollama's embeddings endpoint.

    All configuration (base URL, model name) is read from
    documind_core.config.get_settings() by default, but can be overridden
    by passing explicit constructor arguments — handy for tests or for
    pointing at a second Ollama instance.
    """

    base_url: str | None = None
    model: str | None = None
    batch_size: int = DEFAULT_BATCH_SIZE
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS

    def __post_init__(self) -> None:
        settings = get_settings()
        self.base_url = self.base_url or settings.ollama_base_url
        self.model = self.model or settings.ollama_embed_model
        self._client = ollama.Client(host=self.base_url)

    # ─── Public API ────────────────────────────────────────────────────────

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of document chunks, batching requests and retrying
        transient failures.

        Parameters
        ----------
        texts:
            List of chunk texts to embed, in order. Empty strings are
            rejected up front (Ollama returns degenerate embeddings for
            them, which would silently corrupt the vector store).

        Returns
        -------
        list[list[float]]
            One 768-dim embedding vector per input text, in the same
            order as `texts`.

        Raises
        ------
        ValueError
            If `texts` is empty or contains a blank/whitespace-only entry.
        OllamaUnavailableError
            If Ollama cannot be reached after all retries.
        OllamaModelNotFoundError
            If the configured embedding model isn't pulled.
        EmbeddingDimensionMismatchError
            If returned vectors aren't 768-dim.
        """
        if not texts:
            return []

        for i, t in enumerate(texts):
            if not t or not t.strip():
                raise ValueError(f"texts[{i}] is empty or whitespace-only; cannot embed.")

        all_vectors: list[list[float]] = []
        for batch_start in range(0, len(texts), self.batch_size):
            batch = texts[batch_start : batch_start + self.batch_size]
            vectors = self._embed_batch_with_retry(batch)
            all_vectors.extend(vectors)

        return all_vectors

    def embed_query(self, text: str) -> list[float]:
        """
        Embed a single query string.

        Parameters
        ----------
        text:
            The query text to embed.

        Returns
        -------
        list[float]
            A single 768-dim embedding vector.

        Raises
        ------
        ValueError
            If `text` is empty or whitespace-only.
        OllamaUnavailableError, OllamaModelNotFoundError,
        EmbeddingDimensionMismatchError
            Same as embed_documents().
        """
        if not text or not text.strip():
            raise ValueError("text is empty or whitespace-only; cannot embed.")

        vectors = self._embed_batch_with_retry([text])
        return vectors[0]

    def health_check(self) -> None:
        """
        Verify Ollama is reachable AND the configured embedding model is
        available, raising a clear, specific error otherwise.

        Intended to be called once at application startup so failures
        surface immediately with an actionable message, rather than as
        a confusing stack trace deep inside an ingestion pipeline.

        Raises
        ------
        OllamaUnavailableError
            If the Ollama server cannot be reached at `self.base_url`.
        OllamaModelNotFoundError
            If Ollama is reachable but `self.model` has not been pulled.
        """
        try:
            response = self._client.list()
        except ConnectionError as exc:
            raise OllamaUnavailableError(
                f"Could not reach Ollama at '{self.base_url}'. "
                "Is Ollama running? Start it with `ollama serve`, or check "
                "OLLAMA_BASE_URL in your .env if it's running elsewhere."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected clearly
            raise OllamaUnavailableError(
                f"Unexpected error while checking Ollama at '{self.base_url}': {exc}"
            ) from exc

        available_models = {m.model for m in response.models if m.model}

        # Ollama model names are often suffixed with ":latest" — match
        # leniently so "nomic-embed-text" matches "nomic-embed-text:latest".
        configured = self.model
        is_available = configured in available_models or any(
            name.split(":")[0] == configured.split(":")[0] for name in available_models
        )

        if not is_available:
            raise OllamaModelNotFoundError(
                f"Embedding model '{configured}' is not available in Ollama. "
                f"Pull it with `ollama pull {configured}`. "
                f"Currently available models: {sorted(available_models) or '(none)'}"
            )

        logger.info("Ollama health check passed (model='%s', host='%s')", configured, self.base_url)

    # ─── Internal helpers ──────────────────────────────────────────────────

    def _embed_batch_with_retry(self, batch: list[str]) -> list[list[float]]:
        """
        Call Ollama for one batch, retrying transient failures
        (connection errors, momentary server hiccups) with exponential
        backoff. Non-transient failures — the model isn't pulled, or the
        model returns the wrong embedding dimension — are raised
        immediately since retrying cannot fix them.
        """
        last_exception: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                return self._embed_batch(batch)
            except (OllamaModelNotFoundError, EmbeddingDimensionMismatchError):
                # Non-transient — retrying won't help (wrong/missing model).
                raise
            except ollama.ResponseError as exc:
                message = str(exc).lower()
                if "not found" in message or "no such model" in message:
                    raise OllamaModelNotFoundError(
                        f"Embedding model '{self.model}' is not available in Ollama. "
                        f"Pull it with `ollama pull {self.model}`."
                    ) from exc
                # Other ResponseErrors (5xx, malformed request, etc.) are
                # treated as transient below.
                last_exception = exc
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt, exc)
                else:
                    logger.error("Ollama embed call failed after %d attempts: %s", self.max_retries, exc)
            except Exception as exc:  # noqa: BLE001 - connection errors, timeouts, etc.
                last_exception = exc
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt, exc)
                else:
                    logger.error("Ollama embed call failed after %d attempts: %s", self.max_retries, exc)

        raise OllamaUnavailableError(
            f"Failed to get embeddings from Ollama at '{self.base_url}' "
            f"after {self.max_retries} attempts. Last error: {last_exception}"
        ) from last_exception

    def _sleep_backoff(self, attempt: int, exc: Exception) -> None:
        """Sleep with exponential backoff and log the retry."""
        sleep_s = self.retry_backoff_seconds * (2 ** (attempt - 1))
        logger.warning(
            "Ollama embed call failed (attempt %d/%d): %s. Retrying in %.1fs...",
            attempt, self.max_retries, exc, sleep_s,
        )
        time.sleep(sleep_s)

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        """
        Single attempt at embedding one batch — no retry logic here.

        ConnectionError is intentionally left unwrapped so the retry loop
        in _embed_batch_with_retry can treat it as transient and retry.
        Only non-transient failures (model not found, wrong dimension)
        are converted to our specific exception types here.
        """
        from documind_core.observability.langfuse_client import (
            observe_embedding, update_generation, estimate_tokens,
        )
        label = "embed:query" if len(batch) == 1 else f"embed:documents({len(batch)})"
        total_input_tokens = sum(estimate_tokens(t) for t in batch)

        with observe_embedding(label, model=self.model, input_texts=batch):
            response = self._client.embed(model=self.model, input=batch)
            update_generation(
                output=f"<{len(batch)} vectors>",
                input_tokens=total_input_tokens,
            )

        vectors = list(response.embeddings)

        if not vectors:
            raise OllamaUnavailableError(
                f"Ollama returned no embeddings for a batch of {len(batch)} text(s). "
                "This usually indicates a server-side issue — check `ollama logs`."
            )

        for vec in vectors:
            if len(vec) != EXPECTED_EMBED_DIM:
                raise EmbeddingDimensionMismatchError(
                    f"Expected {EXPECTED_EMBED_DIM}-dim embeddings from model "
                    f"'{self.model}', got {len(vec)}-dim. Is OLLAMA_EMBED_MODEL "
                    "set to a non-nomic-embed-text model?"
                )

        return [list(v) for v in vectors]
