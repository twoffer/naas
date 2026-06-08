"""Event ingestion service integration: dual-write to PostgreSQL and Redis Stream."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

# third-party
import pytest


# ---------------------------------------------------------------------------
# Shared test data helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides: Any):
    """Build a LoginEventIngest with sensible defaults.

    Uses deterministic values from the project test-data reference values where
    possible. This is NOT datetime.now() — the timestamp is fixed to avoid
    flaky tests.
    """
    from naas_shared.models import LoginEventIngest

    defaults = {
        "user_id": "alice",
        "client_ip": "192.168.1.1",
        "protocol": "oidc",
        "timestamp": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "source": "user",
        "is_synthetic": False,
        "is_historical": False,
        "raw_attributes": {"email": "alice@corp.com"},
    }
    defaults.update(overrides)
    return LoginEventIngest(**defaults)


# ---------------------------------------------------------------------------
# Fakes satisfying the EventRepository / EventPublisher protocols
# ---------------------------------------------------------------------------

class FakeRepo:
    """In-memory fake implementing the EventRepository Protocol interface.

    Records calls to a shared call_log so ordering assertions can be made.
    Does NOT persist anything — it only records the calls in memory.

    Assumption: EventRepository.persist(record) and persist_many(records) are
    both async methods returning None. This fake mirrors that signature exactly.
    """

    def __init__(self, call_log: list):
        self._call_log = call_log
        self.persisted_records: list = []

    async def persist(self, record) -> None:
        self._call_log.append(("persist", record))
        self.persisted_records.append(record)

    async def persist_many(self, records: list) -> None:
        self._call_log.append(("persist_many", records))
        self.persisted_records.extend(records)


class FakePublisher:
    """In-memory fake implementing the EventPublisher Protocol interface.

    Can be toggled to raise an exception to test the _safe_publish failure path.

    Assumption: EventPublisher.publish(record) is an async method returning None.
    """

    def __init__(self, call_log: list, should_raise: bool = False):
        self._call_log = call_log
        self._should_raise = should_raise
        self.published_records: list = []

    async def publish(self, record) -> None:
        self._call_log.append(("publish", record))
        self.published_records.append(record)
        if self._should_raise:
            raise RuntimeError("Simulated Redis publish failure")


def _make_fake_logger() -> MagicMock:
    """Return a MagicMock logger that records error() calls.

    WHY: The spec §5.4 states the logger is injected into IngestionService
    (IngestionService(repo, publisher, logger)). Using a MagicMock lets us assert
    that logger.error was called with the correct keyword arguments without
    depending on structlog's internal API.
    """
    return MagicMock()


# ===========================================================================
# CLASS 1 — Import: app.service.IngestionService is importable
# ===========================================================================


class TestIngestionServiceImport:
    """app/service.py must be importable and expose IngestionService.

    WHY: a missing module surfaces as a clear import failure rather than a
    confusing collection error.
    """

    def test_ingestion_service_is_importable(self) -> None:
        """from app.service import IngestionService must succeed."""
        from app.service import IngestionService  # noqa: F401

    def test_ingestion_service_is_constructable(self) -> None:
        """IngestionService(repo, publisher, logger) must construct without error.

        WHY: The service constructor signature per spec §5.4 is
        IngestionService(repo: EventRepository, publisher: EventPublisher, logger).
        A TypeError here means the constructor has a different signature.
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        publisher = FakePublisher(call_log)
        logger = _make_fake_logger()

        service = IngestionService(repo=repo, publisher=publisher, logger=logger)
        assert service is not None


# ===========================================================================
# CLASS 2 — ingest_one: happy path (dual-write in correct order)
# ===========================================================================


class TestIngestOneDualWrite:
    """IngestionService.ingest_one must persist then publish (in that order).

    WHY: The spec §5.5 is explicit: PostgreSQL is the system of record; the
    Redis Stream is transport. Order is non-negotiable. If publish happens
    before commit, a crash between the two leaves the stream message pointing
    to a row that doesn't exist yet — consumers would try to read a non-existent
    event_id and silently fail.
    """

    def test_ingest_one_returns_a_uuid(self) -> None:
        """ingest_one(event) must return a UUID.

        WHY: The route handler uses the returned id to build IngestAccepted(id=...).
        If a non-UUID (or None) is returned, the Pydantic response model fails
        validation and the request returns a 422 instead of 202.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        event = _make_event()
        result = asyncio.get_event_loop().run_until_complete(service.ingest_one(event))

        assert isinstance(result, uuid.UUID), (
            f"ingest_one must return a uuid.UUID, got {type(result).__name__!r}."
        )

    def test_ingest_one_returns_uuid_matching_persisted_record(self) -> None:
        """The UUID returned by ingest_one must equal the persisted record's id.

        WHY: Downstream consumers correlate the Redis stream message back to the
        PostgreSQL row using this UUID. If the returned id doesn't match the
        persisted record's id, the pipeline loses correlation and every downstream
        service (normalization, risk evaluator) operates on the wrong event.
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        service = IngestionService(
            repo=repo,
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        event = _make_event()
        returned_id = asyncio.get_event_loop().run_until_complete(service.ingest_one(event))

        assert len(repo.persisted_records) == 1, (
            f"Expected exactly 1 persisted record, got {len(repo.persisted_records)}."
        )
        persisted_id = repo.persisted_records[0].id
        assert returned_id == persisted_id, (
            f"Returned UUID ({returned_id}) must match the persisted record's id "
            f"({persisted_id}). The route handler builds IngestAccepted(id=returned_id) "
            "and downstream stages use this id to find the PG row."
        )

    def test_ingest_one_calls_persist_exactly_once(self) -> None:
        """ingest_one must call repo.persist exactly once.

        WHY: Each call to ingest_one ingests exactly one event. Multiple persist
        calls would create duplicate rows in the events table, violating the
        'exactly one row per event' contract (spec §3.1). Zero calls would mean
        the event was never durably stored.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        asyncio.get_event_loop().run_until_complete(service.ingest_one(_make_event()))

        persist_calls = [entry for entry in call_log if entry[0] == "persist"]
        assert len(persist_calls) == 1, (
            f"Expected exactly 1 call to repo.persist, got {len(persist_calls)}."
        )

    def test_ingest_one_calls_publish_exactly_once(self) -> None:
        """ingest_one must call publisher.publish exactly once (after persist).

        WHY: Each event must be published to the login_events stream once. Multiple
        publishes would cause downstream services (normalization, enrichment, risk
        evaluator) to process the same event multiple times, generating duplicate
        decisions and potentially duplicate alerts.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        asyncio.get_event_loop().run_until_complete(service.ingest_one(_make_event()))

        publish_calls = [entry for entry in call_log if entry[0] == "publish"]
        assert len(publish_calls) == 1, (
            f"Expected exactly 1 call to publisher.publish, got {len(publish_calls)}."
        )

    def test_ingest_one_persist_precedes_publish(self) -> None:
        """repo.persist must be called before publisher.publish in ingest_one.

        WHY: Spec §5.5 is explicit: 'Persist to PostgreSQL first and commit.
        The commit is the point of no return. Then publish to login_events.
        Publishing strictly follows a successful commit.' If publish happens before
        persist, a crash between the two leaves a stream message for an event that
        doesn't exist in PostgreSQL. Downstream consumers would read a dangling id.

        We detect ordering by checking positions in the shared call_log list.
        Both fakes append to the same list, so their relative positions capture
        the actual call order.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        asyncio.get_event_loop().run_until_complete(service.ingest_one(_make_event()))

        call_names = [entry[0] for entry in call_log]
        assert "persist" in call_names, "persist was never called"
        assert "publish" in call_names, "publish was never called"

        persist_index = call_names.index("persist")
        publish_index = call_names.index("publish")
        assert persist_index < publish_index, (
            f"repo.persist must be called BEFORE publisher.publish. "
            f"In the call log, persist is at index {persist_index} "
            f"and publish is at index {publish_index}. "
            "Spec §5.5: PostgreSQL is the system of record; the commit is the "
            "point of no return before publishing to the stream."
        )


# ===========================================================================
# CLASS 3 — ingest_one: publish failure (fail-safe behavior)
# ===========================================================================


class TestIngestOnePublishFailure:
    """When the publisher raises, ingest_one must NOT propagate the exception.

    WHY: Spec §5.5 §4: 'If the publish fails after a successful commit: the
    durable record already exists and is replayable. Catch the error, log it
    (structured, including the event id), and still return 202.'
    A 500 response after a committed event would confuse callers — they would
    retry and create a duplicate row. Returning 202 is the safe behavior because
    the event IS accepted (it's in PostgreSQL).
    """

    def test_ingest_one_returns_id_even_when_publisher_raises(self) -> None:
        """ingest_one must return the record's id even when publish raises.

        WHY: If ingest_one re-raises the publisher's exception, the route handler
        catches a 500 and the caller retries. But the event is already committed
        to PostgreSQL, so the retry creates a new duplicate row. Returning the id
        allows the caller to treat the request as accepted.
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        service = IngestionService(
            repo=repo,
            publisher=FakePublisher(call_log, should_raise=True),
            logger=_make_fake_logger(),
        )
        # Must NOT raise
        returned_id = asyncio.get_event_loop().run_until_complete(
            service.ingest_one(_make_event())
        )

        assert isinstance(returned_id, uuid.UUID), (
            f"ingest_one must return a UUID even when publish raises, "
            f"got {type(returned_id).__name__!r}."
        )
        persisted_id = repo.persisted_records[0].id
        assert returned_id == persisted_id, (
            "Returned UUID must equal the persisted record's id even after publish failure."
        )

    def test_ingest_one_does_not_propagate_publisher_exception(self) -> None:
        """ingest_one must swallow the publisher's exception (no reraise).

        WHY: If the exception propagates, FastAPI converts it to a 500 response.
        The event IS committed to PostgreSQL, so the caller would retry and create
        a duplicate. The spec mandates: 'Catch the error ... and still return 202.'
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log, should_raise=True),
            logger=_make_fake_logger(),
        )

        # This must complete without raising
        try:
            asyncio.get_event_loop().run_until_complete(
                service.ingest_one(_make_event())
            )
        except Exception as exc:
            pytest.fail(
                f"ingest_one must not propagate publisher exceptions. "
                f"Got: {type(exc).__name__}: {exc}. "
                "Spec §5.5: catch the error, log it, still return the id."
            )

    def test_ingest_one_calls_logger_error_when_publisher_raises(self) -> None:
        """When publish fails, logger.error must be called exactly once.

        WHY: Spec §5.4 states: 'self._log.error("login_events publish failed",
        event_id=str(record.id), exc_info=True)'. Structured logging is how
        operators learn that the event needs to be replayed from PostgreSQL.
        Without logging, a silent publish failure would leave the event in the DB
        without any downstream processing, with no observable signal.
        """
        from app.service import IngestionService

        call_log: list = []
        logger = _make_fake_logger()
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log, should_raise=True),
            logger=logger,
        )
        asyncio.get_event_loop().run_until_complete(service.ingest_one(_make_event()))

        assert logger.error.call_count == 1, (
            f"logger.error must be called exactly once when publish fails. "
            f"Got {logger.error.call_count} calls."
        )

    def test_ingest_one_logger_error_called_with_event_id_kwarg(self) -> None:
        """logger.error must be called with event_id=str(record.id) as a keyword arg.

        WHY: Spec §5.4 explicitly shows 'event_id=str(record.id)'. Structured
        loggers (like structlog) bind keyword arguments as JSON fields. The event_id
        must be a string (UUID str) so it appears correctly in logs and is searchable
        by operators investigating a pipeline gap (event in DB but not processed).
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        logger = _make_fake_logger()
        service = IngestionService(
            repo=repo,
            publisher=FakePublisher(call_log, should_raise=True),
            logger=logger,
        )
        asyncio.get_event_loop().run_until_complete(service.ingest_one(_make_event()))

        persisted_record = repo.persisted_records[0]
        expected_event_id_str = str(persisted_record.id)

        # Extract the kwargs from the logger.error call
        assert logger.error.call_count == 1
        _, kwargs = logger.error.call_args
        assert "event_id" in kwargs, (
            f"logger.error must be called with event_id= keyword argument. "
            f"Got kwargs: {kwargs}. "
            "Spec §5.4 shows: self._log.error('...', event_id=str(record.id), ...)"
        )
        assert kwargs["event_id"] == expected_event_id_str, (
            f"logger.error event_id must be str(record.id) = {expected_event_id_str!r}. "
            f"Got: {kwargs['event_id']!r}."
        )


# ===========================================================================
# CLASS 4 — ingest_many: happy path
# ===========================================================================


class TestIngestManyHappyPath:
    """IngestionService.ingest_many must persist all records in a single batch call.

    WHY: The spec §5.4 and §5.5 state: 'persist_many(records)' is a single
    transaction (all-or-nothing). Using individual persist() calls would mean N
    separate transactions — if one fails partway through, some events would be
    committed and others not, breaking the all-or-nothing guarantee for the batch.
    """

    def test_ingest_many_returns_list_of_uuids(self) -> None:
        """ingest_many([e1,e2,e3]) must return a list of UUIDs.

        WHY: The route handler uses the returned list to build
        BulkIngestAccepted(accepted=3, event_ids=[...]). If the return type is
        wrong, FastAPI's response model validation fails and the bulk endpoint
        returns a 422.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        result = asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        assert isinstance(result, list), (
            f"ingest_many must return a list, got {type(result).__name__!r}."
        )
        assert len(result) == 3, (
            f"ingest_many must return 3 UUIDs for 3 input events, got {len(result)}."
        )
        for i, item in enumerate(result):
            assert isinstance(item, uuid.UUID), (
                f"Result item {i} must be a uuid.UUID, got {type(item).__name__!r}."
            )

    def test_ingest_many_calls_persist_many_exactly_once(self) -> None:
        """ingest_many([e1,e2,e3]) must call repo.persist_many exactly once.

        WHY: The spec §5.3 and §5.5 require a single transaction for the whole batch:
        'persist_many(...): single transaction, all-or-nothing'. Using persist() in a
        loop would mean N transactions — any partial failure would leave some events
        committed and others not. Using persist_many() gives the adapter the opportunity
        to wrap them in a single transaction.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        persist_many_calls = [entry for entry in call_log if entry[0] == "persist_many"]
        assert len(persist_many_calls) == 1, (
            f"Expected exactly 1 call to repo.persist_many, got {len(persist_many_calls)}. "
            "All events in the batch must be persisted in a single call for atomicity."
        )

    def test_ingest_many_passes_all_records_in_single_persist_many_call(self) -> None:
        """persist_many must be called with all 3 records in a single list argument.

        WHY: If the adapter receives fewer records than expected (e.g., only 2 of 3),
        the batch is silently truncated. Passing all records in one call allows the
        adapter to use a single INSERT ... VALUES (...), (...), (...) for efficiency
        and atomic rollback.
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        service = IngestionService(
            repo=repo,
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        persist_many_calls = [entry for entry in call_log if entry[0] == "persist_many"]
        records_arg = persist_many_calls[0][1]
        assert len(records_arg) == 3, (
            f"persist_many must receive a 3-element list, got {len(records_arg)} records."
        )

    def test_ingest_many_returns_ids_in_input_order(self) -> None:
        """IDs returned by ingest_many must match the persisted records in input order.

        WHY: The route handler builds BulkIngestAccepted(event_ids=ids). Callers
        use position in event_ids to correlate back to their input events (the i-th
        id corresponds to the i-th input event). Out-of-order ids break this
        positional correlation contract.
        """
        from app.service import IngestionService

        call_log: list = []
        repo = FakeRepo(call_log)
        service = IngestionService(
            repo=repo,
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        returned_ids = asyncio.get_event_loop().run_until_complete(
            service.ingest_many(events)
        )

        # Persisted records are added to repo.persisted_records in call order
        persisted_ids = [r.id for r in repo.persisted_records]
        assert returned_ids == persisted_ids, (
            f"Returned IDs must match persisted record IDs in order. "
            f"Returned: {returned_ids}, Persisted: {persisted_ids}."
        )

    def test_ingest_many_calls_publish_for_each_record(self) -> None:
        """ingest_many must call publisher.publish once per record (3 events → 3 publishes).

        WHY: Each event must be published to the login_events stream independently
        so the downstream normalization service processes them as separate stream
        messages. Batch-publishing (if even supported) would deviate from the
        per-event XADD contract and break consumer group processing.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        publish_calls = [entry for entry in call_log if entry[0] == "publish"]
        assert len(publish_calls) == 3, (
            f"Expected 3 publish calls (one per event), got {len(publish_calls)}."
        )


# ===========================================================================
# CLASS 5 — ingest_many: publish failure (best-effort per-event)
# ===========================================================================


class TestIngestManyPublishFailure:
    """When publish raises for every record in ingest_many, the service must:
       1. Still attempt publish for all records (best-effort, not short-circuit)
       2. Not propagate the exception

    WHY: Spec §5.5 for bulk: 'publishing is then per-event best-effort with the
    same catch-and-log policy.' Best-effort means: even if record[0] publish fails,
    we still try record[1] and record[2]. Short-circuiting on the first failure
    would leave records[1..n-1] uncommitted in the stream when their PG row exists
    (all were committed in the single batch transaction). The spec explicitly says
    'per-event' so the loop must not abort on a publish failure.
    """

    def test_ingest_many_attempts_publish_for_all_records_even_when_publisher_raises(
        self,
    ) -> None:
        """All 3 publish attempts must be made even when each one raises.

        WHY: 'Best-effort' per the spec means: attempt each record's publish
        independently and catch failures per record. If the loop short-circuits on the
        first publish failure, records 2 and 3 never get their stream message attempted,
        leaving them in a 'committed but not published' state with no retry trigger.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log, should_raise=True),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        publish_calls = [entry for entry in call_log if entry[0] == "publish"]
        assert len(publish_calls) == 3, (
            f"All 3 publish attempts must be made even when every publish raises. "
            f"Got {len(publish_calls)} publish calls. "
            "Spec §5.5: publishing is per-event best-effort; don't short-circuit on failure."
        )

    def test_ingest_many_does_not_propagate_publisher_exception(self) -> None:
        """ingest_many must not propagate the publisher's exception.

        WHY: All records were committed in a single PG transaction. A 500 response
        would be misleading — the events ARE accepted (they are durable in PostgreSQL).
        The spec mandates returning the ids even after publish failure.
        """
        from app.service import IngestionService

        call_log: list = []
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log, should_raise=True),
            logger=_make_fake_logger(),
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]

        try:
            result = asyncio.get_event_loop().run_until_complete(
                service.ingest_many(events)
            )
        except Exception as exc:
            pytest.fail(
                f"ingest_many must not propagate publisher exceptions. "
                f"Got: {type(exc).__name__}: {exc}."
            )

        assert isinstance(result, list) and len(result) == 3, (
            "ingest_many must return 3 UUIDs even when all publishes fail."
        )

    def test_ingest_many_logs_error_for_each_failed_publish(self) -> None:
        """logger.error must be called once per failed publish in ingest_many.

        WHY: Each failed publish represents a potentially missing stream message.
        Logging each failure gives operators full visibility into which event ids
        need replay. Logging only the first failure (or none) would hide the scope
        of the problem.
        """
        from app.service import IngestionService

        call_log: list = []
        logger = _make_fake_logger()
        service = IngestionService(
            repo=FakeRepo(call_log),
            publisher=FakePublisher(call_log, should_raise=True),
            logger=logger,
        )
        events = [_make_event(user_id=f"user{i}") for i in range(3)]
        asyncio.get_event_loop().run_until_complete(service.ingest_many(events))

        assert logger.error.call_count == 3, (
            f"logger.error must be called once per failed publish (3 events). "
            f"Got {logger.error.call_count} error calls."
        )
