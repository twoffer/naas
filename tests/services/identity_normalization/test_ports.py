"""Service port configuration and Docker Compose port mapping for identity-normalization."""

import inspect
import typing

# third-party


# ---------------------------------------------------------------------------
# Helper: get method names from a class
# ---------------------------------------------------------------------------


def _method_names(cls: type) -> set[str]:
    """Return all public method names defined directly on cls."""
    return {
        name
        for name, member in inspect.getmembers(cls, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def _is_runtime_checkable_protocol(cls: type) -> bool:
    """Return True if cls is a typing.Protocol with @runtime_checkable."""
    return (
        isinstance(cls, type)
        and issubclass(cls, typing.Protocol)  # type: ignore[arg-type]
        and getattr(cls, "_is_protocol", False)
        and getattr(cls, "_is_runtime_protocol", False)
    )


# ===========================================================================
# CLASS 1 — Module imports without error
# ===========================================================================


class TestPortsModuleImport:
    """app.ports must be importable and must define all four Protocol classes.

    WHY: The composition root (app/main.py) imports these Protocols to wire
    concrete adapters into NormalizationService. An ImportError here crashes
    the service on startup and prevents any test doubles from being constructed.
    """

    def test_ports_module_is_importable(self) -> None:
        """from app.ports import ... must succeed without raising.

        WHY: The module exposes the ProtocolAdapter port. A ModuleNotFoundError
        means services/identity-normalization/app/ports.py is absent or broken.
        """
        import app.ports  # noqa: F401

    def test_protocol_adapter_is_defined(self) -> None:
        """app.ports must expose a name ProtocolAdapter.

        WHY: ProtocolAdapter is the port for OIDC/SAML/LDAP adapters. The domain
        service type-hints against this Protocol; missing it causes AttributeError
        at composition root wiring time.
        """
        from app import ports

        assert hasattr(ports, "ProtocolAdapter"), (
            "app.ports must define 'ProtocolAdapter'. "
            "It is the port interface for OIDC/SAML/LDAP protocol adapters."
        )

    def test_ldap_enricher_is_defined(self) -> None:
        """app.ports must expose a name LdapEnricher.

        WHY: LdapEnricher is the port for the LDAP enrichment adapter. The domain
        service calls enrich() on this interface; a missing Protocol means the
        NormalizationService cannot be typed or wired.
        """
        from app import ports

        assert hasattr(ports, "LdapEnricher"), (
            "app.ports must define 'LdapEnricher'. "
            "It is the port interface for LDAP directory enrichment."
        )

    def test_normalization_repository_is_defined(self) -> None:
        """app.ports must expose a name NormalizationRepository.

        WHY: NormalizationRepository is the port for the persistence adapter
        (PostgresNormalizationRepository). The domain service calls write() through
        this interface; missing it prevents the consumer loop from persisting results.
        """
        from app import ports

        assert hasattr(ports, "NormalizationRepository"), (
            "app.ports must define 'NormalizationRepository'. "
            "It is the port interface for persistence (UPDATE events.normalized_attributes)."
        )

    def test_event_publisher_is_defined(self) -> None:
        """app.ports must expose a name EventPublisher.

        WHY: EventPublisher is the port for publishing to the normalized_events stream.
        The consumer loop calls publish_normalized() through this interface after
        persisting; missing it prevents downstream Signal Enrichment from receiving events.
        """
        from app import ports

        assert hasattr(ports, "EventPublisher"), (
            "app.ports must define 'EventPublisher'. "
            "It is the port interface for publishing to the normalized_events Redis Stream."
        )


# ===========================================================================
# CLASS 2 — All four Protocols are typing.Protocol (runtime-checkable)
# ===========================================================================


class TestProtocolsAreRuntimeCheckable:
    """Each port must be a runtime-checkable typing.Protocol.

    WHY: Spec §5 uses structural subtyping so concrete adapters do not need to
    explicitly inherit from the Protocol classes. Runtime-checkability (via
    @runtime_checkable) is required so isinstance() checks can be used in tests
    and in the composition root to verify wiring. A plain class (not a Protocol)
    would break structural subtyping and duck-typing-based adapter injection.
    """

    def test_protocol_adapter_is_a_protocol(self) -> None:
        """ProtocolAdapter must be a typing.Protocol class.

        WHY: If ProtocolAdapter is a plain ABC or regular class, the OIDC/SAML/LDAP
        adapter implementations would need explicit inheritance rather than duck-typing.
        Using Protocol allows clean structural subtyping.
        """
        from app.ports import ProtocolAdapter

        assert _is_runtime_checkable_protocol(ProtocolAdapter), (
            f"ProtocolAdapter must be a @runtime_checkable typing.Protocol. "
            f"Got type: {type(ProtocolAdapter).__name__!r}. "
            "Add @runtime_checkable decorator and inherit from typing.Protocol."
        )

    def test_ldap_enricher_is_a_protocol(self) -> None:
        """LdapEnricher must be a typing.Protocol class.

        WHY: LdapEnricher has async methods (enrich); using a Protocol allows
        structural typing without coupling the domain to the concrete ldap adapter.
        """
        from app.ports import LdapEnricher

        assert _is_runtime_checkable_protocol(LdapEnricher), (
            f"LdapEnricher must be a @runtime_checkable typing.Protocol. "
            f"Got type: {type(LdapEnricher).__name__!r}."
        )

    def test_normalization_repository_is_a_protocol(self) -> None:
        """NormalizationRepository must be a typing.Protocol class.

        WHY: The PostgresNormalizationRepository satisfies NormalizationRepository
        structurally. Other tests use a mock that satisfies the Protocol
        without inheriting from it, enabling clean unit testing of the consumer loop.
        """
        from app.ports import NormalizationRepository

        assert _is_runtime_checkable_protocol(NormalizationRepository), (
            f"NormalizationRepository must be a @runtime_checkable typing.Protocol. "
            f"Got type: {type(NormalizationRepository).__name__!r}."
        )

    def test_event_publisher_is_a_protocol(self) -> None:
        """EventPublisher must be a typing.Protocol class.

        WHY: The composition root wires a concrete Redis stream publisher to the
        EventPublisher port. Using a Protocol allows the consumer loop to be tested
        in isolation with a mock publisher.
        """
        from app.ports import EventPublisher

        assert _is_runtime_checkable_protocol(EventPublisher), (
            f"EventPublisher must be a @runtime_checkable typing.Protocol. "
            f"Got type: {type(EventPublisher).__name__!r}."
        )


# ===========================================================================
# CLASS 3 — ProtocolAdapter method signatures
# ===========================================================================


class TestProtocolAdapterSignature:
    """ProtocolAdapter must define extract(self, raw_attributes: dict) -> dict.

    WHY: Spec §5.2 — 'Each adapter maps protocol-specific raw attributes to the
    unified schema.' The NormalizationService calls adapter.extract(raw_attributes)
    for every event. If this method is absent or named differently, the service
    fails with AttributeError on the first event it processes.
    """

    def test_protocol_adapter_has_extract_method(self) -> None:
        """ProtocolAdapter must define a method named 'extract'.

        WHY: The NormalizationService calls adapter.extract(record.raw_attributes)
        to produce the primary-source unified attribute dict. Missing this method
        means the first OIDC/SAML/LDAP event processed raises AttributeError.
        """
        from app.ports import ProtocolAdapter

        assert "extract" in _method_names(ProtocolAdapter), (
            f"ProtocolAdapter must define an 'extract' method. "
            f"Found methods: {_method_names(ProtocolAdapter)}. "
            "Spec §5.2: extract(self, raw_attributes: dict) -> dict"
        )

    def test_protocol_adapter_extract_takes_raw_attributes_parameter(self) -> None:
        """ProtocolAdapter.extract must accept a 'raw_attributes' parameter.

        WHY: The NormalizationService calls adapter.extract(record.raw_attributes)
        positionally. The parameter must exist so type checkers and runtime
        callers agree on the interface.
        """
        from app.ports import ProtocolAdapter

        sig = inspect.signature(ProtocolAdapter.extract)
        param_names = list(sig.parameters.keys())
        assert "raw_attributes" in param_names, (
            f"ProtocolAdapter.extract must have a 'raw_attributes' parameter. "
            f"Found parameters: {param_names}. "
            "Spec §5.2: extract(self, raw_attributes: dict) -> dict"
        )


# ===========================================================================
# CLASS 4 — LdapEnricher method signatures
# ===========================================================================


class TestLdapEnricherSignature:
    """LdapEnricher must define extract() and async enrich().

    WHY: Spec §5.3 — LdapEnricher has two methods: extract (passive mapping,
    same signature as ProtocolAdapter) and enrich (active LDAP query, async).
    The NormalizationService calls both; missing either raises AttributeError.
    """

    def test_ldap_enricher_has_extract_method(self) -> None:
        """LdapEnricher must define 'extract' method.

        WHY: Spec §5.3 — 'extract(raw_attributes) is the passive mapping in §5.2
        (also used internally to normalize query results).' The LDAP adapter
        extracts attributes from the LDAP query response using this method.
        """
        from app.ports import LdapEnricher

        assert "extract" in _method_names(LdapEnricher), (
            f"LdapEnricher must define an 'extract' method. "
            f"Found methods: {_method_names(LdapEnricher)}. "
            "Spec §5.3: extract(self, raw_attributes: dict) -> dict"
        )

    def test_ldap_enricher_has_enrich_method(self) -> None:
        """LdapEnricher must define an 'enrich' method.

        WHY: Spec §5.3 — 'enrich(correlation_field, lookup_value) -> dict | None
        is the active directory query.' The NormalizationService calls this to
        merge LDAP directory attributes with OIDC/SAML token claims.
        """
        from app.ports import LdapEnricher

        assert "enrich" in _method_names(LdapEnricher), (
            f"LdapEnricher must define an 'enrich' method. "
            f"Found methods: {_method_names(LdapEnricher)}. "
            "Spec §5.3: async def enrich(self, correlation_field: str, lookup_value: str) -> dict | None"
        )

    def test_ldap_enricher_enrich_takes_correlation_field_parameter(self) -> None:
        """LdapEnricher.enrich must accept a 'correlation_field' parameter.

        WHY: The NormalizationService calls enrich(correlation_field=..., lookup_value=...)
        per spec §5.3. The parameter name is part of the public interface contract.
        """
        from app.ports import LdapEnricher

        sig = inspect.signature(LdapEnricher.enrich)
        param_names = list(sig.parameters.keys())
        assert "correlation_field" in param_names, (
            f"LdapEnricher.enrich must have a 'correlation_field' parameter. "
            f"Found parameters: {param_names}. "
            "Spec §5.3: enrich(self, correlation_field: str, lookup_value: str)"
        )

    def test_ldap_enricher_enrich_takes_lookup_value_parameter(self) -> None:
        """LdapEnricher.enrich must accept a 'lookup_value' parameter.

        WHY: The NormalizationService passes the correlation value (e.g., an email
        address) as lookup_value. The LDAP adapter uses this to build the search
        filter after sanitization. Missing parameter means the call site raises
        TypeError.
        """
        from app.ports import LdapEnricher

        sig = inspect.signature(LdapEnricher.enrich)
        param_names = list(sig.parameters.keys())
        assert "lookup_value" in param_names, (
            f"LdapEnricher.enrich must have a 'lookup_value' parameter. "
            f"Found parameters: {param_names}. "
            "Spec §5.3: enrich(self, correlation_field: str, lookup_value: str)"
        )

    def test_ldap_enricher_enrich_is_async(self) -> None:
        """LdapEnricher.enrich must be an async method (coroutine function).

        WHY: Spec §5.3 — 'python-ldap is synchronous; wrap every blocking LDAP call
        in asyncio.to_thread(...)'. The enrich method itself must be declared async
        so the NormalizationService can await it without blocking the event loop.
        """
        from app.ports import LdapEnricher

        assert inspect.iscoroutinefunction(LdapEnricher.enrich), (
            "LdapEnricher.enrich must be declared 'async def'. "
            "Spec §5.3: python-ldap is synchronous; the async boundary is at enrich()."
        )


# ===========================================================================
# CLASS 5 — NormalizationRepository method signatures
# ===========================================================================


class TestNormalizationRepositorySignature:
    """NormalizationRepository must define async write(self, event_id, normalized) -> None.

    WHY: Spec §5.1 — 'await repository.write(record.id, normalized)' is called by the
    consumer loop as step 3 (the point of no return). If write() is synchronous, awaiting
    it raises TypeError. If the parameters are named differently, the call site breaks.
    """

    def test_normalization_repository_has_write_method(self) -> None:
        """NormalizationRepository must define a 'write' method.

        WHY: The consumer loop calls repository.write(record.id, normalized) to
        UPDATE events.normalized_attributes. Missing this method means every event
        processing attempt raises AttributeError before any DB write occurs.
        """
        from app.ports import NormalizationRepository

        assert "write" in _method_names(NormalizationRepository), (
            f"NormalizationRepository must define a 'write' method. "
            f"Found methods: {_method_names(NormalizationRepository)}. "
            "Spec §5.1: async def write(self, event_id, normalized) -> None"
        )

    def test_normalization_repository_write_is_async(self) -> None:
        """NormalizationRepository.write must be an async method.

        WHY: The consumer loop is async (it uses XREADGROUP with block=). The
        write() call is awaited directly: 'await repository.write(...)'. A sync
        write would block the event loop for the duration of the DB round-trip.
        """
        from app.ports import NormalizationRepository

        assert inspect.iscoroutinefunction(NormalizationRepository.write), (
            "NormalizationRepository.write must be declared 'async def'. "
            "The consumer loop awaits it directly per spec §5.1."
        )

    def test_normalization_repository_write_takes_event_id_parameter(self) -> None:
        """NormalizationRepository.write must accept an 'event_id' parameter.

        WHY: The consumer loop calls write(record.id, normalized). The event_id is
        the UUID primary key of the events row to UPDATE. Missing this parameter means
        the repository cannot know which row to update.
        """
        from app.ports import NormalizationRepository

        sig = inspect.signature(NormalizationRepository.write)
        param_names = list(sig.parameters.keys())
        assert "event_id" in param_names, (
            f"NormalizationRepository.write must have an 'event_id' parameter. "
            f"Found parameters: {param_names}."
        )

    def test_normalization_repository_write_takes_normalized_parameter(self) -> None:
        """NormalizationRepository.write must accept a 'normalized' parameter.

        WHY: The consumer loop calls write(record.id, normalized) where normalized
        is the NormalizedAttributes instance to serialize and store. The parameter
        must exist so the repository can receive and persist it.
        """
        from app.ports import NormalizationRepository

        sig = inspect.signature(NormalizationRepository.write)
        param_names = list(sig.parameters.keys())
        assert "normalized" in param_names, (
            f"NormalizationRepository.write must have a 'normalized' parameter. "
            f"Found parameters: {param_names}."
        )


# ===========================================================================
# CLASS 6 — EventPublisher method signatures
# ===========================================================================


class TestEventPublisherSignature:
    """EventPublisher must define async publish_normalized(self, record, normalized) -> None.

    WHY: Spec §5.1 — 'await publisher.publish_normalized(record, normalized)' is
    called by the consumer loop as step 4 (after the DB commit, before ACK). If
    publish_normalized() is synchronous, awaiting it raises TypeError.
    """

    def test_event_publisher_has_publish_normalized_method(self) -> None:
        """EventPublisher must define a 'publish_normalized' method.

        WHY: The consumer loop calls publisher.publish_normalized(record, normalized)
        to XADD the full LoginEventRecord (with populated normalized_attributes) to
        the normalized_events stream. Missing this method breaks the pipeline: Signal
        Enrichment never receives any events.
        """
        from app.ports import EventPublisher

        assert "publish_normalized" in _method_names(EventPublisher), (
            f"EventPublisher must define a 'publish_normalized' method. "
            f"Found methods: {_method_names(EventPublisher)}. "
            "Spec §5.1: async def publish_normalized(self, record, normalized) -> None"
        )

    def test_event_publisher_publish_normalized_is_async(self) -> None:
        """EventPublisher.publish_normalized must be an async method.

        WHY: The consumer loop is async and awaits publish_normalized directly.
        Redis XADD via aioredis is also async. A synchronous publish_normalized
        would block the event loop or raise TypeError when awaited.
        """
        from app.ports import EventPublisher

        assert inspect.iscoroutinefunction(EventPublisher.publish_normalized), (
            "EventPublisher.publish_normalized must be declared 'async def'. "
            "The consumer loop awaits it per spec §5.1."
        )

    def test_event_publisher_publish_normalized_takes_record_parameter(self) -> None:
        """EventPublisher.publish_normalized must accept a 'record' parameter.

        WHY: The consumer loop calls publish_normalized(record, normalized). The
        record is the LoginEventRecord carrying the full event payload. The publisher
        sets record.normalized_attributes = normalized.model_dump(...) before XADD.
        """
        from app.ports import EventPublisher

        sig = inspect.signature(EventPublisher.publish_normalized)
        param_names = list(sig.parameters.keys())
        assert "record" in param_names, (
            f"EventPublisher.publish_normalized must have a 'record' parameter. "
            f"Found parameters: {param_names}."
        )

    def test_event_publisher_publish_normalized_takes_normalized_parameter(
        self,
    ) -> None:
        """EventPublisher.publish_normalized must accept a 'normalized' parameter.

        WHY: The publisher needs the NormalizedAttributes instance to populate
        record.normalized_attributes before serializing and publishing. Without
        this parameter, the publisher cannot know what to include in the stream
        message payload.
        """
        from app.ports import EventPublisher

        sig = inspect.signature(EventPublisher.publish_normalized)
        param_names = list(sig.parameters.keys())
        assert "normalized" in param_names, (
            f"EventPublisher.publish_normalized must have a 'normalized' parameter. "
            f"Found parameters: {param_names}."
        )
