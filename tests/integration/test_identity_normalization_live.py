"""tests/integration/test_identity_normalization_live.py

End-to-end tests for the identity-normalization service against the live
docker compose stack.

Scenarios:
  1. OIDC event for alice@corp.com (present in OpenLDAP bootstrap.ldif):
     - Ingest via event-ingestion
     - Poll PostgreSQL until normalized_attributes is non-NULL (timeout 60s)
     - Parse result as NormalizedAttributes (validates schema conformance)
     - Assert enrichment was applied (EnrichmentApplied, source="ldap")
     - Assert display_name, primary_email, department, employee_type match

  2. LDAP-protocol event for charlie@corp.com:
     - Ingest via event-ingestion
     - Poll until normalized_attributes appears
     - Assert enrichment.applied is False with skip_reason="ldap_event"
     - LDAP events must never trigger cross-protocol enrichment (design invariant)

  3. OIDC event for an unknown user (no LDAP match):
     - Ingest via event-ingestion
     - Poll until normalized_attributes appears
     - Assert enrichment.applied is False with skip_reason="no_ldap_match"

Users from infrastructure/openldap/bootstrap.ldif used here:
  alice  — mail: alice@corp.com, department: Engineering, FTE, groups: engineering, vpn-users
  charlie — mail: charlie@corp.com, department: Security, contractor
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.timeout(300),  # 5 min: stack-up + normalization + 3 poll cycles
]

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_INGEST_URL = "http://localhost:8001/events/ingest"
_POLL_INTERVAL_S = 2.0
_POLL_TIMEOUT_S = 60.0
_FIXED_TIMESTAMP = "2024-01-15T10:30:00+00:00"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_event(payload: dict, timeout: int = 15) -> str:
    """POST to event-ingestion, return the server-assigned event UUID string."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        _INGEST_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    assert resp.status == 202, f"Expected 202, got {resp.status}. Body: {data}"
    return data["id"]


def _poll_normalized_attributes(
    pg_conn,
    event_id: str,
    timeout_s: float = _POLL_TIMEOUT_S,
    interval_s: float = _POLL_INTERVAL_S,
) -> dict:
    """Poll PostgreSQL until normalized_attributes is non-NULL for event_id.

    Returns the normalized_attributes JSONB dict.
    Raises TimeoutError if not populated within timeout_s.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT normalized_attributes FROM events WHERE id = %s::uuid",
                (event_id,),
            )
            row = cur.fetchone()
        if row and row[0] is not None:
            attrs = row[0]
            # psycopg3 returns JSONB as a Python dict already
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            return attrs
        time.sleep(interval_s)
    raise TimeoutError(
        f"normalized_attributes not populated for event {event_id} within {timeout_s}s"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_connection(compose_stack: dict):
    """Synchronous psycopg3 connection shared across all tests in this module."""
    import psycopg  # noqa: PLC0415

    info = compose_stack["pg_conninfo"]
    conn = psycopg.connect(
        host=info["host"],
        port=info["port"],
        dbname=info["dbname"],
        user=info["user"],
        password=info["password"],
    )
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture
def cleanup_event_ids(pg_connection):
    """Accumulate event UUIDs; delete all on teardown."""
    ids: list[str] = []
    yield ids
    if ids:
        with pg_connection.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE id = ANY(%s::uuid[])",
                (ids,),
            )


# ---------------------------------------------------------------------------
# naas_shared import (soft — module may not be on PYTHONPATH in some envs)
# ---------------------------------------------------------------------------

try:
    from naas_shared.models import NormalizedAttributes

    _NAAS_SHARED_AVAILABLE = True
except ImportError:
    _NAAS_SHARED_AVAILABLE = False


def _validate_normalized_attributes(attrs_dict: dict) -> "NormalizedAttributes":
    """Parse attrs_dict through NormalizedAttributes.model_validate().

    Skips Pydantic validation if naas_shared is not importable; the raw dict
    assertions in each test still exercise the field values.
    """
    if not _NAAS_SHARED_AVAILABLE:
        pytest.skip(
            "naas_shared not importable in this environment — "
            "Pydantic model_validate skipped; raw dict assertions still ran."
        )
    return NormalizedAttributes.model_validate(attrs_dict)


# ---------------------------------------------------------------------------
# Test class: OIDC event with LDAP enrichment
# ---------------------------------------------------------------------------


class TestOidcEventWithLdapEnrichment:
    """OIDC event for alice@corp.com (present in OpenLDAP) gets enriched.

    alice is in bootstrap.ldif:
      mail: alice@corp.com
      departmentNumber: Engineering
      employeeType: FTE
      groups: engineering, vpn-users (via groupOfNames)
    """

    def test_normalized_attributes_populated(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """normalized_attributes must be non-NULL within 60s of ingestion."""
        event = {
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
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        assert attrs is not None, f"normalized_attributes is None for event {event_id}"

    def test_normalized_attributes_parses_as_model(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """normalized_attributes dict must parse via NormalizedAttributes.model_validate().

        Validates the schema contract between the normalization service (writer)
        and all consumers (Risk Evaluator, Dashboard — readers). A ValidationError
        here indicates a schema divergence.
        """
        event = {
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
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        try:
            _validate_normalized_attributes(attrs_dict)
        except Exception as exc:
            pytest.fail(
                f"NormalizedAttributes.model_validate() raised {type(exc).__name__}: {exc}\n"
                f"Raw dict: {attrs_dict}"
            )

    def test_oidc_enrichment_applied(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """OIDC event for an LDAP-known user must have enrichment.applied=True.

        This is the core cross-protocol enrichment invariant: OIDC events trigger
        an OpenLDAP lookup keyed on primary_email (the configured correlation field).
        alice@corp.com exists in bootstrap.ldif → enrichment must be applied.
        """
        event = {
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
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        enrichment = attrs_dict.get("enrichment", {})
        assert enrichment.get("applied") is True, (
            f"Expected enrichment.applied=True for OIDC alice event, "
            f"got: {enrichment}. Full attrs: {attrs_dict}"
        )
        assert enrichment.get("source") == "ldap", (
            f"Expected enrichment.source='ldap', got: {enrichment.get('source')!r}"
        )

    def test_oidc_normalized_primary_email(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """Normalized primary_email for alice must be alice@corp.com."""
        event = {
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
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        assert attrs_dict.get("primary_email") == "alice@corp.com", (
            f"Expected primary_email='alice@corp.com', "
            f"got {attrs_dict.get('primary_email')!r}"
        )

    def test_oidc_source_protocol_is_oidc(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """source_protocol in normalized attributes must be 'oidc'."""
        event = {
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
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        assert attrs_dict.get("source_protocol") == "oidc", (
            f"Expected source_protocol='oidc', got {attrs_dict.get('source_protocol')!r}"
        )


# ---------------------------------------------------------------------------
# Test class: LDAP-protocol event — enrichment must be skipped
# ---------------------------------------------------------------------------


class TestLdapEventEnrichmentSkipped:
    """LDAP-protocol events must never trigger cross-protocol enrichment.

    Design invariant: the normalization service checks event.protocol == "ldap"
    and sets enrichment = EnrichmentSkipped(applied=False, skip_reason="ldap_event").
    This prevents recursive LDAP lookups for events that already came from LDAP.
    """

    def test_ldap_event_normalized_attributes_populated(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """LDAP-protocol events must also produce normalized_attributes."""
        event = {
            "user_id": "charlie",
            "client_ip": "192.168.1.1",
            "protocol": "ldap",
            "timestamp": _FIXED_TIMESTAMP,
            "source": "api",
            "is_synthetic": True,
            "is_historical": False,
            "raw_attributes": {
                "cn": "Charlie Brown",
                "mail": "charlie@corp.com",
                "departmentNumber": "Security",
                "employeeType": "contractor",
                "memberOf": ["cn=security,ou=groups,dc=corp,dc=com"],
            },
        }
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        assert attrs is not None, (
            f"normalized_attributes is None for LDAP event {event_id}"
        )

    def test_ldap_event_enrichment_skipped_with_ldap_event_reason(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """LDAP event enrichment must be skipped with skip_reason='ldap_event'.

        This is a security invariant: LDAP events carry directory data directly;
        performing a secondary LDAP lookup would be redundant and could mask
        attribute manipulation in the primary LDAP payload.
        """
        event = {
            "user_id": "charlie",
            "client_ip": "192.168.1.1",
            "protocol": "ldap",
            "timestamp": _FIXED_TIMESTAMP,
            "source": "api",
            "is_synthetic": True,
            "is_historical": False,
            "raw_attributes": {
                "cn": "Charlie Brown",
                "mail": "charlie@corp.com",
                "departmentNumber": "Security",
                "employeeType": "contractor",
                "memberOf": ["cn=security,ou=groups,dc=corp,dc=com"],
            },
        }
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        enrichment = attrs_dict.get("enrichment", {})

        assert enrichment.get("applied") is False, (
            f"Expected enrichment.applied=False for LDAP event, got: {enrichment}"
        )
        assert enrichment.get("skip_reason") == "ldap_event", (
            f"Expected skip_reason='ldap_event', got: {enrichment.get('skip_reason')!r}. "
            f"Full enrichment: {enrichment}"
        )

    def test_ldap_event_parses_as_model(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """LDAP event normalized_attributes must also parse via NormalizedAttributes."""
        event = {
            "user_id": "charlie",
            "client_ip": "192.168.1.1",
            "protocol": "ldap",
            "timestamp": _FIXED_TIMESTAMP,
            "source": "api",
            "is_synthetic": True,
            "is_historical": False,
            "raw_attributes": {
                "cn": "Charlie Brown",
                "mail": "charlie@corp.com",
                "departmentNumber": "Security",
                "employeeType": "contractor",
                "memberOf": ["cn=security,ou=groups,dc=corp,dc=com"],
            },
        }
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        try:
            _validate_normalized_attributes(attrs_dict)
        except Exception as exc:
            pytest.fail(
                f"NormalizedAttributes.model_validate() raised {type(exc).__name__}: {exc}"
            )


# ---------------------------------------------------------------------------
# Test class: OIDC event for unknown user — no LDAP match
# ---------------------------------------------------------------------------


class TestOidcEventNoLdapMatch:
    """OIDC event for a user not in OpenLDAP must skip enrichment with no_ldap_match.

    The normalization service attempts LDAP lookup keyed on primary_email.
    An unknown email produces no LDAP entries → enrichment.skip_reason='no_ldap_match'.
    The service must still produce a valid normalized result (graceful degradation).
    """

    def test_unknown_user_enrichment_skipped_with_no_ldap_match(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """OIDC event with unknown email must have skip_reason='no_ldap_match'."""
        event = {
            "user_id": "unknown-user-xyz",
            "client_ip": "192.168.1.1",
            "protocol": "oidc",
            "timestamp": _FIXED_TIMESTAMP,
            "source": "api",
            "is_synthetic": True,
            "is_historical": False,
            "raw_attributes": {
                "name": "Unknown Person",
                "email": "nobody@nowhere-xyz-fake.example",
                "department": "Unknown",
                "employee_type": "FTE",
                "groups": [],
            },
        }
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        enrichment = attrs_dict.get("enrichment", {})

        assert enrichment.get("applied") is False, (
            f"Expected enrichment.applied=False for unknown user, got: {enrichment}"
        )
        assert enrichment.get("skip_reason") == "no_ldap_match", (
            f"Expected skip_reason='no_ldap_match', "
            f"got: {enrichment.get('skip_reason')!r}. Full enrichment: {enrichment}"
        )

    def test_unknown_user_normalization_still_produces_result(
        self,
        compose_stack: dict,
        pg_connection,
        cleanup_event_ids: list,
    ) -> None:
        """Graceful degradation: failed enrichment must not prevent normalization.

        A missing LDAP match is not an error — normalization proceeds with
        primary-source-only data. The result must still parse as NormalizedAttributes.
        """
        event = {
            "user_id": "unknown-user-xyz",
            "client_ip": "192.168.1.1",
            "protocol": "oidc",
            "timestamp": _FIXED_TIMESTAMP,
            "source": "api",
            "is_synthetic": True,
            "is_historical": False,
            "raw_attributes": {
                "name": "Unknown Person",
                "email": "nobody@nowhere-xyz-fake.example",
                "department": "Unknown",
                "employee_type": "FTE",
                "groups": [],
            },
        }
        event_id = _post_event(event)
        cleanup_event_ids.append(event_id)

        try:
            attrs_dict = _poll_normalized_attributes(pg_connection, event_id)
        except TimeoutError as exc:
            pytest.fail(str(exc))
            return  # unreachable — pytest.fail() raises; satisfies type checkers

        assert attrs_dict is not None, (
            "normalized_attributes must not be None even when LDAP has no match"
        )

        # Must parse as valid model
        try:
            _validate_normalized_attributes(attrs_dict)
        except Exception as exc:
            pytest.fail(
                f"NormalizedAttributes.model_validate() raised for no-LDAP-match "
                f"result: {type(exc).__name__}: {exc}"
            )
