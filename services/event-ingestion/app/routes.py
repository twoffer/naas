"""Event Ingestion Service — APIRouter with exactly three endpoints.

Spec §§5.6, 5.7, 3.3: POST /events/ingest, POST /events/bulk, GET /health.
Route handlers translate HTTP to/from IngestionService; no dual-write logic lives here.
"""

from typing import Annotated, Literal
from uuid import UUID

import naas_shared.database as _db_mod
import naas_shared.redis_client as _redis_mod
from fastapi import APIRouter, Body, Depends
from naas_shared.database import get_db_session
from naas_shared.logging import get_logger
from naas_shared.models import HealthResponse, LoginEventIngest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import PostgresEventRepository, RedisEventPublisher
from app.schemas import BulkIngestAccepted, IngestAccepted
from app.service import IngestionService

router = APIRouter()


async def get_ingestion_service(
    session: AsyncSession = Depends(get_db_session),
) -> IngestionService:
    """FastAPI dependency that constructs an IngestionService for the request.

    Wires the concrete PostgreSQL and Redis adapters to the domain service so
    route handlers receive a ready-to-use service and tests can substitute a
    fake via app.dependency_overrides[get_ingestion_service].
    """
    return IngestionService(
        PostgresEventRepository(session),
        RedisEventPublisher(),
        get_logger("event-ingestion"),
    )


@router.post("/events/ingest", response_model=IngestAccepted, status_code=202)
async def ingest_one(
    event: LoginEventIngest,
    service: IngestionService = Depends(get_ingestion_service),
) -> IngestAccepted:
    """Accept and durably store a single login event (spec §§2.1, 3.3, 5.6).

    Delegates entirely to IngestionService.ingest_one — no dual-write logic here.
    Returns 202 Accepted with the server-assigned event UUID.
    """
    event_id: UUID = await service.ingest_one(event)
    return IngestAccepted(id=event_id)


@router.post("/events/bulk", response_model=BulkIngestAccepted, status_code=202)
async def ingest_many(
    events: Annotated[list[LoginEventIngest], Body(min_length=1, max_length=5000)],
    service: IngestionService = Depends(get_ingestion_service),
) -> BulkIngestAccepted:
    """Accept and durably store a bare JSON array of login events (spec §§2.2, 3.3, 5.6).

    Body is a bare JSON array (not wrapped in an envelope). Array length 1–5000;
    outside that range yields FastAPI 422 before the handler runs.
    Delegates to IngestionService.ingest_many for single-transaction atomicity.
    """
    ids: list[UUID] = await service.ingest_many(events)
    return BulkIngestAccepted(accepted=len(ids), event_ids=ids)


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health() -> HealthResponse:
    """Readiness probe: check PostgreSQL and Redis connectivity (spec §5.6).

    Accesses get_session_factory and get_redis through the naas_shared module
    references at call time so test patches at the naas_shared.* namespace are
    effective.

    Decision table (spec §5.6):
      PG OK + Redis OK  → "healthy"
      PG OK + Redis KO  → "degraded"  (events persist; stream publish will fail)
      PG KO             → "unhealthy" (no new events can be accepted)

    HTTP status is always 200; operational status is in the body.
    """
    pg_ok = True
    try:
        factory = _db_mod.get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — health probe must report unhealthy on any failure, never raise
        pg_ok = False

    redis_ok = True
    try:
        client = await _redis_mod.get_redis()
        await client.ping()
    except Exception:  # noqa: BLE001 — health probe must report unhealthy on any failure, never raise
        redis_ok = False

    status: Literal["healthy", "degraded", "unhealthy"]
    if not pg_ok:
        status = "unhealthy"
    elif not redis_ok:
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(status=status, service="event-ingestion")
