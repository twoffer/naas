"""LDAP injection sanitization in LdapAdapter.enrich(): escape_filter_chars contract."""

from unittest.mock import MagicMock

# third-party
import pytest

from tests.services.identity_normalization.conftest import (
    FakeRedis as _FakeRedis,
)
from tests.services.identity_normalization.conftest import (
    inject_fake_ldap as _inject_fake_ldap,
)

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

    async def test_escape_filter_chars_called_with_lookup_value(
        self, monkeypatch
    ) -> None:
        """escape_filter_chars must be called with the raw lookup_value as argument.

        Verifies enrich() calls escape_filter_chars before building the LDAP filter.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        escape_calls: list = []

        def recording_escape(value: str) -> str:
            escape_calls.append(value)
            return value  # pass through

        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=recording_escape)

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
        await adapter.enrich("primary_email", lookup_value)

        assert len(escape_calls) >= 1, (
            "ldap.filter.escape_filter_chars must be called at least once before "
            "building the search filter. No call was recorded. "
            "This is a security requirement (spec §5.3 ⚠️ REQUIRED)."
        )
        assert lookup_value in escape_calls, (
            f"escape_filter_chars must be called with the raw lookup_value "
            f"{lookup_value!r}. Recorded calls: {escape_calls}"
        )

    async def test_escape_filter_chars_called_before_search(self, monkeypatch) -> None:
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

        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=recording_escape)

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
        await adapter.enrich("primary_email", "alice@corp.com")

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

    async def test_filter_contains_escaped_output_not_raw_value(
        self, monkeypatch
    ) -> None:
        """The filter string must contain the escape_filter_chars output.

        A marking escape function (prepends 'SAFE_') lets us distinguish
        'escaped output used' from 'raw value used'.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        escape_marker = "SAFE_"

        def marking_escape(value: str) -> str:
            return escape_marker + value

        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=marking_escape)

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
        await adapter.enrich("primary_email", raw_lookup)

        assert len(search_calls) >= 1, "search_s must be called"
        filter_str = search_calls[0]

        escaped_value = escape_marker + raw_lookup  # "SAFE_alice@corp.com"

        assert escaped_value in filter_str, (
            f"The filter string must contain the escaped output '{escaped_value}', "
            f"not the raw value '{raw_lookup}'. "
            f"Got filter: {filter_str!r}. "
            f"This confirms escape_filter_chars output was used in interpolation."
        )

    @pytest.mark.parametrize("dangerous_char", ["*", "(", ")", "\\"])
    async def test_ldap_metacharacters_are_not_interpolated_raw(
        self, monkeypatch, dangerous_char: str
    ) -> None:
        """LDAP metacharacters in lookup_value must be escaped in the value slot.

        WHY: LDAP filter injection (analogous to SQL injection) occurs when
        metacharacters change the filter's logical structure. The RFC 4515
        metacharacters are: * ( ) \\ NUL. An unescaped '*' in the value changes
        a presence assertion to a wildcard; '(' and ')' can close/open filter
        terms. This test confirms the value slot uses the escaped output.

        Assertion strategy: the escape function replaces each metachar with
        ESCxxx in the value slot, so we assert:
          1. The full filter matches the expected RFC 4515 form
             f"({ldap_attr}={escaped_value})".
          2. The raw dangerous char does not appear in the value slot
             (the part after '=' and before the closing ')').
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        def neutralizing_escape(value: str) -> str:
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

        raw_lookup = f"user{dangerous_char}inject"
        escaped_lookup = neutralizing_escape(raw_lookup)
        ldap_attr = "mail"  # primary_email → mail

        adapter = LdapAdapter()
        await adapter.enrich("primary_email", raw_lookup)

        assert len(search_calls) >= 1, (
            "search_s must be called for a valid correlation_field"
        )
        filter_str = search_calls[0]
        expected_filter = f"({ldap_attr}={escaped_lookup})"

        assert filter_str == expected_filter, (
            f"Filter must be {expected_filter!r} (RFC 4515 form with escaped value). "
            f"Got filter: {filter_str!r}. "
            f"This is a security requirement — raw interpolation allows LDAP injection."
        )

        # Extra safety: the raw dangerous payload must not appear in the value slot
        # (the part between '=' and the trailing ')').
        value_slot = filter_str[len(f"({ldap_attr}=") : -1]
        assert dangerous_char not in value_slot, (
            f"Raw metacharacter {dangerous_char!r} must not appear in the value slot. "
            f"Value slot: {value_slot!r}. "
            f"escape_filter_chars output must be used, not the raw lookup_value."
        )

    async def test_injection_attempt_does_not_bypass_correlation(
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

        marker = "SAFE_"

        def marking_escape(value: str) -> str:
            return marker + value.replace("*", "").replace("(", "").replace(")", "")

        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=marking_escape)

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
        await adapter.enrich("primary_email", injection_payload)

        assert len(search_calls) >= 1

        filter_str = search_calls[0]

        # The filter must contain the marker (escaped output) — not bare * or )
        assert marker in filter_str, (
            f"The filter must use the escape_filter_chars output (contains '{marker}'). "
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

        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=recording_escape)

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
