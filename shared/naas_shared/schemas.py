"""SQLAlchemy 2.0 ORM table definitions for the NAAS project.

EventORM maps the `events` table created by infrastructure/postgres/init.sql.
This module is a read/write mapping over an existing schema — do not call
Base.metadata.create_all here; the DDL is owned by the init script.
"""

from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all NAAS ORM models."""

    pass


class EventORM(Base):
    """ORM mapping for the `events` table.

    Every column mirrors the DDL in infrastructure/postgres/init.sql exactly.
    Columns left NULL by ingestion (normalized_attributes, enriched_signals)
    are declared nullable=True so that INSERT succeeds without them.
    """

    __tablename__ = "events"

    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)
    client_ip: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_historical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enriched_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
