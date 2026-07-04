"""
LLM-calling wrappers around the pure scoring functions in ragas_metrics.py.

Each function here makes one or more calls to the local Ollama LLM (via
ChatOllama) and/or the embedding model (via OllamaEmbedder), parses a
JSON response robustly (retrying on malformed output, same pattern as
documind_core.agent.nodes.critic_node), and hands the parsed data to the
corresponding pure function to compute the final score.

All three judge functions are independent of documind_core.agent — eval
scripts intentionally don't import agent internals, to keep the
evaluation harness decoupled from the production agent's implementation
details.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from documind_core.config import get_settings
from documind_core.embeddings.ollama_embedder import OllamaEmbedder
from documind_core.retrieval.hybrid import RetrievedChunk

from evaluation.ragas_metrics import (
    compute_answer_relevance,
    compute_context_precision,
    compute_faithfulness_score,
)

logger = logging.getLogger(__name__)

NUM_HYPOTHETICAL_QUESTIONS = 3
MAX_JSON_PARSE_ATTEMPTS = 3


# ─── Prompts ────────────────────────────────────────────────────────────────

FAITHFULNESS_PROMPT = """\
You are auditing an AI-generated answer for factual accuracy against its \
source context.

Question: {question}

Source context:
{context}

Answer to audit:
{answer}

Break the answer down into its individual atomic factual claims, then \
judge each claim as "supported" (true) only if the source context \
directly backs it up, or unsupported (false) otherwise.

Respond with ONLY a JSON object (no markdown fences, no explanation):
{{
  "claims": [
    {{"claim": "<a single factual claim from the answer>", "supported": <true|false>}},
    ...
  ]
}}

If the answer makes no factual claims at all (e.g. it says information is \
insufficient), respond with {{"claims": []}}.
"""

HYPOTHETICAL_QUESTIONS_PROMPT = """\
Given the answer below, write {n} different questions that this answer \
would be a good, direct response to. Each question should be phrased the \
way a real user would ask it.

Answer:
{answer}

Respond with ONLY a JSON object (no markdown fences, no explanation):
{{"questions": ["<question 1>", "<question 2>", ...]}}
"""

CONTEXT_RELEVANCE_PROMPT = """\
You are judging whether each retrieved passage below is relevant to \
answering the given question.

Question: {question}

Passages:
{passages}

For each passage, judge whether it contains information relevant to \
answering the question.

Respond with ONLY a JSON object (no markdown fences, no explanation):
{{"relevance": [<true|false>, <true|false>, ...]}}

The list must have exactly {n} entries, in the same order as the passages.
"""


# ─── JSON parsing helper (same robust pattern as agent/nodes.py) ─────────────

def _parse_json_from_llm(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM response:\n{text[:300]}")
    return json.loads(match.group())


def _invoke_json(llm: ChatOllama, prompt: str) -> dict:
    """Call the LLM and parse its JSON response, retrying on malformed output."""
    last_exc: Exception | None = None
    for attempt in range(1, MAX_JSON_PARSE_ATTEMPTS + 1):
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content if hasattr(response, "content") else str(response)
        try:
            return _parse_json_from_llm(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            last_exc = exc
            logger.warning("JSON parse attempt %d/%d failed: %s", attempt, MAX_JSON_PARSE_ATTEMPTS, exc)
    raise RuntimeError(f"LLM judge failed to return valid JSON after {MAX_JSON_PARSE_ATTEMPTS} attempts") from last_exc


def _llm() -> ChatOllama:
    s = get_settings()
    return ChatOllama(model=s.ollama_llm_model, base_url=s.ollama_base_url, temperature=0.0)


# ─── Judgment result shapes ─────────────────────────────────────────────────

@dataclass
class JudgeResult:
    score: float
    detail: dict


# ─── Public judge functions ─────────────────────────────────────────────────

def judge_faithfulness(question: str, context: str, answer: str) -> JudgeResult:
    """
    Score how well the answer's claims are supported by the context.

    Returns
    -------
    JudgeResult
        score: fraction of claims supported (see compute_faithfulness_score).
        detail: {"claims": [...]} — the raw per-claim judgments, useful for
            debugging low scores.
    """
    prompt = FAITHFULNESS_PROMPT.format(question=question, context=context, answer=answer)
    parsed = _invoke_json(_llm(), prompt)
    claims = parsed.get("claims", [])
    score = compute_faithfulness_score(claims)
    return JudgeResult(score=score, detail={"claims": claims})


def judge_answer_relevance(
    question: str,
    answer: str,
    embedder: OllamaEmbedder | None = None,
) -> JudgeResult:
    """
    Score how relevant the answer is to the question, via RAGAS's
    generate-hypothetical-questions + embedding-similarity method.

    Returns
    -------
    JudgeResult
        score: mean cosine similarity between the real question and N
            LLM-generated hypothetical questions the answer would suit.
        detail: {"generated_questions": [...]}
    """
    embedder = embedder or OllamaEmbedder()

    prompt = HYPOTHETICAL_QUESTIONS_PROMPT.format(answer=answer, n=NUM_HYPOTHETICAL_QUESTIONS)
    parsed = _invoke_json(_llm(), prompt)
    generated_questions = parsed.get("questions", [])

    if not generated_questions:
        return JudgeResult(score=0.0, detail={"generated_questions": []})

    original_embedding = embedder.embed_query(question)
    generated_embeddings = embedder.embed_documents(generated_questions)

    score = compute_answer_relevance(original_embedding, generated_embeddings)
    return JudgeResult(score=score, detail={"generated_questions": generated_questions})


def judge_context_precision(question: str, chunks: list[RetrievedChunk]) -> JudgeResult:
    """
    Score what fraction of the retrieved chunks (rank-weighted) are
    actually relevant to the question.

    Returns
    -------
    JudgeResult
        score: rank-weighted average precision (see compute_context_precision).
        detail: {"relevance_flags": [...]} — per-chunk true/false judgments.
    """
    if not chunks:
        return JudgeResult(score=0.0, detail={"relevance_flags": []})

    passages = "\n\n".join(f"[{i}] {c.text}" for i, c in enumerate(chunks, start=1))
    prompt = CONTEXT_RELEVANCE_PROMPT.format(question=question, passages=passages, n=len(chunks))
    parsed = _invoke_json(_llm(), prompt)
    flags = parsed.get("relevance", [])

    if len(flags) != len(chunks):
        logger.warning(
            "Context relevance judge returned %d flags for %d chunks — padding/truncating.",
            len(flags), len(chunks),
        )
        flags = (flags + [False] * len(chunks))[: len(chunks)]

    score = compute_context_precision([bool(f) for f in flags])
    return JudgeResult(score=score, detail={"relevance_flags": flags})
