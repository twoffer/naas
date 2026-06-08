"""Confidence penalty mechanics for unknown employee_type and attribute conflicts."""

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
# Helpers
# ---------------------------------------------------------------------------


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
# CLASS 1 — Department single-source penalty
# ===========================================================================


class TestDepartmentSingleSourcePenalty:
    """Single-source department: penalty applies iff was_mapped=False.

    WHY: The most common path — one adapter produced a department value.
    was_mapped=True → normal confidence.  was_mapped=False → -0.2 penalty.
    """

    def test_single_source_dept_mapped_no_penalty(self) -> None:
        """department single-source, was_mapped=True → confidence = weight_for('department', src).

        ldap mapped Engineering → confidence = 0.90 (no penalty).
        WHY: Normal path — recognized alias → canonical value → full confidence.
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
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected 0.90 for single-source mapped dept (no penalty), got {detail.confidence!r}."
        )

    def test_single_source_dept_unmapped_applies_penalty(self) -> None:
        """department single-source, was_mapped=False → confidence = weight - 0.2.

        ldap unmapped 'Widgets' → confidence = 0.90 - 0.20 = 0.70.
        WHY: §5.5 — the 0.2 penalty applies when the resolved value is unmapped.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"department": {"ldap": ("Widgets", False)}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.resolved_value == "Widgets", (
            f"Expected resolved_value='Widgets' (retained unmapped), got {detail.resolved_value!r}."
        )
        assert detail.confidence == pytest.approx(0.70), (
            f"Expected 0.90-0.20=0.70 for single-source unmapped dept, got {detail.confidence!r}."
        )

    def test_single_source_dept_oidc_unmapped_penalty(self) -> None:
        """department single-source oidc, was_mapped=False → confidence = 0.70 - 0.20 = 0.50.

        oidc weight = 0.70 for department.  Penalty: 0.70 - 0.20 = 0.50.
        WHY: Verifies the penalty applies to any source's weight, not just ldap.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"department": {"oidc": ("WidgetCorp", False)}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.confidence == pytest.approx(0.50), (
            f"Expected 0.70-0.20=0.50 for oidc single-source unmapped dept, got {detail.confidence!r}."
        )

    def test_penalty_clamped_at_zero_for_very_low_weight(self) -> None:
        """Penalty clamps confidence at 0.0 — never goes negative.

        §5.5.2: 'clamped to [0.0, 1.0]'.
        saml weight for department = 0.50.  0.50 - 0.20 = 0.30 (still positive here).
        To trigger clamping need weight < 0.2.  Use custom config with weight 0.10.
        WHY: negative confidence would fail Pydantic Field(ge=0.0) and crash the model.
        """
        import tempfile

        from app.normalization_config import load_config
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        yaml_content = """
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  department:
    priority: [ldap, oidc, saml]
    weights: {ldap: 0.10, oidc: 0.70, saml: 0.50}

enrichment:
  sources:
    ldap:
      enabled: false
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            tmp_path = Path(f.name)

        cfg = load_config(tmp_path)
        result = resolve(
            attribute_sources={"department": {"ldap": ("WidgetCorp", False)}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, SingleSourceResolution)
        # weight=0.10, penalty=0.20 → raw=-0.10 → clamped to 0.0
        assert detail.confidence >= 0.0, (
            f"Confidence must be clamped to >= 0.0, got {detail.confidence!r}."
        )
        assert detail.confidence == pytest.approx(0.0), (
            f"Expected confidence clamped to 0.0 (0.10-0.20=-0.10 → clamp), "
            f"got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 2 — Department unanimous penalty
# ===========================================================================


class TestDepartmentUnanimousPenalty:
    """Unanimous dept where the agreed value is unmapped → −0.2 on unanimous confidence.

    ENCODED INTERPRETATION: Unanimous resolution still applies the penalty when the
    unanimously-agreed value is unmapped.  §5.5 — penalty applies 'when the resolved
    (winning) value is itself an unmapped value' — resolution type is irrelevant.
    """

    def test_unanimous_dept_all_mapped_no_penalty(self) -> None:
        """Unanimous department with both sources mapped → no penalty.

        oidc and ldap both supply 'Engineering' (mapped).
        Confidence = max(0.70, 0.90) = 0.90.
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("Engineering", True),
                    "oidc": ("Engineering", True),
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, UnanimousResolution)
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected 0.90 for unanimous mapped dept, got {detail.confidence!r}."
        )

    def test_unanimous_dept_unmapped_value_applies_penalty(self) -> None:
        """Unanimous department where both sources agree on an unmapped value → −0.2.

        Both oidc and ldap supply 'WidgetCorp' (unmapped, was_mapped=False).
        Raw confidence = max(0.70, 0.90) = 0.90.
        After penalty: 0.90 - 0.20 = 0.70.
        WHY: The resolved value is unmapped regardless of how many sources agree.
        """
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "ldap": ("WidgetCorp", False),
                    "oidc": ("WidgetCorp", False),
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, UnanimousResolution), (
            f"Expected UnanimousResolution (sources agree), got {type(detail)!r}."
        )
        assert detail.resolved_value == "WidgetCorp"
        assert detail.confidence == pytest.approx(0.70), (
            f"Expected 0.90-0.20=0.70 for unanimous unmapped dept, got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 3 — Department priority resolution penalty
# ===========================================================================


class TestDepartmentPriorityPenalty:
    """Priority resolution: penalty on winning value if winner is unmapped.

    §5.5 — 'penalty attaches to the resolution's confidence only when the
    resolved (winning) value is itself an unmapped value'.
    Winner confidence = winner_weight × 0.8 (standard priority penalty).
    Unmapped penalty is ADDITIONAL: (winner_weight × 0.8) - 0.2.
    """

    def test_priority_dept_mapped_winner_no_unmapped_penalty(self) -> None:
        """Priority resolution: ldap wins with mapped value → confidence = 0.90×0.8 = 0.72.

        §3.3 example: ldap='Engineering' (mapped) beats oidc='Product' (unmapped).
        Winner is MAPPED → only the ×0.8 priority penalty applies, not the -0.2.
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
        assert isinstance(detail, PriorityResolution)
        # Winner is ldap ('Engineering', mapped): confidence = 0.90×0.8 = 0.72 (no unmapped penalty)
        assert detail.confidence == pytest.approx(0.72), (
            f"Expected 0.90×0.8=0.72 for priority with mapped winner, got {detail.confidence!r}. "
            "The unmapped penalty should NOT apply to a mapped winner."
        )

    def test_priority_dept_unmapped_winner_applies_both_penalties(self) -> None:
        """Priority resolution: winner is unmapped → confidence = (winner_weight × 0.8) - 0.2.

        oidc='WidgetCorp' (unmapped, was_mapped=False) vs saml='Sales' (mapped, was_mapped=True).
        priority_for('department') = [ldap, oidc, saml] → ldap absent → oidc wins over saml.
        Winner = oidc with 'WidgetCorp' (unmapped).
        Raw priority confidence = 0.70 × 0.8 = 0.56.
        Unmapped penalty: 0.56 - 0.20 = 0.36.
        WHY: Two separate mechanisms — priority disagreement AND unmapped value — both apply.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "department": {
                    "oidc": ("WidgetCorp", False),
                    "saml": ("Sales", True),
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["department"]
        assert isinstance(detail, PriorityResolution), (
            f"Expected PriorityResolution, got {type(detail)!r}."
        )
        assert detail.winner_source == "oidc", (
            f"Expected winner=oidc (higher priority than saml), got {detail.winner_source!r}."
        )
        assert detail.resolved_value == "WidgetCorp"
        # (0.70 × 0.8) - 0.20 = 0.56 - 0.20 = 0.36
        assert detail.confidence == pytest.approx(0.36), (
            f"Expected (0.70×0.8)-0.20=0.36 for unmapped priority winner, "
            f"got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 4 — employee_type NEVER carries the penalty
# ===========================================================================


class TestEmployeeTypeNeverPenalized:
    """employee_type resolutions must NEVER carry the 0.2 penalty.

    WHY spec §5.5: 'can NEVER happen for employee_type, whose unmapped values are
    discarded to None'.  An unmapped employee_type is never stored — the source
    simply has no value for that attribute and is not in the present-set.
    If resolve() received a non-Literal employee_type value it would fail Pydantic
    validation; the contract is that the attribute_sources for employee_type
    ONLY contains validated Literal values.
    """

    def test_employee_type_single_source_no_penalty(self) -> None:
        """employee_type from single source → confidence = exact weight, no penalty.

        ldap 'FTE' → confidence = 0.95 (not 0.95 - 0.20 = 0.75).
        WHY: employee_type values are always pre-validated Literal — no unmapped path exists.
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
            f"Expected 0.95 (no penalty) for employee_type single-source, "
            f"got {detail.confidence!r}. employee_type must NEVER be penalized."
        )

    def test_employee_type_unanimous_no_penalty(self) -> None:
        """employee_type unanimous (oidc+ldap both FTE) → confidence = max weight, no penalty.

        max(0.60, 0.95) = 0.95.
        WHY: §3.3 example shows employee_type unanimous at 0.95 — no penalty.
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
        assert detail.confidence == pytest.approx(0.95), (
            f"Expected 0.95 for unanimous employee_type, got {detail.confidence!r}."
        )

    def test_employee_type_priority_no_unmapped_penalty(self) -> None:
        """employee_type priority: confidence = winner_weight × 0.8 only.

        ldap='FTE', saml='contractor' → ldap wins (priority=[ldap,saml,oidc]).
        confidence = 0.95 × 0.8 = 0.76.  No additional -0.20 penalty.
        WHY: The two penalties are orthogonal — priority-conflict ×0.8 is always
        applied in a priority resolution; unmapped −0.20 is never applied for employee_type.
        """
        from app.resolution import resolve
        from naas_shared.models import PriorityResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"employee_type": {"ldap": "FTE", "saml": "contractor"}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["employee_type"]
        assert isinstance(detail, PriorityResolution)
        # Only the ×0.8 priority penalty; no -0.20 unmapped penalty
        assert detail.confidence == pytest.approx(0.76), (
            f"Expected 0.95×0.8=0.76 for employee_type priority (no unmapped penalty), "
            f"got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 5 — Discarded source does not penalize surviving source
# ===========================================================================


class TestDiscardedSourceNoPenalty:
    """A discarded value (unmapped employee_type → None) does NOT penalize the surviving source.

    WHY spec §5.5: 'A source whose value was discarded — an unmapped employee_type,
    or any field simply absent — is not a present source for that attribute, so it
    neither contributes nor penalizes: a surviving valid source resolves at its own
    full confidence (the discarded source's failure does NOT reduce it).'

    The attribute_sources dict only contains non-null, validated values.  The
    discarded-source scenario is modelled by the ABSENCE of the discarding source
    from the employee_type sub-dict (it was filtered out by the adapter before calling resolve).
    """

    def test_surviving_employee_type_source_at_full_confidence_when_other_discarded(
        self,
    ) -> None:
        """ldap 'FTE' present, oidc discarded (not in attribute_sources) → ldap at full 0.95.

        The oidc source processed an unmapped employee_type and discarded it upstream.
        It does NOT appear in attribute_sources.  resolve() sees only ldap.
        Result: SingleSourceResolution, confidence=0.95 (not penalized by oidc's absence).
        WHY: If a discarded source somehow penalized the survivor, a user with two
        identity providers where one had a bad employee_type value would have their
        legitimate employment classification downgraded.
        """
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        # oidc discarded its employee_type → not included in attribute_sources
        result = resolve(
            attribute_sources={"employee_type": {"ldap": "FTE"}},
            config=cfg,
            source_protocol="oidc",  # primary protocol is oidc even though it had no valid value
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["employee_type"]
        assert isinstance(detail, SingleSourceResolution), (
            f"Expected SingleSourceResolution for single surviving source, got {type(detail)!r}."
        )
        assert detail.confidence == pytest.approx(0.95), (
            f"Expected 0.95 (full ldap weight), not penalized by absent oidc source. "
            f"Got {detail.confidence!r}."
        )
        assert detail.sources == ["ldap"], (
            f"Expected sources=['ldap'], got {detail.sources!r}."
        )

    def test_employee_type_none_when_all_sources_discarded(self) -> None:
        """If all employee_type values were discarded (no present sources), unified value is None.

        Both oidc and ldap had unmapped employee_type → discarded upstream → empty sub-dict.
        Result: employee_type=None, no resolution_details entry, 0.0 contribution to confidence.
        WHY: This is the 'all discarded' edge case — must not crash or emit a None resolution entry.
        """
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"employee_type": {}},  # all discarded
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert result.employee_type is None, (
            f"Expected employee_type=None when all sources discarded, got {result.employee_type!r}."
        )
        assert "employee_type" not in result.resolution_details, (
            f"Expected 'employee_type' absent from resolution_details when all sources discarded. "
            f"Got keys: {list(result.resolution_details.keys())}."
        )


# ===========================================================================
# CLASS 6 — Other attributes (display_name, primary_email) have no penalty path
# ===========================================================================


class TestNoWasMappedAttributes:
    """display_name and primary_email have no was_mapped tuple — always full confidence.

    WHY: §5.5 — 'can happen ONLY for department'.  display_name and primary_email
    are plain strings passed directly from the adapter with no was_mapped flag.
    The penalty should never be applied to these attributes.

    The attribute_sources shape for these is a plain str, not a tuple.  If resolve()
    accidentally applied a penalty to a non-tuple entry, these tests would catch it.
    """

    def test_display_name_single_source_always_full_weight(self) -> None:
        """display_name from ldap → confidence = 0.90, no penalty regardless of value."""
        from app.resolution import resolve
        from naas_shared.models import SingleSourceResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"display_name": {"ldap": "Alice Smith"}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, SingleSourceResolution)
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected 0.90 for display_name (no penalty path), got {detail.confidence!r}."
        )

    def test_primary_email_single_source_always_full_weight(self) -> None:
        """primary_email from oidc → confidence = 0.95, no penalty."""
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
            f"Expected 0.95 for primary_email (no penalty path), got {detail.confidence!r}."
        )

    def test_display_name_unanimous_oidc_ldap_no_penalty(self) -> None:
        """display_name unanimous: confidence = max(0.60, 0.90) = 0.90, no penalty."""
        from app.resolution import resolve
        from naas_shared.models import UnanimousResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "display_name": {"oidc": "Alice Smith", "ldap": "Alice Smith"}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["display_name"]
        assert isinstance(detail, UnanimousResolution)
        assert detail.confidence == pytest.approx(0.90), (
            f"Expected 0.90 for unanimous display_name, got {detail.confidence!r}."
        )
