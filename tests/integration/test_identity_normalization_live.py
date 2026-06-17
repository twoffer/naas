"""tests/integration/test_identity_normalization_live.py

End-to-end tests for the identity-normalization service against the live
docker compose stack.

Scenarios:
  1. OIDC event for alice@corp.com (present in OpenLDAP bootstrap.ldif):
     - Ingest via event-ingestion
     - Poll PostgreSQL until normalized_attributes is non-NULL (timeout 60s)
     - Parse result as NormalizedAttributes (validates schema conformance)
     - Assert enrichment was applied (EnrichmentApplied, source="ldap")

  2. LDAP-protocol event for charlie@corp.com:
     - Assert enrichment.applied is False with skip_reason="ldap_event"
     - LDAP events must never trigger cross-protocol enrichment (design invariant)

  3. OIDC event for an unknown user (no LDAP match):
     - Assert enrichment.applied is False with skip_reason="no_ldap_match"

Each scenario's event is ingested and polled exactly ONCE in a module-scoped
fixture; the tests are independent assertions over that shared normalized
result. Connection parameters come from the compose_stack fixture (resolved
from .env) — nothing is hardcoded here.

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

_POLL_INTERVAL_S = 2.0
_POLL_TIMEOUT_S = 60.0
_FIXED_TIMESTAMP = "2024-01-15T10:30:00+00:00"


# ---------------------------------------------------------------------------
# Event payload builders
# ---------------------------------------------------------------------------


def _make_alice_oidc_event() -> dict:
    """OIDC event for alice — present in OpenLDAP, enrichment applies."""
    return {
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


def _make_charlie_ldap_event() -> dict:
    """LDAP-protocol event for charlie — enrichment must be skipped."""
    return {
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


def _make_unknown_user_oidc_event() -> dict:
    """OIDC event for a user with no LDAP entry — no_ldap_match expected."""
    return {
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post_event(ingest_url: str, payload: dict, timeout: int = 15) -> str:
    """POST to event-ingestion, return the server-assigned event UUID string."""
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        ingest_url,
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
    import psycopg

    conn = psycopg.connect(**compose_stack["pg_conninfo"])
    conn.autocommit = True
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def module_cleanup_ids(pg_connection):
    """Accumulate event UUIDs across the module; delete all at module teardown."""
    ids: list[str] = []
    yield ids
    if ids:
        with pg_connection.cursor() as cur:
            cur.execute(
                "DELETE FROM events WHERE id = ANY(%s::uuid[])",
                (ids,),
            )


def _ingest_and_normalize(
    compose_stack: dict, pg_connection, module_cleanup_ids: list, payload: dict
) -> dict:
    """Ingest one event and return its normalized_attributes dict (shared path)."""
    ingest_url = compose_stack["event_ingestion_url"] + "/events/ingest"
    event_id = _post_event(ingest_url, payload)
    # Register before polling so a poll timeout still cleans up the row.
    module_cleanup_ids.append(event_id)
    try:
        return _poll_normalized_attributes(pg_connection, event_id)
    except TimeoutError as exc:
        pytest.fail(str(exc))


@pytest.fixture(scope="module")
def alice_attrs(compose_stack: dict, pg_connection, module_cleanup_ids: list) -> dict:
    """Normalized result for the alice OIDC event (ingested once per module)."""
    return _ingest_and_normalize(
        compose_stack, pg_connection, module_cleanup_ids, _make_alice_oidc_event()
    )


@pytest.fixture(scope="module")
def charlie_attrs(compose_stack: dict, pg_connection, module_cleanup_ids: list) -> dict:
    """Normalized result for the charlie LDAP event (ingested once per module)."""
    return _ingest_and_normalize(
        compose_stack, pg_connection, module_cleanup_ids, _make_charlie_ldap_event()
    )


@pytest.fixture(scope="module")
def unknown_user_attrs(
    compose_stack: dict, pg_connection, module_cleanup_ids: list
) -> dict:
    """Normalized result for the unknown-user OIDC event (ingested once per module)."""
    return _ingest_and_normalize(
        compose_stack,
        pg_connection,
        module_cleanup_ids,
        _make_unknown_user_oidc_event(),
    )


# ---------------------------------------------------------------------------
# naas_shared import (soft — module may not be on PYTHONPATH in some envs)
# ---------------------------------------------------------------------------

try:
    from naas_shared.models import NormalizedAttributes

    _NAAS_SHARED_AVAILABLE = True
except ImportError:
    _NAAS_SHARED_AVAILABLE = False


def _validate_normalized_attributes(attrs_dict: dict) -> NormalizedAttributes:
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

    def test_normalized_attributes_populated(self, alice_attrs: dict) -> None:
        """normalized_attributes must be non-NULL within 60s of ingestion."""
        assert alice_attrs is not None, "normalized_attributes is None for alice event"

    def test_normalized_attributes_parses_as_model(self, alice_attrs: dict) -> None:
        """normalized_attributes dict must parse via NormalizedAttributes.model_validate().

        Validates the schema contract between the normalization service (writer)
        and all consumers (Risk Evaluator, Dashboard — readers). A ValidationError
        here indicates a schema divergence.
        """
        try:
            _validate_normalized_attributes(alice_attrs)
        except Exception as exc:
            pytest.fail(
                f"NormalizedAttributes.model_validate() raised {type(exc).__name__}: {exc}\n"
                f"Raw dict: {alice_attrs}"
            )

    def test_oidc_enrichment_applied(self, alice_attrs: dict) -> None:
        """OIDC event for an LDAP-known user must have enrichment.applied=True.

        This is the core cross-protocol enrichment invariant: OIDC events trigger
        an OpenLDAP lookup keyed on primary_email (the configured correlation field).
        alice@corp.com exists in bootstrap.ldif → enrichment must be applied.
        """
        enrichment = alice_attrs.get("enrichment", {})
        assert enrichment.get("applied") is True, (
            f"Expected enrichment.applied=True for OIDC alice event, "
            f"got: {enrichment}. Full attrs: {alice_attrs}"
        )
        assert enrichment.get("source") == "ldap", (
            f"Expected enrichment.source='ldap', got: {enrichment.get('source')!r}"
        )

    def test_oidc_normalized_primary_email(self, alice_attrs: dict) -> None:
        """Normalized primary_email for alice must be alice@corp.com."""
        assert alice_attrs.get("primary_email") == "alice@corp.com", (
            f"Expected primary_email='alice@corp.com', "
            f"got {alice_attrs.get('primary_email')!r}"
        )

    def test_oidc_source_protocol_is_oidc(self, alice_attrs: dict) -> None:
        """source_protocol in normalized attributes must be 'oidc'."""
        assert alice_attrs.get("source_protocol") == "oidc", (
            f"Expected source_protocol='oidc', got {alice_attrs.get('source_protocol')!r}"
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
        self, charlie_attrs: dict
    ) -> None:
        """LDAP-protocol events must also produce normalized_attributes."""
        assert charlie_attrs is not None, (
            "normalized_attributes is None for LDAP charlie event"
        )

    def test_ldap_event_enrichment_skipped_with_ldap_event_reason(
        self, charlie_attrs: dict
    ) -> None:
        """LDAP event enrichment must be skipped with skip_reason='ldap_event'.

        This is a security invariant: LDAP events carry directory data directly;
        performing a secondary LDAP lookup would be redundant and could mask
        attribute manipulation in the primary LDAP payload.
        """
        enrichment = charlie_attrs.get("enrichment", {})

        assert enrichment.get("applied") is False, (
            f"Expected enrichment.applied=False for LDAP event, got: {enrichment}"
        )
        assert enrichment.get("skip_reason") == "ldap_event", (
            f"Expected skip_reason='ldap_event', got: {enrichment.get('skip_reason')!r}. "
            f"Full enrichment: {enrichment}"
        )

    def test_ldap_event_parses_as_model(self, charlie_attrs: dict) -> None:
        """LDAP event normalized_attributes must also parse via NormalizedAttributes."""
        try:
            _validate_normalized_attributes(charlie_attrs)
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
        self, unknown_user_attrs: dict
    ) -> None:
        """OIDC event with unknown email must have skip_reason='no_ldap_match'."""
        enrichment = unknown_user_attrs.get("enrichment", {})

        assert enrichment.get("applied") is False, (
            f"Expected enrichment.applied=False for unknown user, got: {enrichment}"
        )
        assert enrichment.get("skip_reason") == "no_ldap_match", (
            f"Expected skip_reason='no_ldap_match', "
            f"got: {enrichment.get('skip_reason')!r}. Full enrichment: {enrichment}"
        )

    def test_unknown_user_normalization_still_produces_result(
        self, unknown_user_attrs: dict
    ) -> None:
        """Graceful degradation: failed enrichment must not prevent normalization.

        A missing LDAP match is not an error — normalization proceeds with
        primary-source-only data. The result must still parse as NormalizedAttributes.
        """
        assert unknown_user_attrs is not None, (
            "normalized_attributes must not be None even when LDAP has no match"
        )

        # Must parse as valid model
        try:
            _validate_normalized_attributes(unknown_user_attrs)
        except Exception as exc:
            pytest.fail(
                f"NormalizedAttributes.model_validate() raised for no-LDAP-match "
                f"result: {type(exc).__name__}: {exc}"
            )
