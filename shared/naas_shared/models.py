from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def _to_utc(v: datetime) -> datetime:
    """Normalize a datetime to an aware UTC instant.

    Naive inputs (no tzinfo) are treated as UTC rather than left ambiguous —
    a deliberate convention so values that omit an offset are not silently
    shifted by the PostgreSQL session timezone.  Aware inputs from other zones
    are converted to UTC so the pipeline always works with a single canonical
    representation.
    """
    if v.tzinfo is None:
        return v.replace(tzinfo=UTC)
    return v.astimezone(UTC)


class LoginEventBase(BaseModel):
    """Schema for events entering the pipeline via ingestion."""

    user_id: str = Field(..., min_length=1, max_length=255)
    client_ip: str = Field(
        ...,
        pattern=r"^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])$",
    )
    protocol: Literal["oidc", "saml", "ldap"]
    timestamp: datetime
    user_agent: str | None = None
    source: Literal["user", "simulator", "api"] = "user"
    is_synthetic: bool = False
    is_historical: bool = False
    raw_attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="after")
    @classmethod
    def normalize_timestamp_to_utc(cls, v: datetime) -> datetime:
        """Ensure the event timestamp is always an aware UTC instant."""
        return _to_utc(v)


class LoginEventIngest(LoginEventBase):
    """Request body for POST /events/ingest."""



class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has the UUID id assigned)."""

    id: UUID = Field(default_factory=uuid4)
    normalized_attributes: dict[str, Any] | None = None
    enriched_signals: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("created_at", mode="after")
    @classmethod
    def normalize_created_at_to_utc(cls, v: datetime) -> datetime:
        """Normalize an explicitly-supplied created_at to an aware UTC instant.

        The default_factory already yields aware UTC; this validator only fires
        when created_at is passed explicitly (e.g. reconstructing a record from a
        serialized stream payload), keeping it safe-by-construction rather than
        relying on every caller to supply an aware value.
        """
        return _to_utc(v)


# ============================================================
# Type aliases
# ============================================================

SourceProtocol = Literal["oidc", "saml", "ldap"]


# ============================================================
# Resolution Details — discriminated union by `resolution`
# ============================================================


class ResolutionDetailBase(BaseModel):
    """Common fields for all resolution-detail variants.

    Subclasses declare a `resolution` field as a Literal discriminator
    and a `resolved_value` field typed appropriately for the attribute
    kind they describe (scalar vs. list).
    """

    confidence: float = Field(ge=0.0, le=1.0)


class UnanimousResolution(ResolutionDetailBase):
    """All sources agreed on this attribute's value."""

    resolution: Literal["unanimous"]
    resolved_value: str | None = None
    sources: list[SourceProtocol]


class PriorityResolution(ResolutionDetailBase):
    """Sources disagreed; highest-priority source's value won."""

    resolution: Literal["priority"]
    resolved_value: str | None = None
    winner_source: SourceProtocol
    conflicting_values: dict[SourceProtocol, Any]
    penalty_applied: bool


class SingleSourceResolution(ResolutionDetailBase):
    """Only one source provided this attribute (no conflict possible)."""

    resolution: Literal["single_source"]
    resolved_value: str | None = None
    sources: list[SourceProtocol]


class ListMergeResolution(ResolutionDetailBase):
    """List-typed attribute (e.g., groups) merged across sources by strategy."""

    resolution: Literal["list_merge"]
    resolved_value: list[str] = Field(default_factory=list)
    strategy: Literal["union", "intersection", "priority"]
    total_unique_groups: int = Field(ge=0)
    sources: list[SourceProtocol] = Field(default_factory=list)


ResolutionDetail = Annotated[
    UnanimousResolution | PriorityResolution | SingleSourceResolution | ListMergeResolution,
    Field(discriminator="resolution"),
]


# ============================================================
# Enrichment Metadata — discriminated union by `applied`
# ============================================================

EnrichmentSkipReason = Literal[
    "ldap_disabled",  # enrichment.sources.ldap.enabled = false
    "ldap_event",  # event protocol is "ldap" (skip per design)
    "no_ldap_match",  # LDAP query returned no entries
    "ldap_timeout",  # LDAP search exceeded timeout_ms
    "ldap_connection_error",  # connect refused / network error
    "ldap_search_error",  # other LDAP-side error
    "invalid_correlation_key",  # primary attrs missing the correlation_key value
]


class EnrichmentApplied(BaseModel):
    """LDAP enrichment was attempted and a directory match was returned."""

    applied: Literal[True]
    source: Literal["ldap"]
    cache_hit: bool


class EnrichmentSkipped(BaseModel):
    """LDAP enrichment was not applied (skipped or failed)."""

    applied: Literal[False]
    skip_reason: EnrichmentSkipReason


EnrichmentMetadata = Annotated[
    EnrichmentApplied | EnrichmentSkipped,
    Field(discriminator="applied"),
]


# ============================================================
# Top-level normalized attributes payload
# ============================================================


class NormalizedAttributes(BaseModel):
    """Full payload stored in events.normalized_attributes JSONB.

    Produced by the Identity Normalization Service.
    Consumed by the Risk Evaluator and the Dashboard.

    Readers MUST call NormalizedAttributes.model_validate(jsonb_dict)
    and handle pydantic.ValidationError gracefully: rows written before
    a model change may not conform to the current schema. Risk Evaluator:
    log warning, treat as normalization_risk=1.0, continue. Dashboard:
    surface as a "schema mismatch" placeholder in the Normalization tab.
    """

    # Unified identity attributes
    display_name: str | None = None
    primary_email: str | None = None
    department: str | None = None
    employee_type: Literal["FTE", "contractor", "vendor"] | None = None
    groups: list[str] = Field(default_factory=list)

    # Provenance
    source_protocol: SourceProtocol
    normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    resolution_details: dict[str, ResolutionDetail] = Field(default_factory=dict)

    # Cross-protocol enrichment metadata (always populated; even LDAP events
    # get EnrichmentSkipped(applied=False, skip_reason="ldap_event"))
    enrichment: EnrichmentMetadata


class RiskDecision(BaseModel):
    """Published to decisions Pub/Sub channel."""

    event_id: str
    user_id: str
    rule_based_score: float
    ml_based_score: float | None = None
    final_score: float
    decision: Literal["allow", "step_up_mfa", "deny"]
    contributing_factors: dict[str, Any] = Field(default_factory=dict)
    shadow_decision: str | None = None
    shadow_score: float | None = None
    is_historical: bool = False
    timestamp: datetime


class AlertMessage(BaseModel):
    """Published to alerts Pub/Sub channel."""

    alert_id: str
    event_id: str
    user_id: str
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    decision: str
    final_score: float
    timestamp: datetime


class HealthResponse(BaseModel):
    """Standard health check response for all services."""

    status: Literal["healthy", "degraded", "unhealthy"]
    service: str
    version: str = "2.0.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
