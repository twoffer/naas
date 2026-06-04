# Component: NAAS Spec 1 — Chunk 1: event-ingestion app skeleton
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/event-ingestion/app/__init__.py
#   services/event-ingestion/app/main.py
#
# What these tests validate:
#   - `from app.main import app` resolves to a FastAPI instance
#   - GET /health returns HTTP 200 with JSON body where:
#       service == 'event-ingestion' and status == 'healthy'
#   - The /health response conforms to the shared HealthResponse schema
#     (importable from naas_shared.models)
#
# sys.path strategy:
#   We insert services/event-ingestion onto sys.path so that `from app.main import app`
#   resolves once the implementer creates app/main.py in that directory. This mirrors
#   how uvicorn runs the service: it sets the working directory to services/event-ingestion
#   and imports app.main:app. Tests that import app.main without this path setup fail
#   with ModuleNotFoundError, which is the correct TDD initial state.
#
# External dependencies:
#   app/main.py will import from naas_shared (database, redis_client, logging, models,
#   config). These are mocked/patched via TestClient's lifespan handling. The TestClient
#   from starlette (bundled with FastAPI) is used — it does NOT require a running DB or
#   Redis; it only runs the ASGI app in-process. The /health endpoint is designed to
#   check DB/Redis connectivity, but the skeleton test only asserts the happy-path
#   response structure. Integration tests (marked @pytest.mark.integration) would verify
#   real DB/Redis connectivity.
#
# TDD state:
#   services/event-ingestion/app/ does not exist yet. All tests MUST fail with
#   ModuleNotFoundError until the implementer creates the app package and main.py.

# stdlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory containing
    docs/architecture/ — the canonical repo root marker. Capped at 10 levels."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        "Could not locate repo root (expected a directory containing "
        f"docs/architecture/). Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"
SERVICE_DIR = REPO_ROOT / "services" / "event-ingestion"

# Inject shared/ so naas_shared is importable (required by app.main at import time).
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

# Inject services/event-ingestion/ so `from app.main import app` resolves
# once the implementer creates app/main.py there.
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


# ===========================================================================
# CLASS 1 — Import: app.main resolves to a FastAPI instance
# ===========================================================================


class TestAppMainImport:
    """app.main must be importable and must expose a FastAPI instance named `app`.

    WHY: The Dockerfile CMD is 'uvicorn app.main:app --host 0.0.0.0 --port 8001'.
    If `app` is not a FastAPI instance (or is absent), uvicorn crashes immediately
    with 'Could not import module app.main' or 'app is not an ASGI application'.
    """

    def test_app_main_module_is_importable(self) -> None:
        """from app.main import app must succeed without raising.

        WHY: ModuleNotFoundError here means services/event-ingestion/app/main.py
        does not exist yet — the correct TDD initial state. After implementation,
        this must pass without error.
        """
        from app.main import app  # noqa: F401

    def test_app_is_a_fastapi_instance(self) -> None:
        """app must be an instance of fastapi.FastAPI.

        WHY: uvicorn's --app argument expects an ASGI callable. FastAPI is the
        required framework per the project tech stack. A plain dict, None, or a
        Starlette instance without FastAPI's OpenAPI/validation layer would break
        the service's contract with upstream callers.
        """
        from fastapi import FastAPI

        from app.main import app

        assert isinstance(app, FastAPI), (
            f"Expected app to be a FastAPI instance, got {type(app).__name__!r}. "
            "The Dockerfile CMD is 'uvicorn app.main:app' — app must be a FastAPI object."
        )


# ===========================================================================
# CLASS 2 — GET /health endpoint
# ===========================================================================


class TestHealthEndpoint:
    """GET /health must return HTTP 200 with a JSON body where
    service == 'event-ingestion' and status == 'healthy'.

    The health endpoint is the readiness probe for the Docker healthcheck and
    for the depends_on conditions of downstream services. A wrong status value
    or missing service name prevents operators from distinguishing service identity
    when multiple NAAS services are deployed.

    We use starlette.testclient.TestClient (synchronous wrapper around the ASGI app)
    for isolation. The /health endpoint makes real DB and Redis calls in production;
    for the skeleton test we patch those dependencies so the test does not require
    a running database or Redis instance.
    """

    @pytest.fixture(autouse=True)
    def patch_external_dependencies(self):
        """Patch DB session and Redis client so /health works without infrastructure.

        WHY: The health endpoint executes 'SELECT 1' against PostgreSQL and pings
        Redis. In unit tests, neither is running. We patch at the naas_shared level
        so the app resolves its imports cleanly and the /health handler gets working
        mock dependencies. Without this patch the test fails with connection errors
        rather than testing the response structure.
        """
        # Mock async DB session that succeeds on execute("SELECT 1")
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        # Mock Redis client that succeeds on ping()
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        # We use broad patches targeting where the symbols are looked up by app/main.py.
        # If the implementer uses `from naas_shared.database import get_db_session`,
        # we patch naas_shared.database.get_db_session.
        # If the implementer uses `from naas_shared.redis_client import get_redis`,
        # we patch naas_shared.redis_client.get_redis.
        with (
            patch("naas_shared.database.get_db_session", return_value=mock_session),
            patch("naas_shared.redis_client.get_redis", return_value=mock_redis),
        ):
            yield

    def test_health_endpoint_returns_200(self) -> None:
        """GET /health must return HTTP 200.

        WHY: The Docker healthcheck is:
            python -c "import urllib.request,sys; sys.exit(0 if
            urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"
        Any non-200 status causes the container to report 'unhealthy' in docker-compose ps,
        blocking all depends_on services from starting.
        """
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health expected HTTP 200, got {response.status_code}. "
            "The Docker healthcheck depends on this exact status code."
        )

    def test_health_endpoint_response_body_is_json(self) -> None:
        """GET /health must return a JSON-parseable body.

        WHY: The docker healthcheck uses urllib.request which returns the raw response.
        Downstream monitoring tools (Grafana, Prometheus) also parse the /health body.
        A non-JSON response (e.g., plain text) breaks automated health monitoring.
        """
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health returned {response.status_code}, cannot parse JSON body."
        )
        try:
            body = response.json()
        except Exception as exc:
            pytest.fail(
                f"GET /health response body is not valid JSON: {exc}. "
                f"Raw content: {response.text!r}"
            )
        assert body is not None, "GET /health returned a null JSON body"

    def test_health_endpoint_service_field_is_event_ingestion(self) -> None:
        """The /health response body must have service == 'event-ingestion'.

        WHY: The spec §5.6 states 'Set service="event-ingestion"'. The service
        field is how operators identify which NAAS component they are probing when
        multiple services are running. The wrong service name (e.g., 'api-gateway')
        causes false positive health checks that mask deployment errors.
        """
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "event-ingestion", (
            f"Expected service='event-ingestion', got {body.get('service')!r}. "
            "The spec §5.6 mandates this exact value."
        )

    def test_health_endpoint_status_field_is_healthy(self) -> None:
        """The /health response body must have status == 'healthy' when all deps are up.

        WHY: The spec §5.6 states 'Both OK → status="healthy"'. With DB and Redis
        mocked to succeed, the skeleton health check must report 'healthy'. Any other
        value ('degraded', 'unhealthy') on a fresh startup indicates either wrong
        default behavior or a mock that isn't matching the implementation's
        dependency call pattern.
        """
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "healthy", (
            f"Expected status='healthy', got {body.get('status')!r}. "
            "When both DB and Redis are responsive, /health must report 'healthy'."
        )

    def test_health_endpoint_response_conforms_to_health_response_schema(self) -> None:
        """The /health body must validate against the shared HealthResponse model.

        WHY: The spec §3.3 states the health endpoint returns 'the shared HealthResponse
        (see 5.6)' and §4 specifies 'from naas_shared.models import HealthResponse'.
        The response must have all required fields (status, service, version, timestamp)
        in the correct types. An incomplete body would cause Pydantic validation errors
        in any consumer that calls HealthResponse.model_validate(body).
        """
        from naas_shared.models import HealthResponse
        from pydantic import ValidationError
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        body = response.json()

        try:
            validated = HealthResponse.model_validate(body)
        except ValidationError as exc:
            pytest.fail(
                f"GET /health body failed HealthResponse validation: {exc}. "
                f"Body was: {body}"
            )

        assert validated.service == "event-ingestion", (
            f"Validated HealthResponse.service must be 'event-ingestion', "
            f"got {validated.service!r}"
        )
        assert validated.status == "healthy", (
            f"Validated HealthResponse.status must be 'healthy', "
            f"got {validated.status!r}"
        )
