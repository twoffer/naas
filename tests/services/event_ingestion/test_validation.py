"""Input validation logic for login event ingestion."""

import uuid

# third-party
import pytest


# ---------------------------------------------------------------------------
# Deterministic test data
# ---------------------------------------------------------------------------

_KNOWN_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_FIXED_TIMESTAMP = "2024-01-15T10:30:00Z"

_VALID_EVENT: dict = {
    "user_id": "alice",
    "client_ip": "192.168.1.1",
    "protocol": "oidc",
    "timestamp": _FIXED_TIMESTAMP,
    "source": "user",
    "is_synthetic": False,
    "is_historical": False,
    "raw_attributes": {},
}


def _minimal_valid_event(user_id: str = "u") -> dict:
    """Return the minimal dict that passes LoginEventIngest validation."""
    return {
        "user_id": user_id,
        "client_ip": "8.8.8.8",
        "protocol": "oidc",
        "timestamp": _FIXED_TIMESTAMP,
    }


# ---------------------------------------------------------------------------
# Fake IngestionService — call-counter only, no side effects
# ---------------------------------------------------------------------------


class SpyIngestionService:
    """Minimal spy: records call counts. Returns deterministic values.

    WHY a spy (not a full fake): validation tests only need to assert that
    the handler was NOT called. We don't need to verify the return value because
    422 responses have no handler output. Using a spy rather than a full fake
    makes the test intent explicit — we are counting calls, not testing return values.
    """

    def __init__(self) -> None:
        self.ingest_one_call_count = 0
        self.ingest_many_call_count = 0

    async def ingest_one(self, event) -> uuid.UUID:
        self.ingest_one_call_count += 1
        return _KNOWN_UUID

    async def ingest_many(self, events: list) -> list[uuid.UUID]:
        self.ingest_many_call_count += 1
        return [_KNOWN_UUID] * len(events)


# ---------------------------------------------------------------------------
# Helper: locate the IngestionService dependency callable
# ---------------------------------------------------------------------------


def _get_dep_callable():
    """Return get_ingestion_service from app.routes — the single canonical home."""
    from app.routes import get_ingestion_service

    return get_ingestion_service


# ===========================================================================
# CLASS 1 — Bulk size validation (422, writes nothing)
# ===========================================================================


class TestBulkSizeValidation:
    """POST /events/bulk must reject arrays that are too small or too large.

    WHY: Spec §2.2 — 'The array MUST contain at least 1 and at most 5000 events;
    a larger array is rejected with HTTP 422.' An empty array would mean the route
    triggers a transaction with no rows, which is wasteful and semantically wrong.
    An array > 5000 exceeds the historical-generation ceiling and could be used to
    overwhelm the ingestion service.

    The 422 must come from request validation BEFORE the handler runs, so the service
    must NOT be called. We verify this with the spy's call count.
    """

    def test_empty_array_returns_422(self) -> None:
        """POST /events/bulk with an empty array returns HTTP 422.

        WHY: A zero-length batch provides no events to persist and would create
        an empty transaction. The spec mandates at least 1 event. FastAPI should
        reject this at the body-validation layer.
        """
        from starlette.testclient import TestClient
        from app.main import app

        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=[])
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"POST /events/bulk with empty array must return 422, "
            f"got {response.status_code}. Body: {response.text!r}. "
            "Spec §2.2: array must contain at least 1 event."
        )

    def test_empty_array_does_not_call_ingest_many(self) -> None:
        """When empty array → 422, service.ingest_many must NOT be called.

        WHY: A 422 response means request validation failed before the handler
        ran. If ingest_many were called, it would mean the validation was done
        inside the handler (wrong) or validation was skipped entirely (very wrong).
        """
        from starlette.testclient import TestClient
        from app.main import app

        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/bulk", json=[])
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert spy.ingest_many_call_count == 0, (
            f"service.ingest_many must NOT be called when the array is empty. "
            f"Got {spy.ingest_many_call_count} calls. "
            "Validation must reject at the FastAPI body-parsing layer, before the handler."
        )

    def test_oversized_array_returns_422(self) -> None:
        """POST /events/bulk with 5001 events returns HTTP 422.

        WHY: Spec §2.2 — maximum 5000 events (the historical-generation ceiling).
        An array of 5001 must be rejected before the handler runs. The test
        constructs 5001 minimal valid event dicts — this is unavoidable for a
        boundary test.
        """
        from starlette.testclient import TestClient
        from app.main import app

        # 5001 minimal valid events — deterministic, no network calls
        oversized = [_minimal_valid_event(user_id=f"u{i}") for i in range(5001)]

        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=oversized)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"POST /events/bulk with 5001 events must return 422, "
            f"got {response.status_code}. "
            "Spec §2.2: maximum 5000 events per batch."
        )

    def test_oversized_array_does_not_call_ingest_many(self) -> None:
        """When 5001 elements → 422, service.ingest_many must NOT be called.

        WHY: If ingest_many were called with 5001 events, it would create 5001
        PostgreSQL rows before we even checked the limit, wasting resources and
        ignoring the spec constraint. Validation must fire first.
        """
        from starlette.testclient import TestClient
        from app.main import app

        oversized = [_minimal_valid_event(user_id=f"u{i}") for i in range(5001)]

        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/bulk", json=oversized)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert spy.ingest_many_call_count == 0, (
            f"service.ingest_many must NOT be called when the array has 5001 elements. "
            f"Got {spy.ingest_many_call_count} calls. "
            "The size check must occur at validation time, not inside the handler."
        )

    def test_exactly_5000_events_is_accepted(self) -> None:
        """POST /events/bulk with exactly 5000 events must NOT return 422.

        WHY: 5000 is the maximum allowed value per spec §2.2. The boundary must
        be inclusive (5000 allowed, 5001 rejected). A <= vs < off-by-one would
        reject valid batches at exactly the maximum, breaking the simulator which
        generates exactly 5000 historical events.
        """
        from starlette.testclient import TestClient
        from app.main import app

        max_events = [_minimal_valid_event(user_id=f"u{i}") for i in range(5000)]
        fake_ids = [uuid.uuid4() for _ in range(5000)]

        class _MaxFake:
            async def ingest_one(self, event):
                return uuid.uuid4()

            async def ingest_many(self, events):
                return fake_ids[: len(events)]

        dep_callable = _get_dep_callable()
        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: _MaxFake()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=max_events)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code != 422, (
            f"POST /events/bulk with exactly 5000 events must not return 422 "
            f"(boundary is inclusive). Got {response.status_code}. "
            "Spec §2.2: 'at most 5000 events' — 5000 is allowed."
        )

    @pytest.mark.parametrize(
        "length,expect_422",
        [
            (0, True),
            (1, False),
            (5000, False),
            (5001, True),
        ],
    )
    def test_bulk_size_boundary_parametrized(
        self, length: int, expect_422: bool
    ) -> None:
        """Parametrized boundary check for bulk array length constraints.

        WHY: Parametrized tests catch off-by-one errors at both boundaries
        (too small: 0 vs 1; too large: 5000 vs 5001). Testing only the extremes
        would miss the inclusive/exclusive edge.
        """
        from starlette.testclient import TestClient
        from app.main import app

        events = [_minimal_valid_event(user_id=f"u{i}") for i in range(length)]
        fake_ids = [uuid.uuid4() for _ in range(max(length, 1))]

        class _BoundaryFake:
            async def ingest_one(self, event):
                return uuid.uuid4()

            async def ingest_many(self, evts):
                return fake_ids[: len(evts)]

        dep_callable = _get_dep_callable()
        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: _BoundaryFake()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/bulk", json=events)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        if expect_422:
            assert response.status_code == 422, (
                f"Array of length {length} must return 422, got {response.status_code}."
            )
        else:
            assert response.status_code != 422, (
                f"Array of length {length} must NOT return 422, got {response.status_code}."
            )


# ===========================================================================
# CLASS 2 — Field validation rejections (422, writes nothing)
# ===========================================================================


class TestFieldValidationRejections:
    """POST /events/ingest must reject invalid field values with 422.

    WHY: Spec §§2.1, 3.3 — validation failures return 422 with FastAPI's standard
    validation error body. Importantly, the service must NOT be called when
    validation fails (the dual-write must not happen for invalid requests).

    These tests validate the shared model's constraints as surfaced by the routes:
    - client_ip: IPv4 only, each octet 0–255 (the regex in LoginEventBase)
    - protocol: Literal["oidc", "saml", "ldap"] only
    """

    def test_invalid_client_ip_octet_out_of_range_returns_422(self) -> None:
        """POST /events/ingest with client_ip='256.0.0.1' returns HTTP 422.

        WHY: '256.0.0.1' fails the shared LoginEventBase IPv4 regex (octet 0–255
        range). The spec §2.1 states 'Non-IPv4 or malformed values are rejected
        with HTTP 422.' This must be caught at Pydantic validation, not inside the
        route handler.

        Reference IP from project test-data values: 256.0.0.1 (deliberately invalid).
        """
        from starlette.testclient import TestClient
        from app.main import app

        bad_ip_payload = dict(_VALID_EVENT, client_ip="256.0.0.1")
        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=bad_ip_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"POST /events/ingest with client_ip='256.0.0.1' must return 422, "
            f"got {response.status_code}. Body: {response.text!r}. "
            "Spec §2.1: each IP octet must be 0–255."
        )

    def test_invalid_client_ip_does_not_call_ingest_one(self) -> None:
        """When client_ip is invalid, service.ingest_one must NOT be called.

        WHY: A 422 means the request failed Pydantic validation before the handler
        ran. If ingest_one were called, an invalid IP would be written to PostgreSQL,
        which has an INET column type that rejects '256.0.0.1' — causing a DB error
        that would return 500. This is the defense-in-depth: validation at the Pydantic
        layer prevents the DB error layer from being reached.
        """
        from starlette.testclient import TestClient
        from app.main import app

        bad_ip_payload = dict(_VALID_EVENT, client_ip="256.0.0.1")
        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/ingest", json=bad_ip_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert spy.ingest_one_call_count == 0, (
            f"service.ingest_one must NOT be called when client_ip validation fails. "
            f"Got {spy.ingest_one_call_count} calls. "
            "Pydantic validation must reject the request before the handler executes."
        )

    def test_unknown_protocol_returns_422(self) -> None:
        """POST /events/ingest with protocol='kerberos' returns HTTP 422.

        WHY: Spec §2.1 — protocol is Literal['oidc', 'saml', 'ldap']. 'kerberos'
        is not a valid value; the shared LoginEventBase field validates against this
        Literal. An unknown protocol that reaches the pipeline would cause the
        Identity Normalization service to fail with no adapter for the protocol.
        """
        from starlette.testclient import TestClient
        from app.main import app

        bad_protocol_payload = dict(_VALID_EVENT, protocol="kerberos")
        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=bad_protocol_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"POST /events/ingest with protocol='kerberos' must return 422, "
            f"got {response.status_code}. Body: {response.text!r}. "
            "Spec §2.1: protocol must be one of 'oidc', 'saml', 'ldap'."
        )

    def test_unknown_protocol_does_not_call_ingest_one(self) -> None:
        """When protocol is invalid, service.ingest_one must NOT be called.

        WHY: Same rationale as the client_ip test — validation must fire at the
        Pydantic layer, before the handler. An unknown protocol that slips through
        would propagate to Identity Normalization (via the Redis stream) where it
        would cause a routing error with no adapter to handle it.
        """
        from starlette.testclient import TestClient
        from app.main import app

        bad_protocol_payload = dict(_VALID_EVENT, protocol="kerberos")
        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                client.post("/events/ingest", json=bad_protocol_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert spy.ingest_one_call_count == 0, (
            f"service.ingest_one must NOT be called when protocol='kerberos'. "
            f"Got {spy.ingest_one_call_count} calls."
        )

    def test_missing_required_field_returns_422(self) -> None:
        """POST /events/ingest with missing required 'user_id' returns HTTP 422.

        WHY: user_id is required (no default). A missing required field must be
        caught by Pydantic before the handler runs. This is a baseline sanity test
        for FastAPI's built-in body validation wiring.
        """
        from starlette.testclient import TestClient
        from app.main import app

        no_user_id = {k: v for k, v in _VALID_EVENT.items() if k != "user_id"}
        spy = SpyIngestionService()
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: spy
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=no_user_id)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"POST /events/ingest without user_id must return 422, "
            f"got {response.status_code}."
        )
        assert spy.ingest_one_call_count == 0, (
            "service.ingest_one must not be called when user_id is missing."
        )

    @pytest.mark.parametrize(
        "bad_ip",
        [
            "256.0.0.1",  # octet 256 out of range
            "192.168.1.999",  # octet 999 out of range
            "not-an-ip",  # not IP format at all
            "::1",  # IPv6 — spec §7 prohibits IPv6
            "192.168.1",  # too few octets
            "192.168.1.1.1",  # too many octets
        ],
    )
    def test_invalid_ip_variants_return_422(self, bad_ip: str) -> None:
        """Multiple invalid IP forms must all return 422 (not 500 or 200).

        WHY: The IPv4 regex in LoginEventBase is intended to reject all non-IPv4
        values. Parametrized testing catches regex edge cases — a partial regex
        (e.g., one that only checks 256+ but not format) might pass some forms.
        Spec §7: IPv6 is explicitly excluded ('Do NOT add IPv6 handling').
        """
        from starlette.testclient import TestClient
        from app.main import app

        bad_payload = dict(_VALID_EVENT, client_ip=bad_ip)
        dep_callable = _get_dep_callable()

        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: SpyIngestionService()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=bad_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code == 422, (
            f"client_ip={bad_ip!r} must return 422, got {response.status_code}. "
            "All non-IPv4 values must be rejected per spec §2.1."
        )

    @pytest.mark.parametrize(
        "valid_ip",
        [
            "192.168.1.1",  # project reference IP
            "8.8.8.8",  # project reference IP
            "198.51.100.1",  # project reference IP
            "0.0.0.0",  # all-zero edge
            "255.255.255.255",  # all-max edge
        ],
    )
    def test_valid_ip_variants_are_not_rejected(self, valid_ip: str) -> None:
        """Valid IPv4 addresses must not be rejected with 422.

        WHY: The regex must not be over-restrictive. Project reference IPs
        (192.168.1.1, 8.8.8.8, 198.51.100.1) must all pass. Boundary values
        (0.0.0.0, 255.255.255.255) must also pass.
        """
        from starlette.testclient import TestClient
        from app.main import app

        good_payload = dict(_VALID_EVENT, client_ip=valid_ip)
        fake_ids = [uuid.uuid4()]

        class _GoodFake:
            async def ingest_one(self, event):
                return fake_ids[0]

            async def ingest_many(self, events):
                return fake_ids[: len(events)]

        dep_callable = _get_dep_callable()
        if dep_callable is not None:
            app.dependency_overrides[dep_callable] = lambda: _GoodFake()
        try:
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post("/events/ingest", json=good_payload)
        finally:
            if dep_callable is not None:
                app.dependency_overrides.clear()

        assert response.status_code != 422, (
            f"Valid client_ip={valid_ip!r} must not return 422, "
            f"got {response.status_code}. "
            "The IPv4 regex must accept all valid addresses in range 0.0.0.0–255.255.255.255."
        )
