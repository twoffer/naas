"""Redis Streams consumer loop for the Identity Normalization Service.

Reads login events from the login_events stream using XREADGROUP, runs the
full normalization pipeline, persists results, publishes to normalized_events,
and ACKs only after both persist AND publish succeed (§5.1, ADR-0002).

Critical ordering (§5.1, ADR-0002):
  1. normalize()                 — extract + enrich + resolve
  2. repository.write() + commit — point of no return (persist BEFORE publish)
  3. publisher.publish_normalized() — XADD to normalized_events
  4. redis.xack()                — ONLY after both 2 and 3 succeed

WHY this ordering: persisting before publishing and ACKing only after BOTH
succeed means a crash or failure at any step leaves the message in the consumer
group's Pending Entries List (PEL) rather than silently dropped — so no
normalized result is lost.  ACKing before commit, by contrast, could drop a
result on a crash with no recovery path.  Note: Redis Streams do NOT
auto-redeliver pending entries (there is no visibility timeout); reprocessing a
stuck entry requires a claim-and-retry / dead-letter policy (XAUTOCLAIM), which
is deferred (docs/FOLLOWUPS.md).  Downstream services stay safe against any such
future reprocessing because normalization is idempotent.
"""

from __future__ import annotations

import asyncio
import json
import socket

import naas_shared.redis_client as _redis_mod
import pydantic
import structlog
from naas_shared.constants import GROUP_NORMALIZATION, STREAM_LOGIN_EVENTS
from naas_shared.logging import get_logger
from naas_shared.models import LoginEventRecord

from app.ports import EventPublisher, NormalizationRepository, Normalizer

# Minimum pause on an empty XREADGROUP batch.  In production, `block=2000` means
# Redis holds the connection open for up to 2 s before returning [] — so this
# sleep is negligible there.  Its purpose is to prevent a misbehaving or mocked
# Redis that ignores `block` from busy-spinning the event loop at 100 % CPU.
# asyncio.sleep(0) is NOT sufficient because it only yields once, not for real time.
_EMPTY_BATCH_SLEEP_S: float = 0.5

_logger = get_logger(__name__)


async def run_consumer_loop(
    service: Normalizer,
    repository: NormalizationRepository,
    publisher: EventPublisher,
    redis: object | None = None,
) -> None:
    """Process login events from the Redis Stream indefinitely.

    Uses XREADGROUP so messages are delivered to exactly one consumer in the
    group at a time.  The consumer name is derived from the hostname to be
    unique per replica.

    On any per-message exception: log the error, do NOT XACK (the message
    stays in the consumer group's Pending Entries List).  Redis Streams do NOT
    auto-redeliver pending entries — there is no visibility timeout, and a
    claim-and-retry / dead-letter policy (XAUTOCLAIM) is deferred
    (docs/FOLLOWUPS.md) — so the entry is not reprocessed automatically.  The
    loop simply continues to the next batch, so a single bad message does not
    stall the pipeline.

    EnrichmentSkipped in the normalized result is NOT a processing failure;
    such messages proceed through the full write → publish → XACK path.

    Args:
        service:    NormalizationService instance (has normalize(record) -> NormalizedAttributes).
        repository: PostgresNormalizationRepository (has write(event_id, normalized) -> None).
        publisher:  NormalizationPublisher (has publish_normalized(record, normalized) -> None).
        redis:      Async Redis client (aioredis.Redis or compatible AsyncMock in tests).
    """
    if redis is None:
        redis = await _redis_mod.get_redis()

    consumer_name = f"{socket.gethostname()}-normalization"
    log = _logger.bind(consumer=consumer_name, group=GROUP_NORMALIZATION)

    log.info("consumer_loop_started", stream=STREAM_LOGIN_EVENTS)

    while True:
        # XREADGROUP: block up to 2 s, read up to 10 new messages per iteration.
        # ">" means: deliver only messages not yet delivered to any consumer.
        # Transient network errors (e.g., a momentary Redis blip) are caught here
        # so a single I/O failure does not kill the consumer process. CancelledError
        # is NOT caught — it signals intentional task cancellation on shutdown and
        # must propagate to allow clean termination.
        try:
            batches = await redis.xreadgroup(
                GROUP_NORMALIZATION,
                consumer_name,
                streams={STREAM_LOGIN_EVENTS: ">"},
                count=10,
                block=2000,
            )
        except Exception as xread_exc:  # noqa: BLE001 — any transient read error must not kill the consumer loop
            log.warning(
                "xreadgroup_transient_error",
                error=str(xread_exc)[:200],
                error_type=type(xread_exc).__name__,
            )
            await asyncio.sleep(_EMPTY_BATCH_SLEEP_S)
            continue

        if not batches:
            # Yield real wall-clock time so a non-blocking client (e.g. an
            # AsyncMock in tests that ignores `block`) cannot spin the event
            # loop at 100 % CPU.  Production Redis with block=2000 waits in the
            # server, so this sleep is effectively a no-op there.
            await asyncio.sleep(_EMPTY_BATCH_SLEEP_S)
            continue

        for _stream, messages in batches:
            for msg_id, fields in messages:
                await _process_message(
                    msg_id=msg_id,
                    fields=fields,
                    service=service,
                    repository=repository,
                    publisher=publisher,
                    redis=redis,
                    log=log,
                )


async def _process_message(
    *,
    msg_id: str,
    fields: dict,
    service: Normalizer,
    repository: NormalizationRepository,
    publisher: EventPublisher,
    redis: object,
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Handle one stream message end-to-end.

    Failures at any step are caught, logged, and do NOT XACK.  This keeps the
    message in the consumer group's Pending Entries List (Redis does not
    auto-redeliver it; see run_consumer_loop and docs/FOLLOWUPS.md).

    WHY bytes handling: redis-py may return field keys/values as either str or
    bytes depending on decode_responses setting.  We normalize here so the
    consumer works in both modes.
    """
    try:
        # Decode bytes if needed (redis-py without decode_responses returns bytes)
        data_raw = fields.get("data") or fields.get(b"data")
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")

        record = LoginEventRecord.model_validate(json.loads(data_raw))

        # Step 1: normalize (extract + enrich + resolve)
        normalized = await service.normalize(record)

        # Step 2: persist + commit (point of no return)
        await repository.write(record.id, normalized)

        # Step 3: publish to normalized_events stream
        await publisher.publish_normalized(record, normalized)

        # Step 4: ACK only after BOTH write and publish succeed
        await redis.xack(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION, msg_id)

        log.debug(
            "message_processed",
            msg_id=msg_id,
            event_id=str(record.id),
            protocol=record.protocol,
        )

    except Exception as exc:  # noqa: BLE001 — per-message boundary: a poison message must not crash the loop (no-ACK leaves it pending)
        # For Pydantic ValidationErrors: log field locations only, NOT the raw exception
        # string. str(ValidationError) embeds input_value for each failing field, which
        # can contain PII (e.g., an email address that arrived in a UUID field).
        # For all other exceptions: truncate the error string to bound PII exposure.
        if isinstance(exc, pydantic.ValidationError):
            log.error(
                "message_processing_failed",
                msg_id=msg_id,
                error_locations=[e["loc"] for e in exc.errors()],
                error_type=type(exc).__name__,
            )
        else:
            log.error(
                "message_processing_failed",
                msg_id=msg_id,
                error=str(exc)[:200],
                error_type=type(exc).__name__,
            )
        # Do NOT XACK — message stays in the consumer group's PEL (no auto-redelivery)
