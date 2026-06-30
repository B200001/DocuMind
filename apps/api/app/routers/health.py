"""
GET /health — checks Ollama and Qdrant are reachable.
Returns 200 when all services are healthy, 503 when any are degraded.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.deps import get_embedder, get_store
from app.schemas import HealthResponse, ServiceStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health_check(
    embedder=Depends(get_embedder),
    store=Depends(get_store),
) -> JSONResponse:
    """Check Ollama (model pulled?) and Qdrant (collection exists?)."""
    services: list[ServiceStatus] = []

    # Ollama — verify server reachable and embedding model is pulled
    try:
        await asyncio.to_thread(embedder.health_check)
        services.append(ServiceStatus(name="ollama", status="ok"))
    except Exception as exc:
        logger.warning("[health] Ollama check failed: %s", exc)
        services.append(ServiceStatus(name="ollama", status="degraded", detail=str(exc)))

    # Qdrant — verify server reachable and collection exists
    try:
        exists = await asyncio.to_thread(
            store._client.collection_exists, store.collection_name
        )
        if not exists:
            raise RuntimeError(f"Collection '{store.collection_name}' not found.")
        count = await asyncio.to_thread(store._client.count, store.collection_name)
        services.append(ServiceStatus(
            name="qdrant", status="ok",
            detail=f"{count.count} vectors",
        ))
    except Exception as exc:
        logger.warning("[health] Qdrant check failed: %s", exc)
        services.append(ServiceStatus(name="qdrant", status="degraded", detail=str(exc)))

    overall = "ok" if all(s.status == "ok" for s in services) else "degraded"
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content=HealthResponse(status=overall, services=services).model_dump(),
    )
