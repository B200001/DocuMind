"""
SQLModel table definitions and database session helpers.

Tables
------
Document  – a source file ingested into the system
Chunk     – a text chunk derived from a Document
Job       – an async ingestion/processing job
Message   – a chat turn stored for history / evaluation

Usage
-----
    from documind_core.models import get_session, Document

    with get_session() as session:
        session.add(Document(title="My PDF", source_path="/data/uploads/my.pdf"))
        session.commit()
"""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlmodel import Field, Relationship, Session, SQLModel, create_engine

from documind_core.config import get_settings
from documind_core.paths import ensure_dirs


# ─── Enums ────────────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    PENDING   = "pending"
    INGESTING = "ingesting"
    READY     = "ready"
    FAILED    = "failed"


class JobStatus(str, Enum):
    QUEUED     = "queued"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"


class MessageRole(str, Enum):
    USER      = "user"
    ASSISTANT = "assistant"
    SYSTEM    = "system"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _uuid() -> str:
    return str(uuid.uuid4())


# ─── Tables ───────────────────────────────────────────────────────────────────

class Document(SQLModel, table=True):
    """A source file that has been uploaded and (optionally) ingested."""

    __tablename__ = "documents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    title: str
    source_path: str                           # absolute path on disk
    mime_type: Optional[str] = None
    status: DocumentStatus = DocumentStatus.PENDING
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # relationships
    chunks: list["Chunk"] = Relationship(back_populates="document")
    jobs:   list["Job"]   = Relationship(back_populates="document")


class Chunk(SQLModel, table=True):
    """A text chunk derived from a Document and stored in Qdrant."""

    __tablename__ = "chunks"

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: str = Field(foreign_key="documents.id", index=True)
    chunk_index: int                           # order within the document
    text: str
    page_number: Optional[int] = None
    qdrant_id: Optional[str] = None           # corresponding vector ID
    created_at: datetime = Field(default_factory=_utcnow)

    # relationships
    document: Optional[Document] = Relationship(back_populates="chunks")


class Job(SQLModel, table=True):
    """An async ingestion or processing task tied to a Document."""

    __tablename__ = "jobs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: Optional[str] = Field(
        default=None, foreign_key="documents.id", index=True
    )
    job_type: str                              # e.g. "ingest", "reindex"
    status: JobStatus = JobStatus.QUEUED
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)

    # relationships
    document: Optional[Document] = Relationship(back_populates="jobs")


class Message(SQLModel, table=True):
    """A single chat turn (user or assistant) stored for history/evals."""

    __tablename__ = "messages"

    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str = Field(index=True)       # groups turns into a conversation
    role: MessageRole
    content: str
    sources: Optional[str] = None             # JSON-encoded list of chunk IDs
    latency_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)


# ─── Engine & Session ─────────────────────────────────────────────────────────

def _make_engine():
    ensure_dirs()                              # guarantee data/ exists first
    settings = get_settings()
    connect_args = {"check_same_thread": False}   # needed for SQLite
    return create_engine(
        settings.sqlite_url,
        echo=False,
        connect_args=connect_args,
    )


# Module-level singleton – imported directly by callers that need it
engine = _make_engine()


def create_db_and_tables() -> None:
    """Create all tables if they don't exist (idempotent)."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    """
    Return a new Session bound to the shared engine.

    Intended for use as a context manager:

        with get_session() as s:
            s.add(doc)
            s.commit()
    """
    return Session(engine)
