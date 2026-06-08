"""Service port configuration and Docker Compose port mapping for event-ingestion."""

import inspect
import typing

# third-party


# ===========================================================================
# CLASS 1 — Import: app.ports exposes EventRepository and EventPublisher
# ===========================================================================


class TestPortsModuleImport:
    """app/ports.py must be importable and expose the two port Protocols.

    WHY: Without a clean import the service cannot start (main.py imports ports
    to build the dependency injection wiring); an import failure surfaces here
    directly rather than as a confusing collection error.
    """

    def test_event_repository_is_importable(self) -> None:
        """from app.ports import EventRepository must succeed.

        WHY: EventRepository is the persistence boundary. The IngestionService,
        PostgresEventRepository adapter, and tests all import it from this module.
        Missing it means the service cannot wire its dependencies.
        """
        from app.ports import EventRepository  # noqa: F401

    def test_event_publisher_is_importable(self) -> None:
        """from app.ports import EventPublisher must succeed.

        WHY: EventPublisher is the stream-publish boundary. The IngestionService
        and RedisEventPublisher adapter both reference this Protocol.
        """
        from app.ports import EventPublisher  # noqa: F401

    def test_both_ports_importable_in_single_statement(self) -> None:
        """from app.ports import EventRepository, EventPublisher must succeed together.

        WHY: app/main.py, app/service.py, and app/adapters.py all import both symbols
        in a single import line. If either is missing, all three modules break.
        """
        from app.ports import EventPublisher, EventRepository  # noqa: F401


# ===========================================================================
# CLASS 2 — Structural: both ports are typing.Protocol classes
# ===========================================================================


class TestPortsAreProtocols:
    """EventRepository and EventPublisher must both be typing.Protocol subclasses.

    WHY: The spec §5.2 explicitly states 'as typing.Protocol classes'. Protocol
    structural subtyping is what allows FakeRepo and FakePublisher in tests to
    satisfy the port contract without inheriting from it. Using a plain class or
    ABC instead would require test doubles to inherit, coupling the test to the
    implementation class hierarchy and making mocking harder.
    """

    def test_event_repository_is_a_protocol(self) -> None:
        """EventRepository must be a typing.Protocol subclass.

        WHY: Structural typing via Protocol is required so that any class
        implementing the correct method signatures satisfies the port — no
        explicit subclassing needed. The IngestionService only depends on the
        Protocol-defined interface, not on any specific adapter class.
        """
        from app.ports import EventRepository

        # typing.Protocol stores runtime_checkable metadata and inherits from Protocol.
        # We check the MRO for Protocol membership.
        assert typing.Protocol in EventRepository.__mro__, (
            f"EventRepository must be a typing.Protocol subclass. "
            f"MRO is: {[c.__name__ for c in EventRepository.__mro__]}"
        )

    def test_event_publisher_is_a_protocol(self) -> None:
        """EventPublisher must be a typing.Protocol subclass.

        WHY: Same reasoning as EventRepository — structural subtyping is required
        for the hexagonal architecture to be testable with fake adapters.
        """
        from app.ports import EventPublisher

        assert typing.Protocol in EventPublisher.__mro__, (
            f"EventPublisher must be a typing.Protocol subclass. "
            f"MRO is: {[c.__name__ for c in EventPublisher.__mro__]}"
        )


# ===========================================================================
# CLASS 3 — Interface: EventRepository declares the required async methods
# ===========================================================================


class TestEventRepositoryInterface:
    """EventRepository must declare exactly the methods specified in §5.2.

    WHY: The IngestionService calls repo.persist(record) and
    repo.persist_many(records). If these methods are missing from the Protocol,
    the type checker and the service both break. The methods must be async
    (they perform I/O against PostgreSQL) — a sync signature would cause
    'object is not awaitable' errors at runtime.
    """

    def test_event_repository_has_persist_method(self) -> None:
        """EventRepository must declare a `persist` method.

        WHY: IngestionService.ingest_one() calls `await self._repo.persist(record)`.
        A missing persist method makes IngestionService fail at construction or at
        first call with AttributeError.
        """
        from app.ports import EventRepository

        assert hasattr(EventRepository, "persist"), (
            "EventRepository must declare a 'persist' method per spec §5.2."
        )

    def test_event_repository_has_persist_many_method(self) -> None:
        """EventRepository must declare a `persist_many` method.

        WHY: IngestionService.ingest_many() calls `await self._repo.persist_many(records)`.
        A missing persist_many method breaks the bulk ingest path entirely.
        """
        from app.ports import EventRepository

        assert hasattr(EventRepository, "persist_many"), (
            "EventRepository must declare a 'persist_many' method per spec §5.2."
        )

    def test_event_repository_persist_is_coroutine_function(self) -> None:
        """EventRepository.persist must be an async method (coroutine function).

        WHY: Persistence against PostgreSQL is always async I/O in this service
        (SQLAlchemy async engine). A sync signature causes 'object is not awaitable'
        when IngestionService calls `await self._repo.persist(record)`.
        """
        from app.ports import EventRepository

        assert inspect.iscoroutinefunction(EventRepository.persist), (
            "EventRepository.persist must be an async method (coroutine function)."
        )

    def test_event_repository_persist_many_is_coroutine_function(self) -> None:
        """EventRepository.persist_many must be an async method (coroutine function).

        WHY: Same reasoning as persist — all SQLAlchemy calls use the async session,
        which requires await. A sync persist_many would block the event loop.
        """
        from app.ports import EventRepository

        assert inspect.iscoroutinefunction(EventRepository.persist_many), (
            "EventRepository.persist_many must be an async method (coroutine function)."
        )


# ===========================================================================
# CLASS 4 — Interface: EventPublisher declares the required async method
# ===========================================================================


class TestEventPublisherInterface:
    """EventPublisher must declare exactly the methods specified in §5.2.

    WHY: IngestionService._safe_publish() calls `await self._publisher.publish(record)`.
    The method must be async because publish_to_stream is itself an async function
    (it performs a Redis XADD over the network).
    """

    def test_event_publisher_has_publish_method(self) -> None:
        """EventPublisher must declare a `publish` method.

        WHY: IngestionService._safe_publish() calls `await self._publisher.publish(record)`.
        Missing this method causes AttributeError at runtime.
        """
        from app.ports import EventPublisher

        assert hasattr(EventPublisher, "publish"), (
            "EventPublisher must declare a 'publish' method per spec §5.2."
        )

    def test_event_publisher_publish_is_coroutine_function(self) -> None:
        """EventPublisher.publish must be an async method (coroutine function).

        WHY: publish_to_stream (the underlying helper) is async; therefore
        EventPublisher.publish must be async too. A sync wrapper would cause
        'object is not awaitable' in _safe_publish.
        """
        from app.ports import EventPublisher

        assert inspect.iscoroutinefunction(EventPublisher.publish), (
            "EventPublisher.publish must be an async method (coroutine function)."
        )
