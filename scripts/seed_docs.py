#!/usr/bin/env python3
"""
Ingest the sample corpus in evaluation/datasets/corpus/ into documind, so
that evaluation/retrieval_eval.py and evaluation/run_eval.py have real,
searchable data to evaluate against.

USAGE
-----
    python scripts/seed_docs.py

Requires Ollama and Qdrant to be running (see docker-compose.yml / `make up`
and `./scripts/pull_models.sh`), since ingestion computes real embeddings.

This is idempotent: documind_core.ingestion.pipeline.ingest_document()
uses a deterministic doc_id derived from each file's path, so re-running
this script re-ingests (delete-then-upsert) rather than duplicating.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "evaluation" / "datasets" / "corpus"

sys.path.insert(0, str(REPO_ROOT / "packages" / "documind_core"))


def main() -> int:
    from documind_core.ingestion.pipeline import IngestionError, ingest_document
    from documind_core.models import create_db_and_tables

    if not CORPUS_DIR.exists():
        print(f"Corpus directory not found: {CORPUS_DIR}")
        return 1

    corpus_files = sorted(CORPUS_DIR.glob("*.md"))
    if not corpus_files:
        print(f"No .md files found in {CORPUS_DIR}")
        return 1

    print(f"Found {len(corpus_files)} corpus file(s) in {CORPUS_DIR}")
    print("Ensuring database tables exist...")
    create_db_and_tables()

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    for path in corpus_files:
        print(f"\nIngesting {path.name}...")
        try:
            result = ingest_document(str(path))
            print(
                f"  -> doc_id={result.doc_id}  status={result.status.value}  "
                f"chunks={result.chunk_count}  pages={result.page_count}"
            )
            succeeded.append(path.name)
        except IngestionError as exc:
            print(f"  -> FAILED: {exc}")
            failed.append((path.name, str(exc)))

    print("\n" + "=" * 60)
    print(f"Seeding complete: {len(succeeded)} succeeded, {len(failed)} failed")
    print("=" * 60)

    if succeeded:
        print("\nSucceeded:")
        for name in succeeded:
            print(f"  - {name}")

    if failed:
        print("\nFailed:")
        for name, error in failed:
            print(f"  - {name}: {error}")
        print(
            "\nCommon causes: Ollama isn't running (`ollama serve`), the "
            "embedding model isn't pulled (`./scripts/pull_models.sh`), or "
            "Qdrant isn't running (`make up`)."
        )
        return 1

    print(
        f"\nAll {len(succeeded)} document(s) ingested successfully. "
        "You can now run:\n"
        "  python -m evaluation.retrieval_eval\n"
        "  python -m evaluation.run_eval"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
