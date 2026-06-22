import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from sqlmodel import Field, Relationship, Session, SQLModel, create_engine

from documind_core.config import get_settings
from documind_core.paths import ensure_dirs


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _uuid() -> str:
    return str(uuid.uuid4())


class Document(SQLModel, table=True):
    __tablename__ = "documents"

    id: str = Field(default_factory=_uuid, primary_key=True)
    title: str
    source_path: str
    mime_type: Optional[str] = None
    status: DocumentStatus = DocumentStatus.PENDING
    page_count: Optional[int] = None
    chunk_count: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    chunks: List["Chunk"] = Relationship(back_populates="document")
    jobs:   List["Job"]   = Relationship(back_populates="document")


class Chunk(SQLModel, table=True):
    __tablename__ = "chunks"

    id: str = Field(primary_key=True)   # deterministic: f"{doc_id}:{ordinal}"
    document_id: str = Field(foreign_key="documents.id", index=True)
    chunk_index: int
    text: str
    page_number: Optional[int] = None
    qdrant_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)

    document: Optional[Document] = Relationship(back_populates="chunks")


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(default_factory=_uuid, primary_key=True)
    document_id: Optional[str] = Field(default=None, foreign_key="documents.id", index=True)
    job_type: str
    status: JobStatus = JobStatus.QUEUED
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_utcnow)

    document: Optional[Document] = Relationship(back_populates="jobs")


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=_uuid, primary_key=True)
    session_id: str = Field(index=True)
    role: MessageRole
    content: str
    sources: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=_utcnow)


def _make_engine():
    ensure_dirs()
    settings = get_settings()
    connect_args = {"check_same_thread": False}
    return create_engine(settings.sqlite_url, echo=False, connect_args=connect_args)


engine = _make_engine()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
