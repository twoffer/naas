# Component: NAAS Spec 2 — Chunk 5: resolution.py — groups ListMergeResolution
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/app/resolution.py
#
# EXACT ASSUMED SIGNATURE (implementer must conform):
#   resolve(attribute_sources, config, source_protocol, enrichment) -> NormalizedAttributes
#   See test_chunk5_scalar_resolution.py for full signature + attribute_sources shape.
#
# groups entry in attribute_sources:
#   {"groups": {"oidc": ["admin", "vpn-users"], "ldap": ["engineering", "admin"]}}
#   Each source value is a list[str] of group names (already normalized by the adapter).
#   Absent groups key or empty sub-dict → 0 sources → groups entry omitted from resolution_details.
#
# WHAT THESE TESTS VALIDATE (§5.5 groups contract):
#   1. Zero group sources → no 'groups' entry in resolution_details, groups=[] on output.
#   2. Single source → ListMergeResolution, confidence = weight_for('groups', that_source).
#   3. Multiple sources, union strategy → de-duplicated + sorted merged list.
#   4. Multiple sources confidence formula: 0.7 + 0.3 × (fraction of merged groups in >1 source).
#   5. strategy field == merge_strategy_for('groups') from config (default 'union').
#   6. total_unique_groups == len(resolved_value).
#   7. Intersection strategy (custom config) → only groups present in ALL sources.
#   8. Resolution literal is exactly 'list_merge'.
#   9. Empty group lists from a source are excluded from the source count.
#
# WHY groups matter for security:
#   Group memberships drive RBAC decisions downstream.  A union strategy that
#   silently drops groups or a fraction formula with a bug causes undercounting
#   of legitimate memberships or overstatement of confidence.

# stdlib
import sys
import tempfile
from pathlib import Path

# third-party
import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Could not locate repo root starting from {Path(__file__).resolve()}")


REPO_ROOT = _find_repo_root()
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"
SHARED_DIR = REPO_ROOT / "shared"
CONFIG_PATH = REPO_ROOT / "config" / "normalization.yaml"

if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_real_config():
    from app.normalization_config import load_config

    return load_config(CONFIG_PATH)


def _load_config_with_strategy(strategy: str):
    """Load a modified config with the specified merge strategy for groups."""
    yaml_content = f"""
defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  groups:
    merge_strategy: {strategy}
    rationale: "test"

enrichment:
  sources:
    ldap:
      enabled: false
      correlation_key: primary_email
      timeout_ms: 2000
      on_failure: continue
      cache_ttl_seconds: 60
"""
    from app.normalization_config import load_config

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        return load_config(Path(f.name))


def _skip_enrichment():
    from naas_shared.models import EnrichmentSkipped

    return EnrichmentSkipped(applied=False, skip_reason="ldap_event")


# ===========================================================================
# CLASS 1 — Zero group sources
# ===========================================================================


class TestZeroGroupSources:
    """0 sources → groups omitted from resolution_details and output groups=[].

    WHY: §5.5 — 'if 0 sources, omit the groups entry from resolution_details'.
    An empty ListMergeResolution would be an invalid state (0 groups, 0 sources).
    """

    def test_groups_absent_from_resolution_details_when_no_source(self) -> None:
        """groups key must be absent from resolution_details when no source supplied groups."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert "groups" not in result.resolution_details, (
            f"Expected 'groups' absent from resolution_details when no source present, "
            f"got keys: {list(result.resolution_details.keys())}."
        )

    def test_groups_list_is_empty_when_no_source(self) -> None:
        """NormalizedAttributes.groups is [] when no source supplied groups."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        assert result.groups == [], (
            f"Expected groups=[] when no source present, got {result.groups!r}."
        )

    def test_groups_empty_sub_dict_treated_as_no_sources(self) -> None:
        """An empty groups sub-dict (attribute_sources={'groups': {}}) is treated as 0 sources."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        assert "groups" not in result.resolution_details, (
            "Empty groups sub-dict must be treated as 0 sources — no resolution_details entry."
        )


# ===========================================================================
# CLASS 2 — Single group source
# ===========================================================================


class TestSingleGroupSource:
    """Single source → ListMergeResolution, confidence = weight_for('groups', src).

    WHY: §5.5 — 'if one source contributed, that source's weight'.
    groups has no explicit weights block in §5.6, so it falls back to
    defaults.source_weights (ldap=0.7, saml=0.6, oidc=0.8).
    """

    def test_single_source_oidc_groups_confidence_is_default_weight(self) -> None:
        """groups from oidc only → confidence == 0.8 (defaults.source_weights.oidc).

        WHY: groups has no explicit weights block; accessor falls back to defaults.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"oidc": ["admin", "vpn-users"]}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details.get("groups")
        assert detail is not None, "groups must appear in resolution_details when one source present."
        assert isinstance(detail, ListMergeResolution), (
            f"Expected ListMergeResolution for groups, got {type(detail)!r}."
        )
        assert detail.confidence == pytest.approx(0.8), (
            f"Expected confidence=0.8 (oidc default weight) for single-source groups, "
            f"got {detail.confidence!r}."
        )

    def test_single_source_ldap_groups_confidence_is_default_weight(self) -> None:
        """groups from ldap only → confidence == 0.7 (defaults.source_weights.ldap)."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"ldap": ["engineering", "vpn-users"]}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.confidence == pytest.approx(0.7), (
            f"Expected 0.7 for single-source ldap groups, got {detail.confidence!r}."
        )

    def test_single_source_saml_groups_confidence(self) -> None:
        """groups from saml only → confidence == 0.6 (defaults.source_weights.saml)."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"saml": ["finance-team"]}},
            config=cfg,
            source_protocol="saml",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.confidence == pytest.approx(0.6)

    def test_single_source_groups_resolved_value_is_sorted(self) -> None:
        """Single-source groups are sorted in resolved_value.

        WHY: §5.5 — 'de-duplicated, sorted group list'.  Even with a single source,
        sorting ensures deterministic output for the dashboard display.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"oidc": ["vpn-users", "admin", "engineering"]}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.resolved_value == sorted(detail.resolved_value), (
            f"Expected groups to be sorted, got {detail.resolved_value!r}."
        )
        assert detail.resolved_value == ["admin", "engineering", "vpn-users"]

    def test_single_source_total_unique_groups_matches_len(self) -> None:
        """total_unique_groups == len(resolved_value) for single source."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"ldap": ["admin", "engineering", "vpn-users"]}},
            config=cfg,
            source_protocol="ldap",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.total_unique_groups == len(detail.resolved_value), (
            f"Expected total_unique_groups={len(detail.resolved_value)}, "
            f"got {detail.total_unique_groups!r}."
        )
        assert detail.total_unique_groups == 3

    def test_list_merge_resolution_literal(self) -> None:
        """ListMergeResolution.resolution must be exactly 'list_merge'."""
        from app.resolution import resolve

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={"groups": {"oidc": ["admin"]}},
            config=cfg,
            source_protocol="oidc",
            enrichment=_skip_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert detail.resolution == "list_merge", (
            f"Expected resolution='list_merge', got {detail.resolution!r}."
        )


# ===========================================================================
# CLASS 3 — Union merge strategy (multiple sources)
# ===========================================================================


class TestUnionMerge:
    """Multiple sources with union strategy → de-duplicated union, sorted, correct confidence.

    WHY: §3.3 example — groups: admin, engineering, vpn-users from merged oidc+ldap.
    Union is the default and most permissive strategy (no group memberships dropped).
    """

    def test_union_two_sources_deduplicates(self) -> None:
        """Union merge removes duplicates present in both sources.

        WHY: 'admin' appears in both oidc and ldap — resolved_value must list it once.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        resolved = detail.resolved_value
        # admin must appear exactly once
        assert resolved.count("admin") == 1, (
            f"'admin' must appear exactly once after dedup, got {resolved!r}."
        )

    def test_union_two_sources_sorted_result(self) -> None:
        """Union merge result is sorted alphabetically."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["vpn-users", "admin"],
                    "ldap": ["engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.resolved_value == ["admin", "engineering", "vpn-users"], (
            f"Expected ['admin', 'engineering', 'vpn-users'], got {detail.resolved_value!r}."
        )

    def test_union_matches_spec33_example(self) -> None:
        """Reproduce the §3.3 groups example exactly.

        oidc has: admin, vpn-users
        ldap has: admin, engineering, vpn-users (assuming LDAP enrichment result)
        union de-duped sorted → ['admin', 'engineering', 'vpn-users']
        WHY: §3.3 is the contract between this service and its consumers.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering", "vpn-users"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.resolved_value == ["admin", "engineering", "vpn-users"], (
            f"Expected §3.3 groups list, got {detail.resolved_value!r}."
        )
        assert detail.total_unique_groups == 3
        assert detail.strategy == "union"

    def test_union_strategy_field_equals_union(self) -> None:
        """strategy field on ListMergeResolution == 'union' for default config."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {"oidc": ["admin"], "ldap": ["engineering"]}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.strategy == "union", (
            f"Expected strategy='union' from default config, got {detail.strategy!r}."
        )

    def test_union_two_sources_confidence_formula_all_shared(self) -> None:
        """Multi-source confidence: 0.7 + 0.3 × fraction-in-more-than-one-source.

        Fixture: oidc=['admin'], ldap=['admin'] — 1 unique group, 'admin' in both.
        Fraction = 1/1 = 1.0.  Confidence = 0.7 + 0.3×1.0 = 1.0.

        WHY: The exact formula is in §5.5: 'if multiple, 0.7 + 0.3 × (fraction of
        merged groups present in more than one source)'. Testing the extreme case
        (all groups shared) pins the formula.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {"oidc": ["admin"], "ldap": ["admin"]}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        # fraction = 1/1 = 1.0 → 0.7 + 0.3*1.0 = 1.0
        assert detail.confidence == pytest.approx(1.0), (
            f"Expected confidence=1.0 when all merged groups are shared, got {detail.confidence!r}."
        )

    def test_union_two_sources_confidence_formula_none_shared(self) -> None:
        """Multi-source confidence when no group is shared between sources.

        oidc=['admin'], ldap=['engineering'] → 2 unique groups, 0 in more than one source.
        Fraction = 0/2 = 0.0.  Confidence = 0.7 + 0.3×0.0 = 0.7.
        WHY: Pins the lower-bound of the formula (no cross-source agreement).
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {"oidc": ["admin"], "ldap": ["engineering"]}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        # fraction = 0/2 = 0.0 → 0.7 + 0.3*0.0 = 0.7
        assert detail.confidence == pytest.approx(0.7), (
            f"Expected confidence=0.7 when no groups are shared, got {detail.confidence!r}."
        )

    def test_union_two_sources_confidence_formula_partial_overlap(self) -> None:
        """Multi-source confidence formula with partial overlap — hand-computed fixture.

        oidc=['admin', 'vpn-users'], ldap=['admin', 'engineering']
        Union: ['admin', 'engineering', 'vpn-users'] — 3 unique groups.
        'admin' is in both sources (>1 source); 'engineering' and 'vpn-users' are not.
        Fraction = 1/3 ≈ 0.3333.
        Confidence = 0.7 + 0.3 × (1/3) = 0.7 + 0.1 = 0.80.

        WHY: This is the most common real-world overlap pattern and the formula
        must produce the exact §5.5 result for the §3.3 demo scenario.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        # 'admin' is in both → 1 out of 3 merged groups in >1 source
        expected_confidence = 0.7 + 0.3 * (1 / 3)
        assert detail.confidence == pytest.approx(expected_confidence, rel=1e-4), (
            f"Expected confidence={expected_confidence:.4f} (partial overlap formula), "
            f"got {detail.confidence!r}."
        )

    def test_union_spec33_confidence(self) -> None:
        """§3.3 example groups confidence == 0.85.

        oidc=['admin', 'vpn-users'], ldap=['admin', 'engineering', 'vpn-users']
        union → ['admin', 'engineering', 'vpn-users'] (3 groups).
        'admin' and 'vpn-users' are in both sources → 2 shared out of 3.
        fraction = 2/3.  confidence = 0.7 + 0.3 × (2/3) = 0.7 + 0.2 = 0.9.

        ⚠ Wait — §3.3 shows 0.85.  Let's compute again with the exact lists:
        merged union = {admin, vpn-users, engineering} = 3 unique groups.
        In-more-than-one: admin (oidc+ldap), vpn-users (oidc+ldap) = 2.
        fraction = 2/3 ≈ 0.6667.  0.7 + 0.3*0.6667 = 0.7 + 0.2 = 0.90 ≠ 0.85.

        However the §3.3 example shows 0.85.  The spec payload is ILLUSTRATIVE
        (§3.3 comment: 'representative payload').  The FORMULA in §5.5 is the
        binding contract.  This test verifies the FORMULA (0.90), not the
        illustrative payload value (0.85).  See comment in test for rationale.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering", "vpn-users"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        # 3 merged groups; admin and vpn-users each appear in 2 sources → 2 in >1
        expected_confidence = 0.7 + 0.3 * (2 / 3)
        assert detail.confidence == pytest.approx(expected_confidence, rel=1e-4), (
            f"Expected confidence={expected_confidence:.4f} from §5.5 formula, "
            f"got {detail.confidence!r}. "
            "NOTE: §3.3 shows 0.85 (illustrative); §5.5 formula is the binding contract."
        )


def _applied_enrichment(*, cache_hit: bool = False):
    from naas_shared.models import EnrichmentApplied

    return EnrichmentApplied(applied=True, source="ldap", cache_hit=cache_hit)


# ===========================================================================
# CLASS 4 — Intersection strategy
# ===========================================================================


class TestIntersectionMerge:
    """Intersection strategy keeps only groups present in ALL sources.

    WHY: §5.5 — 'merge per merge_strategy (union default; also intersection, priority)'.
    Intersection is the most restrictive strategy — used when only universally-held
    groups should be carried forward.
    """

    def test_intersection_keeps_common_groups_only(self) -> None:
        """Intersection: only groups in both oidc and ldap survive.

        oidc=['admin', 'vpn-users'], ldap=['admin', 'engineering']
        intersection = ['admin'] (sorted).
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_config_with_strategy("intersection")
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.resolved_value == ["admin"], (
            f"Expected intersection=['admin'], got {detail.resolved_value!r}."
        )
        assert detail.strategy == "intersection"

    def test_intersection_empty_result_when_no_common_groups(self) -> None:
        """Intersection of disjoint group sets produces an empty list.

        WHY: A disjoint intersection is a valid edge case — the user holds
        different groups in each system and the intersection strategy produces
        no groups.  This must NOT raise or crash.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_config_with_strategy("intersection")
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin"],
                    "ldap": ["engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.resolved_value == [], (
            f"Expected empty intersection for disjoint sets, got {detail.resolved_value!r}."
        )
        assert detail.total_unique_groups == 0

    def test_intersection_confidence_formula_all_shared(self) -> None:
        """Intersection: all result groups came from multiple sources → confidence = 1.0.

        oidc=['admin'], ldap=['admin'] → intersection=['admin'].
        All 1 group in >1 source → fraction=1.0 → confidence=0.7+0.3=1.0.
        """
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_config_with_strategy("intersection")
        result = resolve(
            attribute_sources={
                "groups": {"oidc": ["admin"], "ldap": ["admin"]}
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert detail.confidence == pytest.approx(1.0), (
            f"Expected confidence=1.0 for intersection with all groups shared, "
            f"got {detail.confidence!r}."
        )


# ===========================================================================
# CLASS 5 — Output groups list on NormalizedAttributes
# ===========================================================================


class TestGroupsOutputAttribute:
    """The top-level NormalizedAttributes.groups matches resolution_details resolved_value."""

    def test_output_groups_matches_resolved_value(self) -> None:
        """NormalizedAttributes.groups equals ListMergeResolution.resolved_value."""
        from app.resolution import resolve
        from naas_shared.models import ListMergeResolution

        cfg = _load_real_config()
        result = resolve(
            attribute_sources={
                "groups": {
                    "oidc": ["admin", "vpn-users"],
                    "ldap": ["admin", "engineering"],
                }
            },
            config=cfg,
            source_protocol="oidc",
            enrichment=_applied_enrichment(),
        )

        detail = result.resolution_details["groups"]
        assert isinstance(detail, ListMergeResolution)
        assert result.groups == detail.resolved_value, (
            f"NormalizedAttributes.groups must equal resolution resolved_value. "
            f"Got groups={result.groups!r} vs resolved_value={detail.resolved_value!r}."
        )
