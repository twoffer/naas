"""API route registration and shape for event-ingestion."""

import uuid
from typing import Any

# third-party
import pytest


# ---------------------------------------------------------------------------
# Deterministic test data (no datetime.now(), no unseeded randomness)
# ---------------------------------------------------------------------------

_KNOWN_UUID_1 = uuid.UUID("12345678-1234-5678-1234-567812345678")
_KNOWN_UUID_2 = uuid.UUID("12345678-1234-5678-1234-567812345679")
_KNOWN_UUID_3 = uuid.UUID("12345678-1234-5678-1234-567812345680")
_KNOWN_UUIDS = [_KNOWN_UUID_1, _KNOWN_UUID_2, _KNOWN_UUID_3]

_FIXED_TIMESTAMP = "2024-01-15T10:30:00Z"

_VALID_SINGLE_EVENT = {
    "user_id": "alice",
    "client_ip": "192.168.1.1",
    "protocol": "oidc",
    "timestamp": _FIXED_TIMESTAMP,
    "source": "user",
    "is_synthetic": False,
    "is_historical": False,
    "raw_attributes": {"email": "alice@corp.com"},
}


def _make_valid_event(**overrides: Any) -> dict:
    """Build a valid LoginEventIngest dict with deterministic defaults."""
    base = dict(_VALID_SINGLE_EVENT)
    base.update(overrides)
    return base


def _make_bulk_events(n: int, **overrides: Any) -> list[dict]:
    """Build a list of n valid event dicts with distinct user_ids."""
    return [_make_valid_event(user_id=f"user{i}", **overrides) for i in range(n)]


# ---------------------------------------------------------------------------
# Fake IngestionService — replaces the real service via dependency_overrides
# ---------------------------------------------------------------------------

class FakeIngestionService:
    """Fake IngestionService injected via dependency_overrides.

    Records calls to ingest_one / ingest_many and returns deterministic UUIDs.
    Used to assert route delegation behavior without any DB or Redis.

    WHY a hand-rolled fake rather than MagicMock: we need async methods and
    explicit call tracking. AsyncMock works too, but the fake is more readable
    and does not require patching.
    """

    def __init__(
        self,
        one_returns: uuid.UUID | None = None,
        many_returns: list[uuid.UUID] | None = None,
    ) -> None:
        self._one_returns = one_returns or _KNOWN_UUID_1
        self._many_returns = many_returns or list(_KNOWN_UUIDS)
        self.ingest_one_call_count = 0
        self.ingest_many_call_count = 0
        self.last_ingest_one_arg = None
        self.last_ingest_many_arg = None

    async def ingest_one(self, event) -> uuid.UUID:
        self.ingest_one_call_count += 1
        self.last_ingest_one_arg = event
        return self._one_returns

    async def ingest_many(self, events: list) -> list[uuid.UUID]:
        self.ingest_many_call_count += 1
        self.last_ingest_many_arg = events
        return self._many_returns[: len(events)]


# ---------------------------------------------------------------------------
# Helper: get the app and the service dependency callable
# ---------------------------------------------------------------------------

def _import_app_and_service_dep():
    """Import app + the dependency callable used for IngestionService injection.

    Returns (app, get_ingestion_service) where get_ingestion_service is the
    callable used as the FastAPI Depends(...) argument in routes.py / main.py.

    ASSUMPTION: The implementer will expose the IngestionService dependency as
    `get_ingestion_service` from either `app.routes` or `app.main`. We try
    both locations and fall back to a sentinel that causes the test to fail
    clearly rather than with an obscure AttributeError.

    If neither location works after implementation, the implementer should
    update the override target here to match their chosen name. The comment
    below documents exactly what to change.
    """
    # The router must be mounted for these tests to matter.
    from app.main import app  # routes must be mounted for these tests to matter

    # Try to locate the dependency callable. Implementer: if you name your
    # IngestionService dependency differently, update the lookup below.
    dep_callable = None
    for module_path, attr_name in [
        ("app.main", "get_ingestion_service"),
        ("app.routes", "get_ingestion_service"),
    ]:
        try:
            import importlib
            mod = importlib.import_module(module_path)
            dep_callable = getattr(mod, attr_name, None)
            if dep_callable is not None:
                break
        except (ImportError, ModuleNotFoundError):
            continue

    return app, dep_callable


# ===========================================================================
# CLASS 1 — Endpoint surface: exactly three routes
# ===========================================================================


class TestEndpointSurface:
    """The app must expose exactly three application routes.

    WHY: Spec §5.6 / §7 explicitly states 'Do NOT add endpoints beyond
    /events/ingest, /events/bulk, and /health.' Extra routes widen the attack
    surface. Missing routes mean the spec contract is not fulfilled.

    We ignore FastAPI's auto-generated routes (/openapi.json, /docs, /redoc)
    which FastAPI adds by default and are not part of the spec's surface.
    FastAPI mounts these as special routes (APIRoute with include_in_schema=False
    for some; others are Mount instances). We filter to APIRoute instances only
    and exclude the standard OpenAPI paths.
    """

    _OPENAPI_PATHS = frozenset({"/openapi.json", "/docs", "/redoc"})

    def _application_routes(self, app) -> list:
        """Return non-OpenAPI APIRoute instances from the app."""
        from fastapi.routing import APIRoute
        return [
            r for r in app.routes
            if isinstance(r, APIRoute) and r.path not in self._OPENAPI_PATHS
        ]

    def test_app_has_exactly_three_routes(self) -> None:
        """The app must have exactly 3 non-OpenAPI routes.

        WHY: Spec §5.6 / §7 — exactly POST /events/ingest, POST /events/bulk,
        and GET /health. Any extra route violates spec §7.
        """
        from app.main import app

        routes = self._application_routes(app)
        route_descriptions = [
            f"{sorted(r.methods)} {r.path}" for r in routes
        ]
        assert len(routes) == 3, (
            f"Expected exactly 3 application routes, found {len(routes)}: "
            f"{route_descriptions}. "
            "Spec §5.6 defines exactly POST /events/ingest, POST /events/bulk, GET /health."
        )

    def test_route_post_events_ingest_exists(self) -> None:
        """POST /events/ingest must be registered."""
        from app.main import app

        routes = self._application_routes(app)
        matched = [
            r for r in routes
            if r.path == "/events/ingest" and "POST" in (r.methods or set())
        ]
        assert len(matched) == 1, (
            f"Expected exactly 1 route for POST /events/ingest, found {len(matched)}. "
            "Existing routes: " + str([f"{r.methods} {r.path}" for r in routes])
        )

    def test_route_post_events_bulk_exists(self) -> None:
        """POST /events/bulk must be registered."""
        from app.main import app

        routes = self._application_routes(app)
        matched = [
            r for r in routes
            if r.path == "/events/bulk" and "POST" in (r.methods or set())
        ]
        assert len(matched) == 1, (
            f"Expected exactly 1 route for POST /events/bulk, found {len(matched)}. "
            "Existing routes: " + str([f"{r.methods} {r.path}" for r in routes])
        )

    def test_route_get_health_exists(self) -> None:
        """GET /health must be registered."""
        from app.main import app

        routes = self._application_routes(app)
        matched = [
            r for r in routes
            if r.path == "/health" and "GET" in (r.methods or set())
        ]
        assert len(matched) == 1, (
            f"Expected exactly 1 route for GET /health, found {len(matched)}. "
            "Existing routes: " + str([f"{r.methods} {r.path}" for r in routes])
        )

    def test_no_auth_endpoints_present(self) -> None:
        """No /auth, /token, /login, or /oauth routes must be registered.

        WHY: Spec §7 states 'Do NOT add authentication, JWT verification, or
        rate limiting. Auth is handled upstream by the gateway/Keycloak.'
        Any auth endpoint here is a spec violation and a security risk (unauthenticated
        auth endpoint before the gateway layer).
        """
        from app.main import app

        routes = self._application_routes(app)
        auth_pattern_paths = [
            r.path for r in routes
            if any(seg in r.path for seg in ("/auth", "/token", "/login", "/oauth"))
        ]
        assert len(auth_pattern_paths) == 0, (
            f"Found unexpected auth-related routes: {auth_pattern_paths}. "
            "Spec §7: auth is handled upstream by the gateway."
        )


# ===========================================================================
# CLASS 2 — Single ingest happy path (POST /events/ingest → 202)
# ===========================================================================


class TestSingleIngestHappyPath:
    """POST /events/ingest with a valid body must return 202 and the correct body.

    WHY: Spec §3.3 — 202 Accepted with body {"id": "<uuid>", "status": "accepted"}.
    The route handler must NOT perform any dual-write logic itself; it delegates
    entirely to the injected IngestionService.

    Override strategy: we override the dependency that yields IngestionService
    and assert that (a) the response is 202, (b) the id in the body matches
    the UUID returned by the fake service, and (c) ingest_one was called once.
    """

    def test_single_ingest_returns_202(self) -> None:
        """POST /events/ingest with a valid body returns HTTP 202.

        WHY: 202 Accepted is required by spec §3.3. 200 OK is wrong (the event
        is accepted for asynchronous processing; 200 implies synchronous completion).
        201 Created would imply the resource is directly addressable. 202 is correct.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        app_dep, dep_callable = _import_app_and_service_dep()

        if dep_callable is None:
            pytest.fail(
                "Could not find 'get_ingestion_service' in app.main or app.routes. "
                "The implementer must expose the IngestionService dependency under "
                "that name for test overrides to work. Update _import_app_and_service_dep "
                "if a different name is used."
            )

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202, (
            f"POST /events/ingest expected 202, got {response.status_code}. "
            f"Body: {response.text!r}. Spec §3.3 requires 202 Accepted."
        )

    def test_single_ingest_response_body_contains_id(self) -> None:
        """The response body must contain an 'id' field equal to the assigned UUID.

        WHY: The route must propagate the UUID returned by ingest_one to the caller.
        The caller uses this id to correlate the event with downstream pipeline
        outputs (normalization result, risk decision). A missing or wrong id breaks
        that correlation chain.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found — see _import_app_and_service_dep")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202, f"Unexpected status: {response.status_code}"
        body = response.json()
        assert "id" in body, (
            f"Response body must contain 'id' field. Got: {body}. "
            "Spec §3.3: body is IngestAccepted with fields 'id' and 'status'."
        )
        assert body["id"] == str(_KNOWN_UUID_1), (
            f"Response 'id' must equal the UUID returned by ingest_one "
            f"({_KNOWN_UUID_1}), got {body['id']!r}."
        )

    def test_single_ingest_response_body_status_is_accepted(self) -> None:
        """The response body must have status == 'accepted'.

        WHY: Spec §3.3 body is IngestAccepted where status is Literal['accepted'].
        Downstream callers check body.status == 'accepted' to confirm reception.
        Any other value breaks API contracts.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        body = response.json()
        assert body.get("status") == "accepted", (
            f"Response body status must be 'accepted', got {body.get('status')!r}. "
            "Spec §3.3 / app/schemas.py IngestAccepted."
        )

    def test_single_ingest_calls_ingest_one_exactly_once(self) -> None:
        """The route handler must call service.ingest_one exactly once.

        WHY: The route must delegate to the service, not duplicate the dual-write
        logic inline. Calling ingest_one twice would create two PostgreSQL rows for
        the same request, violating the 'exactly one row per event' contract.
        Calling it zero times would mean nothing was persisted.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert fake.ingest_one_call_count == 1, (
            f"Route must call service.ingest_one exactly once. "
            f"Got {fake.ingest_one_call_count} calls. "
            "The route handler must NOT contain dual-write logic (spec §5.6)."
        )

    def test_single_ingest_does_not_call_ingest_many(self) -> None:
        """POST /events/ingest must NOT call ingest_many.

        WHY: ingest_many wraps all inserts in a single transaction. Using it
        for a single event is harmless but incorrect — it deviates from the
        port contract and makes it harder to distinguish single vs. batch paths
        in structured logs.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert fake.ingest_many_call_count == 0, (
            f"POST /events/ingest must not call service.ingest_many. "
            f"Got {fake.ingest_many_call_count} calls. "
            "Single-event endpoint must use ingest_one, not ingest_many."
        )


# ===========================================================================
# CLASS 3 — Bulk happy path (POST /events/bulk → 202)
# ===========================================================================


class TestBulkIngestHappyPath:
    """POST /events/bulk with a bare JSON array of 3 events returns 202.

    WHY: Spec §§2.2, 3.3 — body is a bare array (not an envelope), response
    is BulkIngestAccepted: {"accepted": 3, "event_ids": [3 uuids], "status": "accepted"}.
    """

    def test_bulk_ingest_returns_202(self) -> None:
        """POST /events/bulk with 3 valid events returns HTTP 202."""
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202, (
            f"POST /events/bulk expected 202, got {response.status_code}. "
            f"Body: {response.text!r}. Spec §3.3."
        )

    def test_bulk_ingest_response_accepted_count_equals_input_length(self) -> None:
        """Response body 'accepted' field must equal the number of submitted events."""
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        body = response.json()
        assert body.get("accepted") == 3, (
            f"BulkIngestAccepted.accepted must be 3, got {body.get('accepted')!r}. "
            "Spec §3.3: accepted == count of events written."
        )

    def test_bulk_ingest_response_event_ids_matches_service_return(self) -> None:
        """Response body 'event_ids' must equal the UUIDs returned by ingest_many."""
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        body = response.json()
        expected_ids = [str(u) for u in _KNOWN_UUIDS]
        assert body.get("event_ids") == expected_ids, (
            f"BulkIngestAccepted.event_ids must be {expected_ids}, "
            f"got {body.get('event_ids')!r}. "
            "Spec §3.3: event_ids are the assigned events.id values."
        )

    def test_bulk_ingest_response_status_is_accepted(self) -> None:
        """Response body 'status' must be 'accepted'."""
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202
        body = response.json()
        assert body.get("status") == "accepted", (
            f"BulkIngestAccepted.status must be 'accepted', got {body.get('status')!r}."
        )

    def test_bulk_ingest_calls_ingest_many_exactly_once(self) -> None:
        """The route handler must call service.ingest_many exactly once.

        WHY: The route must delegate to the service. One call = one batch transaction.
        Multiple calls would break the all-or-nothing guarantee.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert fake.ingest_many_call_count == 1, (
            f"Route must call service.ingest_many exactly once. "
            f"Got {fake.ingest_many_call_count} calls."
        )

    def test_bulk_ingest_does_not_call_ingest_one(self) -> None:
        """POST /events/bulk must NOT call ingest_one for each event in the batch."""
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=list(_KNOWN_UUIDS))
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/bulk", json=_make_bulk_events(3))
        finally:
            app.dependency_overrides.clear()

        assert fake.ingest_one_call_count == 0, (
            f"POST /events/bulk must not call service.ingest_one. "
            f"Got {fake.ingest_one_call_count} calls. "
            "Bulk endpoint must use ingest_many for single-transaction atomicity."
        )

    def test_bulk_ingest_accepts_bare_json_array_not_envelope(self) -> None:
        """POST /events/bulk body must be a bare JSON array, not an envelope object.

        WHY: Spec §2.2 — 'Request body is a bare JSON array of LoginEventIngest objects
        (not wrapped in an envelope).' The persona simulator sends bare arrays.
        An envelope (e.g., {"events": [...]}) would reject real upstream payloads.
        """
        from starlette.testclient import TestClient
        from app.main import app

        fake = FakeIngestionService(many_returns=[_KNOWN_UUID_1])
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        # Bare array of 1 event — this is the spec-required format
        bare_array = [_VALID_SINGLE_EVENT]

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=bare_array)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202, (
            f"POST /events/bulk with a bare JSON array must return 202, "
            f"got {response.status_code}. Body: {response.text!r}. "
            "Spec §2.2: body must be a bare JSON array, not an envelope."
        )


# ===========================================================================
# CLASS 4 — Publish-after-commit resilience (route returns 202 despite publish fail)
# ===========================================================================


class TestPublishFailureResilience:
    """POST /events/ingest must return 202 even when publish fails.

    WHY: Spec §5.5 step 4 — 'If the publish fails after a successful commit:
    the durable record already exists and is replayable. Catch the error, log it,
    and still return 202. Do NOT roll back the PostgreSQL write and DO NOT return
    an error — a committed event is an accepted event.'

    The IngestionService._safe_publish swallows publish failures (spec §5.5 step 4).
    This test validates the route-level behavior: even if the service were to surface
    a publish failure (e.g., a future refactor changes the exception boundary), the
    route must handle it. Here we test the observable behavior from the route's
    perspective: 202 is returned and the assigned id is present in the body.

    We drive this with a fake service that simulates commit-success + publish-failure
    by returning the UUID normally (because _safe_publish already swallows it).
    This is the correct test at the route level — the route's contract is to return
    202 with the id; the service's contract is to swallow publish exceptions.
    """

    def test_single_ingest_returns_202_when_service_swallows_publish_failure(
        self,
    ) -> None:
        """Route returns 202 when service has internally swallowed a publish failure.

        The fake simulates IngestionService behavior when publish fails but
        _safe_publish catches it: ingest_one still returns the UUID normally.
        The route must accept that UUID and return 202.
        """
        from starlette.testclient import TestClient
        from app.main import app

        # This fake models the "committed OK, publish swallowed" case —
        # ingest_one returns normally (which is what IngestionService._safe_publish
        # guarantees per spec §5.5).
        fake = FakeIngestionService(one_returns=_KNOWN_UUID_1)
        _, dep_callable = _import_app_and_service_dep()
        if dep_callable is None:
            pytest.fail("get_ingestion_service dependency not found")

        app.dependency_overrides[dep_callable] = lambda: fake
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=_VALID_SINGLE_EVENT)
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 202, (
            f"Route must return 202 when service successfully returns a UUID "
            f"(even after internally swallowing a publish failure). "
            f"Got {response.status_code}. Body: {response.text!r}."
        )
        body = response.json()
        assert body.get("id") == str(_KNOWN_UUID_1), (
            f"Response id must be the UUID returned by the service ({_KNOWN_UUID_1}), "
            f"got {body.get('id')!r}."
        )
