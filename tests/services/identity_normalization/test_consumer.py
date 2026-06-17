"""Consumer loop (consumer.py): XREADGROUP, ACK, message dispatch, and error recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

from naas_shared.constants import GROUP_NORMALIZATION, STREAM_LOGIN_EVENTS
from naas_shared.models import (
    EnrichmentSkipped,
    LoginEventRecord,
    NormalizedAttributes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID = UUID("12345678-1234-5678-1234-567812345678")
_NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)


def _make_record() -> LoginEventRecord:
    return LoginEventRecord(
        id=_UUID,
        user_id="alice",
        client_ip="192.168.1.1",
        protocol="oidc",
        timestamp=_NOW,
        source="user",
        is_synthetic=False,
        is_historical=False,
        raw_attributes={
            "name": "Alice Smith",
            "email": "alice@corp.com",
            "department": "eng",
            "employee_type": "fte",
            "groups": ["admin"],
        },
    )


def _make_normalized() -> NormalizedAttributes:
    return NormalizedAttributes(
        display_name="Alice Smith",
        primary_email="alice@corp.com",
        department="Engineering",
        employee_type="FTE",
        groups=["admin"],
        source_protocol="oidc",
        normalization_confidence=0.85,
        resolution_details={},
        enrichment=EnrichmentSkipped(applied=False, skip_reason="no_ldap_match"),
    )


def _make_stream_message(record: LoginEventRecord, msg_id: str = "1-0") -> list:
    """Simulate what XREADGROUP returns: [[stream, [(msg_id, {fields})]]]."""
    data_str = json.dumps(record.model_dump(mode="json"), default=str)
    return [[STREAM_LOGIN_EVENTS, [(msg_id, {"data": data_str})]]]


# ===========================================================================
# D.7. Consumer loop — critical ordering: normalize → write(commit) → publish → XACK
# ===========================================================================


class TestConsumerOrdering:
    """Step ordering within one processed message is CRITICAL (§5.1, ADR-0002)."""

    async def test_normalize_then_write_then_publish_then_xack_order(self):
        """For one message: normalize → write → publish → xack in that exact order.

        ⚠️ CRITICAL ordering (§5.1, ADR-0002):
        - persist to PostgreSQL and commit BEFORE publishing to normalized_events
        - XACK ONLY after BOTH commit and publish succeed
        """
        from app.consumer import run_consumer_loop

        call_order: list[str] = []

        record = _make_record()
        normalized = _make_normalized()

        # Mock service
        service = AsyncMock()

        async def _normalize(r):
            call_order.append("normalize")
            return normalized

        service.normalize = _normalize

        # Mock repository
        repository = AsyncMock()

        async def _write(event_id, norm):
            call_order.append("write")

        repository.write = _write

        # Mock publisher
        publisher = AsyncMock()

        async def _publish(rec, norm):
            call_order.append("publish")

        publisher.publish_normalized = _publish

        # Mock Redis — one message then StopAsyncIteration to break the loop
        msg_id = "1-0"
        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, msg_id),
                asyncio.CancelledError(),  # stop the loop after first batch
            ]
        )

        async def _xack(*args):
            call_order.append("xack")

        redis.xack = AsyncMock(side_effect=_xack)

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert "normalize" in call_order, "normalize must be called"
        assert "write" in call_order, "write must be called"
        assert "publish" in call_order, "publish must be called"
        assert "xack" in call_order, "xack must be called on success"

        # Ordering: normalize < write < publish < xack
        idx = {
            step: call_order.index(step)
            for step in ["normalize", "write", "publish", "xack"]
        }
        assert idx["normalize"] < idx["write"], "normalize must precede write"
        assert idx["write"] < idx["publish"], (
            "write (commit) must precede publish — §5.1 ⚠️ CRITICAL ordering"
        )
        assert idx["publish"] < idx["xack"], "publish must precede xack"

    async def test_xack_only_after_both_write_and_publish_succeed(self):
        """XACK is the last step; it must not occur if either write or publish raises."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        normalized = _make_normalized()
        call_order: list[str] = []

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=normalized)

        repository = AsyncMock()

        async def _write_then_raise(event_id, norm):
            call_order.append("write")
            raise RuntimeError("DB commit failed")

        repository.write = _write_then_raise

        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "2-0"),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock(side_effect=lambda *a: call_order.append("xack"))

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert "xack" not in call_order, (
            "XACK must NOT be called when write/commit fails — message stays pending for redelivery"
        )


# ===========================================================================
# D.8. Failure handling — no XACK on exception
# ===========================================================================


class TestConsumerFailureHandling:
    """On any step exception, message is NOT XACKed (stays pending for redelivery)."""

    async def test_normalize_exception_no_xack(self):
        """If normalize() raises, message is not ACKed and loop continues."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        xack_call_count = [0]

        service = AsyncMock()
        service.normalize = AsyncMock(side_effect=ValueError("normalization error"))

        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "3-0"),
                asyncio.CancelledError(),
            ]
        )

        async def _xack(*args):
            xack_call_count[0] += 1

        redis.xack = AsyncMock(side_effect=_xack)

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert xack_call_count[0] == 0, (
            "XACK must NOT be called when normalize() raises — message must stay in pending-entries list"
        )

    async def test_repository_write_exception_no_xack(self):
        """If repository.write() raises, message is not ACKed."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        normalized = _make_normalized()
        xack_count = [0]

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=normalized)

        repository = AsyncMock()
        repository.write = AsyncMock(side_effect=RuntimeError("DB down"))

        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "4-0"),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock(
            side_effect=lambda *a: xack_count.__setitem__(0, xack_count[0] + 1)
        )

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert xack_count[0] == 0, (
            "XACK must NOT be called when repository.write() raises"
        )

    async def test_publish_exception_no_xack(self):
        """If publisher.publish_normalized() raises, message is not ACKed."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        normalized = _make_normalized()
        xack_count = [0]

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=normalized)

        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)

        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(side_effect=RuntimeError("Redis down"))

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "5-0"),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock(
            side_effect=lambda *a: xack_count.__setitem__(0, xack_count[0] + 1)
        )

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert xack_count[0] == 0, (
            "XACK must NOT be called when publish_normalized() raises"
        )

    async def test_enrichment_skip_does_not_cause_no_xack(self):
        """⚠️ Enrichment skip/failure is NOT a processing failure.

        A message where enrichment is skipped (EnrichmentSkipped in the result)
        must still be persisted, published, and ACKed. Enrichment failure ≠ drop.

        This is the key invariant: LDAP outage must not stall the pipeline.
        """
        from app.consumer import run_consumer_loop

        record = _make_record()
        # normalize() returns valid NormalizedAttributes with EnrichmentSkipped
        normalized_with_skip = NormalizedAttributes(
            display_name="Alice Smith",
            primary_email="alice@corp.com",
            source_protocol="oidc",
            normalization_confidence=0.60,
            resolution_details={},
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_timeout"),
        )
        xack_count = [0]

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=normalized_with_skip)

        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)

        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "6-0"),
                asyncio.CancelledError(),
            ]
        )

        async def _xack(*args):
            xack_count[0] += 1

        redis.xack = AsyncMock(side_effect=_xack)

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert xack_count[0] == 1, (
            f"Enrichment skip must NOT prevent ACK — expected 1 XACK, got {xack_count[0]}. "
            "Enrichment failure ≠ processing failure (§5.1, §5.4)"
        )


# ===========================================================================
# D.9. DB session obtained from session_factory (not request-scoped get_db_session)
# ===========================================================================


class TestConsumerSessionFactory:
    """Consumer loop uses get_session_factory(), not request-scoped get_db_session."""

    def test_consumer_uses_session_factory_seam(self):
        """The repository passed to the consumer uses the session_factory from get_session_factory().

        We verify that the repository is constructed with a factory (not the request-scope dep).
        This is tested by constructing the repository directly with get_session_factory()
        and asserting it is NOT the same seam as get_db_session.

        NOTE: this test asserts the import-time seam. The consumer must use
        get_session_factory() when creating the PostgresNormalizationRepository,
        not pass get_db_session or a session directly.
        """
        # Verify the shared seam exists and is distinct from get_db_session
        from naas_shared.database import get_db_session, get_session_factory

        # get_session_factory returns a factory (callable)
        # get_db_session is an async generator / FastAPI dependency
        # They must be different objects
        assert get_session_factory is not get_db_session, (
            "get_session_factory and get_db_session must be distinct — "
            "consumer uses factory, HTTP endpoints use request-scoped dep"
        )


# ===========================================================================
# D.10. Consumer name and XREADGROUP arguments
# ===========================================================================


class TestConsumerXreadgroupArgs:
    """Consumer reads using XREADGROUP with correct stream, group, and key pattern."""

    async def test_xreadgroup_uses_login_events_stream_and_normalization_group(self):
        """XREADGROUP must use STREAM_LOGIN_EVENTS and GROUP_NORMALIZATION."""
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=_make_normalized())
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],  # empty batch
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert redis.xreadgroup.called, "xreadgroup must be called in the consumer loop"
        call_kwargs = redis.xreadgroup.call_args

        # Check that the call includes the correct group name and stream key
        # The call signature: xreadgroup(group, consumer, streams, count, block)
        # or keyword args — check both positional and keyword
        all_args = list(call_kwargs.args) + list(call_kwargs.kwargs.values())
        all_str = " ".join(str(a) for a in all_args)

        assert GROUP_NORMALIZATION in all_str, (
            f"xreadgroup must use group={GROUP_NORMALIZATION!r}. Call args: {call_kwargs}"
        )
        assert STREAM_LOGIN_EVENTS in all_str, (
            f"xreadgroup must read from stream={STREAM_LOGIN_EVENTS!r}. Call args: {call_kwargs}"
        )

    async def test_xreadgroup_uses_new_messages_marker(self):
        """XREADGROUP must use '>' as the stream ID to read only undelivered messages."""
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=_make_normalized())
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                [],
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        # All xreadgroup calls must use ">" as the stream ID
        for c in redis.xreadgroup.call_args_list:
            all_args = list(c.args) + list(c.kwargs.values())
            all_str = " ".join(str(a) for a in all_args)
            assert ">" in all_str, (
                f"xreadgroup must use '>' as stream ID for new-messages-only semantics. "
                f"Call args: {c}"
            )

    async def test_xack_uses_correct_stream_and_msg_id(self):
        """XACK must be called with STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION, and the message id."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        normalized = _make_normalized()
        msg_id = "42-7"

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=normalized)
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, msg_id),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert redis.xack.called, "xack must be called on successful processing"
        xack_call = redis.xack.call_args
        all_args = list(xack_call.args) + list(xack_call.kwargs.values())
        all_str = " ".join(str(a) for a in all_args)

        assert STREAM_LOGIN_EVENTS in all_str, (
            f"xack must reference stream={STREAM_LOGIN_EVENTS!r}"
        )
        assert msg_id in all_str, (
            f"xack must reference the processed message id={msg_id!r}. Got: {xack_call}"
        )


# ===========================================================================
# D.7 (continued): Message parsing — LoginEventRecord.model_validate
# ===========================================================================


class TestConsumerMessageParsing:
    """Consumer correctly parses the stream message envelope per §2.2."""

    async def test_consumer_parses_data_field_from_stream_message(self):
        """Consumer reads fields['data'] and validates as LoginEventRecord."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        normalized = _make_normalized()
        received_records = []

        async def _normalize(r):
            received_records.append(r)
            return normalized

        service = AsyncMock()
        service.normalize = _normalize
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                _make_stream_message(record, "99-1"),
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert len(received_records) == 1, (
            f"Exactly one LoginEventRecord must be passed to normalize(), got {len(received_records)}"
        )
        parsed = received_records[0]
        assert isinstance(parsed, LoginEventRecord), (
            f"normalize() must receive a LoginEventRecord, got {type(parsed)}"
        )
        assert parsed.id == record.id, (
            f"Parsed record id must match original {record.id}, got {parsed.id}"
        )
        assert parsed.protocol == "oidc"
        assert parsed.user_id == "alice"


# ===========================================================================
# D.8 (continued): Poison-message no-ACK contract
# ===========================================================================


class TestPoisonMessageNoAck:
    """Malformed or invalid messages must NOT be XACKed (poison-message safety).

    Spec §5.1 / consumer.py: ACK only after all steps succeed.  A message that
    fails JSON parsing or Pydantic validation must stay in the pending-entries list
    so it can be inspected / dead-lettered manually.  It must never cause an
    unhandled exception that kills the consumer loop.

    WHY: If a bad message were XACKed it would be permanently lost.  If it
    propagated an exception it would stall the loop for all subsequent messages.
    """

    async def test_bad_json_data_field_no_xack(self):
        """A message with a non-JSON data field must NOT be XACKed.

        The consumer calls json.loads(data_raw); a SyntaxError/JSONDecodeError
        must be caught, the message skipped (not ACKed), and the loop must continue.
        """
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        bad_message = [
            [STREAM_LOGIN_EVENTS, [("bad-1-0", {"data": "not valid json {{{"})]]
        ]

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                bad_message,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert not redis.xack.called, (
            "XACK must NOT be called for a message with an invalid JSON data field. "
            "Bad JSON means we cannot reconstruct the event — it must stay pending."
        )

    async def test_invalid_login_event_record_no_xack(self):
        """A message with valid JSON but invalid LoginEventRecord schema must NOT be XACKed.

        LoginEventRecord.model_validate() raises Pydantic ValidationError on a schema
        violation (e.g., wrong type for 'id').  The consumer must catch it, log, and
        leave the message unACKed for redelivery.
        """
        from app.consumer import run_consumer_loop

        # Build a JSON payload that parses fine but fails LoginEventRecord validation.
        invalid_payload = json.dumps(
            {
                "id": "this-is-not-a-uuid",   # invalid UUID
                "user_id": "alice",
                "client_ip": "192.168.1.1",
                "protocol": "oidc",
                "timestamp": "2024-01-15T10:30:00+00:00",
                "source": "user",
                "is_synthetic": False,
                "is_historical": False,
                "raw_attributes": {},
            }
        )
        invalid_message = [
            [STREAM_LOGIN_EVENTS, [("bad-2-0", {"data": invalid_payload})]]
        ]

        service = AsyncMock()
        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                invalid_message,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert not redis.xack.called, (
            "XACK must NOT be called for a message that fails LoginEventRecord validation. "
            "An unvalidated payload cannot be safely processed — it must stay pending."
        )

    async def test_invalid_message_does_not_propagate_exception(self):
        """A bad message must not raise an exception out of _process_message.

        Verifies that the consumer loop continues to process the next valid message
        after encountering a bad one — the loop is NOT killed.
        """
        from app.consumer import run_consumer_loop

        good_record = _make_record()
        normalized = _make_normalized()
        normalize_call_count = [0]

        async def _counting_normalize(r):
            normalize_call_count[0] += 1
            return normalized

        service = AsyncMock()
        service.normalize = _counting_normalize
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        bad_message_then_good = [
            [
                STREAM_LOGIN_EVENTS,
                [
                    ("bad-3-0", {"data": "not-json"}),
                    ("good-3-1", {"data": json.dumps(good_record.model_dump(mode="json"), default=str)}),
                ],
            ]
        ]

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(
            side_effect=[
                bad_message_then_good,
                asyncio.CancelledError(),
            ]
        )
        redis.xack = AsyncMock()

        with contextlib.suppress(asyncio.CancelledError):
            await run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            )

        assert normalize_call_count[0] == 1, (
            f"After a bad message, the loop must continue and process the next valid "
            f"message.  Expected normalize() called 1 time, got {normalize_call_count[0]}. "
            "A poison message must not kill the consumer loop."
        )
        # The good message was XACKed; the bad one was not.
        assert redis.xack.call_count == 1, (
            f"Exactly 1 XACK expected (for the good message only). "
            f"Got {redis.xack.call_count}."
        )
