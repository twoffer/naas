"""Event Ingestion Service — composition root.

Creates the FastAPI application, configures structured logging, and exposes
the module-level `app` instance for uvicorn.

Mounts the APIRouter from app.routes, which provides the three endpoints
defined in spec §§5.6, 5.7: POST /events/ingest, POST /events/bulk, GET /health.
Re-exports get_ingestion_service so tests can override it via app.main lookup.
"""

from contextlib import asynccontextmanager

import naas_shared.redis_client as _redis_mod
from fastapi import FastAPI

from naas_shared.logging import get_logger, setup_logging

from app.routes import get_ingestion_service, router  # noqa: F401 — re-exported


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Warm the Redis client at startup so the first request is not penalised."""
    try:
        await _redis_mod.get_redis()
    except Exception:
        get_logger("event-ingestion").debug(
            "redis_warmup_skipped",
            reason="Redis unavailable at startup — will retry on first request",
        )
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance.

    Calls setup_logging once so all subsequent log calls emit structured JSON
    with the service name bound.  The module-level `app` is the uvicorn entry
    point: `uvicorn app.main:app`.

    The router from app.routes provides exactly three endpoints (spec §5.6, §7):
      POST /events/ingest, POST /events/bulk, GET /health.
    No other endpoints are added here.
    """
    setup_logging("event-ingestion")

    application = FastAPI(
        title="event-ingestion",
        version="2.0.0",
        lifespan=lifespan,
    )
    application.include_router(router)

    return application


app = create_app()
