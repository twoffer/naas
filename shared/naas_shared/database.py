from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from naas_shared.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return (or lazily create) the shared async SQLAlchemy engine.

    Module-level singleton so all coroutines share the same connection pool.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            # asyncpg forwards server_settings as Postgres connection params; this
            # pins every pooled session's TZ to UTC so TIMESTAMPTZ round-trips are
            # deterministic regardless of host/image timezone. Do NOT flatten to
            # connect_args={"timezone": "UTC"} — asyncpg-under-SQLAlchemy rejects
            # that as a connect kwarg and raises on first connection.
            connect_args={"server_settings": {"timezone": "UTC"}},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return (or lazily create) the shared async session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for DB sessions.

    Yields a session, commits on clean exit, rolls back on exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Dispose the engine and reset the module singletons.

    For service lifespan shutdown. Safe to call when never initialized.
    Disposes the connection pool so all pooled connections are closed cleanly.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
