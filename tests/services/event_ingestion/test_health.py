"""GET /health endpoint happy-path, degraded, and unhealthy states for event-ingestion."""

from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest


# ---------------------------------------------------------------------------
# Mock builders for DB session and Redis client
# ---------------------------------------------------------------------------

def _make_ok_db_session() -> AsyncMock:
    """Async mock session whose execute() succeeds (SELECT 1 returns a row).

    WHY: The /health handler runs 'SELECT 1' against PostgreSQL to check
    connectivity. A successful execute() simulates a healthy PostgreSQL.
    The return value of execute() is not inspected — only the absence of
    an exception signals health.
    """
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock())
    return session


def _make_failing_db_session(exc: Exception | None = None) -> AsyncMock:
    """Async mock session whose execute() raises an exception.

    WHY: Simulates PostgreSQL unavailability. The exception type can be
    sqlalchemy.exc.OperationalError, asyncpg.PostgresConnectionError, or
    a generic Exception — the handler should catch Exception broadly.
    """
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=exc or Exception("Simulated DB connection failure")
    )
    return session


def _make_ok_redis_client() -> AsyncMock:
    """Async mock Redis client whose ping() succeeds.

    WHY: The /health handler calls `(await get_redis()).ping()`. A successful
    ping() simulates a healthy Redis. The return value (True or b'+PONG') is
    not important — absence of exception signals health.
    """
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(return_value=True)
    return redis_client


def _make_failing_redis_client(exc: Exception | None = None) -> AsyncMock:
    """Async mock Redis client whose ping() raises an exception.

    WHY: Simulates Redis unavailability. Per spec §5.6, Redis failure alone
    → 'degraded' (events can still be persisted, but pipeline publish will fail).
    """
    redis_client = AsyncMock()
    redis_client.ping = AsyncMock(
        side_effect=exc or Exception("Simulated Redis connection failure")
    )
    return redis_client


# ---------------------------------------------------------------------------
# Context manager: patch DB + Redis simultaneously
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _patch_health_deps(db_session=None, redis_client=None):
    """Patch naas_shared.database.get_db_session and naas_shared.redis_client.get_redis.

    ASSUMPTION: The /health endpoint uses:
        - get_db_session (as a FastAPI dependency OR called directly)
        - get_redis() (called directly or via dependency)

    We patch at the naas_shared module level because app.main imports these symbols
    from naas_shared at module import time. Patching the naas_shared namespace
    ensures the in-process references used by the handler get the mock.

    If the implementer imports `from naas_shared.database import get_db_session`
    in routes.py or main.py, we also patch at the app.routes / app.main namespace
    (both patches are applied via dependency_overrides + these module-level patches
    for belt-and-suspenders coverage).
    """
    db_sess = db_session if db_session is not None else _make_ok_db_session()
    redis_cli = redis_client if redis_client is not None else _make_ok_redis_client()

    # Build async generator wrapper for get_db_session (it's an async generator dep)
    async def _fake_get_db_session():
        yield db_sess

    # Build coroutine wrapper for get_redis (it's a regular async function)
    async def _fake_get_redis():
        return redis_cli

    # We apply dependency_overrides via app after importing it inside the context.
    # The caller must import app themselves — this context manager only patches modules.
    with (
        patch("naas_shared.database.get_db_session", new=_fake_get_db_session),
        patch("naas_shared.redis_client.get_redis", new=_fake_get_redis),
    ):
        yield db_sess, redis_cli


# ===========================================================================
# CLASS 1 — Both PG and Redis OK → healthy (200)
# ===========================================================================


class TestHealthStatusHealthy:
    """Both PG and Redis OK → status='healthy', HTTP 200.

    WHY: Spec §5.6 — 'Both OK → status="healthy"'. This is the green-path
    state that operators monitor in production. The Docker healthcheck depends
    on HTTP 200 from this endpoint. A wrong status string under healthy conditions
    would trigger false-positive alerts.
    """

    def test_health_returns_200_when_both_deps_ok(self) -> None:
        """GET /health returns HTTP 200 when PG and Redis are both responsive."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as (db_sess, redis_cli):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health expected 200, got {response.status_code}. "
            "Spec §5.6: endpoint always returns HTTP 200."
        )

    def test_health_status_is_healthy_when_both_deps_ok(self) -> None:
        """GET /health body status is 'healthy' when both PG and Redis respond."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("status") == "healthy", (
            f"Expected status='healthy' when both PG and Redis are OK. "
            f"Got: {body.get('status')!r}. Spec §5.6."
        )

    def test_health_service_field_is_event_ingestion_when_healthy(self) -> None:
        """GET /health body service field is 'event-ingestion' in healthy state."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps() as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "event-ingestion", (
            f"Expected service='event-ingestion', got {body.get('service')!r}. "
            "Spec §5.6: Set service='event-ingestion'."
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
        assert validated.service == "event-ingestion"


# ===========================================================================
# CLASS 2 — Redis fails, PG OK → degraded (200)
# ===========================================================================


class TestHealthStatusDegraded:
    """Redis ping fails but PG SELECT 1 succeeds → status='degraded', HTTP 200.

    WHY: Spec §5.6 — 'Redis down but PG OK → "degraded" (events can still be
    persisted, but pipeline publish will fail).' The distinction between "degraded"
    and "unhealthy" is operationally important: degraded means events are durable
    (PG writes succeed) but the pipeline is stalled (no stream messages). Operators
    can replay from PG. Unhealthy means no new events can be persisted at all.
    """

    def test_health_returns_200_when_redis_fails(self) -> None:
        """GET /health returns HTTP 200 even when Redis is unavailable.

        WHY: Spec §5.6 states the endpoint returns HTTP 200 in all three health
        states. Returning non-200 on Redis failure would cause the Docker healthcheck
        to report the container as unhealthy, preventing depends_on services from
        starting — even though ingestion can still write to PostgreSQL.
        """
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(redis_client=_make_failing_redis_client()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health must return 200 even when Redis fails, "
            f"got {response.status_code}. Spec §5.6: always HTTP 200."
        )

    def test_health_status_is_degraded_when_redis_fails_and_pg_ok(self) -> None:
        """GET /health body status is 'degraded' when Redis fails but PG succeeds.

        WHY: Spec §5.6 — 'Redis down but PG OK → "degraded"'. The probe reports
        'degraded', not the unconditional 'healthy' that a stub would return.
        """
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
            "Spec §5.6: 'Redis down but PG OK → degraded'."
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
        assert validated.status == "degraded", (
            f"Validated HealthResponse.status must be 'degraded', got {validated.status!r}."
        )
        assert validated.service == "event-ingestion"

    def test_health_service_field_is_event_ingestion_when_degraded(self) -> None:
        """Service field is 'event-ingestion' even in degraded state."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(redis_client=_make_failing_redis_client()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "event-ingestion", (
            f"service field must be 'event-ingestion' in degraded state, "
            f"got {body.get('service')!r}."
        )


# ===========================================================================
# CLASS 3 — PG fails → unhealthy (200)
# ===========================================================================


class TestHealthStatusUnhealthy:
    """PG SELECT 1 fails → status='unhealthy', HTTP 200.

    WHY: Spec §5.6 — 'PG down → "unhealthy"'. If PostgreSQL is unavailable, the
    ingestion service cannot persist any events at all. Operators must be able to
    distinguish "no new events being persisted" (unhealthy) from "events persisted
    but not streaming" (degraded). This distinction drives different runbooks.
    """

    def test_health_returns_200_when_pg_fails(self) -> None:
        """GET /health returns HTTP 200 even when PostgreSQL is unavailable.

        WHY: Spec §5.6: all three states return HTTP 200. The Docker healthcheck
        relies on the HTTP 200; the status string in the body is for human/alert
        consumption. Returning 503 here would mark the container unhealthy and
        prevent dependent services from starting.
        """
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(db_session=_make_failing_db_session()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200, (
            f"GET /health must return 200 even when PG fails, "
            f"got {response.status_code}. Spec §5.6: always HTTP 200."
        )

    def test_health_status_is_unhealthy_when_pg_fails(self) -> None:
        """GET /health body status is 'unhealthy' when PG SELECT 1 fails.

        WHY: Spec §5.6 — 'PG down → "unhealthy"'. This is the most critical
        health state: no new events can be accepted at all. The probe reports
        'unhealthy' when Postgres is down (not an unconditional 'healthy').
        """
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
            "Spec §5.6: 'PG down → unhealthy'."
        )

    def test_health_status_is_unhealthy_when_both_pg_and_redis_fail(self) -> None:
        """When both PG and Redis fail, status is 'unhealthy' (PG takes precedence).

        WHY: 'Unhealthy' is the most severe state — it means no event can be
        durably accepted. If both PG and Redis fail, PG failure is the dominant
        condition (because PG is the system of record, not Redis). The status
        must be 'unhealthy', not 'degraded'. Spec §5.6 does not define a fourth
        state; 'unhealthy' covers the case where PG is down regardless of Redis.
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
        assert validated.status == "unhealthy", (
            f"Validated HealthResponse.status must be 'unhealthy', got {validated.status!r}."
        )
        assert validated.service == "event-ingestion"

    def test_health_service_field_is_event_ingestion_when_unhealthy(self) -> None:
        """Service field is 'event-ingestion' even in unhealthy state."""
        from starlette.testclient import TestClient
        from app.main import app

        with _patch_health_deps(db_session=_make_failing_db_session()) as _:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body.get("service") == "event-ingestion", (
            f"service field must be 'event-ingestion' in unhealthy state, "
            f"got {body.get('service')!r}."
        )


# ===========================================================================
# CLASS 4 — HTTP status is always 200 (all health states)
# ===========================================================================


class TestHealthAlwaysReturnsHttp200:
    """GET /health must always return HTTP 200, regardless of the body status.

    WHY: Spec §5.6 — 'Per spec §5.6 the endpoint returns HTTP 200 in all three
    cases; the status is in the body.' The Docker healthcheck script uses urllib
    and checks response.status == 200; any other HTTP status causes the container
    to be marked unhealthy. This is a deliberate design: even when the service is
    unhealthy, the /health endpoint itself must respond (it's still up — it just
    can't reach its dependencies).
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

        WHY: Parametrized to exercise all four possible PG/Redis combinations
        in one test class. The expected_body_status values come directly from
        spec §5.6's decision table.
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
            f"got {response.status_code}. Spec §5.6."
        )

        body = response.json()
        assert body.get("status") == expected_body_status, (
            f"Scenario {scenario!r}: expected body status={expected_body_status!r}, "
            f"got {body.get('status')!r}. Spec §5.6 decision table."
        )
