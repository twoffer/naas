"""Port Protocol definitions for the Event Ingestion Service.

Defines the two abstract boundaries the domain depends on — EventRepository
(persistence) and EventPublisher (stream transport).  Using typing.Protocol
enables structural subtyping so test fakes and real adapters both satisfy the
ports without inheriting from any concrete base class.
"""

from typing import Protocol

from naas_shared.models import LoginEventRecord


class EventRepository(Protocol):
    """Persistence boundary: write login events to the system of record.

    Implementations MUST commit explicitly (PostgreSQL) so the caller knows
    the write is durable before the publish step (spec §5.5).
    """

    async def persist(self, record: LoginEventRecord) -> None:
        """Persist a single event and commit."""
        ...

    async def persist_many(self, records: list[LoginEventRecord]) -> None:
        """Persist a batch of events in a single all-or-nothing transaction."""
        ...


class EventPublisher(Protocol):
    """Transport boundary: publish a login event to the stream pipeline.

    publish() is best-effort — callers (IngestionService._safe_publish) catch
    any exception from this method and log it without re-raising (spec §5.5).
    """

    async def publish(self, record: LoginEventRecord) -> None:
        """Publish the event to the login_events Redis Stream."""
        ...
