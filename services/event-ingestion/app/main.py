"""Event Ingestion Service — composition root.

Creates the FastAPI application, configures structured logging, and exposes
the module-level `app` instance for uvicorn.

Mounts the APIRouter from app.routes, which provides the three endpoints
defined in spec §§5.6, 5.7: POST /events/ingest, POST /events/bulk, GET /health.
"""

from contextlib import asynccontextmanager

import naas_shared.redis_client as _redis_mod
from fastapi import FastAPI
from naas_shared.database import dispose_engine
from naas_shared.logging import get_logger, setup_logging
from naas_shared.middleware import CorrelationIdMiddleware
from naas_shared.redis_client import close_redis

from app.routes import router


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Warm the Redis client at startup; tear down connections on shutdown."""
    try:
        await _redis_mod.get_redis()
    except Exception:  # noqa: BLE001 — startup warmup is best-effort; any failure degrades to retry-on-first-request
        get_logger("event-ingestion").warning(
            "redis_warmup_skipped",
            reason="Redis unavailable at startup — will retry on first request",
        )
    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()


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
    # Bind a per-request correlation_id into the structlog context (see
    # naas_shared.middleware.CorrelationIdMiddleware) so every log line emitted
    # while serving a request is traceable to that request.
    application.add_middleware(CorrelationIdMiddleware)
    application.include_router(router)

    return application


app = create_app()
