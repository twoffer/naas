# Component: NAAS Spec 2 — Chunk 4: LdapAdapter.enrich() mechanics
# Mode: TDD — all tests MUST fail until the implementer adds enrich() to:
#   services/identity-normalization/app/adapters/ldap.py
#
# What these tests validate:
#   C. enrich() mechanics (mock LDAP + mock Redis):
#   5. Reverse mapping: correlation_field → LDAP attr via UNIFIED_TO_LDAP
#   7. Search + match: LDAP result → extract() → unified dict returned
#   8. No-match / error → None (no uncaught LDAP exceptions)
#   10. enrich() is awaitable (async coroutine)
#
# CRITICAL ENVIRONMENT NOTE — python-ldap is NOT installed in the dev venv.
#   The 'ldap' C extension requires system build deps only present in Docker.
#   Strategy: inject a fake 'ldap' module via sys.modules BEFORE importing
#   app.adapters.ldap. The implementation uses a lazy import (import inside
#   enrich/helper), so the module can be imported without error, and the
#   fake ldap is seen when the code path executes.
#
# Mock injection pattern:
#   1. Create a MagicMock() for the top-level 'ldap' module.
#   2. Attach sub-modules: fake_ldap.filter = MagicMock(), fake_ldap.dn = MagicMock()
#   3. sys.modules["ldap"] = fake_ldap (and "ldap.filter", "ldap.dn")
#   4. import app.adapters.ldap AFTER injection (or clear sys.modules["app.*"] first).
#   5. Configure fake_ldap.SCOPE_SUBTREE = 2 (standard ldap constant).
#   6. Inject a fake Redis client via monkeypatch at the naas_shared.redis_client seam.
#
# Do NOT import ldap at the top of this file — it would error-collect the file
# in the dev environment, masking all test assertions.
#
# Scope note: Do NOT test skip_reason / EnrichmentApplied / EnrichmentSkipped here.
# Those are chunk 6 concerns. This file tests the adapter mechanics contract only.
#
# TDD state:
#   enrich() currently raises NotImplementedError (stub from chunk 2).
#   All tests MUST fail until the full implementation is in place.

# stdlib
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find docs/architecture/ — repo root marker."""
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
# Shared fake-ldap injection helpers
# ---------------------------------------------------------------------------


def _make_fake_ldap_module() -> MagicMock:
    """Build a fake 'ldap' MagicMock that mimics the minimal ldap API used by enrich().

    The fake provides:
    - ldap.SCOPE_SUBTREE = 2
    - ldap.filter.escape_filter_chars (a real callable — controlled in per-test setup)
    - ldap.dn.dn2str (unused directly but present so no AttributeError)
    - ldap.initialize(uri) → a connection mock
    - ldap.LDAPError base exception class
    - ldap.TIMEOUT_EXCEEDED (int sentinel, per python-ldap convention)
    - ldap.SERVER_DOWN (int sentinel)
    - ldap.NO_SUCH_OBJECT (int sentinel)
    """
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2

    # Exception classes — must be real classes so except clauses work
    class LDAPError(Exception):
        pass

    class TIMEOUT_EXCEEDED(LDAPError):
        pass

    class SERVER_DOWN(LDAPError):
        pass

    class NO_SUCH_OBJECT(LDAPError):
        pass

    class OPERATIONS_ERROR(LDAPError):
        pass

    fake_ldap.LDAPError = LDAPError
    fake_ldap.TIMEOUT_EXCEEDED = TIMEOUT_EXCEEDED
    fake_ldap.SERVER_DOWN = SERVER_DOWN
    fake_ldap.NO_SUCH_OBJECT = NO_SUCH_OBJECT
    fake_ldap.OPERATIONS_ERROR = OPERATIONS_ERROR

    # ldap.filter sub-module
    fake_filter = MagicMock(name="ldap.filter")
    # Default pass-through: escape_filter_chars returns the input unchanged
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake_ldap.filter = fake_filter

    # ldap.dn sub-module
    fake_dn = MagicMock(name="ldap.dn")
    fake_ldap.dn = fake_dn

    return fake_ldap


def _inject_fake_ldap(monkeypatch) -> MagicMock:
    """Inject fake ldap modules into sys.modules and return the top-level mock.

    The injection must happen before importing app.adapters.ldap (or the cached
    import must be cleared so it re-imports with the fake in place).
    """
    fake_ldap = _make_fake_ldap_module()
    monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap.dn)
    # Clear any cached app.adapters.ldap import so the next import re-evaluates
    for key in list(sys.modules.keys()):
        if key == "app.adapters.ldap" or key == "app.adapters":
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake_ldap


def _make_fake_redis(get_return=None, set_calls=None) -> MagicMock:
    """Build a fake async Redis client.

    Args:
        get_return: What redis.get() returns (None = miss, b'"null"' = negative hit,
                    JSON bytes = positive hit).
        set_calls: A list to record (key, value, ex=ttl) calls for assertion.
    """
    fake_redis = AsyncMock(name="redis")

    recorded_sets = set_calls if set_calls is not None else []

    async def fake_get(key: str):
        return get_return

    async def fake_setex(key: str, ttl: int, value):
        recorded_sets.append({"key": key, "ttl": ttl, "value": value})

    async def fake_set(key: str, value, ex=None):
        recorded_sets.append({"key": key, "ttl": ex, "value": value})

    fake_redis.get = AsyncMock(side_effect=fake_get)
    fake_redis.setex = AsyncMock(side_effect=fake_setex)
    fake_redis.set = AsyncMock(side_effect=fake_set)

    return fake_redis


# ---------------------------------------------------------------------------
# LDAP search result factory
# ---------------------------------------------------------------------------


def _make_ldap_result(
    cn: str = "Alice Smith",
    mail: str = "alice@corp.com",
    dept: str = "engineering",
    employee_type: str = "FTE",
    member_of: list | None = None,
) -> list:
    """Build a fake LDAP search result in python-ldap tuple format.

    python-ldap search_s returns a list of (dn, attr_dict) tuples where all
    attribute values are lists of bytes.

    The adapter must decode bytes to str — test the decode contract here.
    """
    if member_of is None:
        member_of = []

    dn = "uid=alice,ou=users,dc=corp,dc=com"
    attrs = {
        "cn": [cn.encode("utf-8")],
        "mail": [mail.encode("utf-8")],
        "departmentNumber": [dept.encode("utf-8")],
        "employeeType": [employee_type.encode("utf-8")],
    }
    if member_of:
        attrs["memberOf"] = [v.encode("utf-8") for v in member_of]

    return [(dn, attrs)]


# ===========================================================================
# CLASS 1 — enrich() is awaitable (async coroutine)
# ===========================================================================


class TestEnrichIsAwaitable:
    """enrich() must be an async coroutine that can be awaited.

    WHY: The identity-normalization service is fully async (FastAPI + asyncio).
    A synchronous enrich() would block the event loop during every LDAP call,
    starving all other concurrent pipeline events. The spec §5.3 explicitly
    requires wrapping blocking LDAP calls in asyncio.to_thread().
    """

    def test_enrich_returns_coroutine_on_call(self, monkeypatch) -> None:
        """LdapAdapter().enrich(...) must return a coroutine, not a plain value.

        TDD: currently raises NotImplementedError because it is a stub.
        After implementation this must return a coroutine object (inspect.iscoroutine).
        """
        import inspect

        _inject_fake_ldap(monkeypatch)
        fake_redis = _make_fake_redis(
            get_return=b'"null"'
        )  # negative cache → no LDAP call
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.enrich("primary_email", "alice@corp.com")

        assert inspect.iscoroutine(result), (
            f"LdapAdapter().enrich() must return a coroutine (async def), "
            f"got {type(result).__name__!r}. Spec §5.3 requires asyncio.to_thread wrapping."
        )
        # Close the coroutine to avoid ResourceWarning
        result.close()

    def test_enrich_can_be_awaited(self, monkeypatch) -> None:
        """await LdapAdapter().enrich(...) must complete without RuntimeError.

        TDD: currently raises NotImplementedError.
        """
        _inject_fake_ldap(monkeypatch)
        fake_redis = _make_fake_redis(get_return=b'"null"')
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()

        # Must not raise RuntimeError("cannot reuse already awaited coroutine") etc.
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        # Negative cache hit → attrs is None (no LDAP search); outcome is a str
        assert attrs is None or isinstance(attrs, dict), (
            f"enrich() attrs must be None or dict, got {type(attrs).__name__!r}"
        )
        assert isinstance(outcome, str), (
            f"enrich() outcome must be a str, got {type(outcome).__name__!r}"
        )


# ===========================================================================
# CLASS 2 — Reverse mapping (correlation_field → LDAP attr)
# ===========================================================================


class TestEnrichReverseMapping:
    """enrich() must reverse-map unified field names to LDAP attribute names.

    WHY: The enrichment config (§5.6) names unified fields (e.g., 'primary_email'),
    NOT LDAP attribute names. The adapter is the single source of truth for the
    unified↔LDAP translation (§5.3). If enrich() builds its filter using the raw
    unified field name as the LDAP attribute ('primary_email=alice'), the LDAP
    search will always return zero results — a silent misconfiguration.
    """

    def test_known_correlation_field_does_not_return_immediately_as_none(
        self, monkeypatch
    ) -> None:
        """A correlation_field in UNIFIED_TO_LDAP must attempt an LDAP query.

        Verify by injecting a fake LDAP connection that records search calls and
        confirming at least one search was attempted (i.e., the adapter did NOT
        short-circuit to None before querying).

        TDD: currently raises NotImplementedError.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        # Configure LDAP: connection binds OK, search returns a match
        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=_make_ldap_result())
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        # Cache miss → must query LDAP
        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert conn_mock.search_s.called, (
            "LdapAdapter.enrich('primary_email', ...) must call search_s at least once. "
            "The correlation_field 'primary_email' is in UNIFIED_TO_LDAP and must be queried."
        )

    def test_unknown_correlation_field_returns_none_without_ldap_query(
        self, monkeypatch
    ) -> None:
        """A correlation_field NOT in UNIFIED_TO_LDAP must return None immediately.

        WHY: 'favorite_color' is not a mappable unified field. Building a search
        filter for it would be meaningless. The adapter must detect this and return
        None (the 'un-reverse-mappable' path from spec §5.3). No LDAP search,
        no Redis cache write. This avoids confusing results and guards against
        misconfigured enrichment config.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        set_calls: list = []
        fake_redis = _make_fake_redis(get_return=None, set_calls=set_calls)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("favorite_color", "blue")
        )

        assert attrs is None, (
            f"enrich('favorite_color', ...) must return attrs=None for an unmappable "
            f"correlation_field, got {attrs!r}"
        )
        assert outcome == "unmappable_field", (
            f"enrich('favorite_color', ...) must return outcome='unmappable_field', "
            f"got {outcome!r}"
        )
        assert not conn_mock.search_s.called, (
            "enrich() must NOT call search_s for an unmappable correlation_field. "
            "Querying LDAP with an unmapped attribute would always return empty results."
        )

    @pytest.mark.parametrize(
        "unified_field,expected_ldap_attr",
        [
            ("primary_email", "mail"),
            ("display_name", "cn"),
            ("department", "departmentNumber"),
            ("employee_type", "employeeType"),
            ("groups", "memberOf"),
        ],
    )
    def test_correlation_field_reverse_maps_to_correct_ldap_attr(
        self,
        monkeypatch,
        unified_field: str,
        expected_ldap_attr: str,
    ) -> None:
        """Each unified field must map to the correct LDAP attribute in the filter.

        WHY: The mapping table is 'TRANSCRIBE EXACTLY' in spec §5.2. A wrong
        mapping (e.g., primary_email→uid instead of primary_email→mail) means the
        search filter never matches real LDAP entries.

        This test records the actual filter string passed to search_s and asserts
        it contains the correct LDAP attribute name.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        # escape_filter_chars passes through unchanged for simple values
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append(
                {
                    "base_dn": base_dn,
                    "scope": scope,
                    "filter_str": filter_str,
                    "attrlist": attrlist,
                }
            )
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich(unified_field, "test_value")
        )

        assert len(search_calls) >= 1, (
            f"enrich('{unified_field}', ...) must call search_s — no search was recorded."
        )

        filter_str = search_calls[0]["filter_str"]
        assert expected_ldap_attr in filter_str, (
            f"enrich('{unified_field}', ...) must build a filter containing "
            f"'{expected_ldap_attr}' (the LDAP attribute for this unified field). "
            f"Got filter: {filter_str!r}"
        )


# ===========================================================================
# CLASS 3 — Search + match: LDAP result through extract() → unified dict
# ===========================================================================


class TestEnrichSearchAndMatch:
    """On a successful LDAP match, enrich() must run the result through extract()
    and return the unified-schema dict.

    WHY: The adapter must not return raw LDAP attribute dicts (with bytes values
    and LDAP attribute names). The caller (NormalizationService) expects a unified
    dict with string values using unified field names. Using extract() internally
    ensures the same normalization path as direct LDAP events.
    """

    def test_enrich_match_returns_dict_with_unified_keys(self, monkeypatch) -> None:
        """A successful LDAP match must return a dict with unified schema keys.

        WHY: The unified dict is merged with primary-source attributes during
        conflict resolution (§5.5). Wrong key names (e.g., 'cn' instead of
        'display_name') would cause the resolution engine to ignore the LDAP data,
        silently producing single-source results for all enriched events.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="engineering",
                employee_type="FTE",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is not None, (
            "enrich() returned attrs=None on a successful LDAP match — expected a dict. "
            "When search_s returns a non-empty result, enrich() must return the "
            "unified dict, not None."
        )
        assert isinstance(attrs, dict), (
            f"enrich() must return a dict on match, got {type(attrs).__name__!r}"
        )
        assert outcome == "ldap_match", (
            f"enrich() outcome must be 'ldap_match' on a successful LDAP match, "
            f"got {outcome!r}"
        )

        expected_keys = {
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        }
        actual_keys = set(attrs.keys())
        assert expected_keys.issubset(actual_keys), (
            f"enrich() result must contain all unified schema keys. "
            f"Missing: {expected_keys - actual_keys}. Got keys: {actual_keys}"
        )

    def test_enrich_match_decodes_bytes_to_str(self, monkeypatch) -> None:
        """LDAP attribute values are bytes; enrich() must decode them to str.

        WHY: python-ldap returns attribute values as lists of bytes
        (e.g., b"Alice Smith"). Storing bytes in the unified dict would cause
        JSON serialization to fail with TypeError, breaking the stream publish.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="engineering",
                employee_type="FTE",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is not None, "Expected a match result, got attrs=None"

        # Scalar string fields must be str, not bytes
        for field in ("display_name", "primary_email"):
            val = attrs.get(field)
            if val is not None:
                assert isinstance(val, str), (
                    f"attrs['{field}'] must be str after bytes decoding, "
                    f"got {type(val).__name__!r}: {val!r}"
                )

    def test_enrich_match_applies_value_normalization(self, monkeypatch) -> None:
        """enrich() must apply value normalization (via extract()) to LDAP results.

        WHY: The caller (NormalizationService) runs conflict resolution expecting
        canonical values (e.g., 'Engineering', not 'engineering'). Skipping
        normalization in the enrichment path would cause canonical-value mismatches
        in unanimous resolution, silently flipping unanimous results to priority
        resolution with incorrect winner selection.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        # LDAP stores 'eng' — must normalize to 'Engineering'
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="eng",
                employee_type="fte",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is not None, "Expected a match result, got attrs=None"
        assert attrs.get("department") == "Engineering", (
            f"enrich() must normalize department 'eng' → 'Engineering' via extract(). "
            f"Got: {attrs.get('department')!r}"
        )
        assert attrs.get("employee_type") == "FTE", (
            f"enrich() must normalize employee_type 'fte' → 'FTE' via extract(). "
            f"Got: {attrs.get('employee_type')!r}"
        )


# ===========================================================================
# CLASS 4 — No match / errors → None (graceful, no uncaught exceptions)
# ===========================================================================


class TestEnrichNoMatchAndErrors:
    """enrich() must return None on no-match and absorb LDAP errors gracefully.

    WHY (spec §5.3, §5.4 — graceful degradation, ADR-0008):
    Enrichment failure must NEVER propagate as an exception to the consumer
    loop. A raised exception would cause the consumer to skip XACK, leaving
    the event in the pending list. On redelivery, the event would fail again
    (since the LDAP condition persists), creating an infinite redelivery loop
    that fills the Redis pending list and prevents all subsequent events
    from being processed. All LDAP error conditions must be absorbed.
    """

    def test_enrich_empty_search_result_returns_none(self, monkeypatch) -> None:
        """An empty LDAP search result (no directory entry) must return None.

        WHY: This is the 'no_ldap_match' path. The caller (chunk 6) will map
        this to EnrichmentSkipped(skip_reason='no_ldap_match'). enrich() must
        not raise KeyError or IndexError when the result list is empty.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])  # empty result
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "unknown@corp.com")
        )

        assert attrs is None, (
            f"enrich() must return attrs=None when LDAP search returns no results, "
            f"got {attrs!r}"
        )
        assert outcome == "ldap_no_match", (
            f"enrich() outcome must be 'ldap_no_match' on empty result, got {outcome!r}"
        )

    def test_enrich_ldap_connection_error_returns_none(self, monkeypatch) -> None:
        """An LDAP connection error (SERVER_DOWN) must not propagate out of enrich().

        WHY: If LDAP is down, the event must still be processed using primary-
        source-only data. Propagating the exception would break the consumer loop.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(
            side_effect=fake_ldap.SERVER_DOWN("connection refused")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        # Must NOT raise — graceful degradation
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is None, (
            f"enrich() must return attrs=None on connection error, not propagate SERVER_DOWN. "
            f"Got: {attrs!r}"
        )
        assert outcome == "ldap_connection_error", (
            f"enrich() outcome must be 'ldap_connection_error' on SERVER_DOWN, "
            f"got {outcome!r}"
        )

    def test_enrich_ldap_search_error_returns_none(self, monkeypatch) -> None:
        """An LDAP search error (OPERATIONS_ERROR) must not propagate out of enrich().

        WHY: Search errors can occur due to LDAP server load, ACL issues, or
        malformed filters that pass sanitization. In all cases, the event must be
        processed with primary-source-only data.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=fake_ldap.OPERATIONS_ERROR("search failed")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is None, (
            f"enrich() must return attrs=None on LDAP search error, "
            f"not propagate OPERATIONS_ERROR. Got: {attrs!r}"
        )
        assert outcome == "ldap_search_error", (
            f"enrich() outcome must be 'ldap_search_error' on OPERATIONS_ERROR, "
            f"got {outcome!r}"
        )

    def test_enrich_ldap_timeout_returns_none(self, monkeypatch) -> None:
        """An LDAP timeout (TIMEOUT_EXCEEDED) must not propagate out of enrich().

        WHY: The config specifies timeout_ms (§5.6). A timeout is a transient
        condition. The event must still be published downstream with primary-
        source-only data.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=fake_ldap.TIMEOUT_EXCEEDED("query timed out")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is None, (
            f"enrich() must return attrs=None on LDAP timeout, "
            f"not propagate TIMEOUT_EXCEEDED. Got: {attrs!r}"
        )
        assert outcome == "ldap_timeout", (
            f"enrich() outcome must be 'ldap_timeout' on TIMEOUT_EXCEEDED, "
            f"got {outcome!r}"
        )

    def test_enrich_unexpected_exception_returns_none(self, monkeypatch) -> None:
        """Unexpected exceptions during LDAP query must not propagate out of enrich().

        WHY: Belt-and-suspenders test. Even an unexpected exception (RuntimeError,
        ValueError from malformed LDAP response) must be absorbed gracefully.
        The event pipeline must not stall due to any single LDAP failure.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=RuntimeError("unexpected LDAP response format")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is None, (
            f"enrich() must return attrs=None on unexpected exceptions, got {attrs!r}"
        )
        assert outcome == "ldap_unexpected_error", (
            f"enrich() outcome must be 'ldap_unexpected_error' on unexpected exception, "
            f"got {outcome!r}"
        )
