"""Identity Normalization Service — composition root.

Creates the FastAPI application, configures structured logging, and exposes
the module-level `app` instance for uvicorn.

Exposes GET /health; the full consumer loop pipeline is wired in the lifespan
(chunk 6).
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

import naas_shared.database as _db_mod
import naas_shared.redis_client as _redis_mod
from fastapi import APIRouter, FastAPI
from naas_shared.constants import GROUP_NORMALIZATION, STREAM_LOGIN_EVENTS
from naas_shared.database import get_session_factory
from naas_shared.logging import get_logger, setup_logging
from naas_shared.models import HealthResponse
from sqlalchemy import text

# Import load_config at module level so tests can patch app.main.load_config
from app.normalization_config import load_config
from app.consumer import run_consumer_loop

_logger = get_logger(__name__)

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
    """Startup: load config, ensure consumer group, construct pipeline components, launch consumer.

    WHY exception propagation on invalid config: the service MUST NOT start
    with a broken normalization configuration.  A bad correlation_key or
    on_failure value would silently produce wrong enrichment decisions for every
    event.  Letting the exception propagate aborts startup with a descriptive
    error (§5.1, §5.6).

    WHY asyncio.create_task: the consumer loop runs indefinitely; blocking the
    lifespan with await would prevent FastAPI from completing startup and serving
    /health requests.  create_task schedules the loop concurrently so both the
    consumer and the HTTP server run in the same event loop.

    Shutdown: the background task is cancelled and awaited to allow clean
    in-flight processing before the process exits.
    """
    from app.adapters.ldap import LdapAdapter
    from app.adapters.oidc import OidcAdapter
    from app.adapters.saml import SamlAdapter
    from app.repository import PostgresNormalizationRepository
    from app.service import NormalizationPublisher, NormalizationService

    # Load and validate config — let the exception propagate on invalid config.
    # Resolution order:
    #   1. NORMALIZATION_CONFIG_PATH env var (Docker/CI/test override)
    #   2. /app/config/normalization.yaml (compose mount: ./config:/app/config:ro)
    #   3. Repo-relative fallback for host/dev: 4 parents from __file__ → repo root
    _compose_default = Path("/app/config/normalization.yaml")
    _repo_fallback = (
        Path(__file__).parent.parent.parent.parent / "config" / "normalization.yaml"
    )
    _env_override = os.environ.get("NORMALIZATION_CONFIG_PATH")
    if _env_override:
        config_path = Path(_env_override)
    elif _compose_default.exists():
        config_path = _compose_default
    else:
        config_path = _repo_fallback
    config = load_config(config_path)

    # Ensure the consumer group exists (idempotent; BUSYGROUP is swallowed).
    # Call via module reference so tests can patch naas_shared.redis_client.ensure_consumer_group.
    await _redis_mod.ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION)

    # Construct pipeline components
    oidc_adapter = OidcAdapter()
    saml_adapter = SamlAdapter()
    ldap_adapter = LdapAdapter()

    service = NormalizationService(
        config=config,
        oidc_adapter=oidc_adapter,
        saml_adapter=saml_adapter,
        ldap_adapter=ldap_adapter,
    )

    repository = PostgresNormalizationRepository(session_factory=get_session_factory())
    publisher = NormalizationPublisher()

    # Launch the consumer as a background task.
    # The consumer loop calls get_redis() internally on startup so the lifespan
    # does not need to establish a Redis connection during startup — this keeps
    # test patching simple (only ensure_consumer_group and run_consumer_loop are patched).
    consumer_task = asyncio.create_task(
        run_consumer_loop(
            service=service,
            repository=repository,
            publisher=publisher,
        )
    )

    # Yield to the event loop so the task starts executing before the yield point.
    # WHY: asyncio.create_task schedules the coroutine but does not start it immediately.
    # The sleep(0) allows the task to reach its first await (e.g. xreadgroup with block=2000)
    # before we yield to FastAPI's application lifecycle. This ensures the task is actually
    # running (not just scheduled) when the lifespan is active.
    await asyncio.sleep(0)

    _logger.info("identity_normalization_startup_complete")

    try:
        yield
    finally:
        # Cancel the background consumer task and await clean termination
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        _logger.info("identity_normalization_shutdown_complete")


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
