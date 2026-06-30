"""
FastAPI application factory for the Documind API.

Startup (lifespan):
  1. Create SQLite tables (idempotent)
  2. Ensure Qdrant collection exists (recreates if embedding dim changed)
  3. Initialise DI singletons (OllamaEmbedder, QdrantStore)

CORS: allows the Next.js dev server on localhost:3000.

Run:
    cd apps/api && uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.deps import init_singletons, teardown_singletons
from app.routers import chat, documents, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    logger.info("=== Documind API startup ===")

    # 1. SQLite tables
    from documind_core.models import create_db_and_tables
    create_db_and_tables()
    logger.info("[startup] SQLite tables ready.")

    # 2. Qdrant collection (network call → thread)
    from documind_core.vectorstore.qdrant_store import QdrantStore
    await asyncio.to_thread(QdrantStore().ensure_collection)
    logger.info("[startup] Qdrant collection ready.")

    # 3. DI singletons
    init_singletons()
    logger.info("[startup] Singletons ready. Serving requests.")

    yield

    # Shutdown
    logger.info("=== Documind API shutting down ===")
    from documind_core.observability.langfuse_client import flush
    flush()
    teardown_singletons()
    logger.info("=== Shutdown complete ===")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Documind API",
        description="RAG-powered document Q&A backend.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",    # Next.js dev server
            "http://localhost:3001",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Type", "X-Accel-Buffering"],
    )

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(chat.router)

    @app.get("/", include_in_schema=False)
    async def root():
        return {"service": "documind-api", "version": "0.1.0", "docs": "/docs"}

    return app


app = create_app()
