"""app.main exists, exposes a FastAPI instance, and serves GET /health for event-ingestion."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest


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

        WHY: The module exposes an importable FastAPI `app`. A ModuleNotFoundError
        means services/event-ingestion/app/main.py is absent or broken.
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

        # The health handler calls get_session_factory() to get a factory,
        # then uses it as an async context manager: async with factory() as session.
        @asynccontextmanager
        async def _fake_session_cm():
            yield mock_session

        def _fake_get_session_factory():
            return _fake_session_cm

        # Mock Redis client that succeeds on ping()
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        # Patch get_session_factory and get_redis at the naas_shared module level
        # so the module-reference lookups in the health handler pick them up.
        with (
            patch(
                "naas_shared.database.get_session_factory",
                new=_fake_get_session_factory,
            ),
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
