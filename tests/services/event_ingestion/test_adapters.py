"""OIDC, SAML, and LDAP adapter protocol for event-ingestion (placeholder)."""

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# third-party
import pytest


# ---------------------------------------------------------------------------
# Reference values (project test-data reference values from agent instructions)
# ---------------------------------------------------------------------------

_TEST_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
_TEST_TIMESTAMP = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
_TEST_IP = "192.168.1.1"


def _make_record(**overrides: Any):
    """Build a LoginEventRecord with deterministic values.

    LoginEventRecord has an auto-generated id via uuid4 default.
    We override it with _TEST_UUID for deterministic assertions.
    """
    from naas_shared.models import LoginEventRecord

    defaults = {
        "id": _TEST_UUID,
        "user_id": "alice",
        "client_ip": _TEST_IP,
        "protocol": "oidc",
        "timestamp": _TEST_TIMESTAMP,
        "user_agent": "Mozilla/5.0 (test)",
        "source": "user",
        "is_synthetic": False,
        "is_historical": False,
        "raw_attributes": {"email": "alice@corp.com", "groups": ["engineering"]},
    }
    defaults.update(overrides)
    return LoginEventRecord(**defaults)


def _make_fake_async_session() -> MagicMock:
    """Build a MagicMock that looks like an SQLAlchemy AsyncSession.

    async methods (commit, execute, flush) are AsyncMock.
    sync methods (add, add_all) are plain MagicMock.
    """
    session = MagicMock()
    session.commit = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=MagicMock())
    session.flush = AsyncMock(return_value=None)
    # add and add_all are sync in SQLAlchemy's async session
    session.add = MagicMock()
    session.add_all = MagicMock()
    return session


# ===========================================================================
# CLASS 1 — Import: app.adapters exposes the two adapter classes
# ===========================================================================


class TestAdaptersModuleImport:
    """app/adapters.py must be importable and expose the adapter classes.

    WHY: main.py wires IngestionService(PostgresEventRepository(session),
    RedisEventPublisher(), ...). If either class is missing, the service cannot
    start and every request fails with ImportError.
    """

    def test_postgres_event_repository_is_importable(self) -> None:
        """from app.adapters import PostgresEventRepository must succeed."""
        from app.adapters import PostgresEventRepository  # noqa: F401

    def test_redis_event_publisher_is_importable(self) -> None:
        """from app.adapters import RedisEventPublisher must succeed."""
        from app.adapters import RedisEventPublisher  # noqa: F401

    def test_both_adapters_importable_together(self) -> None:
        """from app.adapters import PostgresEventRepository, RedisEventPublisher."""
        from app.adapters import PostgresEventRepository, RedisEventPublisher  # noqa: F401


# ===========================================================================
# CLASS 2 — PostgresEventRepository: _to_orm mapping contract
# ===========================================================================


class TestPostgresEventRepositoryToORM:
    """PostgresEventRepository must map a LoginEventRecord to an EventORM correctly.

    Spec §§5.3, 3.1: the adapter maps the record fields to the ORM model. The
    mapping must be exact: every field copied from the record must equal the ORM
    column value. Fields left NULL by ingestion (normalized_attributes,
    enriched_signals, created_at) must not be set by the adapter.

    Assumption: _to_orm is accessible as PostgresEventRepository._to_orm (static
    or class method) or as a module-level function called _to_orm in app.adapters.
    We test both access paths; the test passes as long as at least one resolves.
    If neither resolves, the test falls back to observing session.add() behavior
    in persist() to validate the mapping indirectly.
    """

    def _get_to_orm_callable(self):
        """Resolve _to_orm from the adapter class or module.

        Returns the callable, or None if not accessible directly (in which case
        the caller falls back to the persist()-based approach).
        """
        import app.adapters as adapters_mod
        from app.adapters import PostgresEventRepository

        # Try class-level static method first
        if hasattr(PostgresEventRepository, "_to_orm"):
            fn = getattr(PostgresEventRepository, "_to_orm")
            # If it's a classmethod descriptor, call it on the class
            return fn

        # Try module-level function
        if hasattr(adapters_mod, "_to_orm"):
            return adapters_mod._to_orm

        return None

    def test_to_orm_returns_event_orm_instance(self) -> None:
        """_to_orm(record) must return an EventORM instance.

        WHY: session.add() expects a mapped ORM instance. If _to_orm returns a
        dict or a plain object, SQLAlchemy raises a TypeError at the add() call,
        crashing the persist path for every event.
        """
        import asyncio
        from naas_shared.schemas import EventORM

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            assert isinstance(result, EventORM), (
                f"_to_orm must return an EventORM instance, got {type(result).__name__!r}."
            )
        else:
            # Fallback: observe what session.add receives in persist()
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))

            assert session.add.called, "session.add must be called in persist()"
            added_obj = session.add.call_args[0][0]
            assert isinstance(added_obj, EventORM), (
                f"Object passed to session.add must be an EventORM instance, "
                f"got {type(added_obj).__name__!r}."
            )

    def test_to_orm_maps_id_from_record(self) -> None:
        """_to_orm must copy the record's id to the ORM object.

        WHY: The event id is the correlation key for the entire pipeline
        (spec §3.1). If the ORM object gets a different (or freshly generated)
        id, the PG row diverges from the stream message id, breaking every
        downstream consumer that reads the events table by id.
        """
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            assert result.id == record.id, (
                f"ORM id must equal record.id ({record.id}), got {result.id!r}."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.id == record.id, (
                f"ORM id must equal record.id. Got {added_obj.id!r}."
            )

    def test_to_orm_maps_user_id_from_record(self) -> None:
        """_to_orm must copy user_id from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(user_id="bob")

        if to_orm is not None:
            assert to_orm(record).user_id == "bob", (
                "ORM user_id must equal record.user_id."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.user_id == "bob"

    def test_to_orm_maps_protocol_from_record(self) -> None:
        """_to_orm must copy protocol from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(protocol="saml")

        if to_orm is not None:
            assert to_orm(record).protocol == "saml", (
                "ORM protocol must equal record.protocol."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.protocol == "saml"

    def test_to_orm_maps_client_ip_from_record(self) -> None:
        """_to_orm must copy client_ip from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(client_ip="8.8.8.8")

        if to_orm is not None:
            assert to_orm(record).client_ip == "8.8.8.8", (
                "ORM client_ip must equal record.client_ip."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.client_ip == "8.8.8.8"

    def test_to_orm_maps_timestamp_from_record(self) -> None:
        """_to_orm must copy timestamp from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            assert result.timestamp == _TEST_TIMESTAMP, (
                f"ORM timestamp must equal record.timestamp ({_TEST_TIMESTAMP}), "
                f"got {result.timestamp!r}."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.timestamp == _TEST_TIMESTAMP

    def test_to_orm_maps_source_from_record(self) -> None:
        """_to_orm must copy source from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(source="simulator")

        if to_orm is not None:
            assert to_orm(record).source == "simulator", (
                "ORM source must equal record.source."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.source == "simulator"

    def test_to_orm_maps_is_synthetic_from_record(self) -> None:
        """_to_orm must copy is_synthetic from the record to the ORM object."""
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(is_synthetic=True)

        if to_orm is not None:
            assert to_orm(record).is_synthetic is True, (
                "ORM is_synthetic must equal record.is_synthetic."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.is_synthetic is True

    def test_to_orm_maps_is_historical_from_record(self) -> None:
        """_to_orm must copy is_historical from the record to the ORM object.

        WHY: is_historical is a critical safety flag — historical events must never
        trigger alerts. If it is not mapped correctly, the alert service may fire
        on historical replay data. This is a security invariant in the NAAS pipeline.
        """
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record(is_historical=True)

        if to_orm is not None:
            assert to_orm(record).is_historical is True, (
                "ORM is_historical must equal record.is_historical. "
                "This flag prevents alerts from firing on historical replay events."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.is_historical is True

    def test_to_orm_maps_raw_attributes_from_record(self) -> None:
        """_to_orm must copy raw_attributes from the record to the ORM object.

        WHY: raw_attributes is the opaque protocol-specific payload that downstream
        services (identity normalization) read from the PostgreSQL row. If it is
        not stored, the normalization service has no data to work from.
        """
        import asyncio

        payload = {"email": "test@corp.com", "groups": ["admin"]}
        to_orm = self._get_to_orm_callable()
        record = _make_record(raw_attributes=payload)

        if to_orm is not None:
            result = to_orm(record)
            assert result.raw_attributes == payload, (
                f"ORM raw_attributes must equal record.raw_attributes. "
                f"Got: {result.raw_attributes!r}."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.raw_attributes == payload

    def test_to_orm_leaves_normalized_attributes_unset(self) -> None:
        """_to_orm must NOT set normalized_attributes on the ORM object.

        WHY: Spec §3.1 explicitly states 'normalized_attributes: NULL at ingestion.
        Populated by Identity Normalization.' If ingestion sets this column,
        the normalization service would find pre-existing data and might skip
        normalization or silently overwrite it. The column must be None/unset
        at ingestion time.
        """
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            assert result.normalized_attributes is None, (
                f"_to_orm must leave normalized_attributes as None. "
                f"Got: {result.normalized_attributes!r}. "
                "Spec §3.1: normalized_attributes is NULL at ingestion."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.normalized_attributes is None

    def test_to_orm_leaves_enriched_signals_unset(self) -> None:
        """_to_orm must NOT set enriched_signals on the ORM object.

        WHY: Spec §3.1 states 'enriched_signals: NULL at ingestion. Populated by
        Signal Enrichment.' Signal enrichment is a later pipeline stage; ingestion
        must not populate this column.
        """
        import asyncio

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            assert result.enriched_signals is None, (
                f"_to_orm must leave enriched_signals as None. "
                f"Got: {result.enriched_signals!r}. "
                "Spec §3.1: enriched_signals is NULL at ingestion."
            )
        else:
            from app.adapters import PostgresEventRepository

            session = _make_fake_async_session()
            repo = PostgresEventRepository(session=session)
            asyncio.get_event_loop().run_until_complete(repo.persist(record))
            added_obj = session.add.call_args[0][0]
            assert added_obj.enriched_signals is None

    def test_to_orm_leaves_created_at_unset(self) -> None:
        """_to_orm must NOT set created_at on the ORM object.

        WHY: Spec §3.1 states 'created_at: DB default (CURRENT_TIMESTAMP).
        Ingestion timestamp. Do not set it from the app.' If the app sets
        created_at, it bypasses the database's default and may produce incorrect
        timestamps (e.g., if the app clock drifts from the DB clock, or if the
        ORM model sets a Python default instead of the DB server_default).
        """

        to_orm = self._get_to_orm_callable()
        record = _make_record()

        if to_orm is not None:
            result = to_orm(record)
            # created_at should be None (not set by the adapter; server_default handles it)
            # Note: SQLAlchemy may have a sentinel value vs None; we check for None only.
            assert result.created_at is None, (
                f"_to_orm must leave created_at as None (DB server_default sets it). "
                f"Got: {result.created_at!r}. "
                "Spec §3.1: 'Do not set it from the app.'"
            )
        else:
            # In the fallback path, we cannot easily check created_at is unset
            # on the ORM object without knowing SQLAlchemy's sentinel. We skip.
            pytest.skip(
                "_to_orm not directly accessible; created_at assertion requires direct access."
            )


# ===========================================================================
# CLASS 3 — PostgresEventRepository.persist session interaction
# ===========================================================================


class TestPostgresEventRepositoryPersist:
    """PostgresEventRepository.persist must call session.add() and session.commit().

    WHY: The spec §5.3 explicitly shows:
        self._session.add(_to_orm(record))
        await self._session.commit()
    The explicit commit in persist() is the durability point (spec §5.5).
    Without await commit(), the row is staged in the SQLAlchemy session but not
    flushed to PostgreSQL — a crash before the implicit end-of-request commit
    would lose the event.
    """

    def test_persist_calls_session_add_once(self) -> None:
        """persist(record) must call session.add() exactly once.

        WHY: add() stages the ORM object for INSERT. Zero calls = event not saved.
        Multiple calls = duplicate rows (UQ violation on the PK or silent data bloat).
        """
        import asyncio
        from app.adapters import PostgresEventRepository

        session = _make_fake_async_session()
        repo = PostgresEventRepository(session=session)
        asyncio.get_event_loop().run_until_complete(repo.persist(_make_record()))

        assert session.add.call_count == 1, (
            f"session.add must be called exactly once in persist(). "
            f"Got {session.add.call_count} calls."
        )

    def test_persist_calls_session_commit_once(self) -> None:
        """persist(record) must call session.commit() exactly once.

        WHY: The explicit commit in persist() is the durability point (spec §5.5).
        Zero commits = the INSERT is not durable (lost on crash). Multiple commits =
        extra round-trips and potential transaction-state confusion.
        """
        import asyncio
        from app.adapters import PostgresEventRepository

        session = _make_fake_async_session()
        repo = PostgresEventRepository(session=session)
        asyncio.get_event_loop().run_until_complete(repo.persist(_make_record()))

        assert session.commit.call_count == 1, (
            f"session.commit must be called exactly once in persist(). "
            f"Got {session.commit.call_count} calls."
        )


# ===========================================================================
# CLASS 4 — PostgresEventRepository.persist_many session interaction
# ===========================================================================


class TestPostgresEventRepositoryPersistMany:
    """PostgresEventRepository.persist_many must use add_all + a single commit.

    WHY: The spec §5.3 shows:
        self._session.add_all([_to_orm(r) for r in records])
        await self._session.commit()
    add_all batches the INSERT for efficiency. A single commit wraps the whole
    batch in one transaction (all-or-nothing per spec §5.5).
    """

    def test_persist_many_calls_session_add_all_once(self) -> None:
        """persist_many([r1,r2,r3]) must call session.add_all() exactly once.

        WHY: add_all() sends all ORM objects in a single batch, enabling efficient
        multi-row INSERT. Multiple add_all() calls or individual add() calls would
        split the batch into separate statements, defeating the atomicity guarantee.
        """
        import asyncio
        from app.adapters import PostgresEventRepository

        session = _make_fake_async_session()
        repo = PostgresEventRepository(session=session)
        records = [_make_record(user_id=f"user{i}", id=uuid.uuid4()) for i in range(3)]
        asyncio.get_event_loop().run_until_complete(repo.persist_many(records))

        assert session.add_all.call_count == 1, (
            f"session.add_all must be called exactly once in persist_many(). "
            f"Got {session.add_all.call_count} calls."
        )

    def test_persist_many_passes_correct_number_of_orm_objects_to_add_all(
        self,
    ) -> None:
        """persist_many([r1,r2,r3]) must pass a list of 3 ORM objects to add_all().

        WHY: If fewer ORM objects are passed, some events are silently not inserted.
        If more are passed, spurious duplicate rows appear.
        """
        import asyncio
        from naas_shared.schemas import EventORM
        from app.adapters import PostgresEventRepository

        session = _make_fake_async_session()
        repo = PostgresEventRepository(session=session)
        records = [_make_record(user_id=f"user{i}", id=uuid.uuid4()) for i in range(3)]
        asyncio.get_event_loop().run_until_complete(repo.persist_many(records))

        orm_list_arg = session.add_all.call_args[0][0]
        assert len(orm_list_arg) == 3, (
            f"add_all must receive 3 ORM objects for 3 records, got {len(orm_list_arg)}."
        )
        for i, obj in enumerate(orm_list_arg):
            assert isinstance(obj, EventORM), (
                f"Object at index {i} passed to add_all must be an EventORM instance, "
                f"got {type(obj).__name__!r}."
            )

    def test_persist_many_calls_session_commit_once(self) -> None:
        """persist_many must call session.commit() exactly once (one transaction).

        WHY: A single commit for the whole batch is the all-or-nothing guarantee.
        Per-record commits would mean N transactions, each of which could independently
        fail, leaving the batch partially committed. The spec §5.5 states:
        'any insert failure rolls back the whole batch' — a single transaction makes
        this possible.
        """
        import asyncio
        from app.adapters import PostgresEventRepository

        session = _make_fake_async_session()
        repo = PostgresEventRepository(session=session)
        records = [_make_record(user_id=f"user{i}", id=uuid.uuid4()) for i in range(3)]
        asyncio.get_event_loop().run_until_complete(repo.persist_many(records))

        assert session.commit.call_count == 1, (
            f"session.commit must be called exactly once in persist_many(). "
            f"Got {session.commit.call_count} calls. "
            "A single commit wraps the whole batch in one transaction."
        )


# ===========================================================================
# CLASS 5 — RedisEventPublisher.publish: stream publish contract
# ===========================================================================


class TestRedisEventPublisherPublish:
    """RedisEventPublisher.publish must call publish_to_stream with the correct args.

    Spec §5.3: 'publish calls await publish_to_stream(STREAM_LOGIN_EVENTS,
    record.model_dump(mode="json"))'

    Spec §3.2: The published payload is a LoginEventRecord serialized to JSON and
    MUST carry 'id' (the correlation key). The 'id' in the JSON must be a STRING
    (not a UUID object) because JSON has no native UUID type — consumers parse the
    JSON and reconstruct the UUID from the string.

    We patch 'app.adapters.publish_to_stream' (the name as imported in adapters.py).
    If the implementer imports it differently (e.g., keeps a reference via the module),
    we also patch 'naas_shared.redis_client.publish_to_stream' as a fallback note.
    """

    def test_publish_calls_publish_to_stream_once(self) -> None:
        """RedisEventPublisher.publish must call publish_to_stream exactly once.

        WHY: Each event produces exactly one stream message. Zero calls = event
        not in the pipeline (normalization never processes it). Multiple calls =
        duplicate stream messages → duplicate downstream processing.
        """
        import asyncio
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        assert mock_pts.call_count == 1, (
            f"publish_to_stream must be called exactly once per publish() call. "
            f"Got {mock_pts.call_count} calls."
        )

    def test_publish_calls_publish_to_stream_with_stream_login_events_as_first_arg(
        self,
    ) -> None:
        """publish must pass STREAM_LOGIN_EVENTS as the first arg to publish_to_stream.

        WHY: The shared constant STREAM_LOGIN_EVENTS = 'login_events' is the agreed
        stream name for the pipeline's first stage. If a hardcoded string is used
        instead, a constant rename would silently break routing. More critically, if
        the wrong stream name is used (e.g., 'normalized_events'), events would skip
        the normalization stage entirely.
        """
        import asyncio
        from naas_shared.constants import STREAM_LOGIN_EVENTS
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        stream_arg = mock_pts.call_args[0][0]
        assert stream_arg == STREAM_LOGIN_EVENTS, (
            f"First arg to publish_to_stream must be STREAM_LOGIN_EVENTS "
            f"('{STREAM_LOGIN_EVENTS}'), got {stream_arg!r}."
        )

    def test_publish_calls_publish_to_stream_with_dict_as_second_arg(self) -> None:
        """publish must pass a dict as the second arg to publish_to_stream.

        WHY: publish_to_stream(stream, data) expects `data` to be a dict
        (it JSON-encodes it internally). Passing the LoginEventRecord object
        directly would cause a TypeError in publish_to_stream because Pydantic
        models are not JSON-serializable by json.dumps without mode='json'.
        The adapter must call record.model_dump(mode='json') first.
        """
        import asyncio
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        data_arg = mock_pts.call_args[0][1]
        assert isinstance(data_arg, dict), (
            f"Second arg to publish_to_stream must be a dict (from model_dump(mode='json')). "
            f"Got {type(data_arg).__name__!r}."
        )

    def test_publish_payload_contains_id_key(self) -> None:
        """The dict passed to publish_to_stream must contain an 'id' key.

        WHY: Spec §3.2 states the published payload 'MUST carry id (the correlation
        key downstream uses to locate the row it just read)'. Consumers on the
        login_events stream (identity normalization) use this id to look up the
        event row by PK. A missing id makes the stream message useless.
        """
        import asyncio
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        data_arg = mock_pts.call_args[0][1]
        assert "id" in data_arg, (
            f"Published payload dict must contain an 'id' key. "
            f"Got keys: {list(data_arg.keys())}. "
            "Spec §3.2: the payload MUST carry 'id'."
        )

    def test_publish_payload_id_is_a_string(self) -> None:
        """The 'id' value in the published payload dict must be a string.

        WHY: JSON has no native UUID type. model_dump(mode='json') serializes UUID
        objects to strings. If the implementer uses model_dump() without mode='json',
        the 'id' value would be a UUID object, which json.dumps cannot serialize
        (it would raise TypeError inside publish_to_stream). Consumers also expect
        a string id to reconstruct the UUID from.
        """
        import asyncio
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        data_arg = mock_pts.call_args[0][1]
        id_value = data_arg.get("id")
        assert isinstance(id_value, str), (
            f"Published payload 'id' must be a string (from model_dump(mode='json')). "
            f"Got {type(id_value).__name__!r}: {id_value!r}. "
            "Use record.model_dump(mode='json') to ensure UUID → str conversion."
        )

    def test_publish_payload_id_matches_record_id(self) -> None:
        """The 'id' string in the published payload must equal str(record.id).

        WHY: The correlation key on the stream must identify the exact PG row.
        If the id is wrong (different UUID), downstream consumers look up the
        wrong row (or no row), silently processing the wrong event or failing.
        """
        import asyncio
        from app.adapters import RedisEventPublisher

        record = _make_record()
        with patch("app.adapters.publish_to_stream", new=AsyncMock()) as mock_pts:
            publisher = RedisEventPublisher()
            asyncio.get_event_loop().run_until_complete(publisher.publish(record))

        data_arg = mock_pts.call_args[0][1]
        assert data_arg["id"] == str(record.id), (
            f"Published 'id' must equal str(record.id) = {str(record.id)!r}. "
            f"Got: {data_arg['id']!r}."
        )
