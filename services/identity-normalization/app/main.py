"""Identity Normalization Service — composition root.

Creates the FastAPI application, configures structured logging, and exposes
the module-level `app` instance for uvicorn.

Exposes GET /health only in Chunk 1; the consumer loop and normalization
endpoints are wired in later chunks.
"""

from contextlib import asynccontextmanager

import naas_shared.database as _db_mod
import naas_shared.redis_client as _redis_mod
from fastapi import APIRouter, FastAPI
from naas_shared.logging import setup_logging
from naas_shared.models import HealthResponse
from sqlalchemy import text


router = APIRouter()


@router.get("/health", response_model=HealthResponse, status_code=200)
async def health() -> HealthResponse:
    """Readiness probe: check PostgreSQL and Redis connectivity (spec §5.8).

    Accesses get_db_session and get_redis through the naas_shared module
    references at call time so test patches at the naas_shared.* namespace
    are effective.

    Decision table (spec §5.8):
      PG OK + Redis OK  → "healthy"
      PG OK + Redis KO  → "degraded"  (events can persist; stream publish fails)
      PG KO             → "unhealthy" (cannot persist normalized_attributes)

    HTTP status is always 200; operational status is in the body.
    """
    pg_ok = True
    agen = _db_mod.get_db_session()
    try:
        session = await agen.__anext__()
        await session.execute(text("SELECT 1"))
    except Exception:
        pg_ok = False
    finally:
        await agen.aclose()

    redis_ok = True
    try:
        client = await _redis_mod.get_redis()
        await client.ping()
    except Exception:
        redis_ok = False

    if not pg_ok:
        status = "unhealthy"
    elif not redis_ok:
        status = "degraded"
    else:
        status = "healthy"

    return HealthResponse(status=status, service="identity-normalization")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Minimal lifespan stub for Chunk 1.

    The consumer loop, consumer group setup, and config load are wired in
    later chunks. This stub exists so the app starts cleanly without any
    background tasks.
    """
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance.

    Calls setup_logging once so all subsequent log calls emit structured JSON
    with the service name bound. The module-level `app` is the uvicorn entry
    point: `uvicorn app.main:app`.

    In Chunk 1, exposes only GET /health (spec §5.8 scope boundary).
    """
    setup_logging("identity-normalization")

    application = FastAPI(
        title="identity-normalization",
        version="2.0.0",
        lifespan=lifespan,
        swagger_ui_oauth2_redirect_url=None,
    )
    application.include_router(router)

    return application


app = create_app()
