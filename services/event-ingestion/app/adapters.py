"""Concrete adapters for the Event Ingestion Service ports.

PostgresEventRepository — implements EventRepository over an async SQLAlchemy
    session.  The explicit commit in persist() / persist_many() is the
    durability point before the stream publish (spec §5.5).

RedisEventPublisher — implements EventPublisher by calling the shared
    publish_to_stream helper, which performs a Redis XADD with maxlen capping.

_to_orm is a module-level helper; tests access it directly via
    `app.adapters._to_orm`.
"""

from naas_shared.constants import STREAM_LOGIN_EVENTS
from naas_shared.models import LoginEventRecord
from naas_shared.redis_client import publish_to_stream
from naas_shared.schemas import EventORM
from sqlalchemy.ext.asyncio import AsyncSession


def _to_orm(record: LoginEventRecord) -> EventORM:
    """Map a LoginEventRecord to an EventORM instance for insertion.

    Only the fields owned by ingestion are set (spec §3.1).  The columns
    populated by later pipeline stages — normalized_attributes,
    enriched_signals, and the DB-default created_at — are intentionally
    left unset so they remain NULL / use the server_default.
    """
    return EventORM(
        id=record.id,
        user_id=record.user_id,
        protocol=record.protocol,
        client_ip=record.client_ip,
        user_agent=record.user_agent,
        timestamp=record.timestamp,
        source=record.source,
        is_synthetic=record.is_synthetic,
        is_historical=record.is_historical,
        raw_attributes=record.raw_attributes,
    )


class PostgresEventRepository:
    """Persistence adapter: writes login events to the PostgreSQL events table.

    The explicit commit after each add / add_all is required — it is the
    durability point (spec §5.5 step 1).  The get_db_session dependency's
    end-of-request commit then becomes a harmless no-op.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist(self, record: LoginEventRecord) -> None:
        """Persist a single event and commit (durability point)."""
        self._session.add(_to_orm(record))
        await self._session.commit()

    async def persist_many(self, records: list[LoginEventRecord]) -> None:
        """Persist a batch in one all-or-nothing transaction."""
        self._session.add_all([_to_orm(r) for r in records])
        await self._session.commit()


class RedisEventPublisher:
    """Transport adapter: publishes login events to the login_events Redis Stream.

    Uses the shared publish_to_stream helper (XADD with maxlen capping).
    model_dump(mode='json') serializes UUID → str so the payload is JSON-safe
    and the stream message carries the 'id' correlation key (spec §3.2).
    """

    async def publish(self, record: LoginEventRecord) -> None:
        """Publish the event payload to the login_events stream."""
        await publish_to_stream(STREAM_LOGIN_EVENTS, record.model_dump(mode="json"))
