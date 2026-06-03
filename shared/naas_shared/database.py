from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from naas_shared.config import get_settings

_engine = None
_session_factory = None


def get_engine():
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


async def get_db_session() -> AsyncSession:
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
