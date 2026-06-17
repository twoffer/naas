"""Port Protocol definitions for the Identity Normalization Service.

Defines the five abstract boundaries the domain depends on — ProtocolAdapter
(per-protocol attribute extraction), LdapEnricher (cross-protocol directory
enrichment), NormalizationRepository (persistence), EventPublisher (stream
transport), and Normalizer (the service entry point consumed by the consumer
layer).

Using typing.Protocol with @runtime_checkable enables structural subtyping so
concrete adapters and test doubles satisfy the ports without explicit inheritance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from naas_shared.models import LoginEventRecord, NormalizedAttributes


@runtime_checkable
class ProtocolAdapter(Protocol):
    """Port for OIDC/SAML/LDAP protocol-specific attribute extraction.

    Spec §5.2 — each adapter maps protocol-specific raw attributes from a login
    event to the shared unified schema. The NormalizationService calls
    adapter.extract(record.raw_attributes) as the primary attribute source.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map protocol-specific raw attributes to the unified schema.

        WHY: Each protocol (OIDC, SAML, LDAP) names identity attributes
        differently (e.g., 'email' vs. 'mail' vs. 'urn:oid:...'). The adapter
        normalizes these to the canonical attribute names expected by
        NormalizationService.
        """
        ...


@runtime_checkable
class LdapEnricher(Protocol):
    """Port for cross-protocol LDAP directory enrichment.

    Spec §5.3 — used by NormalizationService when the event protocol is oidc
    or saml. Performs a live LDAP query to merge directory attributes (department,
    groups, employee_type, etc.) with token claims. LDAP events skip enrichment.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map LDAP raw attributes to the unified schema (passive mapping).

        WHY: Mirrors ProtocolAdapter.extract; used internally by the LDAP
        adapter to normalize query results before merging with primary attrs.
        """
        ...

    async def enrich(
        self,
        correlation_field: str,
        lookup_value: str,
        *,
        cache_ttl_seconds: int = 60,
        timeout_ms: int = 2000,
        enrich_attributes: list[str] | None = None,
    ) -> tuple[dict | None, str]:
        """Perform an active LDAP directory query and return normalized attributes.

        WHY: Spec §5.3 — python-ldap is synchronous; every blocking LDAP call
        is wrapped in asyncio.to_thread(...) inside the concrete adapter. The
        method itself is declared async so NormalizationService can await it
        without blocking the event loop.

        Args:
            correlation_field:  The unified schema field used to build the LDAP
                filter (e.g., "primary_email"). The adapter reverse-maps this to
                the LDAP attribute name (e.g., "mail").
            lookup_value:       The value to search for (e.g., "alice@corp.com").
            cache_ttl_seconds:  TTL for positive and negative cache entries.
            timeout_ms:         Network and operation timeout in milliseconds.
            enrich_attributes:  When not None, restricts the LDAP fetch to
                the specified unified field names; None fetches all five.

        Returns:
            A 2-tuple ``(attrs, outcome)`` where:
              attrs   — unified attribute dict on a successful match; None on
                        no-match, error, or negative cache hit.
              outcome — an outcome code string (e.g., "ldap_match",
                        "cache_hit_positive", "ldap_no_match", "ldap_timeout",
                        "ldap_connection_error", "ldap_search_error",
                        "ldap_unexpected_error", "unmappable_field").
                        Callers use the outcome code to build the correct
                        EnrichmentSkipped skip_reason without inspecting attrs.
        """
        ...


@runtime_checkable
class Normalizer(Protocol):
    """Port for the normalization service entry point consumed by the consumer layer.

    Spec §5.1 — the consumer loop calls normalize(record) as step 1 of the
    four-step pipeline (extract + enrich + resolve). Declared as a Protocol so
    the consumer layer is typed without a hard import of NormalizationService.
    """

    async def normalize(self, record: LoginEventRecord) -> NormalizedAttributes:
        """Extract, enrich, and resolve attributes for a single login event.

        WHY: Declared async because every internal stage (LDAP enrichment via
        asyncio.to_thread, Redis cache reads) is async. The consumer loop awaits
        this call per message; a sync implementation would block the event loop.

        Args:
            record: The deserialized login event from the Redis Stream.

        Returns:
            NormalizedAttributes with all unified fields populated.
        """
        ...


@runtime_checkable
class NormalizationRepository(Protocol):
    """Port for persisting normalized attributes to the events table.

    Spec §5.1 — the consumer loop calls write(record.id, normalized) as step 3
    (the point of no return) after extracting and enriching attributes. The
    implementation UPDATEs events.normalized_attributes in PostgreSQL.
    """

    async def write(
        self,
        event_id,
        normalized: NormalizedAttributes,
    ) -> None:
        """UPDATE events.normalized_attributes for the given event_id.

        WHY: Normalization is an enrichment step on an already-ingested event
        row. The event row exists (written by event-ingestion); the repository
        updates it with the normalized JSONB payload. Declared async because the
        consumer loop awaits it directly — a sync write would block the event loop.
        """
        ...


@runtime_checkable
class EventPublisher(Protocol):
    """Port for publishing to the normalized_events Redis Stream.

    Spec §5.1 — the consumer loop calls publish_normalized(record, normalized)
    as step 4 (after the DB commit, before ACK). The implementation populates
    record.normalized_attributes and XADDs the full LoginEventRecord to the
    normalized_events stream so Signal Enrichment can consume it.
    """

    async def publish_normalized(
        self,
        record: LoginEventRecord,
        normalized: NormalizedAttributes,
    ) -> None:
        """Publish the normalized event to the normalized_events Redis Stream.

        WHY: Signal Enrichment subscribes to the normalized_events stream via
        XREADGROUP. Without this publish step, the downstream pipeline stalls:
        no enriched signals, no risk scores, no decisions. Declared async because
        the consumer loop awaits it and the underlying Redis XADD is async.
        """
        ...
