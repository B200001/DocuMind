"""
LangGraph node functions — one function per node in the agent graph.

EACH NODE:
  - Receives the full AgentState dict.
  - Returns a dict with ONLY the keys it changed.
  - LangGraph merges that partial dict back into the state automatically.
  - Nodes must be pure functions of state (no side effects beyond logging).

NODE OVERVIEW
--------------
  plan      — LLM decomposes the query into sub-queries + a retrieval plan.
  retrieve  — Calls retrieve_and_rerank for each sub-query; deduplicates.
  generate  — LLM writes a cited answer from numbered sources.
  critic    — LLM audits the draft for faithfulness + citation coverage.
  finalize  — Passthrough: marks the answer as accepted (no-op node).

ROUTING (in graph.py):
  After critic: if faithful + fully_cited + no gaps → finalize
                elif loops < MAX_CRITIC_LOOPS → retrieve (refined query)
                else → finalize (best effort, loop budget exhausted)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from documind_core.agent.prompts import (
    CRITIC_PROMPT,
    GENERATE_PROMPT,
    PLAN_PROMPT,
    REFINE_QUERY_PROMPT,
)
from documind_core.agent.state import AgentState, CriticResult
from documind_core.config import get_settings
from documind_core.retrieval.hybrid import RetrievedChunk
from documind_core.retrieval.rerank import retrieve_and_rerank

logger = logging.getLogger(__name__)
from documind_core.observability.langfuse_client import (  # noqa: E402
    observe_node, observe_llm_call, update_span, update_generation, estimate_tokens,
)

# ─── LLM factory ──────────────────────────────────────────────────────────────

def _llm(temperature: float = 0.1) -> ChatOllama:
    """
    Return a ChatOllama instance pointed at settings.ollama_llm_model.
    Temperature 0.1 keeps outputs focused and reproducible.
    """
    s = get_settings()
    return ChatOllama(model=s.ollama_llm_model, base_url=s.ollama_base_url, temperature=temperature)


# ─── Formatting helpers ───────────────────────────────────────────────────────

def _build_sources_block(chunks: list[RetrievedChunk]) -> str:
    """
    Format retrieved chunks as a numbered source list for prompts.

    Example output:
        [1] (doc1 p.2 § Refund Policy)
        Full refunds are available within 30 days of purchase...

        [2] (doc1 p.3 § Shipping)
        Shipping costs are non-refundable...
    """
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(f"[{i}] ({chunk.source_ref})")
        lines.append(chunk.text.strip())
        lines.append("")   # blank line between sources
    return "\n".join(lines).strip()


def _extract_citations(draft: str, chunks: list[RetrievedChunk]) -> list[str]:
    """
    Scan the draft for [n] markers and return the corresponding source_ref
    strings. These become the formal citation list returned to the caller.
    """
    cited_indices = {int(m) for m in re.findall(r"\[(\d+)\]", draft)}
    citations = []
    for idx in sorted(cited_indices):
        if 1 <= idx <= len(chunks):
            citations.append(chunks[idx - 1].source_ref)
    return citations


def _parse_json_from_llm(text: str) -> dict[str, Any]:
    """
    Robustly extract JSON from an LLM response.

    Models sometimes wrap JSON in ```json ... ``` fences or add preamble
    text. This strips fences and finds the first {...} block.
    """
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response:\n{text[:300]}")
    return json.loads(match.group())


# ─── Nodes ────────────────────────────────────────────────────────────────────

def plan_node(state: AgentState) -> dict:
    """
    Decompose the user's query into a retrieval plan + sub-queries.

    Calls the LLM with PLAN_PROMPT and parses its JSON response.
    Falls back to a single sub-query equal to the original query if
    the LLM returns malformed JSON (resilient to model quirks).
    """
    logger.info("[plan] Decomposing query: %r", state["query"])

    prompt = PLAN_PROMPT.format(query=state["query"])
    s = get_settings()
    with observe_node("plan", input={"query": state["query"]}):
        with observe_llm_call("llm:plan", model=s.ollama_llm_model, prompt=prompt):
            response = _llm().invoke([HumanMessage(content=prompt)])
            raw = response.content if hasattr(response, "content") else str(response)
            update_generation(output=raw,
                              input_tokens=estimate_tokens(prompt),
                              output_tokens=estimate_tokens(raw))
    try:
        parsed = _parse_json_from_llm(raw)
        plan = parsed.get("plan", "Direct retrieval")
        sub_queries = parsed.get("sub_queries", [state["query"]])
        if not sub_queries:
            sub_queries = [state["query"]]
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("[plan] JSON parse failed (%s), falling back to original query.", exc)
        plan = "Direct retrieval (plan parse failed)"
        sub_queries = [state["query"]]

    logger.info("[plan] Plan: %r | Sub-queries: %s", plan, sub_queries)
    return {"plan": plan, "sub_queries": sub_queries}


def retrieve_node(state: AgentState) -> dict:
    """
    Run retrieve_and_rerank for each sub-query (or a refined query on
    subsequent loops), deduplicate by chunk_id, and return as a flat list.

    On loop > 0, the critic found gaps — we build a refined query from
    those gaps and retrieve again. New chunks are APPENDED to state["retrieved"]
    (via the Annotated[list, operator.add] reducer).
    """
    settings = get_settings()

    # On subsequent loops, ask the LLM for a refined query targeting gaps
    if state.get("loops", 0) > 0 and state.get("critique"):
        gaps = state["critique"].get("gaps", [])
        if gaps:
            gap_text = "\n".join(f"- {g}" for g in gaps)
            refine_prompt = REFINE_QUERY_PROMPT.format(
                gaps=gap_text, query=state["query"]
            )
            response = _llm().invoke([HumanMessage(content=refine_prompt)])
            refined = response.content.strip() if hasattr(response, "content") else state["query"]
            queries_to_run = [refined]
            logger.info("[retrieve] Refined query (loop %d): %r", state["loops"], refined)
        else:
            queries_to_run = state.get("sub_queries", [state["query"]])
    else:
        queries_to_run = state.get("sub_queries", [state["query"]])

    # Existing chunk_ids so we don't append duplicates
    existing_ids = {c.chunk_id for c in state.get("retrieved", [])}

    new_chunks: list[RetrievedChunk] = []
    for q in queries_to_run:
        logger.info("[retrieve] Querying: %r", q)
        try:
            hits = retrieve_and_rerank(query=q, top_n=settings.rerank_top_n)
            for h in hits:
                if h.chunk_id not in existing_ids:
                    new_chunks.append(h)
                    existing_ids.add(h.chunk_id)
        except Exception as exc:
            logger.warning("[retrieve] Sub-query %r failed: %s", q, exc)

    logger.info("[retrieve] Got %d new chunks (total will be %d)",
                len(new_chunks), len(state.get("retrieved", [])) + len(new_chunks))
    return {"retrieved": new_chunks}


def generate_node(state: AgentState) -> dict:
    """
    Write a grounded, cited answer using ONLY the retrieved sources.

    Builds a numbered source block from all retrieved chunks, injects it
    into GENERATE_PROMPT, and asks the LLM to cite every claim with [n].
    """
    chunks = state.get("retrieved", [])
    if not chunks:
        logger.warning("[generate] No retrieved chunks — returning insufficient context.")
        return {"draft": "Insufficient context to answer this question.", "citations": []}

    sources_block = _build_sources_block(chunks)
    prompt = GENERATE_PROMPT.format(query=state["query"], sources_block=sources_block)

    logger.info("[generate] Generating answer from %d sources (loop %d)",
                len(chunks), state.get("loops", 0))

    response = _llm(temperature=0.1).invoke([HumanMessage(content=prompt)])
    draft = response.content.strip() if hasattr(response, "content") else str(response)

    citations = _extract_citations(draft, chunks)
    logger.info("[generate] Draft length: %d chars | Citations: %s", len(draft), citations)

    return {"draft": draft, "citations": citations}


def critic_node(state: AgentState) -> dict:
    """
    Audit the draft for faithfulness and citation coverage.

    Retries up to 3 times on JSON parse failure. Defaults to "passes"
    on total failure so the graph doesn't get stuck.
    """
    chunks = state.get("retrieved", [])
    sources_block = _build_sources_block(chunks)
    prompt = CRITIC_PROMPT.format(
        query=state["query"],
        sources_block=sources_block,
        draft=state.get("draft", ""),
    )

    logger.info("[critic] Auditing draft (loop %d)", state.get("loops", 0))

    last_exc = None
    for attempt in range(1, 4):
        try:
            response = _llm(temperature=0.0).invoke([HumanMessage(content=prompt)])
            raw = response.content if hasattr(response, "content") else str(response)
            parsed = _parse_json_from_llm(raw)
            critique: CriticResult = {
                "faithful": bool(parsed.get("faithful", True)),
                "fully_cited": bool(parsed.get("fully_cited", True)),
                "gaps": [str(g) for g in parsed.get("gaps", [])],
            }
            logger.info("[critic] Verdict: %s", critique)
            return {"critique": critique, "loops": state.get("loops", 0) + 1}
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            last_exc = exc
            logger.warning("[critic] Attempt %d/3 JSON parse failed: %s", attempt, exc)

    logger.error("[critic] All parse attempts failed (%s). Defaulting to pass.", last_exc)
    return {
        "critique": {"faithful": True, "fully_cited": True, "gaps": []},
        "loops": state.get("loops", 0) + 1,
    }


def finalize_node(state: AgentState) -> dict:
    """
    No-op terminal node. Exists so the graph has a named final state
    that callers can identify in streamed events.
    """
    logger.info("[finalize] Answer accepted. Draft length: %d chars", len(state.get("draft", "")))
    return {}
