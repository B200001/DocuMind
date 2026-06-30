"""
POST /chat — streams agent events as Server-Sent Events.

Event types emitted:
  node_start   — a LangGraph node began executing
  tool_result  — a node completed with its output
  token        — one word of the draft answer
  citation     — the final citation list
  final        — the complete answer (stream is done after this)
  error        — an unhandled exception occurred

The LangGraph agent runs in a background async task. Its events are
bridged to the SSE generator via an asyncio.Queue, keeping the event
loop free while the synchronous LLM/Qdrant calls block in threads.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas import ChatRequest
from app.sse import (
    SSE_HEADERS,
    _make_serialisable,
    make_sse_response,
    sse_citation,
    sse_error_event,
    sse_final,
    sse_node_start,
    sse_token,
    sse_tool_result,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_DONE = object()   # sentinel: producer finished


@router.post("")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """Stream the agent's response as SSE. Connect with EventSource."""
    return make_sse_response(_agent_event_stream(request))


async def _agent_event_stream(request: ChatRequest) -> AsyncIterator[str]:
    """
    Drives the LangGraph agent and yields formatted SSE strings.

    Producer task: runs agent_astream(), puts events into a queue.
    Consumer (this generator): reads from queue, formats and yields SSE.
    """
    from documind_core.agent.graph import astream as agent_astream
    from documind_core.observability.langfuse_client import (
        flush, observe_turn, update_span,
    )

    queue: asyncio.Queue = asyncio.Queue()

    async def _producer() -> None:
        try:
            async for event in agent_astream(request.query):
                await queue.put(event)
        except Exception as exc:
            await queue.put(exc)
        finally:
            await queue.put(_DONE)

    producer_task = asyncio.create_task(_producer())

    final_draft: str = ""
    final_citations: list[str] = []
    final_loops: int = 0

    with observe_turn(request.query,
                      session_id=request.session_id,
                      user_id=request.user_id) as turn_span:
        try:
            while True:
                item = await queue.get()

                if isinstance(item, Exception):
                    logger.error("[chat] Agent error: %s", item)
                    yield sse_error_event(str(item))
                    break

                if item is _DONE:
                    break

                node_name = list(item.keys())[0]
                state_delta: dict = item.get(node_name) or {}

                yield sse_node_start(node_name)
                yield sse_tool_result(node_name, _extract_node_data(node_name, state_delta))

                if node_name == "generate":
                    draft = state_delta.get("draft", "")
                    words = draft.split(" ")
                    for i, word in enumerate(words):
                        text = word if i == len(words) - 1 else word + " "
                        yield sse_token(text)
                        await asyncio.sleep(0)  # yield to event loop
                    final_draft = draft
                    final_citations = state_delta.get("citations", [])

                elif node_name == "critic":
                    final_loops = state_delta.get("loops", 0)

            if final_citations:
                yield sse_citation(final_citations)

            yield sse_final(
                answer=final_draft,
                citations=final_citations,
                loops=final_loops,
            )

            update_span(output={"answer": final_draft[:500], "loops": final_loops})

        except asyncio.CancelledError:
            logger.info("[chat] Client disconnected.")
            producer_task.cancel()
            raise

        except Exception as exc:
            logger.exception("[chat] SSE stream error: %s", exc)
            yield sse_error_event(f"Server error: {exc}")

    try:
        flush()
    except Exception:
        pass

    await producer_task


def _extract_node_data(node_name: str, state_delta: dict) -> dict:
    """Extract a compact, frontend-friendly payload from each node's delta."""
    if node_name == "plan":
        return {
            "plan": state_delta.get("plan", ""),
            "sub_queries": state_delta.get("sub_queries", []),
        }
    if node_name == "retrieve":
        chunks = state_delta.get("retrieved", [])
        return {
            "chunk_count": len(chunks),
            "sources": [
                {
                    "chunk_id": getattr(c, "chunk_id", ""),
                    "source_ref": getattr(c, "source_ref", ""),
                    "score": round(getattr(c, "rrf_score", 0), 4),
                }
                for c in chunks[:5]
            ],
        }
    if node_name == "generate":
        return {
            "draft_length": len(state_delta.get("draft", "")),
            "citation_count": len(state_delta.get("citations", [])),
        }
    if node_name == "critic":
        critique = state_delta.get("critique") or {}
        return {
            "faithful": critique.get("faithful", True),
            "fully_cited": critique.get("fully_cited", True),
            "gaps": critique.get("gaps", []),
            "loops": state_delta.get("loops", 0),
        }
    return {}
