"""
Server-Sent Events (SSE) helpers.

SSE format: each event is `data: {...}\n\n` over text/event-stream.

X-Accel-Buffering: no  — tells nginx not to buffer; required for real-time streaming.
Cache-Control: no-cache — same for Varnish and other HTTP caches.

If the generator raises, sse_error_event() emits a final error event
before closing so the frontend shows an error rather than a hung spinner.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",   # critical: stops nginx buffering the stream
}


def sse_event(type: str, **payload: Any) -> str:
    """Format one SSE event: `data: {"type": "...", ...}\n\n`"""
    data = json.dumps({"type": type, **payload})
    return f"data: {data}\n\n"


def sse_error_event(message: str) -> str:
    """Format a terminal error event."""
    return sse_event("error", message=message)


def sse_node_start(node: str) -> str:
    return sse_event("node_start", node=node)


def sse_tool_result(node: str, data: Any) -> str:
    try:
        safe_data = _make_serialisable(data)
    except Exception:
        safe_data = str(data)
    return sse_event("tool_result", node=node, data=safe_data)


def sse_token(text: str) -> str:
    return sse_event("token", text=text)


def sse_citation(citations: list[str]) -> str:
    return sse_event("citation", citations=citations)


def sse_final(answer: str, citations: list[str], loops: int) -> str:
    return sse_event("final", answer=answer, citations=citations, loops=loops)


def make_sse_response(generator: AsyncIterator[str]) -> StreamingResponse:
    """Wrap an async string generator in a StreamingResponse with SSE headers."""
    return StreamingResponse(
        content=generator,
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


def _make_serialisable(obj: Any) -> Any:
    """Recursively convert dataclasses, dicts, lists to JSON-safe form."""
    import dataclasses
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serialisable(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)
