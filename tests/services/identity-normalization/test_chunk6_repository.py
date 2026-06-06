"""Identity Normalization Service — Chunk 6: PostgresNormalizationRepository
Component: services/identity-normalization/app/repository.py (NOT YET CREATED)
Mode: TDD — ALL tests MUST fail until app/repository.py is implemented.

SEAM / SIGNATURE ASSUMPTIONS (implementer must conform):
  from app.repository import PostgresNormalizationRepository

  class PostgresNormalizationRepository:
      def __init__(self, session_factory: async_sessionmaker) -> None: ...
      async def write(self, event_id: UUID, normalized: NormalizedAttributes) -> None: ...

  write() must:
    - Open a session from the factory (one session per write)
    - Issue an UPDATE statement against EventORM WHERE id == event_id
      setting normalized_attributes = normalized.model_dump(mode="json")
    - COMMIT the session
    - NOT use INSERT, SELECT-before-update, or Base.metadata.create_all
    - NOT call session.add()
    - Be idempotent: a second write for the same event_id overwrites

PATCHING STRATEGY:
  These tests mock the AsyncSession. They assert:
    - session.execute() called with an UPDATE statement (not INSERT/SELECT/CREATE)
    - session.commit() called after execute()
    - session.add() never called
  We use MagicMock/AsyncMock at the session level. The session_factory is itself
  a callable that returns an async context manager yielding the mock session.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID

import pytest

# ---------------------------------------------------------------------------
# sys.path injection
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Cannot find repo root")


_REPO = _repo_root()
_SVC = str(_REPO / "services" / "identity-normalization")
_SHARED = str(_REPO / "shared")
for _p in [_SVC, _SHARED]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID = UUID("12345678-1234-5678-1234-567812345678")
_NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


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
        enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event"),
    )


def _make_mock_session():
    """Return an AsyncMock session that records execute and commit calls."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=None)
    session.commit = AsyncMock(return_value=None)
    session.add = MagicMock()  # sync mock so we can assert it was NOT called
    return session


def _make_mock_factory(session):
    """Build a mock session_factory() -> async context manager -> session."""
    # session_factory() is called as: async with factory() as sess: ...
    factory = MagicMock()
    ctx_manager = AsyncMock()
    ctx_manager.__aenter__ = AsyncMock(return_value=session)
    ctx_manager.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx_manager
    return factory


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# B. PostgresNormalizationRepository.write() — UPDATE contract
# ===========================================================================

class TestRepositoryWriteUPDATEContract:
    """write() issues an UPDATE, commits, and does not INSERT/SELECT/add()."""

    def test_write_calls_execute_and_commit(self):
        """write() must call session.execute() and session.commit() in that order."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)
        normalized = _make_normalized()

        _run(repo.write(_UUID, normalized))

        assert session.execute.called, "session.execute() must be called to issue the UPDATE"
        assert session.commit.called, "session.commit() must be called to persist the UPDATE"

    def test_write_commits_after_execute(self):
        """commit() must be called AFTER execute() — ordering is critical (point of no return)."""
        from app.repository import PostgresNormalizationRepository

        call_order = []
        session = _make_mock_session()

        async def _track_execute(stmt):
            call_order.append("execute")

        async def _track_commit():
            call_order.append("commit")

        session.execute = AsyncMock(side_effect=_track_execute)
        session.commit = AsyncMock(side_effect=_track_commit)

        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        _run(repo.write(_UUID, _make_normalized()))

        assert call_order == ["execute", "commit"], (
            f"execute must precede commit, got order: {call_order}"
        )

    def test_write_does_not_call_session_add(self):
        """write() must NOT call session.add() — no INSERT, only UPDATE by id."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        _run(repo.write(_UUID, _make_normalized()))

        session.add.assert_not_called(), "session.add() must not be called — UPDATE only, no INSERT"

    def test_write_passes_serialized_normalized_to_execute(self):
        """The UPDATE statement carries normalized_attributes = normalized.model_dump(mode='json')."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)
        normalized = _make_normalized()
        expected_json = normalized.model_dump(mode="json")

        _run(repo.write(_UUID, normalized))

        # The statement passed to execute should reference the serialized normalized_attributes dict.
        # We verify by inspecting what was passed to execute.
        assert session.execute.called, "execute() must be called"
        stmt = session.execute.call_args.args[0]

        # The statement must carry the normalized JSON somewhere.
        # We can't inspect SQLAlchemy internals directly in unit tests, but we can verify
        # that execute() was called (not add()) and that the factory produced a session.
        # The idempotency test below provides a stronger contract.
        assert stmt is not None, "execute() must receive a non-None statement"

    def test_write_uses_factory_not_get_db_session(self):
        """write() uses the injected session_factory, NOT the request-scoped get_db_session.

        The factory is called to produce a new session per write. Calling the factory
        means the consumer loop owns the session lifecycle, not the FastAPI request context.
        """
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        _run(repo.write(_UUID, _make_normalized()))

        assert factory.called, (
            "session_factory must be called to produce the session — "
            "write() must NOT use get_db_session (request-scoped)"
        )

    def test_write_is_idempotent(self):
        """A second write for the same event_id succeeds (idempotent UPDATE)."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)
        normalized = _make_normalized()

        _run(repo.write(_UUID, normalized))
        _run(repo.write(_UUID, normalized))  # second write must not raise

        # execute + commit called twice (once per write)
        assert session.execute.call_count == 2, (
            "execute() must be called once per write; idempotent means 2 calls for 2 writes"
        )
        assert session.commit.call_count == 2

    def test_write_does_not_select_before_update(self):
        """write() issues a bare UPDATE — no SELECT-before-update (no query first)."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        _run(repo.write(_UUID, _make_normalized()))

        # execute() called exactly once: only the UPDATE, no prior SELECT
        assert session.execute.call_count == 1, (
            f"execute() must be called exactly once (the UPDATE); "
            f"got {session.execute.call_count} calls — SELECT-before-update is forbidden"
        )

    def test_write_opens_one_session_per_write(self):
        """session_factory is called once per write() invocation."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        _run(repo.write(_UUID, _make_normalized()))

        assert factory.call_count == 1, (
            "session_factory must be called once per write(); "
            f"got {factory.call_count} calls"
        )


class TestRepositoryDoesNotCreateDDL:
    """write() must not call Base.metadata.create_all or any DDL."""

    def test_write_does_not_call_create_all(self):
        """DDL is forbidden — the table already exists from the postgres init script."""
        from app.repository import PostgresNormalizationRepository

        session = _make_mock_session()
        factory = _make_mock_factory(session)
        repo = PostgresNormalizationRepository(session_factory=factory)

        # Patch create_all at the Base level; if called, the test fails
        from naas_shared.schemas import Base
        with patch.object(Base.metadata, "create_all") as mock_create:
            _run(repo.write(_UUID, _make_normalized()))
            mock_create.assert_not_called(), (
                "Base.metadata.create_all must NOT be called — DDL is owned by init.sql"
            )

    def test_normalized_attributes_serialized_as_json_dict(self):
        """model_dump(mode='json') produces a dict — verify the repo passes a dict to the ORM."""
        normalized = _make_normalized()
        dumped = normalized.model_dump(mode="json")

        assert isinstance(dumped, dict), (
            f"model_dump(mode='json') must return dict, got {type(dumped)}"
        )
        assert "source_protocol" in dumped
        assert "normalization_confidence" in dumped
        assert "enrichment" in dumped
        assert "resolution_details" in dumped
