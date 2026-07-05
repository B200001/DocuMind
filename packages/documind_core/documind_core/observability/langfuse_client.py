"""
Langfuse observability client — one trace per chat turn, spans per agent
node, and generation records for every LLM call and embedding batch.

HOW LANGFUSE v4 WORKS (read this first)
-----------------------------------------
Langfuse v4 is built on top of OpenTelemetry (OTel). When you call
``lf.start_as_current_observation(name=..., as_type=...)``, it creates
an OTel span and sets it as the *current* span in the thread-local OTel
context. Any subsequent call to ``lf.start_as_current_observation(...)``
from the *same thread* will automatically nest under that span.

This means wiring is simple:

    with observe_turn(query) as turn:          # outer trace span
        with observe_node("plan") as node:     # nested span
            ...
            with observe_llm_call(...) as gen: # nested generation
                response = llm.invoke(...)
                gen.update(output=...)

No trace IDs need to be threaded through function arguments — OTel's
context propagation handles it automatically within the same thread.

NO-OP FALLBACK
---------------
If LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY is empty/absent, every
function and context manager in this module is replaced with a no-op
that returns a dummy object. The rest of the codebase never needs to
check whether observability is enabled — it just calls the helpers and
they do nothing when keys are missing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)


# ─── Client initialisation ────────────────────────────────────────────────────

def _build_client():
    """
    Build a real Langfuse client from settings, or return None if keys
    are absent. Called once at module load time.
    """
    try:
        from documind_core.config import get_settings
        s = get_settings()

        if not s.langfuse_public_key or not s.langfuse_secret_key:
            logger.info(
                "Langfuse keys not configured — observability running in no-op mode. "
                "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env to enable."
            )
            return None

        from langfuse import Langfuse
        # base_url (not the deprecated host=) so the configured URL always
        # wins over a stray LANGFUSE_BASE_URL exported in the environment.
        client = Langfuse(
            public_key=s.langfuse_public_key,
            secret_key=s.langfuse_secret_key,
            base_url=s.langfuse_host,
        )
        logger.info("Langfuse client initialised (host=%s).", s.langfuse_host)
        return client

    except Exception as exc:
        logger.warning("Failed to initialise Langfuse client: %s. Falling back to no-op.", exc)
        return None


# Module-level singleton — None means no-op mode, real client otherwise.
_client = _build_client()


def is_enabled() -> bool:
    """Return True if a real Langfuse client is active."""
    return _client is not None


def flush() -> None:
    """
    Flush all pending spans to Langfuse. Call at process shutdown or end
    of a batch job to ensure nothing is lost in the export buffer.
    """
    if _client is not None:
        _client.flush()


# ─── No-op sentinel ───────────────────────────────────────────────────────────

class _NoOpObs:
    """
    Returned by all helpers when Langfuse is not configured.
    Accepts any attribute access / method call silently so callers never
    need to check is_enabled() before calling .update() or .end().
    """
    trace_id = None
    id = None
    def update(self, **_):  pass
    def end(self, **_):     pass
    def __enter__(self):    return self
    def __exit__(self, *_): pass


_NOOP = _NoOpObs()


# ─── Core context managers ────────────────────────────────────────────────────

@contextmanager
def observe_turn(
    query: str,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Generator[Any, None, None]:
    """
    Open a top-level trace span for one complete chat turn.

    Wrap the entire agent.run() / agent.astream() call with this so that
    every span created inside (node spans, LLM generations, embeddings)
    automatically nests under this trace via OTel context propagation.

    Example
    -------
        with observe_turn(query, session_id="abc") as turn:
            state = run(query)
            turn.update(output=state["draft"])
        flush()   # at the end of the request
    """
    if _client is None:
        yield _NOOP
        return

    with _client.start_as_current_observation(
        name="chat-turn",
        as_type="span",
        input={"query": query},
        metadata={"session_id": session_id, "user_id": user_id},
    ) as span:
        try:
            yield span
        except Exception as exc:
            _client.update_current_span(level="ERROR", status_message=str(exc))
            raise


@contextmanager
def observe_node(
    node_name: str,
    input: Optional[dict] = None,
) -> Generator[Any, None, None]:
    """
    Open a span for one agent node (plan, retrieve, generate, critic, finalize).

    Must be called inside an active ``observe_turn`` context so the span
    nests correctly. Safe to call outside — becomes a root span if no
    parent context is active.

    Example
    -------
        with observe_node("plan", input={"query": q}) as span:
            result = do_plan(q)
            span.update(output=result)   # or use update_span()
    """
    if _client is None:
        yield _NOOP
        return

    with _client.start_as_current_observation(
        name=f"node:{node_name}",
        as_type="span",
        input=input,
    ) as span:
        try:
            yield span
        except Exception as exc:
            _client.update_current_span(level="ERROR", status_message=str(exc))
            raise


@contextmanager
def observe_llm_call(
    name: str,
    model: str,
    prompt: Optional[str] = None,
    temperature: float = 0.1,
) -> Generator[Any, None, None]:
    """
    Open a generation span for one LLM call.

    Records model name, prompt, and temperature. Call update_generation()
    inside the context (after the LLM responds) to add output + tokens.

    Example
    -------
        with observe_llm_call("llm:generate", model="llama3.1:8b", prompt=p) as gen:
            response = llm.invoke([HumanMessage(content=p)])
            update_generation(
                output=response.content,
                input_tokens=estimate_tokens(p),
                output_tokens=estimate_tokens(response.content),
            )
    """
    if _client is None:
        yield _NOOP
        return

    with _client.start_as_current_observation(
        name=name,
        as_type="generation",
        model=model,
        model_parameters={"temperature": temperature},
        input=prompt,
    ) as gen:
        try:
            yield gen
        except Exception as exc:
            _client.update_current_generation(level="ERROR", status_message=str(exc))
            raise


@contextmanager
def observe_embedding(
    name: str,
    model: str,
    input_texts: list[str],
) -> Generator[Any, None, None]:
    """
    Open an embedding span for one batch embed call.

    Example
    -------
        with observe_embedding("embed:query", model="nomic-embed-text",
                               input_texts=[query]):
            vectors = client.embed(model=model, input=[query]).embeddings
            update_generation(input_tokens=estimate_tokens(query))
    """
    if _client is None:
        yield _NOOP
        return

    with _client.start_as_current_observation(
        name=name,
        as_type="embedding",
        model=model,
        input=input_texts,
    ) as emb:
        try:
            yield emb
        except Exception as exc:
            _client.update_current_generation(level="ERROR", status_message=str(exc))
            raise


@contextmanager
def observe_retrieval(
    query: str,
    top_k: int,
) -> Generator[Any, None, None]:
    """
    Open a retriever span for one hybrid search + rerank pipeline call.

    Example
    -------
        with observe_retrieval(query, top_k=40) as ret:
            chunks = retrieve_and_rerank(query)
            update_span(output={"count": len(chunks)})
    """
    if _client is None:
        yield _NOOP
        return

    with _client.start_as_current_observation(
        name="retrieval:hybrid",
        as_type="retriever",
        input={"query": query, "top_k": top_k},
    ) as ret:
        try:
            yield ret
        except Exception as exc:
            _client.update_current_span(level="ERROR", status_message=str(exc))
            raise


# ─── Convenience update helpers ───────────────────────────────────────────────
# Call these inside the corresponding context manager to record output.

def update_span(output: Any = None, metadata: Optional[dict] = None) -> None:
    """Update the currently active span. Safe to call in no-op mode."""
    if _client is None:
        return
    kwargs: dict[str, Any] = {}
    if output is not None:
        kwargs["output"] = output
    if metadata is not None:
        kwargs["metadata"] = metadata
    _client.update_current_span(**kwargs)


def update_generation(
    output: Any = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> None:
    """Update the currently active generation span with output + token counts."""
    if _client is None:
        return
    kwargs: dict[str, Any] = {}
    if output is not None:
        kwargs["output"] = output
    if input_tokens is not None or output_tokens is not None:
        usage: dict[str, int] = {}
        if input_tokens is not None:
            usage["input"] = input_tokens
        if output_tokens is not None:
            usage["output"] = output_tokens
        kwargs["usage_details"] = usage
    if metadata is not None:
        kwargs["metadata"] = metadata
    _client.update_current_generation(**kwargs)


# ─── Token estimation ─────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    Rough token estimate: ~1 token per 4 characters.
    Used when Ollama doesn't return usage metadata (common with local models).
    """
    return max(1, len(text) // 4)
