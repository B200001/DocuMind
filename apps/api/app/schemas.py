"""
Pydantic schemas for every request and response body in the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ─── Documents ────────────────────────────────────────────────────────────────

class IngestJobResponse(BaseModel):
    job_id: str
    doc_id: str
    filename: str
    status: str = "queued"
    message: str = "Ingestion started in background."


class DocumentOut(BaseModel):
    doc_id: str
    title: str
    source_path: str
    status: str
    chunk_count: Optional[int]
    page_count: Optional[int]
    created_at: datetime
    updated_at: datetime


class JobStatusOut(BaseModel):
    job_id: str
    doc_id: Optional[str]
    status: str
    error: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class DeleteResponse(BaseModel):
    doc_id: str
    deleted: bool
    message: str


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    session_id: Optional[str] = None
    user_id: Optional[str] = None


class SSEEvent(BaseModel):
    type: str


class NodeStartEvent(SSEEvent):
    type: str = "node_start"
    node: str


class ToolResultEvent(SSEEvent):
    type: str = "tool_result"
    node: str
    data: Any


class TokenEvent(SSEEvent):
    type: str = "token"
    text: str


class CitationEvent(SSEEvent):
    type: str = "citation"
    citations: list[str]


class FinalEvent(SSEEvent):
    type: str = "final"
    answer: str
    citations: list[str]
    loops: int


class ErrorEvent(SSEEvent):
    type: str = "error"
    message: str


# ─── Health ───────────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    name: str
    status: str
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    services: list[ServiceStatus]
