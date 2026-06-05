# Component: NAAS Spec 2 — Chunk 1: identity-normalization app skeleton
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/app/__init__.py
#   services/identity-normalization/app/main.py
#
# What these tests validate:
#   - `from app.main import app` resolves to a FastAPI instance
#   - `app` is created via a module-level `app = create_app()` call pattern
#   - The FastAPI app exists and is an ASGI-compatible instance
#   - The service exposes ONLY /health — no other routes in Chunk 1
#
# sys.path strategy:
#   We insert services/identity-normalization onto sys.path so that
#   `from app.main import app` resolves once the implementer creates
#   app/main.py in that directory. This mirrors how uvicorn runs the service:
#   it sets the working directory to services/identity-normalization and imports
#   app.main:app.  Tests that import app.main without this path setup fail with
#   ModuleNotFoundError, which is the correct TDD initial state.
#
# External dependencies:
#   app/main.py will import from naas_shared (database, redis_client, logging,
#   models, config). The TestClient from starlette (bundled with FastAPI) is used
#   for isolation — it does NOT require a running DB or Redis.
#
# TDD state:
#   services/identity-normalization/app/ does not exist yet. All tests MUST fail
#   with ModuleNotFoundError until the implementer creates the app package and
#   main.py.

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
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"

# Inject shared/ so naas_shared is importable (required by app.main at import time).
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

# Inject services/identity-normalization/ so `from app.main import app` resolves
# once the implementer creates app/main.py there.
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


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

        WHY: ModuleNotFoundError here means services/identity-normalization/app/main.py
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
# CLASS 2 — Only /health route is exposed in Chunk 1
# ===========================================================================


class TestOnlyHealthRouteExposed:
    """The identity-normalization service must expose ONLY /health in Chunk 1.

    WHY: Spec §5.8 — 'Do NOT add endpoints beyond /health' for this chunk.
    Additional routes (event submission, normalization trigger, etc.) are not
    part of this chunk's scope boundary. Exposing them prematurely would create
    untested, unspecified behavior in this service.

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

        with (
            patch("naas_shared.database.get_db_session", return_value=mock_session),
            patch("naas_shared.redis_client.get_redis", return_value=mock_redis),
        ):
            yield

    def test_health_route_is_registered(self) -> None:
        """The FastAPI app must have a route registered for GET /health.

        WHY: Without a /health route, the Docker healthcheck fails immediately,
        and any service that depends_on identity-normalization with
        condition: service_healthy will never start.
        """
        from app.main import app

        route_paths = [route.path for route in app.routes]
        assert "/health" in route_paths, (
            f"Expected /health in app routes. Found: {route_paths}. "
            "The spec §5.8 requires a GET /health endpoint."
        )

    def test_no_routes_beyond_health_and_openapi(self) -> None:
        """No application routes beyond /health must be registered in Chunk 1.

        WHY: Spec §7 — 'Do NOT add endpoints beyond /health'. The consumer loop
        and normalization endpoints belong to later chunks. Extra routes here would
        indicate scope creep and untested behavior.

        OpenAPI routes (/docs, /redoc, /openapi.json) are FastAPI built-ins and
        are excluded from this assertion.
        """
        from app.main import app

        # Paths that are acceptable in Chunk 1 (FastAPI built-ins + the single endpoint)
        acceptable_paths = {"/health", "/docs", "/redoc", "/openapi.json"}

        application_routes = [
            route.path
            for route in app.routes
            if hasattr(route, "path") and route.path not in acceptable_paths
        ]
        assert not application_routes, (
            f"Chunk 1 must expose ONLY /health. "
            f"Found unexpected routes: {application_routes}. "
            "Spec §7: do not add endpoints beyond /health in this chunk."
        )

    def test_get_health_via_test_client_returns_200(self) -> None:
        """GET /health must respond with HTTP 200 via TestClient.

        WHY: End-to-end validation that the route is wired to a handler, not just
        registered as a placeholder. A route without a handler returns 422 or 500.
        """
        from starlette.testclient import TestClient

        from app.main import app

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health expected HTTP 200, got {response.status_code}. "
            "The route must be registered and wired to a working handler."
        )
