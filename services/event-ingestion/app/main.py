"""Event Ingestion Service — composition root.

Creates the FastAPI application, configures structured logging, and exposes
the module-level `app` instance for uvicorn.

Chunk 1 skeleton: provides GET /health only.  The full /events/* router and
readiness-probing health logic (PG + Redis checks, degraded/unhealthy states)
are added in a later chunk that supersedes this stub.
"""

from fastapi import FastAPI

from naas_shared.logging import setup_logging
from naas_shared.models import HealthResponse


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance.

    Calls setup_logging once so all subsequent log calls emit structured JSON
    with the service name bound.  The module-level `app` is the uvicorn entry
    point: `uvicorn app.main:app`.
    """
    setup_logging("event-ingestion")

    application = FastAPI(title="event-ingestion", version="2.0.0")

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Liveness/readiness probe.

        Chunk 1 skeleton returns a static healthy response.  Chunk 3 replaces
        this with real PostgreSQL and Redis connectivity checks.
        """
        return HealthResponse(status="healthy", service="event-ingestion")

    return application


app = create_app()
