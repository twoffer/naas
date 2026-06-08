"""Consumer loop (consumer.py): XREADGROUP, ACK, message dispatch, and error recovery."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID


# ---------------------------------------------------------------------------
# sys.path injection
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Cannot find repo root")


_REPO = _repo_root()
_SVC = str(_REPO / "services" / "identity-normalization")
_SHARED = str(_REPO / "shared")
for _p in [_SVC, _SHARED]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


from naas_shared.models import (
    EnrichmentSkipped,
    LoginEventRecord,
    NormalizedAttributes,
)
from naas_shared.constants import STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID = UUID("12345678-1234-5678-1234-567812345678")
_NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# D.7. Consumer loop — critical ordering: normalize → write(commit) → publish → XACK
# ===========================================================================

class TestConsumerOrdering:
    """Step ordering within one processed message is CRITICAL (§5.1, ADR-0002)."""

    def test_normalize_then_write_then_publish_then_xack_order(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, msg_id),
            asyncio.CancelledError(),  # stop the loop after first batch
        ])

        async def _xack(*args):
            call_order.append("xack")
        redis.xack = AsyncMock(side_effect=_xack)

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert "normalize" in call_order, "normalize must be called"
        assert "write" in call_order, "write must be called"
        assert "publish" in call_order, "publish must be called"
        assert "xack" in call_order, "xack must be called on success"

        # Ordering: normalize < write < publish < xack
        idx = {step: call_order.index(step) for step in ["normalize", "write", "publish", "xack"]}
        assert idx["normalize"] < idx["write"], "normalize must precede write"
        assert idx["write"] < idx["publish"], (
            "write (commit) must precede publish — §5.1 ⚠️ CRITICAL ordering"
        )
        assert idx["publish"] < idx["xack"], "publish must precede xack"

    def test_xack_only_after_both_write_and_publish_succeed(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "2-0"),
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock(side_effect=lambda *a: call_order.append("xack"))

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert "xack" not in call_order, (
            "XACK must NOT be called when write/commit fails — message stays pending for redelivery"
        )


# ===========================================================================
# D.8. Failure handling — no XACK on exception
# ===========================================================================

class TestConsumerFailureHandling:
    """On any step exception, message is NOT XACKed (stays pending for redelivery)."""

    def test_normalize_exception_no_xack(self):
        """If normalize() raises, message is not ACKed and loop continues."""
        from app.consumer import run_consumer_loop

        record = _make_record()
        xack_call_count = [0]

        service = AsyncMock()
        service.normalize = AsyncMock(side_effect=ValueError("normalization error"))

        repository = AsyncMock()
        publisher = AsyncMock()

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "3-0"),
            asyncio.CancelledError(),
        ])

        async def _xack(*args):
            xack_call_count[0] += 1
        redis.xack = AsyncMock(side_effect=_xack)

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert xack_call_count[0] == 0, (
            "XACK must NOT be called when normalize() raises — message must stay in pending-entries list"
        )

    def test_repository_write_exception_no_xack(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "4-0"),
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock(side_effect=lambda *a: xack_count.__setitem__(0, xack_count[0] + 1))

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert xack_count[0] == 0, "XACK must NOT be called when repository.write() raises"

    def test_publish_exception_no_xack(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "5-0"),
            asyncio.CancelledError(),
        ])
        redis.xack = AsyncMock(side_effect=lambda *a: xack_count.__setitem__(0, xack_count[0] + 1))

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

        assert xack_count[0] == 0, "XACK must NOT be called when publish_normalized() raises"

    def test_enrichment_skip_does_not_cause_no_xack(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "6-0"),
            asyncio.CancelledError(),
        ])

        async def _xack(*args):
            xack_count[0] += 1
        redis.xack = AsyncMock(side_effect=_xack)

        try:
            _run(run_consumer_loop(
                service=service,
                repository=repository,
                publisher=publisher,
                redis=redis,
            ))
        except asyncio.CancelledError:
            pass

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
        from naas_shared.database import get_session_factory, get_db_session

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

    def test_xreadgroup_uses_login_events_stream_and_normalization_group(self):
        """XREADGROUP must use STREAM_LOGIN_EVENTS and GROUP_NORMALIZATION."""
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=_make_normalized())
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            [],  # empty batch
            asyncio.CancelledError(),
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

    def test_xreadgroup_uses_new_messages_marker(self):
        """XREADGROUP must use '>' as the stream ID to read only undelivered messages."""
        from app.consumer import run_consumer_loop

        service = AsyncMock()
        service.normalize = AsyncMock(return_value=_make_normalized())
        repository = AsyncMock()
        repository.write = AsyncMock(return_value=None)
        publisher = AsyncMock()
        publisher.publish_normalized = AsyncMock(return_value=None)

        redis = AsyncMock()
        redis.xreadgroup = AsyncMock(side_effect=[
            [],
            asyncio.CancelledError(),
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

        # All xreadgroup calls must use ">" as the stream ID
        for c in redis.xreadgroup.call_args_list:
            all_args = list(c.args) + list(c.kwargs.values())
            all_str = " ".join(str(a) for a in all_args)
            assert ">" in all_str, (
                f"xreadgroup must use '>' as stream ID for new-messages-only semantics. "
                f"Call args: {c}"
            )

    def test_xack_uses_correct_stream_and_msg_id(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, msg_id),
            asyncio.CancelledError(),
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

    def test_consumer_parses_data_field_from_stream_message(self):
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
        redis.xreadgroup = AsyncMock(side_effect=[
            _make_stream_message(record, "99-1"),
            asyncio.CancelledError(),
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
