"""Domain orchestration for the Event Ingestion Service dual-write.

IngestionService is the only place that knows the dual-write order and failure
policy (spec §5.4, §5.5):
  1. Persist to PostgreSQL first and commit (point of no return).
  2. Publish to the login_events Redis Stream (best-effort, catch-and-log).

The route handlers call this service; they never perform the dual-write directly.
"""

from uuid import UUID

import structlog
from naas_shared.models import LoginEventIngest, LoginEventRecord

from app.ports import EventPublisher, EventRepository


class IngestionService:
    """Orchestrates the persist-then-publish dual-write for login events.

    Constructor arguments are injected by the FastAPI dependency (routes.py),
    allowing fakes to be substituted in tests without any mocking framework.
    """

    def __init__(
        self,
        repo: EventRepository,
        publisher: EventPublisher,
        logger: structlog.BoundLogger,
    ) -> None:
        self._repo = repo
        self._publisher = publisher
        self._log = logger

    async def ingest_one(self, event: LoginEventIngest) -> UUID:
        """Dual-write a single login event.  Returns the assigned event id.

        The UUID is assigned app-side via LoginEventRecord's uuid4 default so
        the same id is written to both PostgreSQL and the stream message.
        """
        record = LoginEventRecord(**event.model_dump())
        await self._repo.persist(record)
        await self._safe_publish(record)
        return record.id

    async def ingest_many(self, events: list[LoginEventIngest]) -> list[UUID]:
        """Dual-write a batch of login events.  Returns ids in input order.

        persist_many wraps all INSERTs in one transaction (all-or-nothing).
        Publishing is per-event best-effort: a failure on one record does not
        prevent the publish attempt for the remaining records (spec §5.5).
        """
        records = [LoginEventRecord(**e.model_dump()) for e in events]
        await self._repo.persist_many(records)
        for r in records:
            await self._safe_publish(r)
        return [r.id for r in records]

    async def _safe_publish(self, record: LoginEventRecord) -> None:
        """Attempt to publish the event; catch and log any failure.

        A committed event is an accepted event (spec §5.5 step 4).  If publish
        fails, the durable row already exists in PostgreSQL and is replayable.
        We must NOT re-raise — doing so would cause the caller to return 5xx,
        which would prompt the client to retry and create a duplicate row.
        """
        try:
            await self._publisher.publish(record)
        except Exception:  # noqa: BLE001 — committed row is replayable; publish failure must not re-raise (spec §5.5)
            self._log.error(
                "login_events publish failed",
                event_id=str(record.id),
                exc_info=True,
            )
