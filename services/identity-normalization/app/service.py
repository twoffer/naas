"""NormalizationService and NormalizationPublisher for the Identity Normalization Service.

NormalizationService wires adapter selection, LDAP enrichment, and conflict
resolution (chunks 1-5) into a single async `normalize()` entry point called
by the consumer loop (chunk 6).

NormalizationPublisher satisfies the EventPublisher port: it sets
record.normalized_attributes and publishes the full LoginEventRecord to
the normalized_events Redis Stream per ADR-0011.
"""

from __future__ import annotations

from typing import Any

from app.adapters.ldap import LdapAdapter
from app.adapters.oidc import OidcAdapter
from app.adapters.saml import SamlAdapter
from app.normalization_config import NormalizationConfig
from app.resolution import resolve
import naas_shared.redis_client as _redis_mod
from naas_shared.constants import STREAM_NORMALIZED_EVENTS
from naas_shared.logging import get_logger
from naas_shared.models import (
    EnrichmentApplied,
    EnrichmentSkipped,
    LoginEventRecord,
    NormalizedAttributes,
)

_logger = get_logger(__name__)

# Outcome codes that signal a match (attrs dict will be non-None).
_MATCH_OUTCOMES: frozenset[str] = frozenset({"ldap_match", "cache_hit_positive"})

# Outcome-to-skip-reason mapping for non-match outcomes.
_OUTCOME_TO_SKIP_REASON: dict[str, str] = {
    "ldap_no_match": "no_ldap_match",
    "cache_hit_negative": "no_ldap_match",
    "ldap_timeout": "ldap_timeout",
    "ldap_connection_error": "ldap_connection_error",
    "ldap_search_error": "ldap_search_error",
    "ldap_unexpected_error": "ldap_search_error",
    "unmappable_field": "ldap_search_error",
}


class NormalizationService:
    """Coordinates adapter extraction, LDAP enrichment, and attribute resolution.

    Accepts pre-built adapter instances (dependency injection) so callers in
    tests can mock enrich() without importing python-ldap.

    WHY a service class: the consumer loop constructs one instance at startup
    and reuses it across all messages — stateless within a single normalize()
    call but the adapters themselves may maintain connection pools (LdapAdapter).
    """

    def __init__(
        self,
        config: NormalizationConfig,
        oidc_adapter: OidcAdapter,
        saml_adapter: SamlAdapter,
        ldap_adapter: LdapAdapter,
    ) -> None:
        self._config = config
        self._oidc_adapter = oidc_adapter
        self._saml_adapter = saml_adapter
        self._ldap_adapter = ldap_adapter

    async def normalize(self, record: LoginEventRecord) -> NormalizedAttributes:
        """Extract, enrich, and resolve attributes for a single login event.

        WHY three-stage: extraction maps raw claims to unified names; enrichment
        merges LDAP directory attributes for non-LDAP protocols; resolution picks
        the authoritative value per attribute and computes normalization_confidence.

        On ANY enrichment failure the method degrades gracefully — primary-source
        attributes are still resolved and returned (ADR-0008). normalize() NEVER
        raises; callers may always expect a valid NormalizedAttributes.

        Args:
            record: The deserialized login event from the Redis Stream.

        Returns:
            NormalizedAttributes with all fields, resolution_details, and
            enrichment metadata populated.
        """
        log = _logger.bind(
            event_id=str(record.id),
            protocol=record.protocol,
            user_id=record.user_id,
        )

        # --- Stage 1: adapter selection and primary attribute extraction ---
        adapter = self._select_adapter(record.protocol)
        primary_attrs = adapter.extract(record.raw_attributes)

        # --- Stage 2: build attribute_sources for resolution ---
        attribute_sources = _build_attribute_sources(record.protocol, primary_attrs)

        # --- Stage 3: enrichment decision and execution ---
        enrichment = await self._determine_enrichment(
            record, primary_attrs, attribute_sources, log
        )

        # --- Stage 4: resolution ---
        return resolve(
            attribute_sources=attribute_sources,
            config=self._config,
            source_protocol=record.protocol,
            enrichment=enrichment,
        )

    def _select_adapter(self, protocol: str) -> OidcAdapter | SamlAdapter | LdapAdapter:
        """Return the adapter for the given protocol.

        WHY: open-closed — new protocols only require adding a branch here and a
        concrete adapter class; the service loop is unchanged.
        """
        if protocol == "oidc":
            return self._oidc_adapter
        if protocol == "saml":
            return self._saml_adapter
        return self._ldap_adapter

    async def _determine_enrichment(
        self,
        record: LoginEventRecord,
        primary_attrs: dict[str, Any],
        attribute_sources: dict[str, Any],
        log: Any,
    ) -> EnrichmentApplied | EnrichmentSkipped:
        """Decide whether to enrich and, if so, call LdapAdapter.enrich().

        Enrichment is attempted IFF:
          - config.enrichment.sources.ldap.enabled is True, AND
          - record.protocol is "oidc" or "saml" (never "ldap"), AND
          - the correlation value for the configured key is non-empty.

        On ANY exception from enrich(), degrades gracefully to ldap_search_error.
        NEVER branches on is_synthetic (§5.4 invariant).
        """
        ldap_cfg = self._config.enrichment.sources.ldap

        if not ldap_cfg.enabled:
            return EnrichmentSkipped(applied=False, skip_reason="ldap_disabled")

        if record.protocol == "ldap":
            return EnrichmentSkipped(applied=False, skip_reason="ldap_event")

        # Determine correlation value from primary attributes
        correlation_key = ldap_cfg.correlation_key
        lookup_value: str | None = primary_attrs.get(correlation_key)

        if not lookup_value:
            log.warning(
                "ldap_enrichment_skipped_no_correlation",
                correlation_key=correlation_key,
            )
            return EnrichmentSkipped(
                applied=False, skip_reason="invalid_correlation_key"
            )

        # Call enrich — graceful degradation on ANY exception
        try:
            attrs, outcome = await self._ldap_adapter.enrich(
                correlation_key, lookup_value
            )
        except Exception as exc:
            log.error(
                "ldap_enrichment_unexpected_exception",
                error=str(exc),
            )
            return EnrichmentSkipped(applied=False, skip_reason="ldap_search_error")

        return self._map_outcome_to_enrichment(outcome, attrs, attribute_sources, log)

    def _map_outcome_to_enrichment(
        self,
        outcome: str,
        attrs: dict[str, Any] | None,
        attribute_sources: dict[str, Any],
        log: Any,
    ) -> EnrichmentApplied | EnrichmentSkipped:
        """Map an enrich() outcome code to EnrichmentApplied or EnrichmentSkipped.

        On a match, merges ldap attrs into attribute_sources as the "ldap" source.
        Log levels follow §5.4: no_ldap_match→INFO, timeout/invalid→WARNING,
        connection/search errors→ERROR.
        """
        if outcome == "ldap_match":
            if attrs:
                _merge_ldap_attrs(attrs, attribute_sources)
            return EnrichmentApplied(applied=True, source="ldap", cache_hit=False)

        if outcome == "cache_hit_positive":
            if attrs:
                _merge_ldap_attrs(attrs, attribute_sources)
            return EnrichmentApplied(applied=True, source="ldap", cache_hit=True)

        if outcome in ("ldap_no_match", "cache_hit_negative"):
            log.info("ldap_enrichment_no_match", outcome=outcome)
            return EnrichmentSkipped(applied=False, skip_reason="no_ldap_match")

        if outcome == "ldap_timeout":
            log.warning("ldap_enrichment_timeout")
            return EnrichmentSkipped(applied=False, skip_reason="ldap_timeout")

        if outcome == "ldap_connection_error":
            log.error("ldap_enrichment_connection_error")
            return EnrichmentSkipped(applied=False, skip_reason="ldap_connection_error")

        # ldap_search_error, ldap_unexpected_error, unmappable_field → catch-all
        log.error("ldap_enrichment_error", outcome=outcome)
        return EnrichmentSkipped(applied=False, skip_reason="ldap_search_error")


class NormalizationPublisher:
    """Publishes a fully-normalized LoginEventRecord to the normalized_events stream.

    Satisfies the EventPublisher port (app.ports.EventPublisher). Uses the shared
    publish_to_stream helper so the transport layer is never hand-rolled (§3.2).

    WHY full-record publish (ADR-0011): downstream services (Signal Enrichment, Risk
    Evaluator) need both the original event metadata AND the normalized attributes.
    Sending the full record avoids a second DB read in every downstream service.
    """

    async def publish_normalized(
        self,
        record: LoginEventRecord,
        normalized: NormalizedAttributes,
    ) -> None:
        """Set record.normalized_attributes and publish the full record to the stream.

        Mutates record.normalized_attributes in-place before serializing so the
        published payload contains the normalized data. The consumer loop creates
        a fresh record per message, so mutation is safe here.

        Args:
            record:     The LoginEventRecord from the stream (mutated in-place).
            normalized: The resolved NormalizedAttributes to embed and publish.
        """
        record.normalized_attributes = normalized.model_dump(mode="json")
        await _redis_mod.publish_to_stream(
            STREAM_NORMALIZED_EVENTS, record.model_dump(mode="json")
        )


# ---------------------------------------------------------------------------
# Helpers (module-private)
# ---------------------------------------------------------------------------


def _build_attribute_sources(
    protocol: str,
    attrs: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build the attribute_sources dict expected by resolution.resolve().

    Only non-None, non-empty values are included (per chunk-5 contract).
    The department value is stored as a (normalized_str, was_mapped) tuple
    because resolution._resolve_department inspects was_mapped for the
    confidence penalty.

    Args:
        protocol: The event protocol ("oidc", "saml", "ldap").
        attrs:    The unified dict from adapter.extract().

    Returns:
        Mapping of attribute_name → {source_protocol: value_or_tuple}.
    """
    sources: dict[str, dict[str, Any]] = {}

    for attr in ("display_name", "primary_email", "employee_type"):
        val = attrs.get(attr)
        if val is not None:
            sources.setdefault(attr, {})[protocol] = val

    # department uses (str, was_mapped) tuple
    raw_dept_normalized = attrs.get("department")
    if raw_dept_normalized is not None:
        # Re-derive was_mapped by running normalize_department again with the
        # canonical value to check if it round-trips cleanly.
        # The adapters already ran normalize_department; we need was_mapped.
        # We can't recover was_mapped from the normalized string alone, so we
        # treat a known canonical value as mapped=True, else mapped=False.
        was_mapped = _was_department_mapped(raw_dept_normalized)
        sources.setdefault("department", {})[protocol] = (
            raw_dept_normalized,
            was_mapped,
        )

    # groups: only if non-empty list
    groups = attrs.get("groups")
    if groups:
        sources.setdefault("groups", {})[protocol] = groups

    return sources


def _was_department_mapped(normalized_value: str) -> bool:
    """Determine was_mapped for an already-normalized department string.

    The adapters call normalize_department() and discard the was_mapped flag.
    Resolution needs was_mapped to apply the confidence penalty correctly.

    Strategy: run normalize_department() on the lowercase of the normalized
    value.  If the canonical map returns the same value, it was mapped.
    If not (title-case fallback path), it was NOT in the map — was_mapped=False.

    This round-trip is safe because canonical values are title-case strings
    already present as *values* in DEPARTMENT_CANONICAL (e.g. "Engineering"),
    and their lowercase ("engineering") is a key that maps back to the same value.
    """
    from app.normalization_values import DEPARTMENT_CANONICAL

    key = normalized_value.strip().lower()
    return DEPARTMENT_CANONICAL.get(key) == normalized_value


def _merge_ldap_attrs(
    ldap_attrs: dict[str, Any],
    attribute_sources: dict[str, Any],
) -> None:
    """Merge LDAP-sourced unified attributes into attribute_sources as the "ldap" source.

    Only non-None, non-empty values are included. department is converted to the
    (str, was_mapped) tuple format that _resolve_department expects.

    Mutates attribute_sources in-place.

    Args:
        ldap_attrs:        The unified dict returned by LdapAdapter.enrich().
        attribute_sources: The sources dict being built for resolution.resolve().
    """
    for attr in ("display_name", "primary_email", "employee_type"):
        val = ldap_attrs.get(attr)
        if val is not None:
            attribute_sources.setdefault(attr, {})["ldap"] = val

    dept = ldap_attrs.get("department")
    if dept is not None:
        was_mapped = _was_department_mapped(dept)
        attribute_sources.setdefault("department", {})["ldap"] = (dept, was_mapped)

    groups = ldap_attrs.get("groups")
    if groups:
        attribute_sources.setdefault("groups", {})["ldap"] = groups
