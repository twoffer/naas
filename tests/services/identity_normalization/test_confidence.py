"""resolution.py: overall normalization_confidence calculation across multi-source attributes."""

# third-party
import pytest

from tests.helpers import REPO_ROOT

CONFIG_PATH = REPO_ROOT / "config" / "normalization.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# ATTRIBUTE_IMPORTANCE as specified in §5.5.2 [TRANSCRIBE EXACTLY]
ATTRIBUTE_IMPORTANCE = {
    "display_name": 0.15,
    "primary_email": 0.25,
    "department": 0.20,
    "employee_type": 0.25,
    "groups": 0.15,
}


def _load_real_config():
    from app.normalization_config import load_config

    return load_config(CONFIG_PATH)


def _skip_enrichment():
    from naas_shared.models import EnrichmentSkipped

    return EnrichmentSkipped(applied=False, skip_reason="ldap_event")


def _applied_enrichment(*, cache_hit: bool = False):
    from naas_shared.models import EnrichmentApplied

    return EnrichmentApplied(applied=True, source="ldap", cache_hit=cache_hit)


# ===========================================================================
# CLASS 1 — ATTRIBUTE_IMPORTANCE constants
# ===========================================================================


class TestAttributeImportanceConstants:
    """The module must expose ATTRIBUTE_IMPORTANCE with the exact §5.5.2 values.

    WHY: The confidence formula is an importance-weighted average. A wrong importance
    for primary_email (0.25) would halve or double its contribution to the risk signal.
    The values are [TRANSCRIBE EXACTLY] in the spec.
    """

    def test_attribute_importance_is_exported_from_resolution(self) -> None:
        """app.resolution must expose ATTRIBUTE_IMPORTANCE as a dict."""
        from app import resolution

        importance = getattr(resolution, "ATTRIBUTE_IMPORTANCE", None)
        assert importance is not None, (
            "app.resolution must export ATTRIBUTE_IMPORTANCE. "
            "Spec §5.5.2 marks this [TRANSCRIBE EXACTLY]."
        )
        assert isinstance(importance, dict), (
            f"ATTRIBUTE_IMPORTANCE must be a dict, got {type(importance)!r}."
        )

    def test_attribute_importance_display_name_is_0_15(self) -> None:
        """ATTRIBUTE_IMPORTANCE['display_name'] == 0.15."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        assert ATTRIBUTE_IMPORTANCE.get("display_name") == pytest.approx(0.15), (
            f"Expected ATTRIBUTE_IMPORTANCE['display_name']==0.15, "
            f"got {ATTRIBUTE_IMPORTANCE.get('display_name')!r}."
        )

    def test_attribute_importance_primary_email_is_0_25(self) -> None:
        """ATTRIBUTE_IMPORTANCE['primary_email'] == 0.25."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        assert ATTRIBUTE_IMPORTANCE.get("primary_email") == pytest.approx(0.25), (
            f"Expected ATTRIBUTE_IMPORTANCE['primary_email']==0.25, "
            f"got {ATTRIBUTE_IMPORTANCE.get('primary_email')!r}."
        )

    def test_attribute_importance_department_is_0_20(self) -> None:
        """ATTRIBUTE_IMPORTANCE['department'] == 0.20."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        assert ATTRIBUTE_IMPORTANCE.get("department") == pytest.approx(0.20), (
            f"Expected ATTRIBUTE_IMPORTANCE['department']==0.20, "
            f"got {ATTRIBUTE_IMPORTANCE.get('department')!r}."
        )

    def test_attribute_importance_employee_type_is_0_25(self) -> None:
        """ATTRIBUTE_IMPORTANCE['employee_type'] == 0.25."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        assert ATTRIBUTE_IMPORTANCE.get("employee_type") == pytest.approx(0.25), (
            f"Expected ATTRIBUTE_IMPORTANCE['employee_type']==0.25, "
            f"got {ATTRIBUTE_IMPORTANCE.get('employee_type')!r}."
        )

    def test_attribute_importance_groups_is_0_15(self) -> None:
        """ATTRIBUTE_IMPORTANCE['groups'] == 0.15."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        assert ATTRIBUTE_IMPORTANCE.get("groups") == pytest.approx(0.15), (
            f"Expected ATTRIBUTE_IMPORTANCE['groups']==0.15, "
            f"got {ATTRIBUTE_IMPORTANCE.get('groups')!r}."
        )

    def test_attribute_importance_sums_to_1_0(self) -> None:
        """ATTRIBUTE_IMPORTANCE values must sum to 1.0.

        WHY: An importance sum ≠ 1.0 means the weighted average does not
        represent a proper probability-space confidence.  The spec explicitly
        notes 'sum 1.0' as a constraint.
        """
        from app.resolution import ATTRIBUTE_IMPORTANCE

        total = sum(ATTRIBUTE_IMPORTANCE.values())
        assert total == pytest.approx(1.0), (
            f"Expected ATTRIBUTE_IMPORTANCE values to sum to 1.0, got {total!r}. "
            "Spec §5.5.2: 'weights sum to 1.0'."
        )

    def test_attribute_importance_has_exactly_five_keys(self) -> None:
        """ATTRIBUTE_IMPORTANCE must have exactly the five specified keys."""
        from app.resolution import ATTRIBUTE_IMPORTANCE

        expected_keys = {
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        }
        assert set(ATTRIBUTE_IMPORTANCE.keys()) == expected_keys, (
            f"Expected ATTRIBUTE_IMPORTANCE keys={expected_keys}, "
            f"got {set(ATTRIBUTE_IMPORTANCE.keys())!r}."
        )


# ===========================================================================
# CLASS 2 — Zero and full coverage confidence
# ===========================================================================


class TestConfidenceExtremes:
    """Confidence boundary cases: 0 sources (→ 0.0) and full single-source coverage."""

    def test_zero_sources_confidence_is_zero(self) -> None:
        """normalization_confidence == 0.0 when no attribute has any source.

        WHY: §5.5.2 — 'attributes with no present source contribute 0.0'.
        Returning any positive value would falsely suggest reliable normalization.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert result.normalization_confidence == pytest.approx(0.0), (
            f"Expected normalization_confidence=0.0 for empty attribute_sources, "
            f"got {result.normalization_confidence!r}."
        )

    def test_single_attribute_confidence_is_importance_times_weight(self) -> None:
        """Single primary_email source → confidence = importance × source_weight.

        primary_email importance=0.25, oidc weight=0.95.
        All other attributes absent → 0.0 contribution.
        Overall = 0.25 × 0.95 = 0.2375.

        WHY: Isolates the per-attribute contribution calculation.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"primary_email": {"oidc": "alice@corp.com"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        expected = 0.25 * 0.95
        assert result.normalization_confidence == pytest.approx(expected), (
            f"Expected confidence={expected} (primary_email importance×oidc_weight), "
            f"got {result.normalization_confidence!r}."
        )

    def test_two_attribute_confidence_additive(self) -> None:
        """Two attributes present → confidence = sum of their importance×weight products.

        display_name (oidc, weight=0.70): 0.15 × 0.70 = 0.105
        primary_email (oidc, weight=0.95): 0.25 × 0.95 = 0.2375
        total = 0.3425
        WHY: Additivity of the weighted average is the core formula invariant.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice"},
                "primary_email": {"oidc": "alice@corp.com"},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        expected = 0.15 * 0.70 + 0.25 * 0.95
        assert result.normalization_confidence == pytest.approx(expected, rel=1e-4), (
            f"Expected confidence={expected:.4f} for two attributes, "
            f"got {result.normalization_confidence!r}."
        )


# ===========================================================================
# CLASS 3 — Partial presence (absent attributes contribute 0.0)
# ===========================================================================


class TestPartialPresenceConfidence:
    """Absent attributes contribute exactly 0.0 — not the default weight, not 1.0.

    WHY: §5.5.2 — 'attributes with no present source contribute 0.0'.
    If absent attributes contributed anything positive, a user with only one
    attribute present would still get an inflated confidence score.
    """

    def test_absent_attribute_does_not_contribute_to_confidence(self) -> None:
        """Only present attributes contribute; absent ones are 0.0.

        employee_type absent: contributes 0.0 (not 0.25 × some_default_weight).
        Present attributes: display_name (oidc, 0.70), primary_email (oidc, 0.95).
        Expected = 0.15×0.70 + 0.25×0.95 + 0.0 + 0.0 + 0.0 = 0.3425.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice"},
                "primary_email": {"oidc": "alice@corp.com"},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        # Confirm employee_type is absent
        assert "employee_type" not in result.resolution_details, (
            "employee_type must not appear in resolution_details when absent."
        )

        expected = 0.15 * 0.70 + 0.25 * 0.95
        assert result.normalization_confidence == pytest.approx(expected, rel=1e-4), (
            f"Absent employee_type must contribute 0.0, not boost confidence. "
            f"Expected {expected:.4f}, got {result.normalization_confidence!r}."
        )

    def test_all_five_attributes_from_single_oidc_source(self) -> None:
        """All five attributes from a single oidc source.

        Each attribute's confidence = weight_for(attr, 'oidc'):
          display_name: 0.70,  primary_email: 0.95,  department: 0.70 (mapped)
          employee_type: 0.60,  groups: 0.80 (default)
        Overall = 0.15×0.70 + 0.25×0.95 + 0.20×0.70 + 0.25×0.60 + 0.15×0.80
                = 0.105 + 0.2375 + 0.140 + 0.150 + 0.120
                = 0.7525
        WHY: The all-single-source baseline for an oidc-only event.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice"},
                "primary_email": {"oidc": "alice@corp.com"},
                "department": {"oidc": ("Engineering", True)},
                "employee_type": {"oidc": "FTE"},
                "groups": {"oidc": ["admin"]},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        expected = (
            0.15 * 0.70  # display_name oidc
            + 0.25 * 0.95  # primary_email oidc
            + 0.20 * 0.70  # department oidc (mapped, no penalty)
            + 0.25 * 0.60  # employee_type oidc
            + 0.15 * 0.80  # groups oidc (default weight)
        )
        assert result.normalization_confidence == pytest.approx(expected, rel=1e-4), (
            f"Expected confidence={expected:.4f} for all-oidc single-source event, "
            f"got {result.normalization_confidence!r}."
        )


# ===========================================================================
# CLASS 4 — §3.3 representative example confidence
# ===========================================================================


class TestSpec33ConfidenceExample:
    """Reproduce the §3.3 normalization_confidence example.

    §3.3 payload (enriched OIDC event, department conflict):
      display_name:   unanimous(oidc+ldap) → per_attr_conf = max(0.70, 0.85) = 0.85
      primary_email:  unanimous(oidc+ldap) → per_attr_conf = max(0.95, 0.65) = 0.95
      department:     priority(ldap wins)  → per_attr_conf = 0.90 × 0.8 = 0.72
      employee_type:  unanimous(oidc+ldap) → per_attr_conf = max(0.60, 0.95) = 0.95
      groups:         list_merge           → per_attr_conf depends on formula

    normalization_confidence =
      0.15×0.85 + 0.25×0.95 + 0.20×0.72 + 0.25×0.95 + 0.15×groups_conf

    With groups conf = 0.90 (from the §5.5 formula for the §3.3 groups):
      = 0.1275 + 0.2375 + 0.144 + 0.2375 + 0.15×0.90
      = 0.1275 + 0.2375 + 0.144 + 0.2375 + 0.135 = 0.8815

    The §3.3 payload is ILLUSTRATIVE.
    This test verifies the FORMULA output for the §3.3 input, not the
    illustrative value.

    ENCODED INTERPRETATION: Tests assert the formula result, not an illustrative value.
    """

    def test_spec33_style_event_confidence_formula(self) -> None:
        """Compute normalization_confidence for the §3.3-style input fixture.

        Inputs (matching §3.3 scenario):
          display_name  unanimous oidc+ldap → conf = max(0.70, 0.85) = 0.85
          primary_email unanimous oidc+ldap → conf = max(0.95, 0.65) = 0.95
          department    priority ldap wins  → conf = 0.90 × 0.8 = 0.72
          employee_type unanimous oidc+ldap → conf = max(0.60, 0.95) = 0.95
          groups        oidc+ldap union with fraction 2/3 shared
                        oidc=['admin','vpn-users'] ldap=['admin','engineering','vpn-users']
                        union=['admin','engineering','vpn-users'] (3 groups)
                        shared: admin, vpn-users (2 of 3) → fraction=2/3
                        groups_conf = 0.7 + 0.3×(2/3) = 0.90

        Expected:
          0.15×0.85 + 0.25×0.95 + 0.20×0.72 + 0.25×0.95 + 0.15×0.90
          = 0.1275 + 0.2375 + 0.144 + 0.2375 + 0.135 = 0.8815
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice Smith", "ldap": "Alice Smith"},
                "primary_email": {"oidc": "alice@corp.com", "ldap": "alice@corp.com"},
                "department": {
                    "ldap": ("Engineering", True),
                    "oidc": ("Product", False),
                },
                "employee_type": {"oidc": "FTE", "ldap": "FTE"},
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering", "vpn-users"],
                },
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        # Per-attribute confidences from the formula:
        # display_name:  unanimous, conf = max(0.70, 0.85) = 0.85
        # primary_email: unanimous, conf = max(0.95, 0.65) = 0.95
        # department:    priority ldap, conf = 0.90 × 0.8 = 0.72
        # employee_type: unanimous, conf = max(0.60, 0.95) = 0.95
        # groups:        list_merge, 2/3 shared → 0.7 + 0.3×(2/3) = 0.90
        expected = (
            0.15 * 0.85  # display_name
            + 0.25 * 0.95  # primary_email
            + 0.20 * 0.72  # department (priority, 0.2 penalty encoded in 0.72)
            + 0.25 * 0.95  # employee_type
            + 0.15 * 0.90  # groups
        )
        assert result.normalization_confidence == pytest.approx(expected, rel=1e-3), (
            f"Expected normalization_confidence≈{expected:.4f} for §3.3 scenario, "
            f"got {result.normalization_confidence!r}. "
            "§5.5.2 formula with the §5.6 display_name weights."
        )

    def test_normalization_confidence_is_clamped_to_unit_interval(self) -> None:
        """normalization_confidence must be in [0.0, 1.0] even if raw formula exceeds bounds.

        WHY: The formula can produce values > 1.0 if there are penalties applied
        and importances/weights add up unusually; Pydantic Field(ge=0.0, le=1.0)
        also enforces this.  This test exercises the explicit clamp in §5.5.2:
        'normalization_confidence = max(0.0, min(1.0, confidence))'.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        # All attributes with highest-weight unanimous sources → sum ≤ 1.0
        # With max weights: 0.15×0.85 + 0.25×0.95 + 0.20×0.90 + 0.25×0.95 + 0.15×0.80
        #   = 0.1275 + 0.2375 + 0.18 + 0.2375 + 0.12 = 0.9025 — stays within bounds
        result = resolve(
            attribute_sources={
                "display_name": {"ldap": "Alice Smith"},
                "primary_email": {"oidc": "alice@corp.com"},
                "department": {"ldap": ("Engineering", True)},
                "employee_type": {"ldap": "FTE"},
                "groups": {"oidc": ["admin"]},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert 0.0 <= result.normalization_confidence <= 1.0, (
            f"normalization_confidence must be in [0.0, 1.0], "
            f"got {result.normalization_confidence!r}."
        )


# ===========================================================================
# CLASS 5 — Department priority resolution confidence contribution (§3.3)
# ===========================================================================


class TestDepartmentPriorityConfidenceContribution:
    """The priority resolution confidence (winner_weight × 0.8) flows into the overall score.

    WHY: §5.5 and §5.5.2 must be consistent — the per-attribute confidence used in
    resolution_details.confidence MUST be the same value used in the normalization_confidence
    weighted sum.  A disconnect (using full weight in the global sum but ×0.8 in the detail)
    would give a misleading overall confidence.
    """

    def test_department_priority_confidence_matches_overall_contribution(self) -> None:
        """The per-attribute confidence in resolution_details matches its contribution in overall.

        department priority ldap wins → detail.confidence = 0.90 × 0.8 = 0.72.
        Overall = IMPORTANCE['department'] × detail.confidence = 0.20 × 0.72 = 0.144.
        With only department present, normalization_confidence = 0.144.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("Engineering", True),
                    "oidc": ("Finance", True),
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, PriorityResolution)

        # Per-attribute confidence from resolution
        per_attr_conf = detail.confidence
        # Overall must be importance × per_attr_conf (only department present)
        expected_overall = 0.20 * per_attr_conf
        assert result.normalization_confidence == pytest.approx(
            expected_overall, rel=1e-4
        ), (
            f"Expected normalization_confidence=0.20×{per_attr_conf:.2f}={expected_overall:.4f}, "
            f"got {result.normalization_confidence!r}. "
            "Per-attribute confidence in resolution_details must be the same value "
            "used in the overall importance-weighted sum."
        )
