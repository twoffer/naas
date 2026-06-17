"""tests/integration/test_event_ingestion_live.py

End-to-end tests for the event-ingestion service against the live docker
compose stack.

Scenarios covered:
  - GET /health returns HTTP 200 with body status="healthy"
  - POST /events/ingest returns 202 with {id: <uuid>, status: "accepted"}
  - The accepted event row is persisted in PostgreSQL events table
  - Row cleanup removes test-inserted rows
  - Redis Stream correlation: single ingest message lands on login_events
    stream with correct envelope and payload (Spec 1 §6 criterion 3)
  - Bulk round-trip: POST /events/bulk, N response ids, N PG rows (§6 criterion 4)

All connection parameters (URLs, PostgreSQL credentials, Redis port) come from
the compose_stack fixture plus the repo .env — nothing is hardcoded here.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import pytest

# psycopg (v3) — pinned in requirements-dev.txt.
# Import guard: the test is already skipped unless --integration is set, but
# a missing psycopg would cause an ImportError at collection time even for
# skipped tests.  We defer the import to test-body level inside the fixture.

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(120),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_TIMESTAMP = "2024-01-15T10:30:00+00:00"


def _make_login_event(**overrides: Any) -> dict:
    """Build a minimal valid LoginEventIngest payload."""
    base = {
        "user_id": "alice",
        "client_ip": "192.168.1.1",
        "protocol": "oidc",
        "timestamp": _FIXED_TIMESTAMP,
        "source": "api",
        "is_synthetic": True,
        "is_historical": False,
        "raw_attributes": {
            "name": "Alice Smith",
            "email": "alice@corp.com",
            "department": "eng",
            "employee_type": "FTE",
            "groups": ["engineering", "vpn-users"],
        },
    }
    base.update(overrides)
    return base


def _http_post_json(url: str, payload: dict, timeout: int = 15) -> tuple[int, dict]:
    """POST JSON payload, return (status_code, response_body_dict)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def _http_get_json(url: str, timeout: int = 15) -> tuple[int, dict]:
    """GET, return (status_code, response_body_dict)."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ingest_url(compose_stack: dict) -> str:
    return compose_stack["event_ingestion_url"] + "/events/ingest"


@pytest.fixture(scope="module")
def health_url(compose_stack: dict) -> str:
    return compose_stack["event_ingestion_url"] + "/health"


@pytest.fixture(scope="module")
def pg_connection(compose_stack: dict):
    """Open a synchronous psycopg3 connection to PostgreSQL, yield it, close it.

    Module-scoped so all tests in this file share one connection — saves
    repeated connect/disconnect overhead during the test run.
    """
    import psycopg

    conn = psycopg.connect(**compose_stack["pg_conninfo"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def cleanup_event_ids(pg_connection):
    """Yield a list that tests append their inserted event UUIDs to.

    On teardown, deletes all rows whose IDs were registered during the test.
    """
    ids: list[str] = []
    yield ids
    if ids:
        with pg_connection.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE id = ANY(%s::uuid[])",
                (ids,),
            )


@pytest.fixture(scope="module")
def bulk_url(compose_stack: dict) -> str:
    return compose_stack["event_ingestion_url"] + "/events/bulk"


def _resolve_redis_port() -> int:
    """Resolve the Redis host port the compose stack exposes.

    Mirrors compose's precedence: process environment → .env file → default 6379.
    The Redis container maps ${REDIS_PORT:-6379}:6379 per docker-compose.yml.
    """
    env_val = os.environ.get("REDIS_PORT")
    if env_val:
        return int(env_val)

    # Walk up to repo root to find .env
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            break
        candidate = candidate.parent
    dot_env = candidate / ".env"
    if dot_env.exists():
        for raw_line in dot_env.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("REDIS_PORT="):
                _, _, value = stripped.partition("=")
                value = value.strip().split(" #", 1)[0].rstrip()
                if value:
                    return int(value)
    return 6379


@pytest.fixture(scope="module")
def redis_client():
    """Open a synchronous redis-py connection to the compose stack's Redis.

    Module-scoped — one connection per file, matching the pg_connection pattern.
    Deferred import avoids a collection-time ImportError when redis-py is absent
    in non-integration environments (the skip gate fires before this fixture runs).
    """
    import redis as redis_lib

    port = _resolve_redis_port()
    client = redis_lib.Redis(host="localhost", port=port, db=0, decode_responses=True)
    yield client
    client.close()


# ---------------------------------------------------------------------------
# Test class: health endpoint
# ---------------------------------------------------------------------------


class TestEventIngestionHealth:
    """GET /health must return HTTP 200 with status="healthy" when stack is up."""

    def test_health_returns_200(self, health_url: str) -> None:
        """HTTP status code must be 200."""
        status_code, _ = _http_get_json(health_url)
        assert status_code == 200, (
            f"Expected HTTP 200 from {health_url}, got {status_code}"
        )

    def test_health_body_status_is_healthy(self, health_url: str) -> None:
        """Response body must contain status='healthy' when PG and Redis are up."""
        _, body = _http_get_json(health_url)
        assert body.get("status") == "healthy", (
            f"Expected status='healthy', got {body.get('status')!r}. Full body: {body}"
        )

    def test_health_body_service_name(self, health_url: str) -> None:
        """Response body must identify the service as 'event-ingestion'."""
        _, body = _http_get_json(health_url)
        assert body.get("service") == "event-ingestion", (
            f"Expected service='event-ingestion', got {body.get('service')!r}"
        )


# ---------------------------------------------------------------------------
# Test class: single event ingest
# ---------------------------------------------------------------------------


class TestEventIngestionLive:
    """POST /events/ingest E2E: HTTP contract + PostgreSQL persistence."""

    def test_ingest_returns_202(self, ingest_url: str, cleanup_event_ids: list) -> None:
        """POST /events/ingest must respond with HTTP 202 Accepted."""
        event = _make_login_event()
        status_code, body = _http_post_json(ingest_url, event)
        # Register for cleanup even before asserting so partial failures still clean up
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert status_code == 202, (
            f"Expected HTTP 202 from {ingest_url}, got {status_code}. Body: {body}"
        )

    def test_ingest_response_has_uuid_id(
        self, ingest_url: str, cleanup_event_ids: list
    ) -> None:
        """Response body must include 'id' as a valid UUID string."""
        event = _make_login_event()
        _, body = _http_post_json(ingest_url, event)
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert "id" in body, f"Response body missing 'id': {body}"
        try:
            uuid.UUID(body["id"])
        except (ValueError, AttributeError) as exc:
            pytest.fail(f"Response 'id' is not a valid UUID: {body['id']!r} — {exc}")

    def test_ingest_response_status_is_accepted(
        self, ingest_url: str, cleanup_event_ids: list
    ) -> None:
        """Response body must include status='accepted'."""
        event = _make_login_event()
        _, body = _http_post_json(ingest_url, event)
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert body.get("status") == "accepted", (
            f"Expected status='accepted', got {body.get('status')!r}. Body: {body}"
        )

    def test_ingest_row_persisted_in_postgres(
        self, ingest_url: str, pg_connection, cleanup_event_ids: list
    ) -> None:
        """Accepted event must appear in the PostgreSQL events table.

        Verifies that the dual-write (postgres + redis stream) wrote a row
        with the server-assigned UUID, matching the posted user_id.
        """
        event = _make_login_event(user_id="alice")
        _, body = _http_post_json(ingest_url, event)
        event_id = body["id"]
        cleanup_event_ids.append(event_id)

        with pg_connection.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, protocol, is_synthetic FROM events WHERE id = %s::uuid",
                (event_id,),
            )
            row = cur.fetchone()

        assert row is not None, (
            f"Event {event_id} not found in events table after ingestion"
        )
        db_id, db_user_id, db_protocol, db_is_synthetic = row
        assert str(db_id) == event_id, (
            f"Stored id {db_id!r} does not match returned id {event_id!r}"
        )
        assert db_user_id == "alice", (
            f"Stored user_id {db_user_id!r} does not match posted 'alice'"
        )
        assert db_protocol == "oidc", (
            f"Stored protocol {db_protocol!r} does not match posted 'oidc'"
        )
        assert db_is_synthetic is True, (
            f"Stored is_synthetic {db_is_synthetic!r} should be True"
        )

    def test_ingest_ldap_protocol_event(
        self, ingest_url: str, pg_connection, cleanup_event_ids: list
    ) -> None:
        """LDAP-protocol events must also be accepted and persisted correctly."""
        event = _make_login_event(
            user_id="charlie",
            protocol="ldap",
            raw_attributes={
                "cn": "Charlie Brown",
                "mail": "charlie@corp.com",
                "departmentNumber": "Security",
                "employeeType": "contractor",
                "memberOf": ["cn=security,ou=groups,dc=corp,dc=com"],
            },
        )
        status_code, body = _http_post_json(ingest_url, event)
        if "id" in body:
            cleanup_event_ids.append(body["id"])

        assert status_code == 202, (
            f"LDAP event ingest failed with HTTP {status_code}. Body: {body}"
        )

        event_id = body["id"]
        with pg_connection.cursor() as cur:
            cur.execute(
                "SELECT protocol FROM events WHERE id = %s::uuid",
                (event_id,),
            )
            row = cur.fetchone()

        assert row is not None, f"LDAP event {event_id} not found in events table"
        assert row[0] == "ldap", f"Protocol mismatch: expected 'ldap', got {row[0]!r}"

    def test_ingest_rejects_invalid_payload_with_422(self, ingest_url: str) -> None:
        """Payload with missing required fields must be rejected with HTTP 422.

        FastAPI's Pydantic validation gate rejects malformed events before they
        reach the service layer — this is an explicit security boundary test.
        """
        bad_event = {"user_id": "hacker"}  # Missing client_ip, protocol, timestamp
        body_bytes = json.dumps(bad_event).encode()
        req = urllib.request.Request(
            ingest_url,
            data=body_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pytest.fail(
                    f"Expected HTTP 422, got {resp.status}. "
                    "Invalid payload should be rejected."
                )
        except urllib.error.HTTPError as exc:
            assert exc.code == 422, (
                f"Expected HTTP 422 for invalid payload, got {exc.code}"
            )

    def test_ingest_rejects_invalid_ip_with_422(self, ingest_url: str) -> None:
        """Event with invalid client_ip must be rejected with HTTP 422.

        The client_ip field has a strict IPv4 pattern validator — injecting
        invalid addresses must never succeed.
        """
        bad_event = _make_login_event(client_ip="not-an-ip")
        body_bytes = json.dumps(bad_event).encode()
        req = urllib.request.Request(
            ingest_url,
            data=body_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pytest.fail(f"Expected HTTP 422 for invalid IP, got {resp.status}.")
        except urllib.error.HTTPError as exc:
            assert exc.code == 422, f"Expected HTTP 422 for invalid IP, got {exc.code}"

    def test_cleanup_removes_inserted_rows(
        self, ingest_url: str, pg_connection
    ) -> None:
        """Rows explicitly deleted via cleanup query must no longer exist.

        Verifies the cleanup mechanism used by other tests actually works —
        a broken cleanup would cause cross-test contamination.
        """
        event = _make_login_event(user_id="cleanup-test-user")
        _, body = _http_post_json(ingest_url, event)
        event_id = body["id"]

        # Manually delete (simulates cleanup fixture)
        with pg_connection.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE id = %s::uuid RETURNING id",
                (event_id,),
            )
            deleted = cur.fetchall()

        assert len(deleted) == 1, (
            f"Expected to delete 1 row for event {event_id}, deleted {len(deleted)}"
        )

        with pg_connection.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM events WHERE id = %s::uuid",
                (event_id,),
            )
            assert cur.fetchone() is None, (
                f"Event {event_id} still exists after deletion"
            )


# ---------------------------------------------------------------------------
# Test class: Redis Stream correlation (Spec 1 §6 criterion 3)
# ---------------------------------------------------------------------------


class TestRedisStreamCorrelation:
    """Single POST /events/ingest must land a message on the login_events stream.

    Spec 1 §6 criterion 3: 'The message has a single `data` field; its JSON `id`
    equals the row's `id`.'

    Messages are {"data": "<json>"} envelopes per naas_shared.redis_client
    publish_to_stream.  The stream is shared with other services and may have
    messages from concurrent tests or background activity — we search recent
    entries rather than assuming a fixed stream position.  The stream is capped
    (maxlen 10000) so searching the most recent 200 messages is safe and fast.
    """

    _SEARCH_COUNT = 200  # Number of recent stream entries to scan for the target id

    def test_single_ingest_message_lands_on_login_events_stream(
        self, ingest_url: str, redis_client, cleanup_event_ids: list
    ) -> None:
        """After POST /events/ingest the login_events stream must contain a message
        whose data JSON id matches the returned event_id.

        WHY (Spec 1 §6 criterion 3): the dual-write only succeeds if both the
        PostgreSQL row AND the stream message exist with the same id.  Finding the
        message confirms the publish step ran after a successful commit.
        """
        event = _make_login_event(user_id="stream-corr-alice")
        status_code, body = _http_post_json(ingest_url, event)
        assert status_code == 202, (
            f"Ingest must succeed before we can assert stream presence. "
            f"Got HTTP {status_code}."
        )
        event_id = body["id"]
        cleanup_event_ids.append(event_id)

        # Search recent stream entries for the message whose data.id == event_id.
        # XREVRANGE reads newest-first; we stop as soon as we find the message.
        entries = redis_client.xrevrange("login_events", count=self._SEARCH_COUNT)
        found = None
        for _entry_id, fields in entries:
            raw_data = fields.get("data", "")
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("id") == event_id:
                found = payload
                break

        assert found is not None, (
            f"No message with id={event_id!r} found in the last {self._SEARCH_COUNT} "
            "entries of the login_events Redis stream. "
            "Spec 1 §6 criterion 3: the published stream message must carry the same "
            "id as the PostgreSQL row."
        )

    def test_stream_message_has_correct_user_id_and_protocol(
        self, ingest_url: str, redis_client, cleanup_event_ids: list
    ) -> None:
        """The stream message payload must preserve user_id and protocol from the request.

        WHY: Downstream normalization uses these fields to route the event to the
        correct protocol adapter.  A missing or wrong user_id/protocol would cause
        silent mis-routing in the normalization stage.
        """
        event = _make_login_event(user_id="stream-fields-bob", protocol="saml")
        status_code, body = _http_post_json(ingest_url, event)
        assert status_code == 202, f"Ingest failed with HTTP {status_code}."
        event_id = body["id"]
        cleanup_event_ids.append(event_id)

        entries = redis_client.xrevrange("login_events", count=self._SEARCH_COUNT)
        found = None
        for _entry_id, fields in entries:
            raw_data = fields.get("data", "")
            try:
                payload = json.loads(raw_data)
            except (json.JSONDecodeError, TypeError):
                continue
            if payload.get("id") == event_id:
                found = payload
                break

        assert found is not None, (
            f"Stream message for event_id={event_id!r} not found in login_events."
        )
        assert found.get("user_id") == "stream-fields-bob", (
            f"Stream message user_id must be 'stream-fields-bob', "
            f"got {found.get('user_id')!r}."
        )
        assert found.get("protocol") == "saml", (
            f"Stream message protocol must be 'saml', got {found.get('protocol')!r}."
        )


# ---------------------------------------------------------------------------
# Test class: Bulk ingest round-trip (Spec 1 §6 criterion 4)
# ---------------------------------------------------------------------------


def _http_post_json_bulk(
    url: str, payload: list, timeout: int = 15
) -> tuple[int, dict]:
    """POST a bare JSON array, return (status_code, response_body_dict)."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


class TestBulkIngestRoundTrip:
    """POST /events/bulk with 3 events must produce 3 PG rows (Spec 1 §6 criterion 4).

    Spec 1 §6 criterion 4: 'POST a 3-element array to /events/bulk; expect
    {"accepted":3,...}, the events row count to rise by 3.'

    We verify:
      1. HTTP 202 response with accepted==3 and three event_ids.
      2. Each of the three ids exists as a row in the events table.
      3. Cleanup fixture removes all three rows.
    """

    def test_bulk_ingest_returns_202_with_three_event_ids(
        self, bulk_url: str, cleanup_event_ids: list
    ) -> None:
        """POST /events/bulk with 3 events must return 202 and 3 event_ids.

        WHY (Spec 1 §6 criterion 4): the response body is the primary contract
        for callers — accepted count and id list must match the submitted batch.
        """
        events = [
            _make_login_event(user_id=f"bulk-user-{i}", protocol="oidc")
            for i in range(3)
        ]
        status_code, body = _http_post_json_bulk(bulk_url, events)

        # Register ids for cleanup before asserting so partial failures still clean up
        cleanup_event_ids.extend(body.get("event_ids", []))

        assert status_code == 202, (
            f"POST /events/bulk expected 202, got {status_code}. Body: {body}"
        )
        assert body.get("accepted") == 3, (
            f"BulkIngestAccepted.accepted must be 3, got {body.get('accepted')!r}. "
            "Spec 1 §6 criterion 4."
        )
        event_ids = body.get("event_ids", [])
        assert len(event_ids) == 3, (
            f"BulkIngestAccepted.event_ids must have 3 entries, got {len(event_ids)}."
        )

    def test_bulk_ingest_all_rows_present_in_postgres(
        self, bulk_url: str, pg_connection, cleanup_event_ids: list
    ) -> None:
        """All 3 bulk-ingested events must appear as rows in the events table.

        WHY (Spec 1 §6 criterion 4): confirms the all-or-nothing PostgreSQL
        transaction actually committed all rows — a partial commit would leave
        some event_ids returned by the service but absent from the DB, breaking
        downstream correlation.
        """
        events = [
            _make_login_event(user_id=f"bulk-pg-user-{i}", protocol="ldap")
            for i in range(3)
        ]
        status_code, body = _http_post_json_bulk(bulk_url, events)
        assert status_code == 202, (
            f"Bulk ingest must succeed before asserting PG rows. Got HTTP {status_code}."
        )

        event_ids = body.get("event_ids", [])
        cleanup_event_ids.extend(event_ids)

        assert len(event_ids) == 3, (
            f"Expected 3 event_ids in response, got {len(event_ids)}."
        )

        missing = []
        for eid in event_ids:
            with pg_connection.cursor() as cur:
                cur.execute(
                    "SELECT id FROM events WHERE id = %s::uuid",
                    (eid,),
                )
                row = cur.fetchone()
            if row is None:
                missing.append(eid)

        assert not missing, (
            f"The following event_ids were returned by /events/bulk but are absent "
            f"from the events table: {missing}. "
            "Spec 1 §6 criterion 4: all rows in the batch must be committed atomically."
        )
