"""Consumer and connection resilience hardening for identity-normalization.

Verifies that run_consumer_loop survives transient xreadgroup errors, that
weight_for returns a conservative floor for unknown sources, that broken
pooled LDAP connections call unbind_s() before being freed, that RFC-4514
escaped-comma DNs are reduced correctly, and that _classify_ldap_error maps
real python-ldap exception types to outcome strings without raising.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.services.identity_normalization.conftest import (
    FakeRedis as _FakeRedis,
    inject_fake_ldap as _inject_fake_ldap,
)


# ---------------------------------------------------------------------------
# Note: inject_fake_ldap/_FakeRedis come from the per-service conftest.
# _make_correct_hierarchy_fake_ldap below is intentionally LOCAL — it builds
# the correct-hierarchy fake used to expose the TIMEOUT_EXCEEDED name bug and
# must NOT use the canonical make_fake_ldap_module (which exports TIMEOUT_EXCEEDED).
# ---------------------------------------------------------------------------


def _make_correct_hierarchy_fake_ldap() -> MagicMock:
    """Build a fake ldap module mirroring the REAL python-ldap exception hierarchy.

    Real python-ldap names:
      ldap.LDAPError          — base exception class
      ldap.TIMEOUT            — client / network timeout  (subclass of LDAPError)
      ldap.TIMELIMIT_EXCEEDED — server time-limit exceeded (subclass of LDAPError)
      ldap.SERVER_DOWN        — connection refused / unreachable (subclass of LDAPError)

    Intentionally ABSENT: ldap.TIMEOUT_EXCEEDED
      The current buggy product code accesses ldap_module.TIMEOUT_EXCEEDED, which
      raises AttributeError on this fake (and on the real library). The absence of
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

    # Deliberately NO fake.TIMEOUT_EXCEEDED — the bug accesses this attribute.
    del fake.TIMEOUT_EXCEEDED

    fake_filter = MagicMock(name="ldap.filter")
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake.filter = fake_filter

    fake_dn = MagicMock(name="ldap.dn")
    fake.dn = fake_dn

    return fake


def _inject_correct_hierarchy_ldap(monkeypatch) -> MagicMock:
    """Inject the correct-hierarchy fake ldap and reload app.adapters.ldap."""
    fake = _make_correct_hierarchy_fake_ldap()
    monkeypatch.setitem(sys.modules, "ldap", fake)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake.dn)
    for key in list(sys.modules.keys()):
        if key in ("app.adapters.ldap", "app.adapters"):
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake


# ===========================================================================
# B — Outer xreadgroup resilience
# ===========================================================================


class TestConsumerLoopXreadgroupResilience:
    """run_consumer_loop must survive transient xreadgroup errors and continue.

    WHY: Redis is a network service. A momentary blip raises an exception from
    xreadgroup. If that exception escapes the loop body unhandled, the entire
    consumer process dies. The fix: wrap the outer xreadgroup call in a
    try/except, log, sleep briefly, and continue to the next iteration.

    CancelledError MUST still propagate — it signals intentional shutdown.
    """

    async def test_transient_xreadgroup_error_does_not_kill_loop(self) -> None:
        """A generic Exception from xreadgroup must be caught; loop continues.

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
        redis.xreadgroup = AsyncMock(
            side_effect=[
                RuntimeError("transient redis error"),
                one_message,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        try:
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )
        except asyncio.CancelledError:
            pass

        assert normalize_call_count[0] == 1, (
            f"After a transient xreadgroup error, the loop must continue and process "
            f"the next valid message. Expected normalize() called 1 time, "
            f"got {normalize_call_count[0]}. "
            "The loop must NOT die on a transient Redis error."
        )

    async def test_cancelled_error_propagates_through_loop(self) -> None:
        """asyncio.CancelledError from xreadgroup must propagate (clean shutdown).

        WHY: CancelledError is the mechanism by which the lifespan cancels the
        background consumer task on shutdown. If swallowed, the task runs forever.
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
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )
        except asyncio.CancelledError:
            cancelled_propagated = True

        assert cancelled_propagated, (
            "asyncio.CancelledError must propagate out of run_consumer_loop — "
            "it signals intentional shutdown and must NOT be swallowed by the "
            "transient-error handler."
        )

    async def test_loop_sleeps_after_transient_error(self) -> None:
        """After a transient xreadgroup error the loop must sleep before retrying.

        WHY: Without a sleep, a persistent error would spin the event loop at 100%
        CPU. A brief sleep provides back-off. We verify asyncio.sleep is called
        with a positive value after the error.
        """
        from app.consumer import run_consumer_loop

        sleep_calls: list[float] = []
        real_sleep = asyncio.sleep

        async def _capturing_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            await real_sleep(0)

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                RuntimeError("redis down"),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with patch("asyncio.sleep", side_effect=_capturing_sleep):
            try:
                await run_consumer_loop(
                    service=service,
                    repository=repository,
                    publisher=publisher,
                    redis=redis,
                )
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

    WHY: When a new protocol is introduced, ``defaults.source_weights[source]``
    raises KeyError because the source is not in the YAML defaults block. This
    crash propagates to the resolution layer, dropping the entire normalization
    result and causing the risk evaluator to treat the event as maximum risk.

    The fix: return a documented conservative floor value when the source is
    absent from both the attribute-specific weights and the defaults block.
    """

    def _make_minimal_config(self):
        """Build a NormalizationConfig with known default weights."""
        from app.normalization_config import (
            NormalizationConfig,
            Defaults,
            AttributeConfig,
            EnrichmentConfig,
            EnrichmentSources,
            LdapEnrichmentConfig,
        )

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
        """weight_for(attribute, 'unknown_proto') must not raise KeyError."""
        cfg = self._make_minimal_config()

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
        """weight_for with unknown source returns a floor value in [0.0, min_default]."""
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

        assert isinstance(result, float), f"Expected float return, got {type(result)!r}"

    def test_weight_for_known_source_not_in_defaults_falls_back_correctly(
        self,
    ) -> None:
        """Known source in attribute weights but not in defaults still resolves.

        This is the existing happy-path — verify it still works after the fix.
        """
        cfg = self._make_minimal_config()

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

    WHY: A broken connection discarded without calling unbind_s() leaks the
    server-side session. Under heavy load, this can exhaust the LDAP server's
    connection limit. Calling unbind_s() signals to the server that the session
    is done; a best-effort call (swallowing errors from unbind_s itself) is sufficient.
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

    async def test_unbind_s_called_on_search_failure(self, monkeypatch) -> None:
        """When a pooled connection's search raises, unbind_s() must be called on it."""
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
        await adapter.enrich("primary_email", "alice@corp.com")

        assert broken_conn.unbind_s.called, (
            "unbind_s() must be called on a broken pooled connection before the slot "
            "is freed. This prevents server-side session leaks. "
            f"unbind_s call count: {broken_conn.unbind_s.call_count}"
        )

    async def test_unbind_s_raising_does_not_prevent_slot_free(
        self, monkeypatch
    ) -> None:
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

        adapter = LdapAdapter()

        # First call — broken connection, unbind raises
        await adapter.enrich("primary_email", "alice@corp.com")

        # Second call — must complete (pool has its slot back)
        new_conn = MagicMock()
        new_conn.simple_bind_s = MagicMock(return_value=None)
        new_conn.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=new_conn)

        try:
            await asyncio.wait_for(
                adapter.enrich("primary_email", "bob@corp.com"), timeout=2.0
            )
        except asyncio.TimeoutError:
            pytest.fail(
                "Second enrich() call timed out — the pool slot was not freed after "
                "a failed unbind_s(). put_nowait(None) must be called even when "
                "unbind_s itself raises."
            )

    async def test_unbind_s_called_in_thread(self, monkeypatch) -> None:
        """unbind_s() must be called via asyncio.to_thread (or equivalent thread-safe call).

        WHY: python-ldap is a blocking C extension. Calling unbind_s() on the event
        loop directly would block all concurrent tasks during the unbind. The fix
        must call unbind_s in a thread (via asyncio.to_thread or run_in_executor).
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        broken_conn = self._make_recording_conn(search_exc=Exception("search failed"))
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
            await adapter.enrich("primary_email", "alice@corp.com")

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

    WHY: The current regex-based implementation captures the cn value up to the first
    comma. For a DN like ``cn=Smith\\, John,ou=groups,dc=example,dc=com``, the escaped
    comma (\\,) is part of the cn value, but the regex captures only "Smith\\" instead
    of "Smith, John". The fix: replace the regex with ldap.dn.str2dn, which correctly
    parses RFC-4514 escaped characters.
    """

    def _inject_ldap_with_str2dn(self, monkeypatch) -> MagicMock:
        """Inject fake ldap with a realistic str2dn that handles escaped commas."""
        fake_ldap = _inject_fake_ldap(monkeypatch)

        def _fake_str2dn(dn_str: str):
            """Minimal RFC-4514 str2dn that handles simple and escaped-comma DNs.

            Returns list of RDN lists: [[(attr, value, flags), ...], ...]
            """
            rdns = []
            current = []
            i = 0
            while i < len(dn_str):
                ch = dn_str[i]
                if ch == "\\" and i + 1 < len(dn_str):
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
        """A standard DN like 'cn=engineering,ou=groups,dc=example,dc=com' → 'engineering'."""
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name("cn=engineering,ou=groups,dc=example,dc=com")

        assert result == "engineering", (
            f"Normal DN must reduce to its cn RDN value 'engineering', got {result!r}"
        )

    def test_escaped_comma_dn_preserves_comma_in_group_name(self, monkeypatch) -> None:
        """A DN with escaped comma: 'cn=Smith\\, John,...' → group name 'Smith, John'.

        With the regex approach this fails (returns 'Smith\\'). With str2dn the
        escaped comma is unescaped and preserved in output.
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
        """A bare group name (no '=' in it) is returned as-is."""
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name("engineering")

        assert result == "engineering", (
            f"Bare group name 'engineering' must pass through unchanged, got {result!r}"
        )

    def test_malformed_dn_falls_back_gracefully(self, monkeypatch) -> None:
        """A DN that str2dn raises on must fall back without exception."""
        fake_ldap = _inject_fake_ldap(monkeypatch)

        fake_ldap.dn.str2dn = MagicMock(side_effect=Exception("malformed DN"))

        from app.adapters.ldap import _reduce_dn_to_group_name

        try:
            result = _reduce_dn_to_group_name("not=a=valid=dn=structure=here")
        except Exception as exc:
            pytest.fail(
                f"_reduce_dn_to_group_name must not propagate str2dn exceptions. "
                f"Got: {type(exc).__name__}: {exc}"
            )

        assert result is None or isinstance(result, str), (
            f"Fall-back result must be None or str, got {type(result)!r}"
        )

    def test_empty_dn_returns_none(self, monkeypatch) -> None:
        """An empty string DN returns None (not a group name)."""
        self._inject_ldap_with_str2dn(monkeypatch)
        from app.adapters.ldap import _reduce_dn_to_group_name

        result = _reduce_dn_to_group_name("")

        assert result is None, f"Empty DN must return None, got {result!r}"


# ===========================================================================
# I — _classify_ldap_error: TIMEOUT_EXCEEDED attribute bug
# ===========================================================================


class TestClassifyLdapError:
    """_classify_ldap_error must map real LDAP exception types to outcome strings.

    WHY: The bug is that _classify_ldap_error references ldap.TIMEOUT_EXCEEDED, an
    attribute that does not exist on the real python-ldap library. The resulting
    AttributeError is NOT caught by the existing "except ImportError" handler, so
    the function raises instead of returning a classification string.

    Classification contract after fix:
      ldap.TIMEOUT(...)            → 'ldap_timeout'
      ldap.TIMELIMIT_EXCEEDED(...) → 'ldap_timeout'
      ldap.SERVER_DOWN(...)        → 'ldap_connection_error'
      ldap.LDAPError(...)          → 'ldap_search_error'   (base-class fallback)
      ValueError(...)              → 'ldap_unexpected_error' (non-LDAP)
    """

    def test_timeout_exception_classifies_as_ldap_timeout(self, monkeypatch) -> None:
        """ldap.TIMEOUT instance must classify as 'ldap_timeout'."""
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
        """ldap.TIMELIMIT_EXCEEDED instance must classify as 'ldap_timeout'."""
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
        """ldap.SERVER_DOWN instance must classify as 'ldap_connection_error'."""
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

    def test_ldap_base_error_classifies_as_ldap_search_error(self, monkeypatch) -> None:
        """ldap.LDAPError base instance must classify as 'ldap_search_error'."""
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
        """ValueError (non-LDAP) must classify as 'ldap_unexpected_error'."""
        _inject_correct_hierarchy_ldap(monkeypatch)
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

        The fake ldap module deliberately lacks TIMEOUT_EXCEEDED (mirroring the real
        python-ldap library). The current buggy code accesses ldap_module.TIMEOUT_EXCEEDED,
        which raises AttributeError that escapes the function.
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
