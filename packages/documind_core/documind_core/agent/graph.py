"""
LangGraph state machine for the documind agent.

GRAPH TOPOLOGY
--------------

    START
      │
    [plan]           ← decompose query into sub-queries
      │
    [retrieve]       ← hybrid_search + rerank for each sub-query
      │
    [generate]       ← write cited answer from numbered sources
      │
    [critic]         ← audit faithfulness + citation coverage
      │
      ├─ passes ──────────────────────────────────────────► [finalize] ─► END
      │
      └─ fails + loops < MAX ──► [retrieve] (refined query)
                                       │
                                    [generate]
                                       │
                                    [critic]
                                       ...
      └─ fails + loops >= MAX ─────────────────────────────► [finalize] ─► END


PUBLIC INTERFACE
----------------
    from documind_core.agent.graph import run, astream

    # Blocking
    state = run("what is the refund policy?")
    print(state["draft"])
    print(state["citations"])

    # Streaming — yields one dict per node as it completes
    async for event in astream("what is the refund policy?"):
        node_name = list(event.keys())[0]
        print(f"[{node_name}]", event)
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from langgraph.graph import END, START, StateGraph

from documind_core.agent.nodes import (
    critic_node,
    finalize_node,
    generate_node,
    plan_node,
    retrieve_node,
)
from documind_core.agent.state import AgentState
from documind_core.config import get_settings

logger = logging.getLogger(__name__)


# ─── Routing function ─────────────────────────────────────────────────────────

def _route_after_critic(state: AgentState) -> str:
    """
    Decide what to do after the critic runs.

    Returns "finalize" or "retrieve" — these map to node names in
    add_conditional_edges below.
    """
    settings = get_settings()
    critique = state.get("critique")
    loops = state.get("loops", 0)

    if critique is None:
        logger.warning("[route] No critique found — finalizing.")
        return "finalize"

    critic_passed = (
        critique.get("faithful", True)
        and critique.get("fully_cited", True)
        and not critique.get("gaps", [])
    )

    if critic_passed:
        logger.info("[route] Critic passed → finalize")
        return "finalize"

    if loops < settings.max_critic_loops:
        logger.info("[route] Critic failed (loop %d/%d) → retrieve again",
                    loops, settings.max_critic_loops)
        return "retrieve"

    logger.info("[route] Loop budget exhausted (%d/%d) → finalize",
                loops, settings.max_critic_loops)
    return "finalize"


# ─── Graph construction ───────────────────────────────────────────────────────

def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("plan",     plan_node)
    g.add_node("retrieve", retrieve_node)
    g.add_node("generate", generate_node)
    g.add_node("critic",   critic_node)
    g.add_node("finalize", finalize_node)

    g.add_edge(START,      "plan")
    g.add_edge("plan",     "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "critic")

    g.add_conditional_edges(
        "critic",
        _route_after_critic,
        {"finalize": "finalize", "retrieve": "retrieve"},
    )

    g.add_edge("finalize", END)
    return g


# Module-level singleton — compiled once, reused across all calls
_graph = _build_graph().compile()


# ─── Public interface ─────────────────────────────────────────────────────────

def run(query: str) -> dict:
    """
    Run the agent graph synchronously and return the final state dict.

    Returns AgentState with keys: draft, citations, critique, loops,
    retrieved, plan, sub_queries, query.
    """
    logger.info("[graph.run] Starting for query: %r", query)
    return _graph.invoke({
        "query": query,
        "plan": "",
        "sub_queries": [],
        "retrieved": [],
        "draft": "",
        "citations": [],
        "critique": None,
        "loops": 0,
    })


async def astream(query: str) -> AsyncIterator[dict]:
    """
    Run the agent graph asynchronously, yielding one event dict per node.

    Each yielded event: {node_name: {changed_state_keys...}}

    Example usage in a FastAPI SSE endpoint:
        async for event in astream(query):
            node = list(event.keys())[0]
            yield f"data: {json.dumps({'node': node, 'data': event[node]})}\n\n"
    """
    logger.info("[graph.astream] Starting for query: %r", query)
    async for event in _graph.astream(
        {
            "query": query,
            "plan": "",
            "sub_queries": [],
            "retrieved": [],
            "draft": "",
            "citations": [],
            "critique": None,
            "loops": 0,
        },
        stream_mode="updates",
    ):
        yield event
