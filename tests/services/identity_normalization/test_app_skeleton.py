"""app.main exists, exposes a FastAPI instance, and serves GET /health for identity-normalization."""

from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest

# ===========================================================================
# CLASS 1 — Import: app.main resolves to a FastAPI instance
# ===========================================================================


class TestAppMainImport:
    """app.main must be importable and must expose a FastAPI instance named `app`.

    WHY: The Dockerfile CMD is 'uvicorn app.main:app --host 0.0.0.0 --port 8002'.
    If `app` is not a FastAPI instance (or is absent), uvicorn crashes immediately
    with 'Could not import module app.main' or 'app is not an ASGI application'.
    """

    def test_app_main_module_is_importable(self) -> None:
        """from app.main import app must succeed without raising.

        WHY: The module exposes an importable FastAPI `app`. A ModuleNotFoundError
        means services/identity-normalization/app/main.py is absent or broken.
        """
        from app.main import app  # noqa: F401

    def test_app_is_a_fastapi_instance(self) -> None:
        """app must be an instance of fastapi.FastAPI.

        WHY: uvicorn's --app argument expects an ASGI callable. FastAPI is the
        required framework per the project tech stack. A plain dict, None, or a
        Starlette instance without FastAPI's OpenAPI/validation layer would break
        the service's contract with upstream callers.
        """
        from app.main import app
        from fastapi import FastAPI

        assert isinstance(app, FastAPI), (
            f"Expected app to be a FastAPI instance, got {type(app).__name__!r}. "
            "The Dockerfile CMD is 'uvicorn app.main:app' — app must be a FastAPI object."
        )


# ===========================================================================
# CLASS 2 — Only /health route is exposed
# ===========================================================================


class TestOnlyHealthRouteExposed:
    """The identity-normalization service must expose ONLY /health.

    WHY: Spec §5.8 — 'Do NOT add endpoints beyond /health'.
    Additional routes (event submission, normalization trigger, etc.) are not
    within the scope of this service's initial spec. Exposing them prematurely
    would create untested, unspecified behavior in this service.

    We test this by checking the route table of the FastAPI app.
    """

    @pytest.fixture(autouse=True)
    def patch_external_deps(self):
        """Patch DB and Redis so the app module can be imported without infrastructure."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)

        # Patch the lifespan's background consumer + group setup so entering the
        # TestClient context manager (which fires the FastAPI lifespan) does NOT
        # spawn the real run_consumer_loop. Against an AsyncMock Redis, that loop's
        # `await redis.xreadgroup(..., block=2000)` returns instantly (block is
        # meaningless to a mock) and never suspends, so its `while True` monopolizes
        # the event loop — starving the /health request and hanging the process at
        # 100% CPU. run_consumer_loop is patched at the app.main binding (where it is
        # imported) so other tests that drive app.consumer.run_consumer_loop
        # directly are unaffected.
        with (
            patch("naas_shared.database.get_db_session", return_value=mock_session),
            patch("naas_shared.redis_client.get_redis", return_value=mock_redis),
            patch("naas_shared.redis_client.ensure_consumer_group", new=AsyncMock()),
            patch("app.main.run_consumer_loop", new=AsyncMock()),
        ):
            yield

    def test_health_route_is_registered(self) -> None:
        """The FastAPI app must have a route registered for GET /health.

        WHY: Without a /health route, the Docker healthcheck fails immediately,
        and any service that depends_on identity-normalization with
        condition: service_healthy will never start.
        """
        from app.main import app

        from tests.helpers import iter_routes

        route_paths = [route.path for route in iter_routes(app.routes)]
        assert "/health" in route_paths, (
            f"Expected /health in app routes. Found: {route_paths}. "
            "The spec §5.8 requires a GET /health endpoint."
        )

    def test_no_routes_beyond_health_and_openapi(self) -> None:
        """No application routes beyond /health must be registered.

        WHY: Spec §7 — 'Do NOT add endpoints beyond /health'. Extra routes would
        indicate scope creep and untested behavior.

        OpenAPI routes (/docs, /redoc, /openapi.json) are FastAPI built-ins and
        are excluded from this assertion.
        """
        from app.main import app

        from tests.helpers import iter_routes

        # Acceptable paths: FastAPI built-ins + the single health endpoint
        acceptable_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

        application_routes = [
            route.path
            for route in iter_routes(app.routes)
            if hasattr(route, "path") and route.path not in acceptable_paths
        ]
        assert not application_routes, (
            f"Service must expose ONLY /health. "
            f"Found unexpected routes: {application_routes}. "
            "Spec §7: do not add endpoints beyond /health."
        )

    def test_get_health_via_test_client_returns_200(self) -> None:
        """GET /health must respond with HTTP 200 via TestClient.

        WHY: End-to-end validation that the route is wired to a handler, not just
        registered as a placeholder. A route without a handler returns 422 or 500.
        """
        from app.main import app
        from starlette.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health expected HTTP 200, got {response.status_code}. "
            "The route must be registered and wired to a working handler."
        )
