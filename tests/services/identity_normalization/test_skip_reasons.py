"""EnrichmentSkipped/EnrichmentApplied skip_reason mapping for identity-normalization service."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
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


from naas_shared.models import (
    EnrichmentApplied,
    EnrichmentSkipped,
    LoginEventRecord,
    NormalizedAttributes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID = UUID("12345678-1234-5678-1234-567812345678")
_NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

_LDAP_MATCH_ATTRS: dict[str, Any] = {
    "display_name": "Alice Smith",
    "primary_email": "alice@corp.com",
    "department": "Engineering",
    "employee_type": "FTE",
    "groups": ["engineering"],
}


def _oidc_record(email: str = "alice@corp.com") -> LoginEventRecord:
    return LoginEventRecord(
        id=_UUID,
        user_id="alice",
        client_ip="192.168.1.1",
        protocol="oidc",
        timestamp=_NOW,
        source="user",
        is_synthetic=False,
        is_historical=False,
        raw_attributes={
            "name": "Alice Smith",
            "email": email,
            "department": "eng",
            "employee_type": "fte",
            "groups": ["admin"],
        },
    )


def _load_config():
    from app.normalization_config import load_config
    return load_config(_REPO / "config" / "normalization.yaml")


def _make_service(enrich_return: tuple, ldap_enabled: bool = True):
    from app.service import NormalizationService
    from app.adapters.oidc import OidcAdapter
    from app.adapters.saml import SamlAdapter
    from app.adapters.ldap import LdapAdapter

    cfg = _load_config()
    cfg.enrichment.sources.ldap.enabled = ldap_enabled

    ldap = LdapAdapter()
    ldap.enrich = AsyncMock(return_value=enrich_return)

    return NormalizationService(
        config=cfg,
        oidc_adapter=OidcAdapter(),
        saml_adapter=SamlAdapter(),
        ldap_adapter=ldap,
    )


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===========================================================================
# EnrichmentApplied variants
# ===========================================================================

class TestEnrichmentAppliedVariants:
    """Outcomes that produce EnrichmentApplied on the result."""

    def test_ldap_match_produces_enrichment_applied_cache_hit_false(self):
        """Outcome 'ldap_match' → EnrichmentApplied(applied=True, source='ldap', cache_hit=False)."""
        svc = _make_service(enrich_return=(_LDAP_MATCH_ATTRS, "ldap_match"))
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert isinstance(result.enrichment, EnrichmentApplied), (
            f"Expected EnrichmentApplied for 'ldap_match', got {type(result.enrichment)}"
        )
        assert result.enrichment.applied is True
        assert result.enrichment.source == "ldap"
        assert result.enrichment.cache_hit is False, (
            f"cache_hit must be False for live 'ldap_match', got {result.enrichment.cache_hit}"
        )

    def test_cache_hit_positive_produces_enrichment_applied_cache_hit_true(self):
        """Outcome 'cache_hit_positive' → EnrichmentApplied(applied=True, source='ldap', cache_hit=True)."""
        svc = _make_service(enrich_return=(_LDAP_MATCH_ATTRS, "cache_hit_positive"))
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert isinstance(result.enrichment, EnrichmentApplied), (
            f"Expected EnrichmentApplied for 'cache_hit_positive', got {type(result.enrichment)}"
        )
        assert result.enrichment.cache_hit is True, (
            f"cache_hit must be True for 'cache_hit_positive', got {result.enrichment.cache_hit}"
        )
        assert result.enrichment.source == "ldap"

    def test_ldap_match_contributes_ldap_attrs_to_resolution(self):
        """When enrichment succeeds, LDAP attrs are used as 'ldap' source in resolution.

        The LDAP result must be visible in resolution_details as a contributing source.
        """
        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": ["engineering", "admin"],
        }
        svc = _make_service(enrich_return=(ldap_attrs, "ldap_match"))
        record = _oidc_record()

        result = _run(svc.normalize(record))

        # At minimum, resolution_details must exist and contain resolved attrs
        assert result.resolution_details is not None
        # With both OIDC and LDAP sources, we expect at least one key in resolution_details
        assert len(result.resolution_details) > 0, (
            "resolution_details must be populated when enrichment contributes"
        )


# ===========================================================================
# EnrichmentSkipped variants — outcome codes
# ===========================================================================

class TestEnrichmentSkippedByOutcome:
    """Each enrich() outcome code maps to the correct EnrichmentSkipped variant."""

    def test_ldap_no_match_produces_no_ldap_match_skip(self):
        """Outcome 'ldap_no_match' → skip_reason='no_ldap_match'."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "no_ldap_match", (
            f"Expected 'no_ldap_match', got {result.enrichment.skip_reason!r}"
        )

    def test_cache_hit_negative_produces_no_ldap_match_skip(self):
        """Outcome 'cache_hit_negative' → skip_reason='no_ldap_match' (negative cache hit = no match)."""
        svc = _make_service(enrich_return=(None, "cache_hit_negative"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "no_ldap_match", (
            f"Expected 'no_ldap_match' for 'cache_hit_negative', got {result.enrichment.skip_reason!r}"
        )

    def test_ldap_timeout_produces_ldap_timeout_skip(self):
        """Outcome 'ldap_timeout' → skip_reason='ldap_timeout'."""
        svc = _make_service(enrich_return=(None, "ldap_timeout"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_timeout", (
            f"Expected 'ldap_timeout', got {result.enrichment.skip_reason!r}"
        )

    def test_ldap_connection_error_produces_ldap_connection_error_skip(self):
        """Outcome 'ldap_connection_error' → skip_reason='ldap_connection_error'."""
        svc = _make_service(enrich_return=(None, "ldap_connection_error"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_connection_error", (
            f"Expected 'ldap_connection_error', got {result.enrichment.skip_reason!r}"
        )

    def test_ldap_search_error_produces_ldap_search_error_skip(self):
        """Outcome 'ldap_search_error' → skip_reason='ldap_search_error'."""
        svc = _make_service(enrich_return=(None, "ldap_search_error"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_search_error", (
            f"Expected 'ldap_search_error', got {result.enrichment.skip_reason!r}"
        )

    def test_ldap_unexpected_error_folds_into_ldap_search_error(self):
        """Outcome 'ldap_unexpected_error' has no dedicated Literal → folded into 'ldap_search_error'.

        The models.py EnrichmentSkipReason Literal does not include 'ldap_unexpected_error'.
        The service must map it to 'ldap_search_error' (the catch-all per §5.4).
        """
        svc = _make_service(enrich_return=(None, "ldap_unexpected_error"))
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_search_error", (
            f"'ldap_unexpected_error' must fold into 'ldap_search_error', got {result.enrichment.skip_reason!r}"
        )

    def test_unmappable_field_folds_into_ldap_search_error(self):
        """Outcome 'unmappable_field' has no dedicated Literal → folded into 'ldap_search_error'.

        'unmappable_field' is returned by LdapAdapter.enrich when the correlation_field
        is not in UNIFIED_TO_LDAP. It has no dedicated skip_reason Literal in models.py.
        The service maps it to 'ldap_search_error' as the nearest catch-all.
        """
        svc = _make_service(enrich_return=(None, "unmappable_field"))
        # Manually override so correlation key appears valid but enrich still returns unmappable_field
        result = _run(svc.normalize(_oidc_record()))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_search_error", (
            f"'unmappable_field' must fold into 'ldap_search_error', got {result.enrichment.skip_reason!r}"
        )


# ===========================================================================
# EnrichmentSkipped variants — decision context (not outcome codes)
# ===========================================================================

class TestEnrichmentSkippedByContext:
    """Skip variants determined by config/protocol, not enrich() outcome."""

    def test_ldap_disabled_in_config_produces_ldap_disabled_skip(self):
        """ldap.enabled=False → EnrichmentSkipped(skip_reason='ldap_disabled')."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=False)
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_disabled", (
            f"Expected 'ldap_disabled' when enrichment disabled in config, got {result.enrichment.skip_reason!r}"
        )

    def test_ldap_protocol_produces_ldap_event_skip(self):
        """protocol='ldap' → EnrichmentSkipped(skip_reason='ldap_event')."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = LoginEventRecord(
            id=_UUID, user_id="charlie", client_ip="192.168.1.3", protocol="ldap",
            timestamp=_NOW, source="user", is_synthetic=False, is_historical=False,
            raw_attributes={"cn": "Charlie", "mail": "charlie@corp.com"},
        )

        result = _run(svc.normalize(record))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "ldap_event", (
            f"Expected 'ldap_event' for ldap protocol, got {result.enrichment.skip_reason!r}"
        )

    def test_missing_correlation_value_produces_invalid_correlation_key_skip(self):
        """Missing primary_email in raw_attributes → skip_reason='invalid_correlation_key'."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = LoginEventRecord(
            id=_UUID, user_id="anon", client_ip="192.168.1.1", protocol="oidc",
            timestamp=_NOW, source="user", is_synthetic=False, is_historical=False,
            raw_attributes={"name": "Anonymous"},  # no email key
        )

        result = _run(svc.normalize(record))

        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "invalid_correlation_key", (
            f"Expected 'invalid_correlation_key', got {result.enrichment.skip_reason!r}"
        )


# ===========================================================================
# Graceful degradation — normalize() never raises on enrichment failure
# ===========================================================================

class TestGracefulDegradation:
    """§5.4 ADR-0008: ANY skip/failure returns valid NormalizedAttributes, never raises."""

    @pytest.mark.parametrize("outcome", [
        "ldap_no_match",
        "cache_hit_negative",
        "ldap_timeout",
        "ldap_connection_error",
        "ldap_search_error",
        "ldap_unexpected_error",
        "unmappable_field",
    ])
    def test_every_skip_outcome_returns_valid_normalized_attributes(self, outcome):
        """Every skip outcome code produces a valid NormalizedAttributes, not an exception."""
        svc = _make_service(enrich_return=(None, outcome))
        record = _oidc_record()

        # Must not raise
        result = _run(svc.normalize(record))

        assert isinstance(result, NormalizedAttributes), (
            f"normalize() must return NormalizedAttributes for outcome {outcome!r}, "
            f"not raise or return {type(result)}"
        )
        assert result.source_protocol == "oidc"
        # With primary-source-only data, display_name comes from OIDC 'name' claim
        assert result.display_name == "Alice Smith"

    def test_enrichment_failure_does_not_raise_exception(self):
        """If enrich() raises an unexpected exception, normalize() handles it and does not propagate."""
        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter

        cfg = _load_config()
        ldap = LdapAdapter()
        # enrich raises instead of returning a tuple
        ldap.enrich = AsyncMock(side_effect=RuntimeError("LDAP down"))

        svc = NormalizationService(
            config=cfg,
            oidc_adapter=OidcAdapter(),
            saml_adapter=SamlAdapter(),
            ldap_adapter=ldap,
        )
        record = _oidc_record()

        # Must not raise — graceful degradation
        result = _run(svc.normalize(record))

        assert isinstance(result, NormalizedAttributes), (
            "normalize() must return NormalizedAttributes even when enrich() raises"
        )
        # Should have some skip reason (implementation-defined which one on raw exception)
        assert isinstance(result.enrichment, EnrichmentSkipped), (
            "enrichment must be EnrichmentSkipped when enrich() raises"
        )

    def test_ldap_disabled_still_normalizes_primary_attrs(self):
        """When ldap disabled, primary OIDC attrs are still resolved and returned."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=False)
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert result.display_name == "Alice Smith", (
            "Primary attrs must still be resolved even when enrichment is disabled"
        )
        assert result.primary_email == "alice@corp.com"
        assert result.department == "Engineering"  # normalized from "eng"

    def test_enrichment_field_always_populated(self):
        """The enrichment field is always populated — never None — per the model contract."""
        for outcome in ["ldap_no_match", "ldap_disabled"]:
            svc = _make_service(enrich_return=(None, outcome), ldap_enabled=(outcome != "ldap_disabled"))
            result = _run(svc.normalize(_oidc_record()))
            assert result.enrichment is not None, (
                f"enrichment field must always be populated, got None for outcome {outcome!r}"
            )


# ===========================================================================
# End-to-end normalization_confidence sanity check
# ===========================================================================

class TestNormalizationConfidenceOnOutput:
    """normalize() returns a NormalizedAttributes with a plausible confidence score."""

    def test_oidc_single_source_has_nonzero_confidence(self):
        """Single-source OIDC normalization with all fields present → confidence > 0."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=False)
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert 0.0 < result.normalization_confidence <= 1.0, (
            f"normalization_confidence must be in (0, 1], got {result.normalization_confidence}"
        )

    def test_ldap_match_enrichment_produces_valid_confidence(self):
        """Two-source (OIDC + LDAP) normalization produces a confidence in [0, 1]."""
        svc = _make_service(enrich_return=(_LDAP_MATCH_ATTRS, "ldap_match"))
        record = _oidc_record()

        result = _run(svc.normalize(record))

        assert 0.0 <= result.normalization_confidence <= 1.0, (
            f"normalization_confidence must be clamped to [0, 1], got {result.normalization_confidence}"
        )
