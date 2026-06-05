# Component: NAAS Spec 2 — Chunk 4: LdapAdapter — LDAP injection sanitization
# Mode: TDD — all tests MUST fail until the sanitization is implemented in enrich()
#
# What these tests validate:
#   6. LDAP injection sanitization (spec §5.3 ⚠️ REQUIRED):
#      - The search filter is built by calling ldap.filter.escape_filter_chars
#        on the lookup_value before interpolating into the filter string
#      - A fake escape_filter_chars that records its input confirms the raw
#        lookup_value is passed to it
#      - A lookup_value containing LDAP filter metacharacters ('*', '(', ')', '\\')
#        is never interpolated RAW into the filter string
#      - The CONTRACT is: the filter uses the ESCAPED value, not the raw value
#        (what escape_filter_chars does to it is the real library's job;
#         we only assert the call was made and the raw metacharacters are absent)
#
# WHY LDAP injection sanitization matters (security path):
#   An unsanitized LDAP filter allows attackers to manipulate directory queries.
#   Example: lookup_value = "*)(uid=*))(|(uid=*" with filter "(mail=<value>)"
#   produces "(mail=*)(uid=*))(|(uid=*)" — a valid LDAP filter that matches
#   ALL directory entries regardless of email, bypassing the user-identity correlation
#   entirely. An attacker who controls the lookup_value (via the primary auth token)
#   could force the service to merge ANY directory user's attributes with their event.
#   In an IAM context this is a privilege escalation vector.
#
# Mock strategy:
#   A controlled fake escape_filter_chars that transforms its input (e.g., prefixes
#   "ESCAPED:") lets us assert the filter was built from the escaped output, not the raw
#   input. This is cleaner than checking for RFC-escaped bytes (that's the real library's
#   job, exercised by integration tests in Docker).

# stdlib
import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

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
# Shared helpers (same pattern as other chunk-4 test files)
# ---------------------------------------------------------------------------


def _make_fake_ldap_module() -> MagicMock:
    """Build a fake 'ldap' MagicMock with exception classes and sub-modules."""
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2

    class LDAPError(Exception):
        pass
    class SERVER_DOWN(LDAPError):
        pass
    class TIMEOUT_EXCEEDED(LDAPError):
        pass
    class OPERATIONS_ERROR(LDAPError):
        pass

    fake_ldap.LDAPError = LDAPError
    fake_ldap.SERVER_DOWN = SERVER_DOWN
    fake_ldap.TIMEOUT_EXCEEDED = TIMEOUT_EXCEEDED
    fake_ldap.OPERATIONS_ERROR = OPERATIONS_ERROR

    fake_filter = MagicMock(name="ldap.filter")
    # Default: pass-through (identity function) — overridden per test
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake_ldap.filter = fake_filter

    fake_dn = MagicMock(name="ldap.dn")
    fake_ldap.dn = fake_dn

    return fake_ldap


def _inject_fake_ldap(monkeypatch) -> MagicMock:
    fake_ldap = _make_fake_ldap_module()
    monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap.dn)
    for key in list(sys.modules.keys()):
        if key == "app.adapters.ldap" or key == "app.adapters":
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake_ldap


class _FakeRedis:
    """Minimal fake async Redis — always returns cache miss, records set calls."""

    def __init__(self):
        self.set_calls: list = []

    async def get(self, key: str):
        return None  # always miss → forces LDAP query path

    async def setex(self, key: str, ttl: int, value):
        self.set_calls.append({"key": key, "ttl": ttl, "value": value})

    async def set(self, key: str, value, ex=None):
        self.set_calls.append({"key": key, "ttl": ex, "value": value})


# ===========================================================================
# CLASS 1 — escape_filter_chars is called on the lookup_value
# ===========================================================================


class TestEscapeFilterCharsIsCalled:
    """enrich() must call ldap.filter.escape_filter_chars on the lookup_value.

    WHY: This is the spec §5.3 ⚠️ REQUIRED sanitization. The call is the contract
    — what escape_filter_chars does to the value is the python-ldap library's
    responsibility (tested in the Docker integration suite).

    These tests assert the behavioral contract through enrich() via a fake
    escape_filter_chars that records calls and/or transforms the value in a
    detectable way.
    """

    def test_escape_filter_chars_called_with_lookup_value(
        self, monkeypatch
    ) -> None:
        """escape_filter_chars must be called with the raw lookup_value as argument.

        TDD: fails until enrich() calls escape_filter_chars before building the filter.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        escape_calls: list = []

        def recording_escape(value: str) -> str:
            escape_calls.append(value)
            return value  # pass through

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=recording_escape
        )

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        lookup_value = "alice@corp.com"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", lookup_value)
        )

        assert len(escape_calls) >= 1, (
            "ldap.filter.escape_filter_chars must be called at least once before "
            "building the search filter. No call was recorded. "
            "This is a security requirement (spec §5.3 ⚠️ REQUIRED)."
        )
        assert lookup_value in escape_calls, (
            f"escape_filter_chars must be called with the raw lookup_value "
            f"{lookup_value!r}. Recorded calls: {escape_calls}"
        )

    def test_escape_filter_chars_called_before_search(self, monkeypatch) -> None:
        """escape_filter_chars must be called BEFORE search_s.

        WHY: Calling escape after the filter is built would mean the filter was
        already constructed with the raw (unescaped) value. The escape must
        happen before interpolation, not after.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        call_order: list = []

        def recording_escape(value: str) -> str:
            call_order.append("escape")
            return value

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=recording_escape
        )

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(*args, **kwargs):
            call_order.append("search")
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert "escape" in call_order, "escape_filter_chars must be called"
        assert "search" in call_order, "search_s must be called"

        escape_idx = call_order.index("escape")
        search_idx = call_order.index("search")
        assert escape_idx < search_idx, (
            f"escape_filter_chars (index {escape_idx}) must be called BEFORE "
            f"search_s (index {search_idx}). call_order: {call_order}"
        )


# ===========================================================================
# CLASS 2 — Filter uses escaped value, not raw value (injection prevention)
# ===========================================================================


class TestFilterUsesEscapedValue:
    """The search filter passed to search_s must use the ESCAPED value.

    WHY: If the raw (unescaped) value were interpolated, LDAP metacharacters
    in the lookup_value would change the filter semantics. An attacker controlling
    the primary-source email attribute could craft a value like "*)(uid=*" to
    match arbitrary directory entries.

    Test strategy: provide an escape_filter_chars that prepends "SAFE_" to its
    input. Assert the filter contains "SAFE_" + lookup_value (the escaped output),
    not the raw lookup_value alone. This verifies the escaped output was used
    without relying on the exact RFC 4515 escaping algorithm.
    """

    def test_filter_contains_escaped_output_not_raw_value(
        self, monkeypatch
    ) -> None:
        """The filter string must contain the escape_filter_chars output.

        A marking escape function (prepends 'SAFE_') lets us distinguish
        'escaped output used' from 'raw value used'.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        ESCAPE_MARKER = "SAFE_"

        def marking_escape(value: str) -> str:
            return ESCAPE_MARKER + value

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=marking_escape
        )

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append(filter_str)
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        raw_lookup = "alice@corp.com"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", raw_lookup)
        )

        assert len(search_calls) >= 1, "search_s must be called"
        filter_str = search_calls[0]

        escaped_value = ESCAPE_MARKER + raw_lookup  # "SAFE_alice@corp.com"

        assert escaped_value in filter_str, (
            f"The filter string must contain the escaped output '{escaped_value}', "
            f"not the raw value '{raw_lookup}'. "
            f"Got filter: {filter_str!r}. "
            f"This confirms escape_filter_chars output was used in interpolation."
        )

    @pytest.mark.parametrize("dangerous_char", ["*", "(", ")", "\\"])
    def test_ldap_metacharacters_are_not_interpolated_raw(
        self, monkeypatch, dangerous_char: str
    ) -> None:
        """LDAP metacharacters in lookup_value must not appear raw in the filter.

        WHY: LDAP filter injection (analogous to SQL injection) occurs when
        metacharacters change the filter's logical structure. The RFC 4515
        metacharacters are: * ( ) \\ NUL. An unescaped '*' in the value changes
        a presence assertion to a wildcard; '(' and ')' can close/open filter
        terms. This test confirms no raw metacharacter survives to the filter.

        NOTE: We assert the CONTRACT (escape_filter_chars was called, raw char
        not present) not the exact RFC escaping (that's the real library's job).
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        # Use a transformation that removes the dangerous char from output
        # to simulate what a real escape function would do
        def neutralizing_escape(value: str) -> str:
            # Replace each metachar with its placeholder for test purposes
            return value.replace(dangerous_char, f"ESC{ord(dangerous_char)}")

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=neutralizing_escape
        )

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append(filter_str)
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        # Craft a lookup value containing the metacharacter
        raw_lookup = f"user{dangerous_char}inject"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", raw_lookup)
        )

        assert len(search_calls) >= 1, (
            f"search_s must be called for a valid correlation_field"
        )
        filter_str = search_calls[0]

        # The raw dangerous char must not appear in the filter
        # (the neutralizing_escape replaced it with ESCxxx)
        assert dangerous_char not in filter_str, (
            f"LDAP metacharacter {dangerous_char!r} must not appear raw in the filter. "
            f"Got filter: {filter_str!r}. "
            f"The escape_filter_chars output must be used, not the raw lookup_value. "
            f"This is a security requirement — raw interpolation allows LDAP injection."
        )

    def test_injection_attempt_does_not_bypass_correlation(
        self, monkeypatch
    ) -> None:
        """A classic LDAP injection payload must not produce an unbounded filter.

        WHY: The payload '*)(uid=*))(|(uid=*' is a textbook LDAP injection attempt.
        Combined with the escape_filter_chars contract, the filter must contain the
        escaped value (so the search is for the literal string, not a wildcard).

        This test uses the marking-escape strategy: the escaped output contains
        'SAFE_' prefix, confirming the escaped value was used in the filter.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        MARKER = "SAFE_"

        def marking_escape(value: str) -> str:
            return MARKER + value.replace("*", "").replace("(", "").replace(")", "")

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=marking_escape
        )

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append(filter_str)
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis()
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        injection_payload = "*)(uid=*))(|(uid=*"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", injection_payload)
        )

        assert len(search_calls) >= 1

        filter_str = search_calls[0]

        # The filter must contain the MARKER (escaped output) — not bare * or )
        assert MARKER in filter_str, (
            f"The filter must use the escape_filter_chars output (contains '{MARKER}'). "
            f"Got: {filter_str!r}. Raw injection payload was used instead."
        )

        # Must not contain unescaped injection-specific patterns
        # (the marking_escape strips * ( ) so these should be absent)
        assert "*)(" not in filter_str, (
            f"Injection metacharacter sequence '*)(uid=*' must not appear raw. "
            f"Got filter: {filter_str!r}"
        )


# ===========================================================================
# CLASS 3 — build_search_filter helper (if exposed)
# ===========================================================================


class TestBuildSearchFilterHelper:
    """Tests for the build_search_filter helper if the implementer exposes it.

    WHY: Spec §5.3 shows a build_search_filter helper function. If it is a
    module-level function, it can be tested directly for the filter template.
    If it is private/inlined, these tests still validate the contract through
    enrich() — they are skipped via pytest.importorskip if the helper isn't
    exported, not failed.

    NOTE: The primary sanitization contract tests are in TestEscapeFilterCharsIsCalled
    and TestFilterUsesEscapedValue, which go through enrich() directly. This class
    is supplementary for cases where the implementer exports the helper.
    """

    def _try_import_helper(self, monkeypatch) -> object:
        """Try to import build_search_filter from app.adapters.ldap."""
        _inject_fake_ldap(monkeypatch)
        try:
            from app.adapters.ldap import build_search_filter
            return build_search_filter
        except ImportError:
            return None

    def test_build_search_filter_if_exposed_uses_escaped_value(
        self, monkeypatch
    ) -> None:
        """If build_search_filter is exported, it must call escape_filter_chars.

        If the helper is not exported, the test is skipped (not failed) —
        the contract is already covered via enrich() in the other classes.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        escape_calls: list = []

        def recording_escape(value: str) -> str:
            escape_calls.append(value)
            return "ESCAPED_" + value

        fake_ldap.filter.escape_filter_chars = MagicMock(
            side_effect=recording_escape
        )

        try:
            from app.adapters.ldap import build_search_filter
        except ImportError:
            pytest.skip(
                "build_search_filter not exported from app.adapters.ldap — "
                "sanitization contract is tested via enrich() in other test classes."
            )

        result = build_search_filter("mail", "alice@corp.com")

        assert len(escape_calls) >= 1, (
            "build_search_filter must call escape_filter_chars"
        )
        assert escape_calls[0] == "alice@corp.com", (
            f"build_search_filter must pass the raw lookup_value to escape_filter_chars. "
            f"Got: {escape_calls[0]!r}"
        )
        assert "ESCAPED_alice@corp.com" in result, (
            f"build_search_filter must use the escaped output in the filter. "
            f"Got: {result!r}"
        )
        assert "mail" in result, (
            f"build_search_filter must include the LDAP attribute name in the filter. "
            f"Got: {result!r}"
        )

    def test_build_search_filter_if_exposed_follows_parenthesized_format(
        self, monkeypatch
    ) -> None:
        """If exported, build_search_filter must produce '(attr=value)' format.

        WHY: The spec §5.3 shows the filter format as '(mail=alice@corp.com)'.
        LDAP requires filters to be parenthesized for search_s.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        # Pass-through escape
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        try:
            from app.adapters.ldap import build_search_filter
        except ImportError:
            pytest.skip("build_search_filter not exported — skipping format test.")

        result = build_search_filter("mail", "alice@corp.com")

        assert result.startswith("("), (
            f"Filter must start with '(' (LDAP RFC 4515). Got: {result!r}"
        )
        assert result.endswith(")"), (
            f"Filter must end with ')' (LDAP RFC 4515). Got: {result!r}"
        )
        assert "=" in result, (
            f"Filter must contain '=' for equality assertion. Got: {result!r}"
        )
