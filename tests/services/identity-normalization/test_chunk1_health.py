# Component: NAAS Spec 2 — Chunk 1: GET /health with dependency probing
# Mode: TDD — tests MUST fail until the implementer creates app/main.py with
#   a real /health handler that probes PG and Redis.
#
# What these tests validate (spec §5.8):
#   (a) Both PG and Redis OK → 200 with status="healthy", service="identity-normalization"
#   (b) Redis ping fails but PG OK → 200 with status="degraded"
#   (c) PG check fails → 200 with status="unhealthy"
#   (d) HTTP status code is ALWAYS 200 regardless of health status
#   (e) Response body conforms to the shared HealthResponse model in all three cases
#
# Override strategy:
#   Identical to the event-ingestion Chunk 3 pattern (test_chunk3_health.py):
#   - Patch naas_shared.database.get_db_session with an async generator that
#     yields a mock session whose execute() succeeds or raises.
#   - Patch naas_shared.redis_client.get_redis with a coroutine that returns
#     a mock Redis client whose ping() succeeds or raises.
#   Both patches are applied at the naas_shared namespace level.
#
# Service identity:
#   The key difference from event-ingestion is service="identity-normalization"
#   (not "event-ingestion"). This is verified in every test class.
#
# TDD state:
#   services/identity-normalization/app/main.py does not exist yet.
#   All tests MUST fail with ModuleNotFoundError or assertion errors until
#   the implementer creates the app and wires the /health handler.

# stdlib
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


# ---------------------------------------------------------------------------
# Mock builders for DB session and Redis client
# ---------------------------------------------------------------------------

def _make_ok_db_session() -> AsyncMock:
    """Async mock session whose execute() succeeds (SELECT 1 returns a row).

    WHY: The /health handler runs a SELECT 1 against PostgreSQL to check
    connectivity. A successful execute() simulates a healthy PostgreSQL.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    return session


def _make_failing_db_session(exc: Exception | None = None) -> AsyncMock:
    """Async mock session whose execute() raises an exception.

    WHY: Simulates PostgreSQL unavailability. Per spec §5.8, PG down → 'unhealthy'.
    """
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=exc or Exception("Simulated PG connection failure")
    )
    return session


def _make_ok_redis_client() -> AsyncMock:
    """Async mock Redis client whose ping() succeeds.

    WHY: The /health handler calls get_redis().ping() to probe Redis.
    Successful ping() simulates a healthy Redis.
    """
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(return_value=True)
    return redis_client


def _make_failing_redis_client(exc: Exception | None = None) -> AsyncMock:
    """Async mock Redis client whose ping() raises an exception.

    WHY: Simulates Redis unavailability. Per spec §5.8, Redis down but PG OK
    → 'degraded'.
    """
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(
        side_effect=exc or Exception("Simulated Redis connection failure")
    )
    return redis_client


# ---------------------------------------------------------------------------
# Context manager: patch DB + Redis simultaneously
# ---------------------------------------------------------------------------

@contextmanager
def _patch_health_deps(db_session=None, redis_client=None):
    """Patch naas_shared.database.get_db_session and naas_shared.redis_client.get_redis.

    ASSUMPTION: The /health endpoint uses:
        - get_db_session (as a FastAPI dependency or called directly)
        - get_redis() (called directly or via dependency)

    We patch at the naas_shared module level because app.main imports these symbols
    from naas_shared at module import time.
    """
    db_sess = db_session if db_session is not None else _make_ok_db_session()
    redis_cli = redis_client if redis_client is not None else _make_ok_redis_client()

    async def _fake_get_db_session():
        yield db_sess

    async def _fake_get_redis():
        return redis_cli

    with (
        patch("naas_shared.database.get_db_session", new=_fake_get_db_session),
        patch("naas_shared.redis_client.get_redis", new=_fake_get_redis),
    ):
        yield db_sess, redis_cli


# ===========================================================================
# CLASS 1 — Both PG and Redis OK → healthy (200)
# ===========================================================================


class TestHealthStatusHealthy:
    """Both PG and Redis OK → status='healthy', service='identity-normalization', HTTP 200.

    WHY: Spec §5.8 — 'Both OK → status="healthy"'. This is the green-path
    state probed by the Docker healthcheck. A wrong service name or status string
    prevents operators from identifying which NAAS component is healthy.
    """

    def test_health_returns_200_when_both_deps_ok(self) -> None:
        """GET /health returns HTTP 200 when PG and Redis are both responsive."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health expected 200, got {response.status_code}. "
            "Spec §5.8: endpoint always returns HTTP 200."
        )

    def test_health_status_is_healthy_when_both_deps_ok(self) -> None:
        """GET /health body status is 'healthy' when PG and Redis respond."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "healthy", (
            f"Expected status='healthy' when both PG and Redis are OK. "
            f"Got: {body.get('status')!r}. Spec §5.8."
        )

    def test_health_service_field_is_identity_normalization_when_healthy(self) -> None:
        """GET /health body service field is 'identity-normalization' in healthy state.

        WHY: This service is NOT event-ingestion. Using the wrong service name
        (e.g., copy-pasting from event-ingestion) causes operators to misidentify
        the health source and miss deployment errors for this specific service.
        """
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "identity-normalization", (
            f"Expected service='identity-normalization', got {body.get('service')!r}. "
            "Spec §5.8: Set service='identity-normalization'. "
            "Do not copy the value from event-ingestion (which is 'event-ingestion')."
        )

    def test_health_body_conforms_to_health_response_schema_when_healthy(self) -> None:
        """GET /health body must validate against the shared HealthResponse model."""
        from naas_shared.models import HealthResponse
        from pydantic import ValidationError
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        try:
            validated = HealthResponse.model_validate(body)
        except ValidationError as exc:
            pytest.fail(
                f"GET /health body failed HealthResponse validation (healthy state): "
                f"{exc}. Body: {body}"
            )
        assert validated.status == "healthy"
        assert validated.service == "identity-normalization"


# ===========================================================================
# CLASS 2 — Redis fails, PG OK → degraded (200)
# ===========================================================================


class TestHealthStatusDegraded:
    """Redis ping fails but PG SELECT 1 succeeds → status='degraded', HTTP 200.

    WHY: Spec §5.8 — 'Redis down but PG OK → degraded'. The identity-normalization
    service must mirror the same health classification as event-ingestion: Redis
    failure means the stream consumer cannot publish normalized events (pipeline
    stalls) but the DB is reachable for status queries.

    MUST FAIL AGAINST ANY STUB: A stub that always returns 'healthy' will fail
    these tests. The real implementation must probe both dependencies.
    """

    def test_health_returns_200_when_redis_fails(self) -> None:
        """GET /health returns HTTP 200 even when Redis is unavailable.

        WHY: Spec §5.8 states the endpoint returns HTTP 200 in all three health
        states. Returning non-200 on Redis failure would cause the Docker healthcheck
        to report the container as unhealthy and block depends_on services.
        """
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(redis_client=_make_failing_redis_client()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health must return 200 even when Redis fails, "
            f"got {response.status_code}. Spec §5.8: always HTTP 200."
        )

    def test_health_status_is_degraded_when_redis_fails_and_pg_ok(self) -> None:
        """GET /health body status is 'degraded' when Redis fails but PG succeeds."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(
            db_session=_make_ok_db_session(),
            redis_client=_make_failing_redis_client(),
        ) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "degraded", (
            f"Expected status='degraded' when Redis fails and PG is OK. "
            f"Got: {body.get('status')!r}. "
            "Spec §5.8: 'Redis down but PG OK → degraded'."
        )

    def test_health_service_field_is_identity_normalization_when_degraded(self) -> None:
        """Service field is 'identity-normalization' even in degraded state."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(redis_client=_make_failing_redis_client()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "identity-normalization", (
            f"service field must be 'identity-normalization' in degraded state, "
            f"got {body.get('service')!r}."
        )

    def test_health_body_conforms_to_health_response_schema_when_degraded(self) -> None:
        """GET /health body must validate against HealthResponse when degraded."""
        from naas_shared.models import HealthResponse
        from pydantic import ValidationError
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(redis_client=_make_failing_redis_client()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        try:
            validated = HealthResponse.model_validate(body)
        except ValidationError as exc:
            pytest.fail(
                f"GET /health body failed HealthResponse validation (degraded state): "
                f"{exc}. Body: {body}"
            )
        assert validated.status == "degraded"
        assert validated.service == "identity-normalization"


# ===========================================================================
# CLASS 3 — PG fails → unhealthy (200)
# ===========================================================================


class TestHealthStatusUnhealthy:
    """PG SELECT 1 fails → status='unhealthy', HTTP 200.

    WHY: Spec §5.8 — 'PG down → unhealthy'. If PostgreSQL is unavailable, the
    normalization service cannot persist normalized_attributes to the events table.
    Operators must be able to distinguish 'no normalization persisted' (unhealthy)
    from 'normalized but stream publish failing' (degraded).

    MUST FAIL AGAINST ANY STUB: stub always returns 'healthy'.
    """

    def test_health_returns_200_when_pg_fails(self) -> None:
        """GET /health returns HTTP 200 even when PostgreSQL is unavailable."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(db_session=_make_failing_db_session()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health must return 200 even when PG fails, "
            f"got {response.status_code}. Spec §5.8: always HTTP 200."
        )

    def test_health_status_is_unhealthy_when_pg_fails(self) -> None:
        """GET /health body status is 'unhealthy' when PG SELECT 1 fails."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(
            db_session=_make_failing_db_session(),
            redis_client=_make_ok_redis_client(),
        ) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "unhealthy", (
            f"Expected status='unhealthy' when PG fails. "
            f"Got: {body.get('status')!r}. "
            "Spec §5.8: 'PG down → unhealthy'."
        )

    def test_health_status_is_unhealthy_when_both_pg_and_redis_fail(self) -> None:
        """When both PG and Redis fail, status is 'unhealthy' (PG takes precedence).

        WHY: 'Unhealthy' is the most severe state — PG failure means no normalized
        event can be durably persisted. PG down dominates Redis down; the status
        must be 'unhealthy', not 'degraded'.
        """
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(
            db_session=_make_failing_db_session(),
            redis_client=_make_failing_redis_client(),
        ) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "unhealthy", (
            f"Expected status='unhealthy' when both PG and Redis fail. "
            f"Got: {body.get('status')!r}. "
            "When PG is down (regardless of Redis), status must be 'unhealthy'."
        )

    def test_health_service_field_is_identity_normalization_when_unhealthy(self) -> None:
        """Service field is 'identity-normalization' even in unhealthy state."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(db_session=_make_failing_db_session()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "identity-normalization", (
            f"service field must be 'identity-normalization' in unhealthy state, "
            f"got {body.get('service')!r}."
        )

    def test_health_body_conforms_to_health_response_schema_when_unhealthy(self) -> None:
        """GET /health body must validate against HealthResponse when unhealthy."""
        from naas_shared.models import HealthResponse
        from pydantic import ValidationError
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(db_session=_make_failing_db_session()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        try:
            validated = HealthResponse.model_validate(body)
        except ValidationError as exc:
            pytest.fail(
                f"GET /health body failed HealthResponse validation (unhealthy state): "
                f"{exc}. Body: {body}"
            )
        assert validated.status == "unhealthy"
        assert validated.service == "identity-normalization"


# ===========================================================================
# CLASS 4 — HTTP status is always 200 (parametrized over all health states)
# ===========================================================================


class TestHealthAlwaysReturnsHttp200:
    """GET /health must always return HTTP 200, regardless of the body status.

    WHY: Spec §5.8 — the endpoint returns HTTP 200 in all three cases; the status
    is in the body. The Docker healthcheck checks response.status == 200; any other
    HTTP status causes the container to be marked unhealthy and blocks depends_on
    services (signal-enrichment, risk-evaluator) from starting — even when the
    service itself is running and reachable.
    """

    @pytest.mark.parametrize("scenario,db_ok,redis_ok,expected_body_status", [
        ("both_ok", True, True, "healthy"),
        ("redis_down", True, False, "degraded"),
        ("pg_down", False, True, "unhealthy"),
        ("both_down", False, False, "unhealthy"),
    ])
    def test_health_always_http_200(
        self,
        scenario: str,
        db_ok: bool,
        redis_ok: bool,
        expected_body_status: str,
    ) -> None:
        """HTTP 200 is always returned; body status reflects the actual state.

        WHY: Parametrized to exercise all four PG/Redis combinations in one test
        class. The expected_body_status values come directly from spec §5.8's
        decision table.
        """
        from starlette.testclient import TestClient
        from app.main import app

        db_session = _make_ok_db_session() if db_ok else _make_failing_db_session()
        redis_client = _make_ok_redis_client() if redis_ok else _make_failing_redis_client()

        with _patch_health_deps(db_session=db_session, redis_client=redis_client) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health (scenario={scenario!r}) must always return HTTP 200, "
            f"got {response.status_code}. Spec §5.8."
        )

        body = response.json()
        assert body.get("status") == expected_body_status, (
            f"Scenario {scenario!r}: expected body status={expected_body_status!r}, "
            f"got {body.get('status')!r}. Spec §5.8 decision table."
        )
