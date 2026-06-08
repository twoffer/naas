"""resolution.py: scalar attribute resolution with priority, unanimous, and single_source discriminators."""

from pathlib import Path

# third-party
import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------




def _find_repo_root() -> Path:
    """Walk up until docs/architecture/ is found — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Could not locate repo root from {Path(__file__).resolve()}")

REPO_ROOT = _find_repo_root()

CONFIG_PATH = REPO_ROOT / "config" / "normalization.yaml"



# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_real_config():
    """Load the committed config/normalization.yaml via load_config()."""
    from app.normalization_config import load_config

    return load_config(CONFIG_PATH)


def _skip_enrichment():
    """Return an EnrichmentSkipped with skip_reason='ldap_event' for use as a passthrough param."""
    from naas_shared.models import EnrichmentSkipped

    return EnrichmentSkipped(applied=False, skip_reason="ldap_event")


def _applied_enrichment(*, cache_hit: bool = False):
    """Return an EnrichmentApplied for use as a passthrough param."""
    from naas_shared.models import EnrichmentApplied

    return EnrichmentApplied(applied=True, source="ldap", cache_hit=cache_hit)


# ===========================================================================
# CLASS 1 — Module importability
# ===========================================================================


class TestResolutionModuleImport:
    """app.resolution must be importable and expose a callable resolve().

    WHY: An ImportError means the NormalizationService cannot start.
    A missing module surfaces as a clear failure rather than a collection error.
    """

    def test_resolution_module_is_importable(self) -> None:
        """from app.resolution import resolve must not raise.

        WHY: A missing module surfaces as a clear failure rather than a collection error.
        """
        import app.resolution  # noqa: F401

    def test_resolve_callable_is_exported(self) -> None:
        """app.resolution must expose a callable named resolve."""
        from app import resolution

        assert callable(getattr(resolution, "resolve", None)), (
            "app.resolution must define and export a callable resolve(). "
            "Spec §5.5: this is the algorithmic core entry point."
        )


# ===========================================================================
# CLASS 2 — Zero sources (no present source for a scalar attribute)
# ===========================================================================


class TestZeroSources:
    """Attributes with 0 present sources → None value, no resolution_details entry.

    WHY spec §5.5: 'the unified attribute is None; it contributes 0.0 to the
    overall confidence; and no entry is written to resolution_details.'
    """

    def test_display_name_absent_when_zero_sources(self) -> None:
        """display_name=None when no source supplied it.

        WHY: If absent attributes defaulted to an empty string or omitted key,
        downstream consumers (Risk Evaluator, Dashboard) would misread it.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert result.display_name is None, (
            f"Expected display_name=None when no source supplied it, got {result.display_name!r}."
        )

    def test_zero_source_attribute_omitted_from_resolution_details(self) -> None:
        """An attribute with 0 sources must NOT appear in resolution_details.

        WHY: §5.5 explicitly states 'no entry is written to resolution_details'.
        An extra key would force downstream deserialization to handle a None-value
        resolution variant that the discriminated union does not support.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        for attr in ("display_name", "primary_email", "department", "employee_type"):
            assert attr not in result.resolution_details, (
                f"Expected '{attr}' absent from resolution_details when no source present, "
                f"got keys: {list(result.resolution_details.keys())}."
            )

    def test_zero_sources_all_attrs_produces_valid_normalized_attributes(self) -> None:
        """All-absent attribute_sources returns a valid NormalizedAttributes.

        WHY: Pydantic validation must pass even when all fields are None/empty.
        A failed validation here would crash the NormalizationService for events
        where the adapter produced no usable attributes at all.
        """
        from app.resolution import resolve
        from naas_shared.models import NormalizedAttributes

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        assert isinstance(result, NormalizedAttributes), (
            f"Expected NormalizedAttributes instance, got {type(result)!r}."
        )

    def test_zero_sources_normalization_confidence_near_zero(self) -> None:
        """normalization_confidence == 0.0 when all attributes have zero sources.

        WHY: §5.5.2 — 'attributes with no present source contribute 0.0'.
        Returning 1.0 or any positive value for a fully-absent record would
        suppress the Risk Evaluator's normalization_risk penalty.
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
            f"Expected normalization_confidence==0.0 for all-absent record, "
            f"got {result.normalization_confidence!r}."
        )


# ===========================================================================
# CLASS 3 — Single source (one present source → SingleSourceResolution)
# ===========================================================================


class TestSingleSourceResolution:
    """Exactly 1 present source → SingleSourceResolution with correct weight as confidence.

    WHY spec §5.5: 'SingleSourceResolution(resolution="single_source",
    resolved_value=<value>, confidence=<source weight for this attribute>,
    sources=[that one protocol])'.
    """

    def test_single_source_display_name_oidc(self) -> None:
        """display_name from single oidc source → SingleSourceResolution, confidence=0.60.

        WHY: display_name.weights.oidc == 0.60 per §5.6.  Using the default 0.8
        would overstate OIDC authority for legal-name attributes.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"oidc": "Alice Smith"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details.get("display_name")
        assert detail is not None, "display_name must appear in resolution_details when one source is present."
        assert isinstance(detail, SingleSourceResolution), (
            f"Expected SingleSourceResolution for single-source display_name, got {type(detail)!r}."
        )
        assert detail.resolved_value == "Alice Smith", (
            f"Expected resolved_value='Alice Smith', got {detail.resolved_value!r}."
        )
        assert detail.confidence == pytest.approx(0.60), (
            f"Expected confidence=0.60 (display_name.weights.oidc), got {detail.confidence!r}."
        )
        assert detail.sources == ["oidc"], (
            f"Expected sources=['oidc'], got {detail.sources!r}."
        )

    def test_single_source_primary_email_oidc_weight(self) -> None:
        """primary_email from oidc → confidence == 0.95.

        WHY: primary_email.weights.oidc == 0.95 per §5.6 — highest weight because
        OIDC has the most current email.  Returning 0.8 (default) would understate
        OIDC's authority for the most security-sensitive field.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"primary_email": {"oidc": "alice@corp.com"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["primary_email"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.confidence == pytest.approx(0.95), (
            f"Expected 0.95 for primary_email single-source oidc, got {detail.confidence!r}."
        )

    def test_single_source_department_ldap_mapped_value(self) -> None:
        """department from ldap with was_mapped=True → confidence == 0.90 (no penalty).

        WHY: §5.5 — penalty applies only when the winning value is unmapped.
        A mapped LDAP department value at full confidence 0.90 is the normal path.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"department": {"ldap": ("Engineering", True)}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.resolved_value == "Engineering"
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected 0.90 for single-source mapped department from ldap, got {detail.confidence!r}."
        )

    def test_single_source_employee_type_ldap_weight(self) -> None:
        """employee_type from ldap → confidence == 0.95.

        WHY: employee_type.weights.ldap == 0.95 — HR system most authoritative.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"employee_type": {"ldap": "FTE"}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["employee_type"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.confidence == pytest.approx(0.95), (
            f"Expected 0.95 for employee_type single-source ldap, got {detail.confidence!r}."
        )
        assert detail.resolved_value == "FTE"

    def test_single_source_saml_display_name_weight(self) -> None:
        """display_name from saml → confidence == 0.70 per §5.6."""
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"saml": "Bob Jones"}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.confidence == pytest.approx(0.70), (
            f"Expected 0.70 for display_name single-source saml, got {detail.confidence!r}."
        )

    def test_single_source_result_has_correct_resolution_literal(self) -> None:
        """SingleSourceResolution.resolution field must be exactly 'single_source'.

        WHY: The discriminated union uses this literal as the discriminator.
        Any other value ('single', 'one_source', etc.) would fail Pydantic validation
        and crash the downstream NormalizedAttributes consumers.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"primary_email": {"saml": "user@example.com"}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["primary_email"]
        assert detail.resolution == "single_source", (
            f"Expected resolution='single_source', got {detail.resolution!r}. "
            "§5.5: exactly four resolution literals are permitted."
        )


# ===========================================================================
# CLASS 4 — Two+ sources agreeing (UnanimousResolution)
# ===========================================================================


class TestUnanimousResolution:
    """≥2 present sources with identical normalized values → UnanimousResolution.

    WHY spec §5.5: 'confidence=max authority weight among the agreeing sources'.
    A unanimous resolution should have higher confidence than a single-source
    because multiple independent systems agree — the max-weight reflects the
    most authoritative agreement.
    """

    def test_unanimous_display_name_oidc_ldap_confidence_is_max_weight(self) -> None:
        """display_name: oidc=0.60, ldap=0.90 → unanimous confidence=max=0.90.

        WHY: §3.3 example shows display_name unanimous with sources [oidc, ldap],
        confidence=0.90 (ldap weight, the higher of the two).
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"oidc": "Alice Smith", "ldap": "Alice Smith"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, UnanimousResolution), (
            f"Expected UnanimousResolution for agreeing oidc+ldap, got {type(detail)!r}."
        )
        assert detail.resolved_value == "Alice Smith"
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected confidence=0.90 (max of oidc=0.60, ldap=0.90), got {detail.confidence!r}."
        )
        assert set(detail.sources) == {"oidc", "ldap"}, (
            f"Expected sources={{oidc, ldap}}, got {detail.sources!r}."
        )

    def test_unanimous_primary_email_oidc_ldap_confidence(self) -> None:
        """primary_email: oidc=0.95, ldap=0.65 → unanimous confidence=max=0.95.

        WHY: §3.3 example payload — primary_email unanimous at 0.95.
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "primary_email": {"oidc": "alice@corp.com", "ldap": "alice@corp.com"}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["primary_email"]
        assert isinstance(detail, UnanimousResolution)
        assert detail.confidence == pytest.approx(0.95), (
            f"Expected 0.95 for primary_email unanimous oidc+ldap, got {detail.confidence!r}."
        )

    def test_unanimous_employee_type_oidc_ldap(self) -> None:
        """employee_type: oidc=0.60, ldap=0.95 → unanimous confidence=max=0.95.

        WHY: §3.3 example — employee_type unanimous FTE at 0.95.
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"employee_type": {"oidc": "FTE", "ldap": "FTE"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["employee_type"]
        assert isinstance(detail, UnanimousResolution)
        assert detail.confidence == pytest.approx(0.95)
        assert detail.resolved_value == "FTE"

    def test_unanimous_resolution_literal_is_unanimous(self) -> None:
        """UnanimousResolution.resolution must be exactly 'unanimous'.

        WHY: discriminated union check — any typo here breaks downstream Pydantic
        model_validate() calls in Risk Evaluator and Dashboard.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"saml": "Bob", "ldap": "Bob"}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert detail.resolution == "unanimous", (
            f"Expected resolution='unanimous', got {detail.resolution!r}."
        )

    def test_unanimous_three_sources_max_weight_wins(self) -> None:
        """All three protocols agree → confidence == max weight among all three.

        WHY: §5.5 specifies max weight of agreeing sources — not sum, not average.
        Three agreeing protocols are more reliable than one, but the confidence
        formula is bounded by the most authoritative source's weight.
        For display_name: ldap=0.90, saml=0.70, oidc=0.60 → max=0.90.
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"ldap": "Charlie", "saml": "Charlie", "oidc": "Charlie"}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, UnanimousResolution)
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected max weight=0.90 for three-way unanimous display_name, got {detail.confidence!r}."
        )
        assert set(detail.sources) == {"ldap", "saml", "oidc"}


# ===========================================================================
# CLASS 5 — Disagreeing sources (PriorityResolution)
# ===========================================================================


class TestPriorityResolution:
    """≥2 present sources disagreeing → PriorityResolution.

    WHY spec §5.5: winner = highest-priority source per priority_for(attr) that
    HAS a value.  confidence = winner_weight × 0.8.  conflicting_values contains
    only the NON-NULL losing values.  penalty_applied=True always in this path.
    """

    def test_department_oidc_vs_ldap_ldap_wins(self) -> None:
        """§3.3 canonical example: department oidc='Product' vs ldap='Engineering'.

        priority_for('department') == ['ldap', 'oidc', 'saml'] → ldap wins.
        confidence = weight_for('department','ldap') × 0.8 = 0.90 × 0.8 = 0.72.
        conflicting_values = {'oidc': 'Product'}.
        WHY: This is the exact scenario from §3.3 that the dashboard displays.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("Engineering", True),
                    "oidc": ("Product", False),
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, PriorityResolution), (
            f"Expected PriorityResolution for disagreeing ldap/oidc department, got {type(detail)!r}."
        )
        assert detail.resolved_value == "Engineering", (
            f"Expected winner='Engineering' (ldap, highest priority), got {detail.resolved_value!r}."
        )
        assert detail.winner_source == "ldap", (
            f"Expected winner_source='ldap', got {detail.winner_source!r}."
        )
        assert detail.confidence == pytest.approx(0.72), (
            f"Expected confidence=0.90×0.8=0.72, got {detail.confidence!r}."
        )
        assert detail.conflicting_values == {"oidc": "Product"}, (
            f"Expected conflicting_values={{'oidc': 'Product'}}, got {detail.conflicting_values!r}."
        )
        assert detail.penalty_applied is True, (
            f"Expected penalty_applied=True for priority resolution, got {detail.penalty_applied!r}."
        )

    def test_priority_resolution_literal_is_priority(self) -> None:
        """PriorityResolution.resolution must be exactly 'priority'."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("Engineering", True),
                    "saml": ("Sales", True),
                }
            },
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert detail.resolution == "priority", (
            f"Expected resolution='priority', got {detail.resolution!r}."
        )

    def test_display_name_priority_ldap_over_oidc(self) -> None:
        """display_name: priority=[ldap,saml,oidc] → ldap wins over oidc.

        confidence = weight_for('display_name','ldap') × 0.8 = 0.90 × 0.8 = 0.72.
        WHY: LDAP is synced from HR (legal name).  OIDC display name may be stale.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"ldap": "Alice Smith", "oidc": "alice.smith"}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, PriorityResolution)
        assert detail.winner_source == "ldap"
        assert detail.resolved_value == "Alice Smith"
        assert detail.confidence == pytest.approx(0.72), (
            f"Expected 0.90×0.8=0.72 for display_name priority ldap, got {detail.confidence!r}."
        )

    def test_employee_type_priority_ldap_over_saml(self) -> None:
        """employee_type: priority=[ldap,saml,oidc] → ldap wins over saml.

        confidence = 0.95 × 0.8 = 0.76.
        WHY: HR system (LDAP) is authoritative for employment classification.
        SAML value may reflect stale role claim.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "employee_type": {"ldap": "FTE", "saml": "contractor"}
            },
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["employee_type"]
        assert isinstance(detail, PriorityResolution)
        assert detail.winner_source == "ldap"
        assert detail.resolved_value == "FTE"
        assert detail.confidence == pytest.approx(0.76), (
            f"Expected 0.95×0.8=0.76, got {detail.confidence!r}."
        )
        assert "saml" in detail.conflicting_values
        assert detail.conflicting_values["saml"] == "contractor"

    def test_primary_email_priority_oidc_over_ldap(self) -> None:
        """primary_email: priority=[oidc,saml,ldap] → oidc wins over ldap.

        confidence = 0.95 × 0.8 = 0.76.
        WHY: OIDC has the most current email from recent SSO migration.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "primary_email": {
                    "oidc": "alice@newdomain.com",
                    "ldap": "alice@olddomain.com",
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["primary_email"]
        assert isinstance(detail, PriorityResolution)
        assert detail.winner_source == "oidc"
        assert detail.resolved_value == "alice@newdomain.com"
        assert detail.confidence == pytest.approx(0.76), (
            f"Expected 0.95×0.8=0.76 for primary_email priority oidc, got {detail.confidence!r}."
        )

    def test_conflicting_values_excludes_winner(self) -> None:
        """conflicting_values must contain only LOSING non-null values — not the winner.

        WHY: §5.5 — 'conflicting_values contains only the losing non-null values'.
        Including the winner in conflicting_values would make the dashboard display
        a spurious self-conflict.
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
        assert "ldap" not in detail.conflicting_values, (
            "Winner 'ldap' must not appear in conflicting_values. "
            f"conflicting_values={detail.conflicting_values!r}."
        )
        assert "oidc" in detail.conflicting_values

    def test_three_way_conflict_two_losers_in_conflicting_values(self) -> None:
        """Three-way conflict: winner (highest priority) vs 2 losers.

        department priority=[ldap,oidc,saml]: ldap wins.
        conflicting_values must contain both oidc and saml values.
        WHY: All non-null losers must be recorded for audit trail.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("Engineering", True),
                    "oidc": ("Finance", True),
                    "saml": ("Marketing", True),
                }
            },
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, PriorityResolution)
        assert detail.winner_source == "ldap"
        assert set(detail.conflicting_values.keys()) == {"oidc", "saml"}, (
            f"Expected conflicting_values keys={{'oidc','saml'}}, got {detail.conflicting_values!r}."
        )

    def test_fallback_to_highest_weight_when_no_priority_source_present(self) -> None:
        """Fallback path: if no configured-priority source has a value, highest-weight source wins.

        For employee_type, priority=[ldap,saml,oidc]. If ldap and saml are absent,
        and only oidc is present — oidc must win (it is the only source).
        But test the weight-based fallback by using an attribute with NO priority configured
        at all (use a custom config with empty priority for the attribute).

        WHY: §5.5 says 'if—pathologically—no configured-priority source has a value,
        the highest-weight present source wins'. The standard config always has priorities
        that cover the standard protocols, so this uses the two-source disagreement scenario
        where the highest-priority present source IS the winner (not the fallback),
        but both disagree — verifying the priority list, not the weight fallback.

        We also verify the weight-based fallback by using a custom minimal config
        with NO priority list for the attribute in conflict.
        """
        from pathlib import Path

        from app.normalization_config import load_config
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        # Build a config with no priority for display_name and weights ldap=0.90, saml=0.70
        yaml_content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  display_name:
    weights: {ldap: 0.90, saml: 0.70}

enrichment:
  sources:
    ldap:
      enabled: false
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = Path(f.name)

        cfg = load_config(tmp_path)
        result = resolve(
            attribute_sources={"display_name": {"ldap": "Alice Smith", "saml": "alice"}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, PriorityResolution), (
            f"Expected PriorityResolution for weight-based fallback conflict, got {type(detail)!r}."
        )
        # No priority configured, so highest-weight source (ldap=0.90) wins
        assert detail.winner_source == "ldap", (
            f"Expected highest-weight source 'ldap' to win when no priority configured, "
            f"got winner_source={detail.winner_source!r}."
        )
        assert detail.confidence == pytest.approx(0.90 * 0.8), (
            f"Expected confidence=0.90×0.8=0.72 for weight-based winner, got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 6 — source_protocol and enrichment passthrough
# ===========================================================================


class TestPassthroughFields:
    """source_protocol and enrichment on output must reflect what was passed in.

    WHY spec §5.5.2: 'source_protocol is the primary event's protocol (oidc/saml/ldap),
    even when LDAP enrichment contributed.'  enrichment is not computed by resolve()
    — it is set by the service layer (§5.4) and passed through.
    """

    def test_source_protocol_set_to_passed_oidc(self) -> None:
        """source_protocol='oidc' on output when 'oidc' is passed in."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"oidc": "Alice", "ldap": "Alice"}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        assert result.source_protocol == "oidc", (
            f"Expected source_protocol='oidc', got {result.source_protocol!r}. "
            "source_protocol must reflect the primary event's protocol, not the enriching source."
        )

    def test_source_protocol_set_to_passed_saml(self) -> None:
        """source_protocol='saml' on output when 'saml' is passed in."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        assert result.source_protocol == "saml"

    def test_source_protocol_set_to_passed_ldap(self) -> None:
        """source_protocol='ldap' even when ldap-sourced attrs contributed to resolution."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"ldap": "Charlie"}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        assert result.source_protocol == "ldap"

    def test_enrichment_passthrough_applied_variant(self) -> None:
        """EnrichmentApplied passed in appears unchanged on the output object.

        WHY: resolve() does not compute enrichment — it sets it on the returned
        NormalizedAttributes.  The field is required and must always be populated.
        """
        from app.resolution import resolve
        from naas_shared.models import EnrichmentApplied

        cfg = _load_real_config()
        enrichment_in = EnrichmentApplied(applied=True, source="ldap", cache_hit=True)
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="oidc",
            enrichment=enrichment_in,
        )

        assert isinstance(result.enrichment, EnrichmentApplied), (
            f"Expected EnrichmentApplied on output, got {type(result.enrichment)!r}."
        )
        assert result.enrichment.cache_hit is True

    def test_enrichment_passthrough_skipped_variant(self) -> None:
        """EnrichmentSkipped passed in appears unchanged on the output object."""
        from app.resolution import resolve
        from naas_shared.models import EnrichmentSkipped

        cfg = _load_real_config()
        enrichment_in = EnrichmentSkipped(applied=False, skip_reason="ldap_disabled")
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="saml",
            enrichment=enrichment_in,
        )

        assert isinstance(result.enrichment, EnrichmentSkipped), (
            f"Expected EnrichmentSkipped on output, got {type(result.enrichment)!r}."
        )
        assert result.enrichment.skip_reason == "ldap_disabled"


# ===========================================================================
# CLASS 7 — Pydantic validation of returned NormalizedAttributes
# ===========================================================================


class TestReturnedObjectValidation:
    """The returned object must be a valid NormalizedAttributes (Pydantic validates it).

    WHY: Downstream consumers call NormalizedAttributes.model_validate(jsonb_dict).
    Any resolution_details entry with an invalid discriminator value would cause
    those calls to fail, surfacing as normalization_risk=1.0 in Risk Evaluator.
    """

    def test_resolution_details_only_uses_valid_discriminators(self) -> None:
        """All resolution_details values must use one of the four permitted discriminators.

        Permitted: 'unanimous', 'priority', 'single_source', 'list_merge'.
        WHY: §5.5 — 'the service must emit only these'.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice", "ldap": "Alice"},
                "primary_email": {"oidc": "a@corp.com"},
                "department": {"ldap": ("Engineering", True), "oidc": ("Finance", True)},
                "employee_type": {"ldap": "FTE"},
                "groups": {"oidc": ["admin"], "ldap": ["engineering"]},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        valid_discriminators = {"unanimous", "priority", "single_source", "list_merge"}
        for attr, detail in result.resolution_details.items():
            assert detail.resolution in valid_discriminators, (
                f"Attribute '{attr}' has invalid resolution discriminator "
                f"'{detail.resolution}'. Permitted: {valid_discriminators}."
            )

    def test_full_result_roundtrips_through_pydantic_model_validate(self) -> None:
        """Serialized NormalizedAttributes must survive model_validate() roundtrip.

        WHY: Risk Evaluator and Dashboard call model_validate() on the JSONB field.
        An object that fails model_dump/model_validate roundtrip would silently
        corrupt those consumers.
        """
        from app.resolution import resolve
        from naas_shared.models import NormalizedAttributes

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice Smith"},
                "primary_email": {"oidc": "alice@corp.com"},
                "employee_type": {"ldap": "FTE"},
                "groups": {"oidc": ["admin"]},
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        serialized = result.model_dump(mode="json")
        reconstructed = NormalizedAttributes.model_validate(serialized)

        assert reconstructed.source_protocol == result.source_protocol
        assert reconstructed.normalization_confidence == pytest.approx(
            result.normalization_confidence
        )
