"""
Retrieval evaluation: hit@k, MRR, and nDCG@k over documind's hybrid
retriever (retrieve_and_rerank), measured against evaluation/datasets/qa_pairs.jsonl.

USAGE
-----
    python -m evaluation.retrieval_eval

Prints a summary table and returns a non-zero exit code if any question's
ground-truth chunk could not be resolved in the database (usually means
scripts/seed_docs.py hasn't been run yet, or was run against a different
corpus than qa_pairs.jsonl expects).

HOW GROUND TRUTH IS RESOLVED
------------------------------
See evaluation/datasets/README.md for the full rationale. In short: each
qa_pairs.jsonl entry names a source_doc filename and a source_keyword
phrase rather than a literal chunk_id, because chunk_id is derived from
an absolute filesystem path that differs across machines. This script
resolves the *real* chunk_id(s) by querying the live Chunk table for
chunks whose document matches source_doc and whose text contains
source_keyword.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import select

from documind_core.models import Chunk, Document, get_session
from documind_core.retrieval.rerank import retrieve_and_rerank

from evaluation.metrics import hit_at_k, ndcg_at_k, reciprocal_rank
from evaluation.reporting import format_pct, format_score, print_table

QA_PAIRS_PATH = Path(__file__).parent / "datasets" / "qa_pairs.jsonl"
K_VALUES = [1, 3, 5, 10]
RETRIEVE_TOP_K = 10  # how many results to request from the retriever per query


@dataclass
class QAPair:
    id: str
    question: str
    expected_answer: str
    source_doc: str
    source_keyword: str


@dataclass
class QueryResult:
    qa: QAPair
    relevant_chunk_ids: set[str]
    ranked_chunk_ids: list[str]


def load_qa_pairs(path: Path = QA_PAIRS_PATH) -> list[QAPair]:
    """Load and parse every line of qa_pairs.jsonl."""
    pairs: list[QAPair] = []
    with open(path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
                pairs.append(
                    QAPair(
                        id=raw["id"],
                        question=raw["question"],
                        expected_answer=raw["expected_answer"],
                        source_doc=raw["source_doc"],
                        source_keyword=raw["source_keyword"],
                    )
                )
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_num}: malformed qa_pair entry: {exc}") from exc
    return pairs


def resolve_ground_truth(qa: QAPair, session) -> set[str]:
    """
    Find the real chunk_id(s) matching a qa_pair's source_doc + source_keyword
    against the live database. See the module docstring for why this is
    resolved dynamically rather than read from a hardcoded field.
    """
    documents = session.exec(
        select(Document).where(Document.source_path.like(f"%{qa.source_doc}"))
    ).all()

    if not documents:
        return set()

    doc_ids = [d.id for d in documents]
    chunks = session.exec(select(Chunk).where(Chunk.document_id.in_(doc_ids))).all()

    matching = {
        c.id for c in chunks if qa.source_keyword.lower() in c.text.lower()
    }
    return matching


def run_retrieval_eval(qa_pairs: list[QAPair]) -> tuple[list[QueryResult], list[str]]:
    """
    Run the retriever for every question and resolve ground truth for each.

    Returns
    -------
    (results, warnings):
        results contains one QueryResult per question that had resolvable
        ground truth; warnings lists human-readable messages for any
        question whose ground truth could not be resolved (skipped from
        the metric computation, since a question with no known-correct
        chunk can't meaningfully contribute to hit@k/MRR/nDCG).
    """
    results: list[QueryResult] = []
    warnings: list[str] = []

    with get_session() as session:
        for qa in qa_pairs:
            relevant = resolve_ground_truth(qa, session)
            if not relevant:
                warnings.append(
                    f"[{qa.id}] Could not resolve ground truth for source_doc="
                    f"'{qa.source_doc}' keyword='{qa.source_keyword}'. "
                    "Has scripts/seed_docs.py been run? Skipping this question."
                )
                continue

            hits = retrieve_and_rerank(qa.question, top_n=RETRIEVE_TOP_K)
            ranked_ids = [h.chunk_id for h in hits]

            results.append(
                QueryResult(qa=qa, relevant_chunk_ids=relevant, ranked_chunk_ids=ranked_ids)
            )

    return results, warnings


def summarize(results: list[QueryResult]) -> dict:
    """Aggregate per-query metrics into mean values across the whole eval set."""
    n = len(results)
    if n == 0:
        return {"n": 0}

    hit_rates = {k: 0.0 for k in K_VALUES}
    ndcgs = {k: 0.0 for k in K_VALUES}
    rr_sum = 0.0

    for r in results:
        for k in K_VALUES:
            hit_rates[k] += hit_at_k(r.ranked_chunk_ids, r.relevant_chunk_ids, k)
            ndcgs[k] += ndcg_at_k(r.ranked_chunk_ids, r.relevant_chunk_ids, k)
        rr_sum += reciprocal_rank(r.ranked_chunk_ids, r.relevant_chunk_ids)

    return {
        "n": n,
        "hit_rate": {k: v / n for k, v in hit_rates.items()},
        "ndcg": {k: v / n for k, v in ndcgs.items()},
        "mrr": rr_sum / n,
    }


def print_summary(summary: dict, warnings: list[str]) -> None:
    if summary["n"] == 0:
        print("No questions had resolvable ground truth — nothing to evaluate.")
        return

    headers = ["Metric"] + [f"k={k}" for k in K_VALUES]
    rows = [
        ["Hit Rate"] + [format_pct(summary["hit_rate"][k]) for k in K_VALUES],
        ["nDCG"] + [format_score(summary["ndcg"][k]) for k in K_VALUES],
    ]
    print_table(f"Retrieval Metrics (n={summary['n']} questions)", headers, rows)
    print(f"MRR: {format_score(summary['mrr'])}")

    if warnings:
        print(f"\n{len(warnings)} question(s) skipped:")
        for w in warnings:
            print(f"  - {w}")


def main() -> int:
    qa_pairs = load_qa_pairs()
    print(f"Loaded {len(qa_pairs)} QA pairs from {QA_PAIRS_PATH}")

    results, warnings = run_retrieval_eval(qa_pairs)
    summary = summarize(results)
    print_summary(summary, warnings)

    if warnings:
        print(
            "\nSome questions were skipped due to unresolvable ground truth. "
            "Run `python scripts/seed_docs.py` first if you haven't already."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
