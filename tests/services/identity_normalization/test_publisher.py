"""publish_normalized: serialize NormalizedAttributes and publish to normalized_events stream."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from naas_shared.constants import STREAM_NORMALIZED_EVENTS
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
        raw_attributes={"name": "Alice Smith", "email": "alice@corp.com"},
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


def _get_publisher():
    """Import the concrete publisher class.

    Try service.py first (NormalizationPublisher), then publisher.py.
    The implementer may place it in either module.
    """
    try:
        from app.service import NormalizationPublisher

        return NormalizationPublisher()
    except (ImportError, AttributeError):
        pass
    try:
        from app.publisher import NormalizationPublisher

        return NormalizationPublisher()
    except (ImportError, AttributeError):
        pass
    pytest.fail(
        "NormalizationPublisher not found in app.service or app.publisher. "
        "Implementer must create a NormalizationPublisher class satisfying the EventPublisher port."
    )


# ===========================================================================
# C.6. Publisher — uses shared publish_to_stream (not hand-rolled XADD)
# ===========================================================================


class TestPublisherUsesSharedHelper:
    """The publisher calls naas_shared.redis_client.publish_to_stream."""

    async def test_publish_normalized_calls_shared_publish_to_stream(self):
        """publish_normalized() must call publish_to_stream — not a hand-rolled r.xadd()."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()

        with patch(
            "naas_shared.redis_client.publish_to_stream", new_callable=AsyncMock
        ) as mock_pub:
            await publisher.publish_normalized(record, normalized)

        assert mock_pub.called, (
            "publish_to_stream must be called — do not hand-roll XADD (§3.2)"
        )

    async def test_publish_normalized_uses_stream_normalized_events_constant(self):
        """The first arg to publish_to_stream must be STREAM_NORMALIZED_EVENTS."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()

        with patch(
            "naas_shared.redis_client.publish_to_stream", new_callable=AsyncMock
        ) as mock_pub:
            await publisher.publish_normalized(record, normalized)

        call_args = mock_pub.call_args
        assert call_args is not None, "publish_to_stream was not called"
        stream_arg = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("stream")
        )
        assert stream_arg == STREAM_NORMALIZED_EVENTS, (
            f"publish_to_stream must be called with stream={STREAM_NORMALIZED_EVENTS!r}, "
            f"got {stream_arg!r}"
        )


# ===========================================================================
# C.6. Publisher — full LoginEventRecord with normalized_attributes populated
# ===========================================================================


class TestPublisherFullRecordPayload:
    """Per ADR-0011: publish the FULL LoginEventRecord with normalized_attributes populated."""

    async def test_publish_normalized_sets_normalized_attributes_on_record(self):
        """record.normalized_attributes must be set to normalized.model_dump(mode='json') before publish."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()

        captured_payload: list[dict] = []

        async def _capture(stream: str, data: dict) -> str:
            captured_payload.append(data)
            return "mock-id"

        with patch("naas_shared.redis_client.publish_to_stream", side_effect=_capture):
            await publisher.publish_normalized(record, normalized)

        assert len(captured_payload) == 1, (
            "publish_to_stream must be called exactly once"
        )
        payload = captured_payload[0]

        assert "normalized_attributes" in payload, (
            "Published payload must include 'normalized_attributes' (full LoginEventRecord per ADR-0011)"
        )
        assert payload["normalized_attributes"] is not None, (
            "normalized_attributes must not be None in the published payload"
        )

    async def test_published_payload_contains_full_login_event_record_fields(self):
        """The payload must be the full LoginEventRecord — not a stripped-down dict."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()
        captured: list[dict] = []

        async def _capture(stream: str, data: dict) -> str:
            captured.append(data)
            return "mock-id"

        with patch("naas_shared.redis_client.publish_to_stream", side_effect=_capture):
            await publisher.publish_normalized(record, normalized)

        payload = captured[0]

        # Full LoginEventRecord fields must be present
        expected_fields = {
            "id",
            "user_id",
            "protocol",
            "client_ip",
            "timestamp",
            "source",
            "is_synthetic",
            "is_historical",
            "raw_attributes",
            "normalized_attributes",
        }
        missing = expected_fields - set(payload.keys())
        assert not missing, (
            f"Published payload missing LoginEventRecord fields: {missing}. "
            "Per ADR-0011, the full record must be published."
        )

    async def test_published_normalized_attributes_matches_normalized_model_dump(self):
        """The normalized_attributes in the payload matches normalized.model_dump(mode='json')."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()
        captured: list[dict] = []

        async def _capture(stream: str, data: dict) -> str:
            captured.append(data)
            return "mock-id"

        with patch("naas_shared.redis_client.publish_to_stream", side_effect=_capture):
            await publisher.publish_normalized(record, normalized)

        payload = captured[0]
        expected_normalized = normalized.model_dump(mode="json")

        assert payload["normalized_attributes"] == expected_normalized, (
            "normalized_attributes in payload must exactly match normalized.model_dump(mode='json'). "
            f"Expected: {expected_normalized}. Got: {payload['normalized_attributes']}"
        )

    async def test_published_payload_carries_correct_event_id(self):
        """The published payload carries the correct event id as the correlation key."""
        publisher = _get_publisher()
        record = _make_record()
        normalized = _make_normalized()
        captured: list[dict] = []

        async def _capture(stream: str, data: dict) -> str:
            captured.append(data)
            return "mock-id"

        with patch("naas_shared.redis_client.publish_to_stream", side_effect=_capture):
            await publisher.publish_normalized(record, normalized)

        payload = captured[0]
        # id is serialized as a string by model_dump(mode="json")
        assert str(payload.get("id")) == str(_UUID), (
            f"Published payload must carry event id={_UUID!r} as correlation key. "
            f"Got: {payload.get('id')!r}"
        )


# ===========================================================================
# C.6. Publisher — does not mutate the record before returning to caller
# ===========================================================================


class TestPublisherDoesNotMutateRecordPermanently:
    """publish_normalized() sets normalized_attributes on the record for publishing.

    The record's normalized_attributes field must reflect normalized after publish.
    (The mutated record is fine to keep — the consumer loop creates a fresh record
    per message anyway.)
    """

    async def test_record_normalized_attributes_set_after_publish(self):
        """After publish_normalized(), record.normalized_attributes == normalized.model_dump(mode='json')."""
        publisher = _get_publisher()
        record = _make_record()
        assert record.normalized_attributes is None, (
            "record must start with normalized_attributes=None"
        )
        normalized = _make_normalized()

        with patch(
            "naas_shared.redis_client.publish_to_stream", new_callable=AsyncMock
        ) as mock_pub:
            mock_pub.return_value = "mock-id"
            await publisher.publish_normalized(record, normalized)

        expected = normalized.model_dump(mode="json")
        assert record.normalized_attributes == expected, (
            f"record.normalized_attributes must be set to normalized.model_dump(mode='json') "
            f"after publish. Got: {record.normalized_attributes!r}"
        )
