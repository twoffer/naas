"""tests/integration/test_event_ingestion_live.py

End-to-end tests for the event-ingestion service against the live docker
compose stack.

Scenarios covered:
  - GET /health returns HTTP 200 with body status="healthy"
  - POST /events/ingest returns 202 with {id: <uuid>, status: "accepted"}
  - The accepted event row is persisted in PostgreSQL events table
  - Row cleanup removes test-inserted rows

PostgreSQL connection: psycopg (v3 sync API) to localhost:5432
  credentials: naas / naas_dev_password / naas (from .env defaults)
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

import pytest

# psycopg (v3) — pinned in requirements-dev.txt by feature-implementer.
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

_INGEST_URL = "http://localhost:8001/events/ingest"
_HEALTH_URL = "http://localhost:8001/health"

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
def pg_connection(compose_stack: dict):
    """Open a synchronous psycopg3 connection to PostgreSQL, yield it, close it.

    Module-scoped so all tests in this file share one connection — saves
    repeated connect/disconnect overhead during the test run.
    """
    import psycopg  # noqa: PLC0415

    conninfo = compose_stack["pg_conninfo"]
    conn = psycopg.connect(
        host=conninfo["host"],
        port=conninfo["port"],
        dbname=conninfo["dbname"],
        user=conninfo["user"],
        password=conninfo["password"],
    )
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


# ---------------------------------------------------------------------------
# Test class: health endpoint
# ---------------------------------------------------------------------------


class TestEventIngestionHealth:
    """GET /health must return HTTP 200 with status="healthy" when stack is up."""

    def test_health_returns_200(self, compose_stack: dict) -> None:
        """HTTP status code must be 200."""
        status_code, _ = _http_get_json(_HEALTH_URL)
        assert status_code == 200, (
            f"Expected HTTP 200 from {_HEALTH_URL}, got {status_code}"
        )

    def test_health_body_status_is_healthy(self, compose_stack: dict) -> None:
        """Response body must contain status='healthy' when PG and Redis are up."""
        _, body = _http_get_json(_HEALTH_URL)
        assert body.get("status") == "healthy", (
            f"Expected status='healthy', got {body.get('status')!r}. Full body: {body}"
        )

    def test_health_body_service_name(self, compose_stack: dict) -> None:
        """Response body must identify the service as 'event-ingestion'."""
        _, body = _http_get_json(_HEALTH_URL)
        assert body.get("service") == "event-ingestion", (
            f"Expected service='event-ingestion', got {body.get('service')!r}"
        )


# ---------------------------------------------------------------------------
# Test class: single event ingest
# ---------------------------------------------------------------------------


class TestEventIngestionLive:
    """POST /events/ingest E2E: HTTP contract + PostgreSQL persistence."""

    def test_ingest_returns_202(
        self, compose_stack: dict, cleanup_event_ids: list
    ) -> None:
        """POST /events/ingest must respond with HTTP 202 Accepted."""
        event = _make_login_event()
        status_code, body = _http_post_json(_INGEST_URL, event)
        # Register for cleanup even before asserting so partial failures still clean up
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert status_code == 202, (
            f"Expected HTTP 202 from {_INGEST_URL}, got {status_code}. Body: {body}"
        )

    def test_ingest_response_has_uuid_id(
        self, compose_stack: dict, cleanup_event_ids: list
    ) -> None:
        """Response body must include 'id' as a valid UUID string."""
        event = _make_login_event()
        _, body = _http_post_json(_INGEST_URL, event)
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert "id" in body, f"Response body missing 'id': {body}"
        try:
            uuid.UUID(body["id"])
        except (ValueError, AttributeError) as exc:
            pytest.fail(f"Response 'id' is not a valid UUID: {body['id']!r} — {exc}")

    def test_ingest_response_status_is_accepted(
        self, compose_stack: dict, cleanup_event_ids: list
    ) -> None:
        """Response body must include status='accepted'."""
        event = _make_login_event()
        _, body = _http_post_json(_INGEST_URL, event)
        if "id" in body:
            cleanup_event_ids.append(body["id"])
        assert body.get("status") == "accepted", (
            f"Expected status='accepted', got {body.get('status')!r}. Body: {body}"
        )

    def test_ingest_row_persisted_in_postgres(
        self, compose_stack: dict, pg_connection, cleanup_event_ids: list
    ) -> None:
        """Accepted event must appear in the PostgreSQL events table.

        Verifies that the dual-write (postgres + redis stream) wrote a row
        with the server-assigned UUID, matching the posted user_id.
        """
        event = _make_login_event(user_id="alice")
        _, body = _http_post_json(_INGEST_URL, event)
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
        self, compose_stack: dict, pg_connection, cleanup_event_ids: list
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
        status_code, body = _http_post_json(_INGEST_URL, event)
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

    def test_ingest_rejects_invalid_payload_with_422(self, compose_stack: dict) -> None:
        """Payload with missing required fields must be rejected with HTTP 422.

        FastAPI's Pydantic validation gate rejects malformed events before they
        reach the service layer — this is an explicit security boundary test.
        """
        bad_event = {"user_id": "hacker"}  # Missing client_ip, protocol, timestamp
        body_bytes = json.dumps(bad_event).encode()
        req = urllib.request.Request(
            _INGEST_URL,
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

    def test_ingest_rejects_invalid_ip_with_422(self, compose_stack: dict) -> None:
        """Event with invalid client_ip must be rejected with HTTP 422.

        The client_ip field has a strict IPv4 pattern validator — injecting
        invalid addresses must never succeed.
        """
        bad_event = _make_login_event(client_ip="not-an-ip")
        body_bytes = json.dumps(bad_event).encode()
        req = urllib.request.Request(
            _INGEST_URL,
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
        self, compose_stack: dict, pg_connection
    ) -> None:
        """Rows explicitly deleted via cleanup query must no longer exist.

        Verifies the cleanup mechanism used by other tests actually works —
        a broken cleanup would cause cross-test contamination.
        """
        event = _make_login_event(user_id="cleanup-test-user")
        _, body = _http_post_json(_INGEST_URL, event)
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
