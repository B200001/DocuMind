"""
ingest_document(path) — the main entry point that turns a raw file on disk
into searchable chunks in Qdrant, while keeping SQLite (Document, Chunk,
Job tables) in sync as a readable record of what happened.

WHAT THIS FILE DOES, IN PLAIN ENGLISH
----------------------------------------
Think of ingesting a document as an assembly line with 5 stations:

    1. LOAD     — read the raw file (PDF/DOCX/HTML/Markdown) into plain
                  text sections, using documind_core.loaders.
    2. CHUNK    — break those sections into ~512-token pieces, using
                  documind_core.chunking.
    3. EMBED    — turn each chunk's text into two kinds of vectors:
                    - a "dense" vector (captures MEANING, via Ollama)
                    - a "sparse" vector (captures EXACT WORDS, via our
                      own simple BM25-style term-frequency counter)
    4. STORE    — save both vectors + the raw text into Qdrant, AND save
                  lightweight rows into SQLite so the app can list
                  documents/chunks without re-querying Qdrant.
    5. FINISH   — mark the Job (and Document) as "ready", or "failed"
                  with an error message if anything went wrong along
                  the way.

WHY THIS IS IDEMPOTENT (safe to re-run on the same file)
----------------------------------------------------------
Three things work together to make re-ingesting the SAME file safe:

  a) doc_id is a HASH of the file's absolute path, not a random UUID.
     -> Running ingest_document() twice on the same path always reuses
        the same Document row instead of creating a duplicate.

  b) chunk_id is f"{doc_id}:{ordinal}" (deterministic, from the chunker).
     -> Chunk N of a document always gets the same ID across re-runs.

  c) Before writing NEW chunks, we DELETE all OLD chunks for this doc_id
     — both in Qdrant (QdrantStore.delete_by_doc) and in SQLite (Chunk
     rows) — and then re-insert fresh ones. This "delete-then-upsert"
     pattern means re-ingesting a document that shrank (fewer chunks
     than before) won't leave orphaned old chunks behind, and re-
     ingesting an unchanged document just replaces everything with an
     identical copy (a harmless no-op in effect).

Usage
-----
    from documind_core.ingestion.pipeline import ingest_document

    result = ingest_document("/data/uploads/handbook.pdf")
    print(result.doc_id, result.chunk_count, result.status)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import select

from documind_core.chunking.chunker import chunk_document, ChunkRecord
from documind_core.embeddings.ollama_embedder import OllamaEmbedder
from documind_core.ingestion.sparse_vectorizer import text_to_sparse_vector
from documind_core.loaders.registry import load_document
from documind_core.models import (
    Chunk,
    Document,
    DocumentStatus,
    Job,
    JobStatus,
    get_session,
)
from documind_core.vectorstore.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


# ─── Result shape returned to callers ──────────────────────────────────────────

@dataclass
class IngestResult:
    """
    Summary returned by ingest_document() once it finishes (successfully
    or not). Callers — e.g. an API endpoint — use this to tell the user
    what happened without needing to query the database themselves.
    """

    doc_id: str
    job_id: str
    status: DocumentStatus          # READY if successful, FAILED if not
    chunk_count: int
    page_count: Optional[int]
    error: Optional[str] = None     # populated only when status == FAILED


# ─── Exceptions ────────────────────────────────────────────────────────────────

class IngestionError(RuntimeError):
    """
    Raised when ingestion fails. The Job/Document rows are already marked
    FAILED with the error message by the time this is raised, so callers
    can catch it, log it, and move on — the database is left in a clean,
    inspectable state either way.
    """


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _doc_id_for_path(path: Path) -> str:
    """
    Turn a file path into a short, stable, deterministic ID.

    We hash the resolved (absolute) path so that:
      - The SAME file always gets the SAME doc_id, every time we ingest it.
      - Re-running ingest_document() on that file UPDATES the existing
        Document row instead of creating a brand new one.

    We use the first 24 hex characters of a SHA-256 hash — short enough
    to be a friendly ID, long enough that two different paths colliding
    is astronomically unlikely.
    """
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return digest[:24]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Main pipeline ──────────────────────────────────────────────────────────────

def ingest_document(
    path: str | Path,
    embedder: Optional[OllamaEmbedder] = None,
    store: Optional[QdrantStore] = None,
) -> IngestResult:
    """
    Ingest a single document end-to-end: load -> chunk -> embed -> store.

    Parameters
    ----------
    path:
        Path to the file on disk (PDF, DOCX, HTML, or Markdown — anything
        documind_core.loaders.load_document() supports).
    embedder:
        Optional OllamaEmbedder instance. If not provided, a new one is
        created using settings from get_settings(). Passing your own is
        mainly useful for tests (e.g. injecting a fake embedder).
    store:
        Optional QdrantStore instance. Same idea as `embedder` — defaults
        to a real one, but can be swapped out for tests.

    Returns
    -------
    IngestResult
        A summary of what happened: doc_id, job_id, final status, how
        many chunks were created, and the page count (if known). If
        ingestion failed, `status` is FAILED and `error` holds the
        exception message — IngestionError is also raised in that case.

    Raises
    ------
    IngestionError
        If loading, chunking, embedding, or storing fails for any reason.
        The underlying SQLite rows (Document, Job) are marked FAILED
        with the error message BEFORE this is raised, so the failure
        is always recorded, never silent.
    """
    resolved_path = Path(path).resolve()
    doc_id = _doc_id_for_path(resolved_path)

    # Lazily create real dependencies if the caller didn't inject test doubles.
    embedder = embedder or OllamaEmbedder()
    store = store or QdrantStore()

    with get_session() as session:
        # ── STEP 0: set up (or reuse) the Document + Job rows ──────────────
        # This runs BEFORE any real work, so that even if loading the file
        # crashes immediately, we still have a Job row recording "this was
        # attempted and here's why it failed."
        document = _get_or_create_document(session, doc_id, resolved_path)
        job = _create_job(session, document.id)

        try:
            # ── STEP 1: LOAD ─────────────────────────────────────────────────
            # Turn the raw file into a list of {text, page, section, source_path}
            # dicts. This is where PDF/DOCX/HTML/Markdown-specific parsing happens.
            _set_status(session, document, job, DocumentStatus.INGESTING, JobStatus.RUNNING)
            sections = load_document(resolved_path)

            page_numbers = [s["page"] for s in sections if s.get("page") is not None]
            page_count = max(page_numbers) if page_numbers else None

            # ── STEP 2: CHUNK ────────────────────────────────────────────────
            # Group/split those sections into ~512-token pieces with overlap.
            # Each chunk gets a deterministic id like "abc123:0", "abc123:1", ...
            chunk_records: list[ChunkRecord] = chunk_document(doc_id=doc_id, sections=sections)

            if not chunk_records:
                # An empty/unreadable document isn't a crash, but it IS a
                # situation worth surfacing clearly rather than silently
                # marking it "ready" with zero searchable content.
                raise IngestionError(
                    f"No text could be extracted from '{resolved_path.name}'. "
                    "The file may be empty, corrupted, or (if a PDF) scanned "
                    "without OCR."
                )

            # ── STEP 3: EMBED ────────────────────────────────────────────────
            # For each chunk, compute:
            #   - a dense vector (semantic meaning, from Ollama)
            #   - a sparse vector (exact word counts, computed locally)
            texts = [c.text for c in chunk_records]
            dense_vectors = embedder.embed_documents(texts)
            sparse_vectors = [text_to_sparse_vector(t) for t in texts]

            # ── STEP 4: STORE (the idempotent "delete-then-upsert" part) ────
            # Wipe out any chunks from a PREVIOUS ingestion of this exact
            # document — both in Qdrant and in SQLite — before writing the
            # new ones. This is what makes re-running ingest_document() on
            # the same file safe: old, possibly-stale chunks never linger.
            _set_status(session, document, job, DocumentStatus.INGESTING, JobStatus.RUNNING)

            store.ensure_collection()
            store.delete_by_doc(doc_id)
            _delete_existing_chunk_rows(session, document.id)

            store.upsert_chunks(chunk_records, dense=dense_vectors, sparse=sparse_vectors)
            _insert_chunk_rows(session, document.id, chunk_records)

            # ── STEP 5: FINISH ───────────────────────────────────────────────
            document.chunk_count = len(chunk_records)
            document.page_count = page_count
            _set_status(session, document, job, DocumentStatus.READY, JobStatus.COMPLETED)

            return IngestResult(
                doc_id=doc_id,
                job_id=job.id,
                status=DocumentStatus.READY,
                chunk_count=len(chunk_records),
                page_count=page_count,
            )

        except Exception as exc:
            # ── FAILURE PATH ─────────────────────────────────────────────────
            # No matter WHERE in the pipeline something went wrong (loading,
            # chunking, embedding, or storing), we land here. We record the
            # failure clearly in the database rather than leaving the Job
            # stuck in "running" forever, then re-raise so the caller knows
            # something needs attention.
            error_message = str(exc)
            logger.error(
                "Ingestion failed for '%s' (doc_id=%s): %s",
                resolved_path, doc_id, error_message,
            )
            _set_status(
                session, document, job,
                DocumentStatus.FAILED, JobStatus.FAILED,
                error=error_message,
            )

            raise IngestionError(
                f"Failed to ingest '{resolved_path.name}': {error_message}"
            ) from exc


# ─── Database helper functions ─────────────────────────────────────────────────
# These small functions exist just to keep ingest_document() above readable —
# each one does ONE specific piece of bookkeeping in SQLite.

def _get_or_create_document(session, doc_id: str, path: Path) -> Document:
    """
    Look up the Document row for this doc_id, or create a fresh one if
    this is the first time we've seen this file.

    Because doc_id is derived from the file path (see _doc_id_for_path),
    this naturally finds the SAME row on every re-ingestion of the SAME
    file — that's the whole idempotency trick at the Document level.
    """
    existing = session.get(Document, doc_id)
    if existing is not None:
        return existing

    document = Document(
        id=doc_id,
        title=path.stem,              # filename without extension, as a default title
        source_path=str(path),
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _create_job(session, document_id: str) -> Job:
    """Create a new Job row in the QUEUED state for this ingestion run."""
    job = Job(
        document_id=document_id,
        job_type="ingest",
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _set_status(
    session,
    document: Document,
    job: Job,
    doc_status: DocumentStatus,
    job_status: JobStatus,
    error: Optional[str] = None,
) -> None:
    """
    Update both the Document and Job status together and save to the
    database immediately. We do this at every pipeline stage transition
    (queued -> parsing -> embedding -> ready/failed) so that if the
    process crashes mid-way, the database shows EXACTLY which stage it
    got stuck on, instead of just "queued" forever.
    """
    document.status = doc_status
    document.updated_at = _utcnow()

    job.status = job_status
    if job_status == JobStatus.RUNNING and job.started_at is None:
        job.started_at = _utcnow()
    if job_status in (JobStatus.COMPLETED, JobStatus.FAILED):
        job.finished_at = _utcnow()
    if error is not None:
        job.error = error

    session.add(document)
    session.add(job)
    session.commit()


def _delete_existing_chunk_rows(session, document_id: str) -> None:
    """
    Delete all Chunk rows belonging to this document, in SQLite.

    Called right before inserting fresh chunks, as the SQLite half of
    the "delete-then-upsert" idempotency pattern (the Qdrant half is
    QdrantStore.delete_by_doc, called separately).
    """
    existing_chunks = session.exec(
        select(Chunk).where(Chunk.document_id == document_id)
    ).all()

    for chunk_row in existing_chunks:
        session.delete(chunk_row)

    session.commit()


def _insert_chunk_rows(session, document_id: str, chunk_records: list[ChunkRecord]) -> None:
    """
    Insert one Chunk row per chunk produced by the chunker.

    Note: chunk_records here are ChunkRecord dataclasses (from
    documind_core.chunking.chunker), NOT the SQLModel Chunk table rows —
    this function maps from one to the other. The `qdrant_id` field
    isn't set here because QdrantStore derives its own internal point ID
    from chunk.id; storing chunk.id itself (the human-readable
    "doc_id:ordinal" string) is what other code actually looks up by.
    """
    for record in chunk_records:
        chunk_row = Chunk(
            id=record.id,                  # e.g. "abc123:0" — deterministic
            document_id=document_id,
            chunk_index=record.ordinal,
            text=record.text,
            page_number=record.page,
            qdrant_id=record.id,           # same human-readable id; Qdrant's
                                            # internal UUID is an implementation
                                            # detail callers don't need here
        )
        session.add(chunk_row)

    session.commit()
