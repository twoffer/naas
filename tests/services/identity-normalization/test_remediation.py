# Component: NAAS Spec 2 — Remediation: non-blocking bug fixes
# Mode: TDD — tests A, B, C, E, J, D, F, G, H MUST FAIL against current code
#             (bugs not yet fixed); tests will pass after fixes are applied.
#
# Covers:
#   A — Non-string raw_attributes type confusion in normalize_department,
#       normalize_employee_type, and all three adapter extract() methods.
#   B — Outer xreadgroup resilience: transient errors must not kill the loop;
#       CancelledError must still propagate.
#   C — weight_for unknown-source fallback returns float, not KeyError.
#   E — unbind_s() called before discarding a broken pooled connection.
#   J — RFC-4514 escaped-comma DN reduction via ldap.dn.str2dn.
#   D — Corrupted-cache PII redaction: warning log must NOT echo the full
#       cached string content.
#   F — Malformed message PII redaction: error log must truncate the value
#       for non-ValidationError exceptions (truncation path).
#   G — Non-string display_name / primary_email in all three adapters: a
#       non-str scalar in the name/email field must produce None, not the raw
#       non-str value (e.g., int 42 or dict {"x":1}).  Security gap: a non-str
#       primary_email propagates to the NormalizedAttributes model and can
#       cause downstream Pydantic validation crashes or incorrect identity
#       correlation.
#   H — Consumer ValidationError logging redaction (LOW#1 hardening): when
#       _process_message raises a Pydantic ValidationError the error log must
#       record field locations (no raw input values) rather than str(exc)[:200]
#       which embeds input_value PII.  Non-ValidationError exceptions retain the
#       truncated-string path (covered by F).

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
# Shared helpers reused across test classes (mirrors test_chunk4_ldap_cache.py)
# ---------------------------------------------------------------------------


def _make_fake_ldap_module() -> MagicMock:
    """Build a minimal fake ldap module with real exception classes."""
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2

    # Exception classes MUST be real classes so except-clauses match.
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

    fake_filter = MagicMock(name="ldap.filter")
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake_ldap.filter = fake_filter

    # ldap.dn sub-module — str2dn will be configured per-test for J
    fake_dn = MagicMock(name="ldap.dn")
    fake_ldap.dn = fake_dn

    return fake_ldap


def _inject_fake_ldap(monkeypatch) -> MagicMock:
    """Inject fake ldap into sys.modules and clear cached app.adapters.ldap."""
    fake_ldap = _make_fake_ldap_module()
    monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap.dn)
    for key in list(sys.modules.keys()):
        if key == "app.adapters.ldap" or key == "app.adapters":
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake_ldap


class _FakeRedis:
    """Fake async Redis client — records get/set/setex calls."""

    def __init__(self, get_return=None):
        self._get_return = get_return
        self.get_calls: list = []
        self.set_calls: list = []

    async def get(self, key: str):
        self.get_calls.append(key)
        return self._get_return

    async def setex(self, key: str, ttl: int, value):
        self.set_calls.append({"key": key, "ttl": ttl, "value": value})

    async def set(self, key: str, value, ex=None):
        self.set_calls.append({"key": key, "ttl": ex, "value": value})


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# A — Non-string raw_attributes type confusion
# ===========================================================================


class TestNormalizeHelperNonString:
    """normalize_department and normalize_employee_type must handle non-str inputs gracefully.

    WHY: raw_attributes come from untrusted external token claims. A field that is
    normally a string may arrive as an integer, list, or dict (e.g., Azure AD
    returning ``department: 123``). Passing a non-str to `.strip().lower()` raises
    AttributeError which would crash the normalization pipeline for that login event.
    The fix: guard at the top of each helper — return (None, False) / None respectively.
    """

    def test_normalize_department_with_int_returns_none_false(self) -> None:
        """normalize_department(123) must return (None, False), not raise.

        TDD: currently fails because value.strip() blows up on int.
        """
        from app.normalization_values import normalize_department

        result = normalize_department(123)

        assert result == (None, False), (
            f"normalize_department(123) must return (None, False) for a non-str input, "
            f"got {result!r}"
        )

    def test_normalize_department_with_list_returns_none_false(self) -> None:
        """normalize_department(['x']) must return (None, False), not raise."""
        from app.normalization_values import normalize_department

        result = normalize_department(["x"])

        assert result == (None, False), (
            f"normalize_department(['x']) must return (None, False), got {result!r}"
        )

    def test_normalize_department_with_dict_returns_none_false(self) -> None:
        """normalize_department({'a': 1}) must return (None, False), not raise."""
        from app.normalization_values import normalize_department

        result = normalize_department({"a": 1})

        assert result == (None, False), (
            f"normalize_department({{'a': 1}}) must return (None, False), got {result!r}"
        )

    def test_normalize_department_str_miss_returns_title_false(self) -> None:
        """normalize_department with an unrecognized str still title-cases and returns False.

        This is the existing behavior — we preserve it to avoid regression.
        """
        from app.normalization_values import normalize_department

        result = normalize_department("WidgetCorp")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)!r}"
        assert len(result) == 2
        val, was_mapped = result
        assert was_mapped is False, (
            f"Unrecognized str must return was_mapped=False, got {was_mapped!r}"
        )
        assert isinstance(val, str), (
            f"Unrecognized str must return a str value (title-cased), got {val!r}"
        )

    def test_normalize_department_str_hit_returns_canonical_true(self) -> None:
        """normalize_department('eng') returns ('Engineering', True) — baseline regression."""
        from app.normalization_values import normalize_department

        result = normalize_department("eng")

        assert result == ("Engineering", True), (
            f"normalize_department('eng') must return ('Engineering', True), got {result!r}"
        )

    def test_normalize_employee_type_with_int_returns_none(self) -> None:
        """normalize_employee_type(42) must return None, not raise.

        TDD: currently fails because value.strip() blows up on int.
        """
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type(42)

        assert result is None, (
            f"normalize_employee_type(42) must return None for a non-str input, "
            f"got {result!r}"
        )

    def test_normalize_employee_type_with_list_returns_none(self) -> None:
        """normalize_employee_type(['x']) must return None, not raise."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type(["x"])

        assert result is None, (
            f"normalize_employee_type(['x']) must return None, got {result!r}"
        )

    def test_normalize_employee_type_str_hit_unchanged(self) -> None:
        """normalize_employee_type('fte') returns 'FTE' — baseline regression."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("fte")

        assert result == "FTE", (
            f"normalize_employee_type('fte') must return 'FTE', got {result!r}"
        )


class TestAdapterExtractNonStringInputs:
    """All three adapter extract() methods must handle non-str field values without raising.

    WHY: The adapters call normalize_department and normalize_employee_type. Once those
    helpers guard non-str inputs, the adapters become safe too. But the groups field is
    a separate concern: if groups contains non-str items (e.g., ints), the adapter must
    filter them to strings only — non-str items must be dropped silently.

    Key names per spec §5.2 mapping:
      OIDC:  name, email, department, employee_type, groups
      SAML:  displayName, email, dept, employeeType, groups
      LDAP:  cn, mail, departmentNumber, employeeType, memberOf
    """

    def test_oidc_extract_with_nonstr_department_does_not_raise(self) -> None:
        """OidcAdapter.extract() with department=123 must not raise.

        TDD: currently fails because normalize_department(123) raises AttributeError.
        """
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        # Should not raise
        result = adapter.extract({
            "name": "Alice",
            "email": "alice@corp.com",
            "department": 123,
            "employee_type": "fte",
            "groups": ["admin"],
        })

        assert result["department"] is None, (
            f"OIDC extract with department=123 (non-str) must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_oidc_extract_with_nonstr_employee_type_does_not_raise(self) -> None:
        """OidcAdapter.extract() with employee_type=['x'] must not raise."""
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        result = adapter.extract({
            "name": "Alice",
            "email": "alice@corp.com",
            "department": "eng",
            "employee_type": ["x"],
            "groups": ["admin"],
        })

        assert result["employee_type"] is None, (
            f"OIDC extract with employee_type=['x'] must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_oidc_extract_groups_filters_to_strings_only(self) -> None:
        """OidcAdapter.extract() with groups=[1, 2, 'real-group'] keeps only strings.

        TDD: currently `list(raw_attributes.get('groups') or [])` passes ints through.
        After fix: non-str items are dropped.
        """
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        result = adapter.extract({
            "name": "Alice",
            "email": "alice@corp.com",
            "groups": [1, 2, "real-group"],
        })

        assert result["groups"] == ["real-group"], (
            f"OIDC extract groups with mixed types must keep only strings. "
            f"Expected ['real-group'], got {result['groups']!r}"
        )

    def test_saml_extract_with_nonstr_dept_does_not_raise(self) -> None:
        """SamlAdapter.extract() with dept=123 must not raise."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract({
            "displayName": "Bob",
            "email": "bob@corp.com",
            "dept": 123,
            "employeeType": "fte",
            "groups": ["staff"],
        })

        assert result["department"] is None, (
            f"SAML extract with dept=123 must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_saml_extract_with_nonstr_employee_type_does_not_raise(self) -> None:
        """SamlAdapter.extract() with employeeType={'code': 'fte'} must not raise."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract({
            "displayName": "Bob",
            "email": "bob@corp.com",
            "dept": "eng",
            "employeeType": {"code": "fte"},
            "groups": [],
        })

        assert result["employee_type"] is None, (
            f"SAML extract with employeeType=dict must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_saml_extract_groups_filters_to_strings_only(self) -> None:
        """SamlAdapter.extract() with groups=[1, 2, 'real-group'] keeps only strings."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract({
            "displayName": "Bob",
            "email": "bob@corp.com",
            "groups": [1, 2, "real-group"],
        })

        assert result["groups"] == ["real-group"], (
            f"SAML extract groups with mixed types must keep only strings. "
            f"Expected ['real-group'], got {result['groups']!r}"
        )

    def test_ldap_extract_with_nonstr_department_number_does_not_raise(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with departmentNumber=999 must not raise.

        Note: we inject fake ldap to allow importing app.adapters.ldap.
        """
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract({
            "cn": "Charlie",
            "mail": "charlie@corp.com",
            "departmentNumber": 999,
            "employeeType": "fte",
            "memberOf": [],
        })

        assert result["department"] is None, (
            f"LDAP extract with departmentNumber=999 (non-str) must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_ldap_extract_with_nonstr_employee_type_does_not_raise(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with employeeType=['fte'] must not raise."""
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract({
            "cn": "Charlie",
            "mail": "charlie@corp.com",
            "departmentNumber": "eng",
            "employeeType": ["fte"],
            "memberOf": [],
        })

        assert result["employee_type"] is None, (
            f"LDAP extract with employeeType=['fte'] must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_ldap_extract_member_of_filters_non_strings(self, monkeypatch) -> None:
        """LdapAdapter.extract() with memberOf=[1, 2, 'cn=grp,dc=corp'] keeps only strings.

        WHY: _reduce_dn_to_group_name calls str methods on the DN value; passing an
        int causes AttributeError. Non-str memberOf entries must be dropped.
        """
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract({
            "cn": "Charlie",
            "mail": "charlie@corp.com",
            "departmentNumber": None,
            "employeeType": None,
            "memberOf": [1, 2, "cn=engineering,ou=groups,dc=corp,dc=com"],
        })

        # Ints must be silently dropped; only the str DN is processed.
        # The string DN should reduce to a group name (non-None).
        for g in result["groups"]:
            assert isinstance(g, str), (
                f"All entries in groups must be strings; got {g!r} ({type(g).__name__})"
            )


# ===========================================================================
# B — Outer xreadgroup resilience
# ===========================================================================


class TestConsumerLoopXreadgroupResilience:
    """run_consumer_loop must survive transient xreadgroup errors and continue.

    WHY: Redis is a network service. A momentary blip (connection reset, timeout)
    raises an exception from xreadgroup. If that exception escapes the loop body
    unhandled, the entire consumer process dies and stops processing login events
    until the replica is restarted. The fix: wrap the outer xreadgroup call in a
    try/except, log, sleep briefly, and continue to the next iteration.

    CancelledError MUST still propagate — it signals intentional shutdown.
    """

    def test_transient_xreadgroup_error_does_not_kill_loop(self) -> None:
        """A generic Exception from xreadgroup must be caught; loop continues.

        TDD: currently fails because the outer while-loop does not wrap xreadgroup
        in a try/except, so the exception propagates and terminates the loop.

        Test strategy: xreadgroup side_effect sequence:
          1st call  → raises RuntimeError("transient redis error")
          2nd call  → returns one message (normal processing)
          3rd call  → raises CancelledError (clean shutdown)
        Assert: message from 2nd call is processed (normalize is called once).
        """
        from app.consumer import run_consumer_loop
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        normalized = NormalizedAttributes(
            display_name="Alice",
            primary_email="alice@corp.com",
            source_protocol="oidc",
            normalization_confidence=0.8,
            resolution_details={},
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event"),
        )

        normalize_call_count = [0]

        async def _normalize(record):
            normalize_call_count[0] += 1
            return normalized

        service = AsyncMock()
        service.normalize = _normalize

        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)

        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        from naas_shared.models import LoginEventRecord
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        from datetime import datetime, timezone
        from uuid import UUID
        import json as _json

        record = LoginEventRecord(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            user_id="alice",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={"name": "Alice", "email": "alice@corp.com", "groups": []},
        )
        data_str = _json.dumps(record.model_dump(mode="json"), default=str)
        one_message = [[STREAM_LOGIN_EVENTS, [("1-0", {"data": data_str})]]]

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            RuntimeError("transient redis error"),  # 1st iteration: error
            one_message,                             # 2nd iteration: success
            asyncio.CancelledError(),                # 3rd: clean shutdown
        ])
        redis.xack = AsyncMock()

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert normalize_call_count[0] == 1, (
            f"After a transient xreadgroup error, the loop must continue and process "
            f"the next valid message. Expected normalize() called 1 time, "
            f"got {normalize_call_count[0]}. "
            "The loop must NOT die on a transient Redis error."
        )

    def test_cancelled_error_propagates_through_loop(self) -> None:
        """asyncio.CancelledError from xreadgroup must propagate (clean shutdown).

        WHY: CancelledError is the mechanism by which the lifespan cancels the
        background consumer task on shutdown. If it is swallowed by the transient-
        error handler, the task runs forever and shutdown hangs.
        """
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=asyncio.CancelledError())
        redis.xack = AsyncMock()

        cancelled_propagated = False
        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            cancelled_propagated = True

        assert cancelled_propagated, (
            "asyncio.CancelledError must propagate out of run_consumer_loop — "
            "it signals intentional shutdown and must NOT be swallowed by the "
            "transient-error handler."
        )

    def test_loop_sleeps_after_transient_error(self) -> None:
        """After a transient xreadgroup error the loop must sleep before retrying.

        WHY: Without a sleep, a persistent error (e.g., Redis is unreachable for
        30 s) would spin the event loop at 100% CPU, burning resources and flooding
        logs. A brief sleep (even 0.1 s in tests) provides back-off.

        We verify that asyncio.sleep is called with a positive value after the error.
        We do NOT assert the exact sleep duration — the implementer may choose.
        """
        from app.consumer import run_consumer_loop

        sleep_calls: list[float] = []
        real_sleep = asyncio.sleep

        async def _capturing_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            await real_sleep(0)  # don't actually wait in tests

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            RuntimeError("redis down"),
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock()

        with patch("asyncio.sleep", side_effect=_capturing_sleep):
            try:
                _run(run_consumer_loop(
                    service=service,
                    repository=repository,
                    publisher=publisher,
                    redis=redis,
                ))
            except asyncio.CancelledError:
                pass

        error_sleeps = [d for d in sleep_calls if d > 0]
        assert len(error_sleeps) >= 1, (
            f"After a transient xreadgroup error, run_consumer_loop must call "
            f"asyncio.sleep(positive_value) to avoid spinning. "
            f"sleep calls recorded: {sleep_calls}"
        )


# ===========================================================================
# C — weight_for unknown-source fallback
# ===========================================================================


class TestWeightForUnknownSource:
    """weight_for must return a safe float for unknown sources, not raise KeyError.

    WHY: When a new protocol is introduced (e.g., a future "webauthn" source), or
    when tests inject an unexpected source name, ``defaults.source_weights[source]``
    raises KeyError because the source is not in the YAML defaults block. This
    crash propagates to the resolution layer, dropping the entire normalization
    result and causing the risk evaluator to treat the event as maximum risk.

    The fix: return a documented conservative floor value when the source is absent
    from both the attribute-specific weights and the defaults block.

    IMPLEMENTATION NOTE for feature-implementer:
    The expected floor value is assumed to be a module-level constant in
    normalization_config.py (e.g., _UNKNOWN_SOURCE_WEIGHT_FLOOR = 0.5 or similar).
    This test asserts the floor is in [0.0, min_default_weight] and does NOT raise.
    Coordinate with the implementer to align on the exact constant name/value.
    If the implementer uses a different floor (e.g., 0.3), update this test's
    approximate lower bound accordingly.
    """

    def _make_minimal_config(self):
        """Build a NormalizationConfig with known default weights."""
        from app.normalization_config import NormalizationConfig, Defaults, AttributeConfig, EnrichmentConfig, EnrichmentSources, LdapEnrichmentConfig

        return NormalizationConfig(
            defaults=Defaults(source_weights={"ldap": 0.7, "saml": 0.6, "oidc": 0.8}),
            attributes={
                "display_name": AttributeConfig(
                    weights={"ldap": 0.9, "saml": 0.7, "oidc": 0.6}
                )
            },
            enrichment=EnrichmentConfig(
                sources=EnrichmentSources(
                    ldap=LdapEnrichmentConfig(
                        enabled=False,
                        correlation_key="primary_email",
                        timeout_ms=2000,
                        on_failure="continue",
                        cache_ttl_seconds=60,
                    )
                )
            ),
        )

    def test_weight_for_unknown_source_does_not_raise(self) -> None:
        """weight_for(attribute, 'unknown_proto') must not raise KeyError.

        TDD: currently fails because self.defaults.source_weights['unknown_proto']
        raises KeyError when the source is absent from the defaults block.
        """
        cfg = self._make_minimal_config()

        # Must not raise
        try:
            result = cfg.weight_for("display_name", "unknown_proto")
        except KeyError as exc:
            pytest.fail(
                f"weight_for must not raise KeyError for an unknown source. "
                f"Got KeyError: {exc}. "
                "Expected a conservative floor float to be returned instead."
            )

        assert isinstance(result, float), (
            f"weight_for must return a float for unknown source, got {type(result)!r}"
        )

    def test_weight_for_unknown_source_returns_conservative_floor(self) -> None:
        """weight_for with unknown source returns a floor value in [0.0, min_default].

        The floor must be <= the minimum configured default weight (0.6 in this config)
        so that unknown sources are treated conservatively, not generously.
        """
        cfg = self._make_minimal_config()

        result = cfg.weight_for("primary_email", "unknown_proto")

        min_default = min(cfg.defaults.source_weights.values())  # 0.6

        assert 0.0 <= result <= min_default, (
            f"weight_for floor for unknown source must be in [0.0, min_default={min_default}]. "
            f"Got {result!r}. "
            "The floor should be conservative — not higher than the lowest known source weight."
        )

    def test_weight_for_unknown_source_on_unknown_attribute_does_not_raise(
        self,
    ) -> None:
        """weight_for with both unknown attribute AND unknown source must not raise."""
        cfg = self._make_minimal_config()

        try:
            result = cfg.weight_for("totally_unknown_attr", "unknown_proto")
        except KeyError as exc:
            pytest.fail(
                f"weight_for must not raise KeyError for unknown attribute+source. "
                f"Got: {exc}"
            )

        assert isinstance(result, float), (
            f"Expected float return, got {type(result)!r}"
        )

    def test_weight_for_known_source_not_in_defaults_falls_back_correctly(
        self,
    ) -> None:
        """Known source in attribute weights but not in defaults still resolves.

        This is the existing happy-path — verify it still works after the fix.
        """
        cfg = self._make_minimal_config()

        # 'display_name' has attribute-level weight for 'ldap' = 0.9
        result = cfg.weight_for("display_name", "ldap")

        assert result == pytest.approx(0.9), (
            f"weight_for('display_name', 'ldap') must return attribute-level weight 0.9, "
            f"got {result!r}"
        )


# ===========================================================================
# E — unbind_s() called before discarding a broken pooled connection
# ===========================================================================


class TestPoolSearchUnbindOnBrokenConnection:
    """_pool_search must call unbind_s() on a broken connection before freeing the slot.

    WHY: A broken connection that is discarded without calling unbind_s() leaks the
    server-side session. Under heavy load with frequent search errors, this can
    exhaust the LDAP server's connection limit, causing ALL future connections to
    be refused (including from other services that share the directory). Calling
    unbind_s() signals to the server that the session is done; a best-effort call
    (swallowing errors from unbind_s itself) is sufficient.

    The slot must be freed (put_nowait(None)) regardless of whether unbind_s raises.
    """

    def _make_recording_conn(self, search_exc=None, unbind_exc=None):
        """Build a fake LDAP connection that records method calls."""
        conn = MagicMock()
        conn.simple_bind_s = MagicMock(return_value=None)
        if search_exc is not None:
            conn.search_s = MagicMock(side_effect=search_exc)
        else:
            conn.search_s = MagicMock(return_value=[])

        if unbind_exc is not None:
            conn.unbind_s = MagicMock(side_effect=unbind_exc)
        else:
            conn.unbind_s = MagicMock(return_value=None)

        return conn

    def test_unbind_s_called_on_search_failure(self, monkeypatch) -> None:
        """When a pooled connection's search raises, unbind_s() must be called on it.

        TDD: currently fails because _pool_search calls put_nowait(None) on error
        but does NOT call unbind_s() first.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        broken_conn = self._make_recording_conn(
            search_exc=Exception("search failed unexpectedly")
        )
        fake_ldap.initialize = MagicMock(return_value=broken_conn)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        _run(adapter.enrich("primary_email", "alice@corp.com"))

        assert broken_conn.unbind_s.called, (
            "unbind_s() must be called on a broken pooled connection before the slot "
            "is freed. This prevents server-side session leaks. "
            f"unbind_s call count: {broken_conn.unbind_s.call_count}"
        )

    def test_unbind_s_raising_does_not_prevent_slot_free(self, monkeypatch) -> None:
        """If unbind_s() itself raises, the pool slot must still be freed (put_nowait(None)).

        WHY: If the slot is not freed when unbind_s raises, the pool is permanently
        reduced by one slot. After enough failures the pool is exhausted and all
        LDAP enrichment blocks indefinitely.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        broken_conn = self._make_recording_conn(
            search_exc=Exception("search failed"),
            unbind_exc=Exception("unbind also failed"),
        )
        fake_ldap.initialize = MagicMock(return_value=broken_conn)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        from app.adapters.ldap import LdapAdapter
        import app.adapters.ldap as _ldap_mod

        # After the first call with the broken connection, the slot should be freed.
        # We verify by making a second call — if the slot was not freed, it would
        # block forever (pool.get() blocks when pool is empty with maxsize=pool_size).
        # We use asyncio.wait_for with a short timeout to detect blocking.

        adapter = LdapAdapter()

        # First call — broken connection, unbind raises
        _run(adapter.enrich("primary_email", "alice@corp.com"))

        # Second call — must complete (pool has its slot back)
        # If the slot was not freed, this will block then timeout.
        new_conn = MagicMock()
        new_conn.simple_bind_s = MagicMock(return_value=None)
        new_conn.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=new_conn)

        async def _second_call():
            return await adapter.enrich("primary_email", "bob@corp.com")

        try:
            result = _run(asyncio.wait_for(_second_call(), timeout=2.0))
        except asyncio.TimeoutError:
            pytest.fail(
                "Second enrich() call timed out — the pool slot was not freed after "
                "a failed unbind_s(). put_nowait(None) must be called even when "
                "unbind_s itself raises."
            )

    def test_unbind_s_called_in_thread(self, monkeypatch) -> None:
        """unbind_s() must be called via asyncio.to_thread (or equivalent thread-safe call).

        WHY: python-ldap is a blocking C extension. Calling unbind_s() on the event
        loop directly would block all concurrent tasks during the unbind. The fix
        must call unbind_s in a thread (via asyncio.to_thread or run_in_executor).

        We verify this by checking that asyncio.to_thread is called at least once
        in the error path (in addition to the connection creation and search threads).
        The exact call count is not asserted — we only verify at least 3 to_thread
        calls total (connect + search + unbind).
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        broken_conn = self._make_recording_conn(
            search_exc=Exception("search failed")
        )
        fake_ldap.initialize = MagicMock(return_value=broken_conn)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        to_thread_call_funcs: list = []
        real_to_thread = asyncio.to_thread

        async def _recording_to_thread(func, *args, **kwargs):
            to_thread_call_funcs.append(func)
            return await real_to_thread(func, *args, **kwargs)

        with patch("asyncio.to_thread", side_effect=_recording_to_thread):
            from app.adapters.ldap import LdapAdapter
            adapter = LdapAdapter()
            _run(adapter.enrich("primary_email", "alice@corp.com"))

        # Must have called to_thread for: create_connection, search, and unbind
        assert len(to_thread_call_funcs) >= 3, (
            f"Expected at least 3 asyncio.to_thread calls (connect, search, unbind). "
            f"Got {len(to_thread_call_funcs)} calls with funcs: "
            f"{[getattr(f, '__name__', repr(f)) for f in to_thread_call_funcs]}. "
            "unbind_s must be dispatched to a thread, not called on the event loop."
        )


# ===========================================================================
# J — RFC-4514 escaped-comma DN reduction via ldap.dn.str2dn
# ===========================================================================


class TestReduceDnToGroupNameWithStr2dn:
    """_reduce_dn_to_group_name must use ldap.dn.str2dn for correct escaped-comma handling.

    WHY: The current regex-based implementation uses ``(?:^|,)\\s*cn=([^,]+)`` which
    captures the cn value up to the first comma. For a DN like
    ``cn=Smith\\, John,ou=groups,dc=example,dc=com``, the escaped comma (\\,) is part
    of the cn value, but the regex captures only "Smith\\" instead of "Smith, John".
    The result is a truncated, wrong group name that would fail policy rule evaluation.

    The fix: replace the regex with ldap.dn.str2dn, which correctly parses RFC-4514
    escaped characters and returns the full unescaped cn value.

    We add str2dn to the fake ldap.dn module with a realistic implementation.
    """

    def _inject_ldap_with_str2dn(self, monkeypatch) -> MagicMock:
        """Inject fake ldap with a realistic str2dn that handles escaped commas."""
        fake_ldap = _inject_fake_ldap(monkeypatch)

        def _fake_str2dn(dn_str: str):
            """Minimal RFC-4514 str2dn that handles simple and escaped-comma DNs.

            Returns list of RDN lists: [[(attr, value, flags), ...], ...]
            where each inner list represents one RDN component.

            Handles:
              - Simple DNs: cn=engineering,ou=groups,dc=example,dc=com
              - Escaped-comma: cn=Smith\\, John,ou=groups,dc=example,dc=com
            """
            # Split on commas that are NOT preceded by a backslash.
            # We do a simple manual scan to avoid regex-in-test complexity.
            rdns = []
            current = []
            i = 0
            while i < len(dn_str):
                ch = dn_str[i]
                if ch == "\\" and i + 1 < len(dn_str):
                    # Escaped character — include the next char as literal
                    current.append(dn_str[i + 1])
                    i += 2
                elif ch == ",":
                    rdns.append("".join(current).strip())
                    current = []
                    i += 1
                else:
                    current.append(ch)
                    i += 1
            if current:
                rdns.append("".join(current).strip())

            result = []
            for rdn_str in rdns:
                if "=" in rdn_str:
                    attr, _, value = rdn_str.partition("=")
                    result.append([(attr.strip(), value.strip(), 0)])
                else:
                    result.append([(rdn_str, rdn_str, 0)])
            return result

        fake_ldap.dn.str2dn = MagicMock(side_effect=_fake_str2dn)
        return fake_ldap

    def test_normal_dn_reduces_to_cn_value(self, monkeypatch) -> None:
        """A standard DN like 'cn=engineering,ou=groups,dc=example,dc=com' → 'engineering'.

        This is the existing behavior — verify it still works after the str2dn refactor.
        """
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name(
            "cn=engineering,ou=groups,dc=example,dc=com"
        )

        assert result == "engineering", (
            f"Normal DN must reduce to its cn RDN value 'engineering', got {result!r}"
        )

    def test_escaped_comma_dn_preserves_comma_in_group_name(
        self, monkeypatch
    ) -> None:
        """A DN with escaped comma: 'cn=Smith\\, John,...' → group name 'Smith, John'.

        TDD: currently FAILS because the regex stops at the escaped comma and
        returns only 'Smith\\' instead of 'Smith, John'.
        After fix (str2dn), the escaped comma is unescaped and preserved in output.
        """
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        dn = r"cn=Smith\, John,ou=groups,dc=example,dc=com"
        result = _reduce_dn_to_group_name(dn)

        assert result == "Smith, John", (
            f"Escaped-comma DN must reduce to group name 'Smith, John' "
            f"(comma preserved after unescaping). Got {result!r}. "
            "This fails with the regex approach and requires ldap.dn.str2dn."
        )

    def test_bare_name_passes_through_unchanged(self, monkeypatch) -> None:
        """A bare group name (no '=' in it) is returned as-is.

        This is the existing behavior for LDAP implementations that store group
        names directly in memberOf rather than full DNs.
        """
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name("engineering")

        assert result == "engineering", (
            f"Bare group name 'engineering' must pass through unchanged, got {result!r}"
        )

    def test_malformed_dn_falls_back_gracefully(self, monkeypatch) -> None:
        """A DN that str2dn raises on must fall back without exception.

        WHY: str2dn raises ldap.DECODING_ERROR (or similar) for truly malformed DN
        strings. The caller must not crash — it should return None so the entry is
        skipped.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        # str2dn raises on malformed input
        fake_ldap.dn.str2dn = MagicMock(
            side_effect=Exception("malformed DN")
        )

        from app.adapters.ldap import _reduce_dn_to_group_name

        # Must not raise; should return None or fall back to the existing behavior
        try:
            result = _reduce_dn_to_group_name("not=a=valid=dn=structure=here")
        except Exception as exc:
            pytest.fail(
                f"_reduce_dn_to_group_name must not propagate str2dn exceptions. "
                f"Got: {type(exc).__name__}: {exc}"
            )

        # Result may be None or a fallback string — both are acceptable
        # The key invariant is: no exception
        assert result is None or isinstance(result, str), (
            f"Fall-back result must be None or str, got {type(result)!r}"
        )

    def test_empty_dn_returns_none(self, monkeypatch) -> None:
        """An empty string DN returns None (not a group name)."""
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name("")

        assert result is None, (
            f"Empty DN must return None, got {result!r}"
        )


# ===========================================================================
# D — Corrupted-cache PII redaction
# ===========================================================================


class TestCorruptedCacheLogRedaction:
    """The warning log for a corrupted cache entry must not echo the full cached string.

    WHY (§5.3 / general PII hygiene): The positive cache entry contains a JSON dict
    with the user's email address, display name, and other directory attributes
    (PII). If the cached string is corrupted (e.g., truncated mid-JSON, wrong
    encoding), the current code logs ``cached_value=repr(cached_str)`` which echoes
    the full raw content of the cache entry — potentially including the user's email,
    display name, etc. — to the application log stream. Logs are often collected by
    SIEM systems, log aggregators, or retained on disk in plaintext, making this a
    PII exfiltration risk.

    The fix: replace ``cached_value=repr(cached_str)`` with a redacted form that
    conveys enough for debugging (e.g., length, first N chars, or a hash) without
    exposing PII.

    Assert strategy: verify that a known PII token (e.g., 'alice@corp.com') in
    the corrupt cache content does NOT appear in any log event emitted during the
    enrich() call. We capture structlog output by patching the bound logger.

    NOTE: Because this service uses structlog rather than stdlib logging, we capture
    log events by patching the logger's warning method and inspecting kwargs.
    If the implementer uses a different log-capture seam, the test may need adjustment
    — but the invariant (PII absent from log kwargs) is non-negotiable.
    """

    def test_corrupted_cache_warning_does_not_echo_pii_email(
        self, monkeypatch
    ) -> None:
        """corrupted cache warning must not include the user's email in logged content.

        TDD: currently fails because the warning logs ``cached_value=repr(cached_str)``
        which would contain alice@corp.com verbatim.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        # Corrupted cache entry that contains PII (email in the raw content)
        pii_token = "alice@corp.com"
        corrupted_cache = (
            f'{{"primary_email": "{pii_token}", "display_name": "Alice Smith", '
            f'"dept": "Eng"'  # intentionally unclosed — corrupt JSON
        ).encode("utf-8")

        fake_redis = _FakeRedis(get_return=corrupted_cache)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        # Capture all kwargs passed to any logger.warning call
        logged_warning_kwargs: list[dict] = []

        import app.adapters.ldap as _ldap_mod
        original_warning = None

        class _CapturingLogger:
            def __init__(self, delegate):
                self._delegate = delegate

            def warning(self, event: str, **kwargs):
                logged_warning_kwargs.append({"event": event, **kwargs})
                return self._delegate.warning(event, **kwargs)

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        # Patch the module-level _logger in app.adapters.ldap
        original_logger = _ldap_mod._logger
        capturing = _CapturingLogger(original_logger)
        monkeypatch.setattr(_ldap_mod, "_logger", capturing)

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        _run(adapter.enrich("primary_email", pii_token))

        # Verify at least one warning was emitted (the corrupted-cache path)
        assert len(logged_warning_kwargs) >= 1, (
            "Expected at least one logger.warning call on corrupted cache entry, got none. "
            "Ensure the corrupted-cache path logs a warning."
        )

        # The PII token must NOT appear in any warning log event's string repr
        for log_event in logged_warning_kwargs:
            log_repr = repr(log_event)
            assert pii_token not in log_repr, (
                f"PII token '{pii_token}' must NOT appear in warning log event. "
                f"Found in: {log_repr!r}. "
                "The cached_value kwarg must be redacted (e.g., show length/hash, not raw content)."
            )


# ===========================================================================
# F — Malformed message PII redaction in consumer.py
# ===========================================================================


class TestMalformedMessageLogRedaction:
    """The error log for a malformed stream message must truncate/bound the error string.

    WHY: When a login event message has a malformed 'data' field (e.g., invalid JSON
    or a Pydantic validation error), the consumer logs ``error=str(exc)``. If the
    malformed data contains a user's email or other PII (which is plausible — the
    data field IS the login event JSON), str(exc) may echo the full malformed
    content. For Pydantic ValidationErrors in particular, the exception message
    includes the field values that failed validation.

    The fix (two-part):
      - Non-ValidationError exceptions: truncate the error string in the log to a
        bounded length (e.g., 200 chars) so that large PII-containing exception
        messages do not appear in full.
      - Pydantic ValidationError: log field locations only
        (e.g., ``[e["loc"] for e in exc.errors()]``) — never log the raw
        input_value that the exception message embeds.

    This class covers the non-ValidationError (truncation) path.
    The ValidationError PII redaction path is in TestValidationErrorLogRedaction (H).

    Assert strategy (this class): service.normalize raises a RuntimeError whose
    message contains a 500-char PII-like string; verify that the logged error
    string is bounded in length (i.e., does not contain the full 500-char payload).
    """

    def _make_valid_message_data(self) -> str:
        """Return a valid LoginEventRecord JSON string for use as stream message data."""
        import json as _json
        from naas_shared.models import LoginEventRecord
        from datetime import datetime, timezone
        from uuid import UUID

        record = LoginEventRecord(
            id=UUID("12345678-1234-5678-1234-567812345678"),
            user_id="alice",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={"name": "Alice", "email": "alice@corp.com", "groups": []},
        )
        return _json.dumps(record.model_dump(mode="json"), default=str)

    def _make_capturing_logger(self, logged_errors: list):
        """Return a logger wrapper that captures error() calls without forwarding."""
        import app.consumer as _consumer_mod

        class _CapturingBoundLogger:
            def __init__(self, delegate):
                self._delegate = delegate

            def error(self, event: str, **kwargs):
                logged_errors.append({"event": event, **kwargs})
                # do not forward to real logger in tests

            def bind(self, **kwargs):
                return _CapturingBoundLogger(self._delegate.bind(**kwargs))

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        return _CapturingBoundLogger(_consumer_mod._logger)

    def test_malformed_message_error_log_truncates_long_error(self) -> None:
        """Non-ValidationError exception: consumer error log must truncate to <= 300 chars.

        WHY: This test explicitly covers the non-ValidationError truncation path —
        service.normalize raises a RuntimeError whose message is 500+ chars. After
        the implementer adds the two-path handler, non-ValidationError exceptions
        must still be truncated (str(exc)[:200]); only ValidationError gets the
        location-based treatment (see TestValidationErrorLogRedaction).

        CHANGE FROM ORIGINAL: previously this test used a malformed JSON message
        that produced a Pydantic ValidationError (missing required fields). That
        scenario now falls into the ValidationError branch. To keep this test
        exercising the *truncation* branch specifically, we inject a RuntimeError
        from service.normalize() instead.
        """
        from app.consumer import run_consumer_loop
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        import app.consumer as _consumer_mod

        # A valid message so the parse step succeeds; the long error comes from normalize()
        valid_data = self._make_valid_message_data()
        one_good_message_bad_normalize = [
            [STREAM_LOGIN_EVENTS, [("msg-1-0", {"data": valid_data})]]
        ]

        # service.normalize raises a RuntimeError with a very long message (500+ chars)
        long_error_payload = "RUNTIME-ERR-PAYLOAD-" + ("X" * 500)
        service = AsyncMock()
        service.normalize = AsyncMock(
            side_effect=RuntimeError(long_error_payload)
        )
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            one_good_message_bad_normalize,
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock()

        logged_errors: list[dict] = []
        original_consumer_logger = _consumer_mod._logger
        _consumer_mod._logger = self._make_capturing_logger(logged_errors)

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass
        finally:
            _consumer_mod._logger = original_consumer_logger

        assert len(logged_errors) >= 1, (
            "Expected at least one error log event when normalize() raises RuntimeError."
        )

        # The logged error string must be bounded — not the full 500-char payload
        for log_event in logged_errors:
            error_val = log_event.get("error", "")
            assert len(error_val) <= 300, (
                f"The 'error' field in consumer error log must be truncated to <= 300 chars "
                f"for non-ValidationError exceptions. "
                f"Got {len(error_val)} chars: {error_val[:100]!r}..."
            )


# ===========================================================================
# G — Non-string display_name / primary_email in adapter extract() methods
# ===========================================================================


class TestAdapterExtractNonStringNameEmail:
    """All three adapter extract() methods must return None for non-str name/email fields.

    WHY (security gap): The existing adapters call ``raw_attributes.get("name")``
    (OIDC), ``raw_attributes.get("displayName")`` (SAML), and
    ``raw_attributes.get("cn")`` / ``raw_attributes.get("mail")`` (LDAP) and return
    whatever the dict holds — including non-str values such as an integer or a nested
    dict that a mis-configured IdP may inject.  A non-str ``primary_email`` propagates
    directly into NormalizedAttributes and then into the PostgreSQL JSONB payload.
    Downstream consumers (risk evaluator, dashboard) that call
    NormalizedAttributes.model_validate() on the JSONB will raise a Pydantic
    ValidationError because ``primary_email`` is typed as ``str | None``, not
    ``Any``.  A non-str ``display_name`` causes the same crash.

    The fix mirrors the existing non-str guard in ``normalize_department`` and
    ``normalize_employee_type``: at the top of each extract() method, check each
    scalar field with ``isinstance(v, str)``; if not a str, substitute None.

    Contract (identical to department/employee_type): non-str scalar → None.

    TDD: all six tests FAIL currently because the adapters return the raw non-str
    value instead of None.
    """

    # --- OIDC ---

    def test_oidc_extract_with_nonstr_name_returns_display_name_none(self) -> None:
        """OidcAdapter.extract() with name=42 must return display_name=None, not 42.

        TDD: currently fails because ``raw_attributes.get("name")`` returns 42
        verbatim with no type check.  The fix: guard with isinstance(v, str).
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({
            "name": 42,
            "email": "alice@corp.com",
            "groups": [],
        })

        assert result["display_name"] is None, (
            f"OidcAdapter.extract() with name=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str scalar in name must be coerced to None, not passed through."
        )

    def test_oidc_extract_with_nonstr_email_returns_primary_email_none(self) -> None:
        """OidcAdapter.extract() with email={\"x\":1} must return primary_email=None.

        TDD: currently fails because ``raw_attributes.get("email")`` returns the
        dict verbatim.  A non-str primary_email causes downstream Pydantic
        ValidationError when NormalizedAttributes.model_validate() is called.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({
            "name": "Alice",
            "email": {"x": 1},
            "groups": [],
        })

        assert result["primary_email"] is None, (
            f"OidcAdapter.extract() with email={{\"x\":1}} (non-str) must return "
            f"primary_email=None, got {result['primary_email']!r}. "
            "A dict in the email field must be coerced to None."
        )

    # --- SAML ---

    def test_saml_extract_with_nonstr_display_name_returns_display_name_none(
        self,
    ) -> None:
        """SamlAdapter.extract() with displayName=42 must return display_name=None.

        TDD: currently fails because ``raw_attributes.get("displayName")`` returns
        42 verbatim.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({
            "displayName": 42,
            "email": "bob@corp.com",
            "groups": [],
        })

        assert result["display_name"] is None, (
            f"SamlAdapter.extract() with displayName=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str displayName must be coerced to None."
        )

    def test_saml_extract_with_nonstr_email_returns_primary_email_none(self) -> None:
        """SamlAdapter.extract() with email=[\"a@b.com\"] must return primary_email=None.

        TDD: currently fails because ``raw_attributes.get("email")`` returns the
        list verbatim.  A list primary_email causes Pydantic ValidationError
        downstream.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({
            "displayName": "Bob",
            "email": ["a@b.com"],
            "groups": [],
        })

        assert result["primary_email"] is None, (
            f"SamlAdapter.extract() with email=[\"a@b.com\"] (non-str) must return "
            f"primary_email=None, got {result['primary_email']!r}. "
            "A list in the email field must be coerced to None."
        )

    # --- LDAP ---

    def test_ldap_extract_with_nonstr_cn_returns_display_name_none(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with cn=42 must return display_name=None.

        TDD: currently fails because ``raw_attributes.get("cn")`` returns 42
        verbatim.  We inject fake ldap so app.adapters.ldap is importable.
        """
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "cn": 42,
            "mail": "charlie@corp.com",
            "departmentNumber": None,
            "employeeType": None,
            "memberOf": [],
        })

        assert result["display_name"] is None, (
            f"LdapAdapter.extract() with cn=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str cn must be coerced to None."
        )

    def test_ldap_extract_with_nonstr_mail_returns_primary_email_none(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with mail={\"x\":1} must return primary_email=None.

        TDD: currently fails because ``raw_attributes.get("mail")`` returns the
        dict verbatim.  A dict primary_email causes Pydantic ValidationError
        downstream when the risk evaluator calls model_validate() on the stored
        JSONB payload.
        """
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "cn": "Charlie",
            "mail": {"x": 1},
            "departmentNumber": None,
            "employeeType": None,
            "memberOf": [],
        })

        assert result["primary_email"] is None, (
            f"LdapAdapter.extract() with mail={{\"x\":1}} (non-str) must return "
            f"primary_email=None, got {result['primary_email']!r}. "
            "A dict in the mail field must be coerced to None."
        )


# ===========================================================================
# H — Consumer ValidationError logging redaction (LOW#1 hardening)
# ===========================================================================


class TestValidationErrorLogRedaction:
    """When _process_message raises a Pydantic ValidationError, the error log must
    record field locations — NOT the raw truncated exception string that embeds
    input_value PII.

    WHY (LOW#1): Pydantic v2's ValidationError.__str__() includes an ``input_value``
    field for every failing field.  For a field like ``id`` (UUID) receiving the
    value ``'alice@corp.com'`` (wrong type), str(ValidationError) looks like:

        "1 validation error for LoginEventRecord\\nid\\n  Input should be a valid UUID
         ... [type=uuid_parsing, input_value='alice@corp.com', input_type=str] ..."

    The email appears in the first 200 chars of str(exc), so the existing
    ``str(exc)[:200]`` truncation does NOT hide it.  Logs collected by SIEM
    systems or stored on disk would contain the PII.

    The fix: in the except block of _process_message, distinguish
    ``pydantic.ValidationError`` from other exceptions:
      - ValidationError → log error_locations=[e["loc"] for e in exc.errors()]
        and error_type="ValidationError"; do NOT include error=str(exc)[:200].
      - Other exceptions → keep the existing error=str(exc)[:200] path.

    Assert strategy: construct a stream message that triggers a ValidationError
    whose input_value contains a known PII email; confirm the logged event does
    NOT contain that email in any kwarg.  We use id='alice@corp.com' (invalid
    UUID) because that produces a short error whose input_value appears in the
    first 200 chars of str(exc) — confirmed in test construction.

    TDD: the single test below FAILS currently because the consumer logs
    ``error=str(exc)[:200]`` which DOES contain 'alice@corp.com' when the UUID
    field receives the email as input.  It will PASS after the implementer adds
    the ValidationError branch.
    """

    def _make_capturing_logger(self, logged_errors: list):
        """Return a logger wrapper that captures error() calls without forwarding."""
        import app.consumer as _consumer_mod

        class _CapturingBoundLogger:
            def __init__(self, delegate):
                self._delegate = delegate

            def error(self, event: str, **kwargs):
                logged_errors.append({"event": event, **kwargs})

            def bind(self, **kwargs):
                return _CapturingBoundLogger(self._delegate.bind(**kwargs))

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        return _CapturingBoundLogger(_consumer_mod._logger)

    def test_validation_error_log_does_not_contain_pii_email(self) -> None:
        """ValidationError log must record field locations, not input_value PII.

        Scenario: a stream message whose 'id' field contains a user email instead
        of a UUID string.  LoginEventRecord.model_validate() raises a
        ValidationError; str(ValidationError)[:200] contains 'alice@corp.com' as
        input_value.  After the fix, the logged event omits that email entirely
        (it uses location info instead).

        TDD: FAILS currently because ``error=str(exc)[:200]`` embeds
        'alice@corp.com' in the log event dict.
        """
        import json as _json
        from app.consumer import run_consumer_loop
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        import app.consumer as _consumer_mod

        pii_email = "alice@corp.com"

        # Craft a message where id='alice@corp.com' — valid JSON, but model_validate
        # raises ValidationError because 'id' expects a UUID.
        # We verified in test construction that str(exc)[:200] contains pii_email
        # for this scenario (Pydantic v2 includes input_value in the short repr).
        message_data = _json.dumps({
            "id": pii_email,          # invalid UUID — triggers ValidationError with
                                       # input_value='alice@corp.com' in str(exc)
            "user_id": "alice",
            "client_ip": "192.168.1.1",
            "protocol": "oidc",
            "timestamp": "2024-01-15T10:30:00Z",
            "source": "user",
            "is_synthetic": False,
            "is_historical": False,
            "raw_attributes": {},
        })

        one_pii_message = [
            [STREAM_LOGIN_EVENTS, [("pii-1-0", {"data": message_data})]]
        ]

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            one_pii_message,
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock()

        logged_errors: list[dict] = []
        original_consumer_logger = _consumer_mod._logger
        _consumer_mod._logger = self._make_capturing_logger(logged_errors)

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass
        finally:
            _consumer_mod._logger = original_consumer_logger

        assert len(logged_errors) >= 1, (
            "Expected at least one error log event for the ValidationError message, "
            "got none. The consumer must log the failure."
        )

        # The PII email must NOT appear in any kwarg of any logged error event.
        # After the fix, the implementer logs error_locations=[("id",)] which
        # contains no email; the current broken path logs str(exc)[:200] which
        # DOES contain 'alice@corp.com'.
        for log_event in logged_errors:
            log_repr = repr(log_event)
            assert pii_email not in log_repr, (
                f"PII email '{pii_email}' must NOT appear in the error log event for a "
                f"Pydantic ValidationError. Found in: {log_repr!r}. "
                "The fix must log field locations (e.g., [('id',)]) instead of "
                "str(exc)[:200] which embeds input_value containing the email."
            )

        # Additionally confirm that location information IS present in the log
        # (either as 'error_locations' kwarg or embedded in a safe 'error' value
        # that does not contain the email).  We assert that the logged event has
        # at least one kwarg whose string representation mentions 'id' (the
        # field that failed), confirming the implementer chose location-based logging.
        location_present = any(
            "id" in repr(v)
            for log_event in logged_errors
            for v in log_event.values()
        )
        assert location_present, (
            "The error log event for a ValidationError must include location "
            "information (e.g., the field name 'id' that caused the failure). "
            "Logged events: " + repr(logged_errors)
        )


# ===========================================================================
# I — _classify_ldap_error: TIMEOUT_EXCEEDED attribute bug
# ===========================================================================
#
# THE BUG (ldap.py ~592-604):
#   _classify_ldap_error() does:
#       import ldap as ldap_module
#       if isinstance(exc, ldap_module.TIMEOUT_EXCEEDED):   ← BUG
#
#   python-ldap has NO attribute named TIMEOUT_EXCEEDED.
#   The real attribute names are:
#     ldap.TIMEOUT          – client / network timeout
#     ldap.TIMELIMIT_EXCEEDED – server time-limit exceeded
#     ldap.SERVER_DOWN      – connection-level error
#     ldap.LDAPError        – base class for all LDAP exceptions
#
#   Accessing ldap_module.TIMEOUT_EXCEEDED raises AttributeError, which is
#   caught only by "except ImportError" — that clause does NOT match
#   AttributeError, so the error escapes the function entirely, turning every
#   real LDAP error into an unhandled AttributeError that propagates to the
#   caller instead of returning a classification string.
#   Consequence: 'ldap_timeout' and 'ldap_connection_error' branches are dead
#   code; every real LDAP exception crashes the classifier.
#
# EXPECTED FIX (implementer will apply):
#   1. Replace ldap_module.TIMEOUT_EXCEEDED with ldap.TIMEOUT (and also add
#      a separate check for ldap.TIMELIMIT_EXCEEDED → 'ldap_timeout').
#   2. Keep ldap.SERVER_DOWN → 'ldap_connection_error'.
#   3. Keep ldap.LDAPError  → 'ldap_search_error' (base-class fallback).
#   4. Broaden the except to "(ImportError, AttributeError)" so that a
#      misconfigured or stub ldap module never causes the function to raise.
#
# TEST STRATEGY:
#   Build a "correct-hierarchy" fake ldap module that mirrors the REAL python-ldap
#   hierarchy: TIMEOUT / TIMELIMIT_EXCEEDED / SERVER_DOWN all subclass LDAPError.
#   Critically, do NOT give the fake a TIMEOUT_EXCEEDED attribute — the current
#   buggy code accesses that attribute, raising AttributeError, which is the
#   regression we need to catch.
#
#   Inject the fake via monkeypatch.setitem(sys.modules, "ldap", fake), then
#   force-clear app.adapters.ldap (and app.adapters) from sys.modules so that
#   the next import picks up the new fake.  Import _classify_ldap_error from
#   the freshly-loaded module.
#
#   RED tests (fail now, pass after fix) — ALL SIX:
#     - TIMEOUT instance  → 'ldap_timeout'
#     - TIMELIMIT_EXCEEDED instance → 'ldap_timeout'
#     - SERVER_DOWN instance → 'ldap_connection_error'
#     - LDAPError instance (base) → 'ldap_search_error'
#     - ValueError (non-LDAP) → 'ldap_unexpected_error'  ← also RED now:
#       AttributeError fires on ldap_module.TIMEOUT_EXCEEDED access before
#       isinstance() is evaluated, so the fallback return is unreachable too.
#     - AttributeError regression guard (core bug): function returns a valid
#       outcome string rather than raising AttributeError


def _make_correct_hierarchy_fake_ldap() -> MagicMock:
    """Build a fake ldap module mirroring the REAL python-ldap exception hierarchy.

    Real python-ldap names:
      ldap.LDAPError          — base exception class
      ldap.TIMEOUT            — client / network timeout  (subclass of LDAPError)
      ldap.TIMELIMIT_EXCEEDED — server time-limit exceeded (subclass of LDAPError)
      ldap.SERVER_DOWN        — connection refused / unreachable (subclass of LDAPError)

    Intentionally ABSENT: ldap.TIMEOUT_EXCEEDED
      The current buggy product code accesses ldap_module.TIMEOUT_EXCEEDED, which
      raises AttributeError on this fake (and on the real library).  The absence of
      this attribute is what makes the bug-trigger tests RED.
    """
    fake = MagicMock(name="ldap_correct_hierarchy")
    fake.SCOPE_SUBTREE = 2

    class LDAPError(Exception):
        pass

    class TIMEOUT(LDAPError):
        pass

    class TIMELIMIT_EXCEEDED(LDAPError):
        pass

    class SERVER_DOWN(LDAPError):
        pass

    fake.LDAPError = LDAPError
    fake.TIMEOUT = TIMEOUT
    fake.TIMELIMIT_EXCEEDED = TIMELIMIT_EXCEEDED
    fake.SERVER_DOWN = SERVER_DOWN

    # Deliberately NO fake.TIMEOUT_EXCEEDED — the bug accesses this attribute,
    # which must raise AttributeError to mirror real python-ldap.
    # MagicMock auto-creates attributes on first access; calling del on an
    # attribute that has never been accessed causes AttributeError on any
    # subsequent access (verified: del on fresh MagicMock "blocks" the attribute).
    del fake.TIMEOUT_EXCEEDED

    fake_filter = MagicMock(name="ldap.filter")
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake.filter = fake_filter

    fake_dn = MagicMock(name="ldap.dn")
    fake.dn = fake_dn

    return fake


def _inject_correct_hierarchy_ldap(monkeypatch) -> MagicMock:
    """Inject the correct-hierarchy fake ldap and reload app.adapters.ldap.

    Follows the established pattern from _inject_fake_ldap (test_chunk4_ldap_cache.py):
      1. Register fake module under the 'ldap' key in sys.modules.
      2. Register sub-module stubs (ldap.filter, ldap.dn).
      3. Remove app.adapters.ldap and app.adapters from sys.modules so the next
         import statement picks up the freshly injected fake rather than a cached
         module that already has a reference to the real ldap (or an earlier fake).

    WHY steps 1-3 are all required: Python's import machinery caches modules in
    sys.modules.  If we only inject the fake but leave app.adapters.ldap cached,
    the cached module holds a closure over the old ldap reference and the fake is
    never used.
    """
    fake = _make_correct_hierarchy_fake_ldap()
    monkeypatch.setitem(sys.modules, "ldap", fake)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake.dn)
    for key in list(sys.modules.keys()):
        if key in ("app.adapters.ldap", "app.adapters"):
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake


class TestClassifyLdapError:
    """_classify_ldap_error must map real LDAP exception types to outcome strings.

    WHY these tests exist:
      The bug is that _classify_ldap_error references ldap.TIMEOUT_EXCEEDED, an
      attribute that does not exist on the real python-ldap library.  The resulting
      AttributeError is NOT caught by the existing "except ImportError" handler, so
      the function raises instead of returning a classification string.  This renders
      the 'ldap_timeout' and 'ldap_connection_error' outcomes unreachable dead code —
      every real LDAP error gets misclassified (or crashes the caller).

      The correct fix changes the isinstance check to use ldap.TIMEOUT (and adds a
      parallel check for ldap.TIMELIMIT_EXCEEDED), both → 'ldap_timeout', and
      broadens the except to "(ImportError, AttributeError)" as a defensive guard.

    All tests tagged RED (fail now) use the correct-hierarchy fake that lacks
    TIMEOUT_EXCEEDED.  The single GREEN test (non-LDAP ValueError) does not
    involve the broken isinstance chain at all — it falls through to the final
    'ldap_unexpected_error' return and already passes.

    Classification contract after fix:
      ldap.TIMEOUT(...)            → 'ldap_timeout'
      ldap.TIMELIMIT_EXCEEDED(...) → 'ldap_timeout'
      ldap.SERVER_DOWN(...)        → 'ldap_connection_error'
      ldap.LDAPError(...)          → 'ldap_search_error'   (base-class fallback)
      ValueError(...)              → 'ldap_unexpected_error' (non-LDAP)
    """

    def test_timeout_exception_classifies_as_ldap_timeout(
        self, monkeypatch
    ) -> None:
        """ldap.TIMEOUT instance must classify as 'ldap_timeout'.

        RED now: _classify_ldap_error accesses ldap_module.TIMEOUT_EXCEEDED (absent
        on this fake), raising AttributeError that escapes the function instead of
        returning 'ldap_timeout'.

        GREEN after fix: product code uses ldap.TIMEOUT for this isinstance check.
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = fake.TIMEOUT("client network timeout")

        result = _classify_ldap_error(exc)

        assert result == "ldap_timeout", (
            f"ldap.TIMEOUT instance must classify as 'ldap_timeout', got {result!r}. "
            "The bug: product code checks ldap_module.TIMEOUT_EXCEEDED (does not exist "
            "on python-ldap) → raises AttributeError instead of returning 'ldap_timeout'."
        )

    def test_timelimit_exceeded_exception_classifies_as_ldap_timeout(
        self, monkeypatch
    ) -> None:
        """ldap.TIMELIMIT_EXCEEDED instance must classify as 'ldap_timeout'.

        RED now: same root cause — _classify_ldap_error raises AttributeError when
        accessing ldap_module.TIMEOUT_EXCEEDED before it even reaches the
        TIMELIMIT_EXCEEDED check (which is new code the implementer must add).

        GREEN after fix: product code adds an isinstance check for
        ldap.TIMELIMIT_EXCEEDED → 'ldap_timeout' alongside the ldap.TIMEOUT check.
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = fake.TIMELIMIT_EXCEEDED("server time-limit exceeded")

        result = _classify_ldap_error(exc)

        assert result == "ldap_timeout", (
            f"ldap.TIMELIMIT_EXCEEDED instance must classify as 'ldap_timeout', "
            f"got {result!r}. "
            "ldap.TIMELIMIT_EXCEEDED is the server-side time-limit error; it must "
            "map to 'ldap_timeout' alongside ldap.TIMEOUT (client-side timeout)."
        )

    def test_server_down_exception_classifies_as_ldap_connection_error(
        self, monkeypatch
    ) -> None:
        """ldap.SERVER_DOWN instance must classify as 'ldap_connection_error'.

        RED now: the AttributeError from ldap_module.TIMEOUT_EXCEEDED escapes before
        the isinstance(exc, ldap_module.SERVER_DOWN) check is reached, so
        'ldap_connection_error' is currently unreachable dead code.

        GREEN after fix: with TIMEOUT_EXCEEDED reference removed, the SERVER_DOWN
        branch executes normally and returns 'ldap_connection_error'.
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = fake.SERVER_DOWN("connection refused")

        result = _classify_ldap_error(exc)

        assert result == "ldap_connection_error", (
            f"ldap.SERVER_DOWN instance must classify as 'ldap_connection_error', "
            f"got {result!r}. "
            "The 'ldap_connection_error' branch is currently dead code because the "
            "ldap_module.TIMEOUT_EXCEEDED AttributeError escapes before reaching it."
        )

    def test_ldap_base_error_classifies_as_ldap_search_error(
        self, monkeypatch
    ) -> None:
        """ldap.LDAPError base instance must classify as 'ldap_search_error'.

        RED now: same root cause — AttributeError escapes before the
        isinstance(exc, ldap_module.LDAPError) check, so 'ldap_search_error' is
        also unreachable dead code for any real LDAP exception.

        GREEN after fix: LDAPError is the catch-all for LDAP exceptions that are
        not a timeout or connection error (e.g., NO_SUCH_OBJECT, OPERATIONS_ERROR,
        PROTOCOL_ERROR, etc.).
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = fake.LDAPError("generic ldap error")

        result = _classify_ldap_error(exc)

        assert result == "ldap_search_error", (
            f"ldap.LDAPError base instance must classify as 'ldap_search_error', "
            f"got {result!r}. "
            "The base-class branch is dead code until the TIMEOUT_EXCEEDED bug is fixed."
        )

    def test_non_ldap_exception_classifies_as_ldap_unexpected_error(
        self, monkeypatch
    ) -> None:
        """ValueError (non-LDAP) must classify as 'ldap_unexpected_error'.

        RED now: even for a non-LDAP exception, the bug fires — because accessing
        ldap_module.TIMEOUT_EXCEEDED raises AttributeError unconditionally as the
        first thing in the try block, before isinstance() is evaluated.  So the
        'ldap_unexpected_error' fallback return is unreachable when ldap is importable
        but lacks TIMEOUT_EXCEEDED.

        GREEN after fix: with the broadened except (ImportError, AttributeError), the
        AttributeError from the missing attribute is caught, the loop falls through,
        and the function reaches the final 'ldap_unexpected_error' return.

        This test is a regression guard: it must stay green after the fix to confirm
        the non-LDAP fallback path is preserved.
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = ValueError("not an ldap error at all")

        result = _classify_ldap_error(exc)

        assert result == "ldap_unexpected_error", (
            f"A non-LDAP exception (ValueError) must classify as 'ldap_unexpected_error', "
            f"got {result!r}. "
            "The fallback return must remain intact after the fix."
        )

    def test_classify_does_not_raise_attribute_error_on_real_ldap_exception(
        self, monkeypatch
    ) -> None:
        """Core regression guard: _classify_ldap_error must never raise AttributeError.

        This is the direct test for the bug: the fake ldap module deliberately lacks
        TIMEOUT_EXCEEDED (mirroring the real python-ldap library).  The current buggy
        code accesses ldap_module.TIMEOUT_EXCEEDED, which raises AttributeError that
        escapes the function.  After the fix, no AttributeError escapes.

        We use a SERVER_DOWN instance as the test exception because:
          - It is a genuine LDAP exception (subclass of LDAPError).
          - The buggy isinstance(exc, ldap_module.TIMEOUT_EXCEEDED) fires before the
            SERVER_DOWN check is reached, so the bug triggers immediately.
          - After the fix, SERVER_DOWN must return 'ldap_connection_error' (checked
            separately above), but here we only assert: no exception raised.

        RED now: AttributeError escapes from _classify_ldap_error.
        GREEN after fix: function returns a valid outcome string.
        """
        fake = _inject_correct_hierarchy_ldap(monkeypatch)
        from app.adapters.ldap import _classify_ldap_error

        exc = fake.SERVER_DOWN("connection refused")

        try:
            result = _classify_ldap_error(exc)
        except AttributeError as ae:
            pytest.fail(
                f"_classify_ldap_error raised AttributeError instead of returning an "
                f"outcome string. This confirms the TIMEOUT_EXCEEDED bug: the function "
                f"accesses ldap_module.TIMEOUT_EXCEEDED which does not exist on the real "
                f"python-ldap library. AttributeError: {ae!r}"
            )

        assert isinstance(result, str), (
            f"_classify_ldap_error must return a str outcome, got {type(result)!r}"
        )
        assert result in (
            "ldap_timeout",
            "ldap_connection_error",
            "ldap_search_error",
            "ldap_unexpected_error",
        ), (
            f"_classify_ldap_error must return one of the four outcome codes, "
            f"got {result!r}"
        )
