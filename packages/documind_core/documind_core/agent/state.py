"""
AgentState — the single shared data structure that flows through every
node in the LangGraph.

DESIGN NOTES
-------------
LangGraph passes state between nodes by MERGING return values. Each node
returns a dict with only the keys it touched; unchanged keys carry over
automatically. This means:

  - Simple fields (str, int, Optional) are REPLACED by the last write.
  - List fields annotated with `Annotated[list, operator.add]` are
    ACCUMULATED — each node's returned list is appended to the existing
    one. We use this for `retrieved` (chunks accumulate across retrieval
    loops) and `citations` (built up during generation).

All fields have defaults so the graph can be started with just {"query": "..."}.
"""

from __future__ import annotations

import operator
from typing import Annotated, Optional
from typing_extensions import TypedDict

from documind_core.retrieval.hybrid import RetrievedChunk


class CriticResult(TypedDict):
    """Structured output from the critic node — matches the Pydantic schema."""
    faithful: bool        # every claim is grounded in a provided source
    fully_cited: bool     # every claim carries at least one [n] citation
    gaps: list[str]       # questions the draft left unanswered


class AgentState(TypedDict):
    # ── Inputs ───────────────────────────────────────────────────────────────
    query: str                          # original user question (never mutated)

    # ── Planning ─────────────────────────────────────────────────────────────
    plan: str                           # one-sentence retrieval plan
    sub_queries: list[str]              # decomposed sub-questions for retrieval

    # ── Retrieval ────────────────────────────────────────────────────────────
    # Annotated[..., operator.add] means each node's list is APPENDED, not
    # replaced. This lets the retrieve node accumulate chunks across loops
    # (initial retrieval + refined retrieval on critic failure).
    retrieved: Annotated[list[RetrievedChunk], operator.add]

    # ── Generation ───────────────────────────────────────────────────────────
    draft: str                          # current generated answer
    citations: list[str]                # source_ref strings used in the draft

    # ── Critic loop ──────────────────────────────────────────────────────────
    critique: Optional[CriticResult]    # last critic output (None = not run yet)
    loops: int                          # how many critic→retrieve loops so far
