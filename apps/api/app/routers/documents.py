"""
Document management: upload → background ingest, list, status, delete.

POST /documents/upload
    Saves file to disk, queues ingestion via BackgroundTasks, returns job_id.
    Ingestion runs in asyncio.to_thread — never blocks the event loop.

GET /documents              — list all documents
GET /documents/{id}/status  — poll ingestion job status
DELETE /documents/{id}      — remove from Qdrant + SQLite + disk
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlmodel import select

from app.deps import get_embedder, get_store
from app.schemas import DeleteResponse, DocumentOut, IngestJobResponse, JobStatusOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# ─── POST /documents/upload ───────────────────────────────────────────────────

@router.post("/upload", response_model=IngestJobResponse, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    embedder=Depends(get_embedder),
    store=Depends(get_store),
) -> IngestJobResponse:
    """Accept a file upload and queue background ingestion. Returns immediately."""
    from documind_core.paths import UPLOADS_DIR, ensure_dirs
    from documind_core.ingestion.pipeline import _doc_id_for_path

    ensure_dirs()

    safe_name = Path(file.filename).name if file.filename else "upload"
    dest_path = UPLOADS_DIR / safe_name
    counter = 1
    while dest_path.exists():
        stem = Path(safe_name).stem
        suffix = Path(safe_name).suffix
        dest_path = UPLOADS_DIR / f"{stem}_{counter}{suffix}"
        counter += 1

    content = await file.read()
    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(content)
    logger.info("[documents] Saved upload to %s (%d bytes)", dest_path, len(content))

    doc_id = _doc_id_for_path(dest_path)
    job_id = _create_pending_job(doc_id, str(dest_path))

    # BackgroundTasks dispatches sync functions to a thread pool automatically
    background_tasks.add_task(
        _run_ingestion_in_thread,
        path=str(dest_path),
        embedder=embedder,
        store=store,
    )

    return IngestJobResponse(
        job_id=job_id,
        doc_id=doc_id,
        filename=dest_path.name,
    )


# ─── GET /documents ───────────────────────────────────────────────────────────

@router.get("", response_model=list[DocumentOut])
async def list_documents() -> list[DocumentOut]:
    """Return all ingested documents, newest first."""
    from documind_core.models import Document, get_session

    with get_session() as session:
        docs = session.exec(
            select(Document).order_by(Document.created_at.desc())
        ).all()
        return [
            DocumentOut(
                doc_id=d.id,
                title=d.title,
                source_path=d.source_path,
                status=d.status.value,
                chunk_count=d.chunk_count,
                page_count=d.page_count,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in docs
        ]


# ─── GET /documents/{doc_id}/status ──────────────────────────────────────────

@router.get("/{doc_id}/status", response_model=JobStatusOut)
async def get_document_status(doc_id: str) -> JobStatusOut:
    """Return the most recent ingestion job status for a document."""
    from documind_core.models import Job, get_session

    with get_session() as session:
        job = session.exec(
            select(Job)
            .where(Job.document_id == doc_id)
            .order_by(Job.created_at.desc())
        ).first()

        if job is None:
            raise HTTPException(
                status_code=404,
                detail=f"No job found for document '{doc_id}'.",
            )

        return JobStatusOut(
            job_id=job.id,
            doc_id=job.document_id,
            status=job.status.value,
            error=job.error,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


# ─── DELETE /documents/{doc_id} ───────────────────────────────────────────────

@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    store=Depends(get_store),
) -> DeleteResponse:
    """Delete from Qdrant + SQLite + disk. Idempotent."""
    from documind_core.models import Chunk, Document, Job, get_session

    # 1. Check existence and clean up SQLite first
    with get_session() as session:
        doc = session.get(Document, doc_id)
        source_path = doc.source_path if doc else None
        doc_existed = doc is not None

        for c in session.exec(select(Chunk).where(Chunk.document_id == doc_id)).all():
            session.delete(c)
        for j in session.exec(select(Job).where(Job.document_id == doc_id)).all():
            session.delete(j)
        if doc:
            session.delete(doc)
        session.commit()

    # 2. Remove vectors from Qdrant (always attempt; Qdrant delete is idempotent)
    try:
        await asyncio.to_thread(store.delete_by_doc, doc_id)
    except Exception as exc:
        logger.warning("[documents] Qdrant delete failed for %s: %s", doc_id, exc)

    # 3. Remove file from disk (best-effort)
    if source_path:
        try:
            p = Path(source_path)
            if p.exists():
                p.unlink()
        except Exception as exc:
            logger.warning("[documents] Could not delete file %s: %s", source_path, exc)

    return DeleteResponse(
        doc_id=doc_id,
        deleted=doc_existed,
        message="Document deleted." if doc_existed else "Document not found (already deleted).",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _create_pending_job(doc_id: str, source_path: str) -> str:
    """Pre-create Document + QUEUED Job rows so polling works immediately."""
    from documind_core.models import Document, DocumentStatus, Job, JobStatus, get_session
    from pathlib import Path

    with get_session() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            doc = Document(
                id=doc_id,
                title=Path(source_path).stem,
                source_path=source_path,
                status=DocumentStatus.PENDING,
            )
            session.add(doc)
            session.commit()
            session.refresh(doc)

        job = Job(document_id=doc_id, job_type="ingest", status=JobStatus.QUEUED)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def _run_ingestion_in_thread(path: str, embedder, store) -> None:
    """
    Synchronous ingestion runner — called by BackgroundTasks in a thread.
    Errors are logged and written to the Job row, never crash the server.
    """
    from documind_core.ingestion.pipeline import IngestionError, ingest_document

    logger.info("[documents] Background ingestion starting: %s", path)
    try:
        result = ingest_document(path=path, embedder=embedder, store=store)
        logger.info("[documents] Done: doc_id=%s chunks=%d status=%s",
                    result.doc_id, result.chunk_count, result.status)
    except IngestionError as exc:
        logger.error("[documents] Ingestion failed for %s: %s", path, exc)
    except Exception as exc:
        logger.exception("[documents] Unexpected error ingesting %s: %s", path, exc)
