"""
End-to-end RAGAS-style evaluation: for every question in
evaluation/datasets/qa_pairs.jsonl, retrieve context, generate an answer,
then score it on faithfulness, answer relevance, and context precision
using the local Ollama LLM as judge. Pushes every score to Langfuse (one
trace per question) and prints a summary table.

USAGE
-----
    python -m evaluation.run_eval
    python -m evaluation.run_eval --limit 3      # quick smoke test
    python -m evaluation.run_eval --no-langfuse  # skip pushing scores

This is independent of documind_core.agent — it calls retrieve_and_rerank
and a local generation prompt directly, rather than running the full
plan/retrieve/generate/critic graph. That's a deliberate choice: this
script evaluates the RETRIEVAL + GENERATION quality in isolation, without
the critic's self-correction loop masking problems that pure retrieval-
and-generation would otherwise surface. If you want to evaluate the full
agent (including critic loops), point this script's generate_answer() at
documind_core.agent.graph.run() instead.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama

from documind_core.config import get_settings
from documind_core.embeddings.ollama_embedder import OllamaEmbedder
from documind_core.retrieval.hybrid import RetrievedChunk
from documind_core.retrieval.rerank import retrieve_and_rerank

from evaluation.llm_judge import judge_answer_relevance, judge_context_precision, judge_faithfulness
from evaluation.reporting import format_score, print_table
from evaluation.retrieval_eval import QAPair, load_qa_pairs

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


# ─── Generation (retrieval + a plain grounded-answer prompt) ──────────────────

GENERATE_PROMPT = """\
You are a precise question-answering assistant. Answer the user's question \
using ONLY the numbered sources provided below. Cite every claim with [n]. \
If the sources don't contain enough information, say so plainly.

Question: {question}

Numbered sources:
{sources_block}

Answer:"""


def _build_sources_block(chunks: list[RetrievedChunk]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(f"[{i}] ({chunk.source_ref})")
        lines.append(chunk.text.strip())
        lines.append("")
    return "\n".join(lines).strip()


def generate_answer(question: str, chunks: list[RetrievedChunk], llm: ChatOllama) -> str:
    """Retrieve-then-generate, using a minimal grounded prompt (see module docstring)."""
    if not chunks:
        return "Insufficient context to answer this question."
    prompt = GENERATE_PROMPT.format(question=question, sources_block=_build_sources_block(chunks))
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip() if hasattr(response, "content") else str(response)


# ─── Per-question result ───────────────────────────────────────────────────

@dataclass
class EvalResult:
    qa: QAPair
    answer: str
    context_chunk_count: int
    faithfulness: float
    answer_relevance: float
    context_precision: float
    latency_seconds: float
    error: str | None = None


# ─── Langfuse score pushing ─────────────────────────────────────────────────

def push_scores_to_langfuse(result: EvalResult) -> None:
    """
    Push one Langfuse trace per evaluated question, with all three scores
    attached. No-ops cleanly if Langfuse isn't configured (see
    documind_core.observability.langfuse_client's no-op fallback).
    """
    from documind_core.observability.langfuse_client import is_enabled

    if not is_enabled():
        return

    from documind_core.observability.langfuse_client import _client  # module-level real client

    trace_id = _client.create_trace_id(seed=result.qa.id)
    with _client.start_as_current_observation(
        name="eval:qa_pair",
        as_type="span",
        trace_context={"trace_id": trace_id},
        input={"question": result.qa.question},
        metadata={"qa_id": result.qa.id, "source_doc": result.qa.source_doc},
    ):
        _client.update_current_span(output={"answer": result.answer})
        _client.create_score(
            name="faithfulness", value=result.faithfulness, trace_id=trace_id, data_type="NUMERIC"
        )
        _client.create_score(
            name="answer_relevance", value=result.answer_relevance, trace_id=trace_id, data_type="NUMERIC"
        )
        _client.create_score(
            name="context_precision", value=result.context_precision, trace_id=trace_id, data_type="NUMERIC"
        )


# ─── Orchestration ──────────────────────────────────────────────────────────

def evaluate_one(qa: QAPair, llm: ChatOllama, embedder: OllamaEmbedder) -> EvalResult:
    start = time.monotonic()
    try:
        chunks = retrieve_and_rerank(qa.question)
        answer = generate_answer(qa.question, chunks, llm)
        context_text = "\n\n".join(c.text for c in chunks)

        faithfulness = judge_faithfulness(qa.question, context_text, answer).score
        relevance = judge_answer_relevance(qa.question, answer, embedder=embedder).score
        precision = judge_context_precision(qa.question, chunks).score

        return EvalResult(
            qa=qa,
            answer=answer,
            context_chunk_count=len(chunks),
            faithfulness=faithfulness,
            answer_relevance=relevance,
            context_precision=precision,
            latency_seconds=time.monotonic() - start,
        )
    except Exception as exc:
        logger.error("Evaluation failed for [%s]: %s", qa.id, exc)
        return EvalResult(
            qa=qa,
            answer="",
            context_chunk_count=0,
            faithfulness=0.0,
            answer_relevance=0.0,
            context_precision=0.0,
            latency_seconds=time.monotonic() - start,
            error=str(exc),
        )


def run_all(qa_pairs: list[QAPair], push_to_langfuse: bool = True) -> list[EvalResult]:
    llm = ChatOllama(model=get_settings().ollama_llm_model, base_url=get_settings().ollama_base_url, temperature=0.1)
    embedder = OllamaEmbedder()

    results: list[EvalResult] = []
    for i, qa in enumerate(qa_pairs, start=1):
        print(f"[{i}/{len(qa_pairs)}] {qa.id}: {qa.question}")
        result = evaluate_one(qa, llm, embedder)
        if result.error:
            print(f"    ERROR: {result.error}")
        else:
            print(
                f"    faithfulness={format_score(result.faithfulness)}  "
                f"relevance={format_score(result.answer_relevance)}  "
                f"context_precision={format_score(result.context_precision)}  "
                f"({result.latency_seconds:.1f}s)"
            )
        if push_to_langfuse and not result.error:
            try:
                push_scores_to_langfuse(result)
            except Exception as exc:
                logger.warning("Failed to push scores to Langfuse for [%s]: %s", qa.id, exc)
        results.append(result)

    return results


def print_summary(results: list[EvalResult]) -> None:
    successful = [r for r in results if r.error is None]
    failed = [r for r in results if r.error is not None]

    if not successful:
        print("\nNo questions completed successfully — nothing to summarize.")
        return

    n = len(successful)
    avg_faithfulness = sum(r.faithfulness for r in successful) / n
    avg_relevance = sum(r.answer_relevance for r in successful) / n
    avg_precision = sum(r.context_precision for r in successful) / n
    avg_latency = sum(r.latency_seconds for r in successful) / n

    headers = ["Metric", "Mean Score"]
    rows = [
        ["Faithfulness", format_score(avg_faithfulness)],
        ["Answer Relevance", format_score(avg_relevance)],
        ["Context Precision", format_score(avg_precision)],
    ]
    print_table(f"RAGAS-style Evaluation (n={n} questions)", headers, rows)
    print(f"Average latency per question: {avg_latency:.1f}s")

    print("\nLowest-scoring questions:")
    worst_faithfulness = min(successful, key=lambda r: r.faithfulness)
    print(f"  Faithfulness:       [{worst_faithfulness.qa.id}] {format_score(worst_faithfulness.faithfulness)} — {worst_faithfulness.qa.question}")
    worst_relevance = min(successful, key=lambda r: r.answer_relevance)
    print(f"  Answer Relevance:   [{worst_relevance.qa.id}] {format_score(worst_relevance.answer_relevance)} — {worst_relevance.qa.question}")
    worst_precision = min(successful, key=lambda r: r.context_precision)
    print(f"  Context Precision:  [{worst_precision.qa.id}] {format_score(worst_precision.context_precision)} — {worst_precision.qa.question}")

    if failed:
        print(f"\n{len(failed)} question(s) failed to evaluate:")
        for r in failed:
            print(f"  - [{r.qa.id}] {r.error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Only evaluate the first N questions.")
    parser.add_argument("--no-langfuse", action="store_true", help="Skip pushing scores to Langfuse.")
    args = parser.parse_args()

    qa_pairs = load_qa_pairs()
    if args.limit:
        qa_pairs = qa_pairs[: args.limit]

    print(f"Evaluating {len(qa_pairs)} questions from qa_pairs.jsonl...")
    results = run_all(qa_pairs, push_to_langfuse=not args.no_langfuse)
    print_summary(results)

    return 0 if all(r.error is None for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
