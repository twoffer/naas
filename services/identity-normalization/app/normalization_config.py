"""Normalization configuration model, loader, and startup validation.

Spec §5.6: loads config/normalization.yaml at startup, validates it, and
exposes accessor helpers used by the conflict-resolution layer (§5.5).
Invalid config aborts startup with a descriptive error.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from app.normalization_values import UNIFIED_TO_LDAP

_VALID_UNIFIED_FIELDS: frozenset[str] = frozenset(UNIFIED_TO_LDAP.keys())


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AttributeConfig(BaseModel):
    """Per-attribute authority weight and resolution configuration."""

    priority: Optional[list[str]] = None
    weights: Optional[dict[str, float]] = None
    merge_strategy: Optional[Literal["union", "intersection", "priority"]] = None
    rationale: str = ""


class Defaults(BaseModel):
    """Global fallback weights applied when an attribute has no explicit entry."""

    source_weights: dict[str, float]


class LdapEnrichmentConfig(BaseModel):
    """LDAP enrichment sub-configuration (enrichment.sources.ldap in §5.6)."""

    enabled: bool
    correlation_key: str
    timeout_ms: int
    on_failure: str
    cache_ttl_seconds: int = Field(gt=0)
    enrich_attributes: Optional[list[str]] = None


class EnrichmentSources(BaseModel):
    """Container for protocol-specific enrichment source configs."""

    ldap: LdapEnrichmentConfig


class EnrichmentConfig(BaseModel):
    """Top-level enrichment configuration block."""

    sources: EnrichmentSources


class NormalizationConfig(BaseModel):
    """Root configuration model for the Identity Normalization Service.

    Wraps the parsed normalization.yaml and exposes accessor helpers that
    every conflict-resolution call uses to look up authority weights and
    priority ordering.
    """

    defaults: Defaults
    attributes: dict[str, AttributeConfig]
    enrichment: EnrichmentConfig

    def weight_for(self, attribute: str, source: str) -> float:
        """Return the authority weight for (attribute, source).

        Falls back to defaults.source_weights[source] when:
        - the attribute has no entry in the attributes block, or
        - the attribute's weights block does not include the source.

        WHY: Ensures callers never receive KeyError; new protocols or attributes
        degrade gracefully to default weights rather than crashing resolution.
        """
        attr_cfg = self.attributes.get(attribute)
        if attr_cfg is not None and attr_cfg.weights is not None:
            if source in attr_cfg.weights:
                return attr_cfg.weights[source]
        return self.defaults.source_weights[source]

    def priority_for(self, attribute: str) -> list[str]:
        """Return the priority-ordered source list for an attribute.

        Returns [] when no priority is configured — callers use this to detect
        the 'weight-based winner selection' fallback path (§5.5).
        """
        attr_cfg = self.attributes.get(attribute)
        if attr_cfg is not None and attr_cfg.priority is not None:
            return attr_cfg.priority
        return []

    def merge_strategy_for(self, attribute: str) -> str:
        """Return the merge strategy for a list attribute.

        Returns 'union' (the §5.5 default) when no strategy is configured.
        """
        attr_cfg = self.attributes.get(attribute)
        if attr_cfg is not None and attr_cfg.merge_strategy is not None:
            return attr_cfg.merge_strategy
        return "union"


# ---------------------------------------------------------------------------
# Loader with startup validation
# ---------------------------------------------------------------------------


def load_config(path: Path) -> NormalizationConfig:
    """Load and validate normalization.yaml; raise on any invalid value.

    Spec §5.6: invalid config must abort startup with a descriptive error.
    Callers in main.py must NOT swallow the raised exception.

    Raises:
        ValueError: with a message naming the offending value on any validation
            failure (invalid correlation_key, on_failure, cache_ttl_seconds,
            or enrich_attributes entry).
        FileNotFoundError: if the path does not exist.
        yaml.YAMLError: if the file is not valid YAML.
        pydantic.ValidationError: if structural schema validation fails.
    """
    with open(path) as fh:
        raw = yaml.safe_load(fh)

    cfg = NormalizationConfig.model_validate(raw)

    _validate_ldap_enrichment(cfg.enrichment.sources.ldap)

    return cfg


def _validate_ldap_enrichment(ldap_cfg: LdapEnrichmentConfig) -> None:
    """Apply §5.6 startup validation rules to the LDAP enrichment sub-config.

    WHY: Pydantic enforces structural types (e.g. int for cache_ttl_seconds via
    Field(gt=0)) but §5.6 requires domain-semantic checks that reference
    UNIFIED_TO_LDAP — the single source of truth for reverse-mappable fields.
    These checks are kept here (not on the model) to keep UNIFIED_TO_LDAP as
    the only copy of the valid-field set.
    """
    # (a) correlation_key must be a reverse-mappable unified field
    if ldap_cfg.correlation_key not in _VALID_UNIFIED_FIELDS:
        raise ValueError(
            f"Invalid correlation_key {ldap_cfg.correlation_key!r}: must be one of "
            f"{sorted(_VALID_UNIFIED_FIELDS)}. "
            "This field is reverse-mapped to an LDAP attribute at enrichment time."
        )

    # (b) on_failure must be in the closed set
    _valid_on_failure = {"continue", "fail"}
    if ldap_cfg.on_failure not in _valid_on_failure:
        raise ValueError(
            f"Invalid on_failure {ldap_cfg.on_failure!r}: must be one of "
            f"{sorted(_valid_on_failure)}."
        )

    # (c) enrich_attributes — if present, every entry must be reverse-mappable
    if ldap_cfg.enrich_attributes is not None:
        bad = [f for f in ldap_cfg.enrich_attributes if f not in _VALID_UNIFIED_FIELDS]
        if bad:
            raise ValueError(
                f"enrich_attributes contains unrecognised unified field(s): {bad}. "
                f"Valid fields are {sorted(_VALID_UNIFIED_FIELDS)}."
            )

    # (d) cache_ttl_seconds > 0 is enforced by Pydantic Field(gt=0); the error
    #     message from Pydantic already references cache_ttl_seconds and the value.
    #     No extra check needed here — ValidationError propagates from model_validate.
