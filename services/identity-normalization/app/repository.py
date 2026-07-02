"""PostgreSQL repository for persisting normalized attributes.

Spec §3.1, §5.1 — the consumer loop calls write(event_id, normalized) as the
point-of-no-return step after extraction and enrichment.  The implementation
issues a bare SQLAlchemy UPDATE (no INSERT, no SELECT-before-update) against the
events table owned by event-ingestion's DDL.

WHY UPDATE-only: the event row already exists (written by event-ingestion).
Normalization is an enrichment step that populates normalized_attributes on an
existing row.  A SELECT-before-update would add latency and is unnecessary;
idempotency is guaranteed by the UPDATE semantics (subsequent writes overwrite).
"""

from __future__ import annotations

from uuid import UUID

from naas_shared.logging import get_logger
from naas_shared.models import NormalizedAttributes
from naas_shared.schemas import EventORM
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_logger = get_logger(__name__)


class PostgresNormalizationRepository:
    """Persists normalized attributes to the events table via bare UPDATE.

    Constructed with an async_sessionmaker so the consumer loop — not the
    FastAPI request context — owns the session lifecycle.  One session is
    opened per write() call (and committed before returning) to keep
    transaction scope minimal.

    WHY injected factory: avoids coupling the consumer loop to FastAPI's
    request-scoped get_db_session dependency, which is not valid outside an
    HTTP request context.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """
        Args:
            session_factory: An async_sessionmaker that returns an async context
                manager yielding an AsyncSession when called.  Use
                naas_shared.database.get_session_factory().
        """
        self._session_factory = session_factory

    async def write(self, event_id: UUID, normalized: NormalizedAttributes) -> None:
        """UPDATE events.normalized_attributes for event_id and commit.

        WHY no SELECT: the event row is guaranteed to exist (ingestion wrote it
        before publishing to the stream).  A SELECT-before-update would be wasted
        I/O and would introduce a TOCTOU window.

        WHY no session.add(): SQLAlchemy's add() is for INSERT/merge semantics.
        We issue a targeted UPDATE that touches only the normalized_attributes
        column — no other columns are affected.

        Args:
            event_id:   The UUID primary key of the event row to update.
            normalized: The resolved NormalizedAttributes to persist as JSONB.
        """
        stmt = (
            update(EventORM)
            .where(EventORM.id == event_id)
            .values(normalized_attributes=normalized.model_dump(mode="json"))
        )

        async with self._session_factory() as session:
            await session.execute(stmt)
            await session.commit()

        _logger.debug(
            "normalized_attributes_persisted",
            event_id=str(event_id),
        )
