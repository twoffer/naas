"""PII/log redaction hardening for identity-normalization consumer and LDAP adapter.

Verifies that corrupted-cache warnings, malformed-message error logs, and
Pydantic ValidationError error logs do not echo raw PII (email addresses,
field input values) into the application log stream.
"""

from __future__ import annotations

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_fake_ldap_module() -> MagicMock:
    """Build a minimal fake ldap module with real exception classes."""
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2

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


# ===========================================================================
# D — Corrupted-cache PII redaction
# ===========================================================================


class TestCorruptedCacheLogRedaction:
    """The warning log for a corrupted cache entry must not echo the full cached string.

    WHY (§5.3 / general PII hygiene): The positive cache entry contains a JSON dict
    with the user's email address and other directory attributes (PII). If the cached
    string is corrupted, the current code logs ``cached_value=repr(cached_str)`` which
    echoes the full raw content — potentially including the user's email — to the
    application log stream. Logs are often collected by SIEM systems or retained on
    disk in plaintext, making this a PII exfiltration risk.

    The fix: replace ``cached_value=repr(cached_str)`` with a redacted form that
    conveys enough for debugging (e.g., length, first N chars, or a hash) without
    exposing PII.
    """

    async def test_corrupted_cache_warning_does_not_echo_pii_email(
        self, monkeypatch
    ) -> None:
        """Corrupted cache warning must not include the user's email in logged content."""
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

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

        logged_warning_kwargs: list[dict] = []

        import app.adapters.ldap as _ldap_mod

        class _CapturingLogger:
            def __init__(self, delegate):
                self._delegate = delegate

            def warning(self, event: str, **kwargs):
                logged_warning_kwargs.append({"event": event, **kwargs})
                return self._delegate.warning(event, **kwargs)

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        original_logger = _ldap_mod._logger
        capturing = _CapturingLogger(original_logger)
        monkeypatch.setattr(_ldap_mod, "_logger", capturing)

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        await adapter.enrich("primary_email", pii_token)

        assert len(logged_warning_kwargs) >= 1, (
            "Expected at least one logger.warning call on corrupted cache entry, got none. "
            "Ensure the corrupted-cache path logs a warning."
        )

        for log_event in logged_warning_kwargs:
            log_repr = repr(log_event)
            assert pii_token not in log_repr, (
                f"PII token '{pii_token}' must NOT appear in warning log event. "
                f"Found in: {log_repr!r}. "
                "The cached_value kwarg must be redacted (e.g., show length/hash, not raw content)."
            )


# ===========================================================================
# F — Malformed message PII redaction in consumer.py (non-ValidationError path)
# ===========================================================================


class TestMalformedMessageLogRedaction:
    """The error log for a malformed stream message must truncate/bound the error string.

    WHY: When a login event message causes a non-ValidationError exception in
    service.normalize(), the consumer logs ``error=str(exc)``. If the exception
    message contains PII (plausible for a large error payload), the full content
    could appear in logs. The fix: truncate to a bounded length (e.g., 200 chars).

    This class covers the non-ValidationError (truncation) path.
    The ValidationError PII redaction path is in TestValidationErrorLogRedaction.
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

            def bind(self, **kwargs):
                return _CapturingBoundLogger(self._delegate.bind(**kwargs))

            def __getattr__(self, name):
                return getattr(self._delegate, name)

        return _CapturingBoundLogger(_consumer_mod._logger)

    async def test_malformed_message_error_log_truncates_long_error(self) -> None:
        """Non-ValidationError exception: consumer error log must truncate to <= 300 chars.

        service.normalize raises a RuntimeError whose message is 500+ chars. After
        the implementer adds the two-path handler, non-ValidationError exceptions
        must still be truncated (str(exc)[:200]); only ValidationError gets the
        location-based treatment (see TestValidationErrorLogRedaction).
        """
        from app.consumer import run_consumer_loop
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        import app.consumer as _consumer_mod

        valid_data = self._make_valid_message_data()
        one_good_message_bad_normalize = [
            [STREAM_LOGIN_EVENTS, [("msg-1-0", {"data": valid_data})]]
        ]

        long_error_payload = "RUNTIME-ERR-PAYLOAD-" + ("X" * 500)
        service = AsyncMock()
        service.normalize = AsyncMock(side_effect=RuntimeError(long_error_payload))
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                one_good_message_bad_normalize,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        logged_errors: list[dict] = []
        original_consumer_logger = _consumer_mod._logger
        _consumer_mod._logger = self._make_capturing_logger(logged_errors)

        try:
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )
        except asyncio.CancelledError:
            pass
        finally:
            _consumer_mod._logger = original_consumer_logger

        assert len(logged_errors) >= 1, (
            "Expected at least one error log event when normalize() raises RuntimeError."
        )

        for log_event in logged_errors:
            error_val = log_event.get("error", "")
            assert len(error_val) <= 300, (
                f"The 'error' field in consumer error log must be truncated to <= 300 chars "
                f"for non-ValidationError exceptions. "
                f"Got {len(error_val)} chars: {error_val[:100]!r}..."
            )


# ===========================================================================
# H — Consumer ValidationError logging redaction (PII in Pydantic errors)
# ===========================================================================


class TestValidationErrorLogRedaction:
    """When _process_message raises a Pydantic ValidationError, the error log must
    record field locations — NOT the raw truncated exception string that embeds
    input_value PII.

    WHY (LOW#1): Pydantic v2's ValidationError.__str__() includes an ``input_value``
    field for every failing field. For a field like ``id`` (UUID) receiving the
    value ``'alice@corp.com'`` (wrong type), str(ValidationError) contains the
    email in the first 200 chars. The fix: log error_locations=[e["loc"] for e
    in exc.errors()] and error_type="ValidationError" instead of str(exc)[:200].
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

    async def test_validation_error_log_does_not_contain_pii_email(self) -> None:
        """ValidationError log must record field locations, not input_value PII.

        Scenario: a stream message whose 'id' field contains a user email instead
        of a UUID string. LoginEventRecord.model_validate() raises a ValidationError;
        str(ValidationError)[:200] contains 'alice@corp.com' as input_value. After
        the fix, the logged event omits that email entirely (uses location info instead).
        """
        from app.consumer import run_consumer_loop
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        import app.consumer as _consumer_mod

        pii_email = "alice@corp.com"

        message_data = json.dumps(
            {
                "id": pii_email,  # invalid UUID — triggers ValidationError with
                # input_value='alice@corp.com' in str(exc)
                "user_id": "alice",
                "client_ip": "192.168.1.1",
                "protocol": "oidc",
                "timestamp": "2024-01-15T10:30:00Z",
                "source": "user",
                "is_synthetic": False,
                "is_historical": False,
                "raw_attributes": {},
            }
        )

        one_pii_message = [[STREAM_LOGIN_EVENTS, [("pii-1-0", {"data": message_data})]]]

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                one_pii_message,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        logged_errors: list[dict] = []
        original_consumer_logger = _consumer_mod._logger
        _consumer_mod._logger = self._make_capturing_logger(logged_errors)

        try:
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )
        except asyncio.CancelledError:
            pass
        finally:
            _consumer_mod._logger = original_consumer_logger

        assert len(logged_errors) >= 1, (
            "Expected at least one error log event for the ValidationError message, "
            "got none. The consumer must log the failure."
        )

        for log_event in logged_errors:
            log_repr = repr(log_event)
            assert pii_email not in log_repr, (
                f"PII email '{pii_email}' must NOT appear in the error log event for a "
                f"Pydantic ValidationError. Found in: {log_repr!r}. "
                "The fix must log field locations (e.g., [('id',)]) instead of "
                "str(exc)[:200] which embeds input_value containing the email."
            )

        location_present = any(
            "id" in repr(v) for log_event in logged_errors for v in log_event.values()
        )
        assert location_present, (
            "The error log event for a ValidationError must include location "
            "information (e.g., the field name 'id' that caused the failure). "
            "Logged events: " + repr(logged_errors)
        )
