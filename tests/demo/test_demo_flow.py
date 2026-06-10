# Tests for demo/demo_normalization.py — flow functions:
# submit_scenes, poll_results, verify_results, render_results, cleanup_events,
# SQL query constants, and the confidence_style color helper.
#
# All functions are exercised through injectable seams (http_client, console,
# db_execute) — no live services required.

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path setup
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until docs/architecture/ is found — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Could not locate repo root from {Path(__file__).resolve()}")


REPO_ROOT = _find_repo_root()
SHARED_DIR = str(REPO_ROOT / "shared")
DEMO_SCRIPT = REPO_ROOT / "demo" / "demo_normalization.py"

if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)

# ---------------------------------------------------------------------------
# naas_shared imports for building real-shape fixtures
# ---------------------------------------------------------------------------

from naas_shared.models import (  # noqa: E402
    EnrichmentApplied,
    EnrichmentSkipped,
    ListMergeResolution,
    NormalizedAttributes,
    PriorityResolution,
    SingleSourceResolution,
    UnanimousResolution,
)


# ---------------------------------------------------------------------------
# Fixtures: import the demo module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_mod():
    """Import demo_normalization.py as a live module for function access."""
    if not DEMO_SCRIPT.exists():
        pytest.fail(f"demo_normalization.py not found at {DEMO_SCRIPT}")
    spec = importlib.util.spec_from_file_location("demo_normalization_flow", DEMO_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec so in-test `from demo_normalization_flow import ...`
    # statements resolve (spec_from_file_location does not touch sys.modules).
    sys.modules["demo_normalization_flow"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fixtures: synthetic NormalizedAttributes payloads (real field names/shapes)
#
# Field names confirmed from naas_shared/models.py and
# services/identity-normalization/app/resolution.py:
#
#   NormalizedAttributes:
#     - display_name, primary_email, department, employee_type, groups
#     - source_protocol ("oidc" | "saml" | "ldap")
#     - normalization_confidence  (float 0.0–1.0)
#     - resolution_details  (Dict[str, ResolutionDetail])
#     - enrichment  (EnrichmentApplied | EnrichmentSkipped discriminated by `applied`)
#
#   ResolutionDetail discriminator field: `resolution`
#     values: "single_source" | "unanimous" | "priority" | "list_merge"
#   SingleSourceResolution: resolution, resolved_value, confidence, sources
#   UnanimousResolution:    resolution, resolved_value, confidence, sources
#   PriorityResolution:     resolution, resolved_value, confidence,
#                           winner_source, conflicting_values, penalty_applied
#   ListMergeResolution:    resolution, resolved_value, confidence,
#                           strategy, total_unique_groups
#
#   EnrichmentApplied:  applied=True, source="ldap", cache_hit: bool
#   EnrichmentSkipped:  applied=False, skip_reason: EnrichmentSkipReason
#
# Weights from config/normalization.yaml:
#   display_name:   ldap=0.85, saml=0.75, oidc=0.70  priority=[oidc,saml,ldap]
#   primary_email:  oidc=0.95, saml=0.75, ldap=0.65  priority=[oidc,saml,ldap]
#   department:     ldap=0.90, oidc=0.70, saml=0.50  priority=[ldap,oidc,saml]
#   employee_type:  ldap=0.95, saml=0.80, oidc=0.60  priority=[ldap,saml,oidc]
#   groups:         merge_strategy=union
# ---------------------------------------------------------------------------


def _skipped_enrichment(skip_reason: str = "ldap_event") -> EnrichmentSkipped:
    """Build an EnrichmentSkipped payload."""
    return EnrichmentSkipped(applied=False, skip_reason=skip_reason)  # type: ignore[arg-type]


def _applied_enrichment(*, cache_hit: bool = False) -> EnrichmentApplied:
    """Build an EnrichmentApplied payload."""
    return EnrichmentApplied(applied=True, source="ldap", cache_hit=cache_hit)


def _single_source(
    value: str | None,
    sources: list[str],
    confidence: float,
) -> SingleSourceResolution:
    return SingleSourceResolution(
        resolution="single_source",
        resolved_value=value,
        confidence=confidence,
        sources=sources,  # type: ignore[arg-type]
    )


def _unanimous(
    value: str | None,
    sources: list[str],
    confidence: float,
) -> UnanimousResolution:
    return UnanimousResolution(
        resolution="unanimous",
        resolved_value=value,
        confidence=confidence,
        sources=sources,  # type: ignore[arg-type]
    )


def _priority(
    value: str | None,
    winner_source: str,
    conflicting: dict,
    confidence: float,
    penalty_applied: bool = True,
) -> PriorityResolution:
    return PriorityResolution(
        resolution="priority",
        resolved_value=value,
        confidence=confidence,
        winner_source=winner_source,  # type: ignore[arg-type]
        conflicting_values=conflicting,
        penalty_applied=penalty_applied,
    )


def _list_merge(
    groups: list[str],
    confidence: float,
    strategy: str = "union",
) -> ListMergeResolution:
    return ListMergeResolution(
        resolution="list_merge",
        resolved_value=groups,
        confidence=confidence,
        strategy=strategy,  # type: ignore[arg-type]
        total_unique_groups=len(groups),
    )


# ---------------------------------------------------------------------------
# Scene 1 (index 0) — frank/oidc: single source, no LDAP enrichment
# OIDC only; enrichment skipped because ldap is not yet enriching in this scene
# confidence contributions: display_name(0.70)*0.15 + primary_email(0.95)*0.25
#   + department(0.70)*0.20 + employee_type(0.60)*0.25 + groups(0.70)*0.15
# ---------------------------------------------------------------------------


def _scene1_frank_oidc() -> dict[str, Any]:
    """frank/oidc — all attributes from single OIDC source, enrichment skipped."""
    na = NormalizedAttributes(
        display_name="Frank Castle",
        primary_email="frank@corp.com",
        department="Engineering",
        employee_type="FTE",
        groups=["engineering", "vpn-users"],
        source_protocol="oidc",
        normalization_confidence=0.76,  # approximate: 0.70*0.15+0.95*0.25+0.70*0.20+0.60*0.25+0.70*0.15
        resolution_details={
            "display_name": _single_source("Frank Castle", ["oidc"], 0.70),
            "primary_email": _single_source("frank@corp.com", ["oidc"], 0.95),
            "department": _single_source("Engineering", ["oidc"], 0.70),
            "employee_type": _single_source("FTE", ["oidc"], 0.60),
            "groups": _list_merge(["engineering", "vpn-users"], 0.70),
        },
        enrichment=_skipped_enrichment("no_ldap_match"),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 2 (index 1) — frank/saml: single source, enrichment skipped
# ---------------------------------------------------------------------------


def _scene2_frank_saml() -> dict[str, Any]:
    """frank/saml — all attributes from single SAML source, enrichment skipped."""
    na = NormalizedAttributes(
        display_name="Frank Castle",
        primary_email="frank@corp.com",
        department="Engineering",
        employee_type="FTE",
        groups=["engineering", "vpn-users"],
        source_protocol="saml",
        normalization_confidence=0.74,  # approximate: 0.75*0.15+0.75*0.25+0.50*0.20+0.80*0.25+0.60*0.15
        resolution_details={
            "display_name": _single_source("Frank Castle", ["saml"], 0.75),
            "primary_email": _single_source("frank@corp.com", ["saml"], 0.75),
            "department": _single_source("Engineering", ["saml"], 0.50),
            "employee_type": _single_source("FTE", ["saml"], 0.80),
            "groups": _list_merge(["engineering", "vpn-users"], 0.70),
        },
        enrichment=_skipped_enrichment("no_ldap_match"),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 3 (index 2) — grace/ldap: LDAP-native event, enrichment skip=ldap_event
# ---------------------------------------------------------------------------


def _scene3_grace_ldap() -> dict[str, Any]:
    """grace/ldap — LDAP-native event; enrichment.skip_reason='ldap_event'."""
    na = NormalizedAttributes(
        display_name="Grace Hopper",
        primary_email="grace@corp.com",
        department="R&D",
        employee_type="contractor",
        groups=["admins", "engineering"],
        source_protocol="ldap",
        normalization_confidence=0.88,  # all from ldap with high weights
        resolution_details={
            "display_name": _single_source("Grace Hopper", ["ldap"], 0.85),
            "primary_email": _single_source("grace@corp.com", ["ldap"], 0.65),
            "department": _single_source("R&D", ["ldap"], 0.90),
            "employee_type": _single_source("contractor", ["ldap"], 0.95),
            "groups": _list_merge(["admins", "engineering"], 0.70),
        },
        enrichment=_skipped_enrichment("ldap_event"),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 4 (index 3) — mallory/saml: unmapped department retained with penalty,
# employee_type "wizard" discarded to None.
# Confidence C(4) must be lowest of the four single-source scenes.
# ---------------------------------------------------------------------------


def _scene4_mallory_saml() -> dict[str, Any]:
    """mallory/saml — Sorcery department retained (penalty), wizard employee_type → None."""
    na = NormalizedAttributes(
        display_name="Mallory Quinn",
        primary_email="mallory@corp.com",
        department="Sorcery",  # retained, unmapped
        employee_type=None,    # wizard discarded to None
        groups=["temp-access"],
        source_protocol="saml",
        normalization_confidence=0.52,  # penalized: dept confidence low, employee_type=0
        resolution_details={
            "display_name": _single_source("Mallory Quinn", ["saml"], 0.75),
            "primary_email": _single_source("mallory@corp.com", ["saml"], 0.75),
            # department single_source with penalty applied: saml weight=0.50 − 0.20 = 0.30
            "department": _single_source("Sorcery", ["saml"], 0.30),
            # employee_type absent: "wizard" was discarded to None upstream
            "groups": _list_merge(["temp-access"], 0.60),
        },
        enrichment=_skipped_enrichment("no_ldap_match"),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 5 (index 4) — alice/oidc with LDAP enrichment applied.
# unanimous scalars (display_name, primary_email, employee_type),
# list_merge groups from oidc+ldap, C(5) > C(1).
# ---------------------------------------------------------------------------


def _scene5_alice_oidc_enriched() -> dict[str, Any]:
    """alice/oidc — LDAP enrichment applied; unanimous scalars; groups list_merge."""
    na = NormalizedAttributes(
        display_name="Alice Smith",
        primary_email="alice@corp.com",
        department="Engineering",
        employee_type="FTE",
        groups=["engineering", "product-admins", "vpn-users"],
        source_protocol="oidc",
        normalization_confidence=0.88,  # unanimous/enriched → high confidence
        resolution_details={
            "display_name": _unanimous("Alice Smith", ["ldap", "oidc"], 0.85),
            "primary_email": _unanimous("alice@corp.com", ["ldap", "oidc"], 0.95),
            "department": _unanimous("Engineering", ["ldap", "oidc"], 0.90),
            "employee_type": _unanimous("FTE", ["ldap", "oidc"], 0.95),
            "groups": _list_merge(["engineering", "product-admins", "vpn-users"], 0.90),
        },
        enrichment=_applied_enrichment(cache_hit=False),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 6 (index 5) — diana/oidc with LDAP enrichment applied.
# display_name: priority winner=oidc; department: priority winner=ldap;
# groups: list_merge; C(6) < C(5).
# ---------------------------------------------------------------------------


def _scene6_diana_oidc_conflict() -> dict[str, Any]:
    """diana/oidc — LDAP enrichment; display_name priority winner=oidc; department priority winner=ldap."""
    na = NormalizedAttributes(
        display_name="Di Prince",   # oidc wins (priority=[oidc,saml,ldap])
        primary_email="diana@corp.com",
        department="Engineering",   # ldap wins (priority=[ldap,oidc,saml])
        employee_type="vendor",
        groups=["engineering", "oncall", "vpn-users"],
        source_protocol="oidc",
        normalization_confidence=0.79,  # priority resolutions lower confidence
        resolution_details={
            # display_name: oidc wins priority over ldap; penalty_applied=True
            # confidence = 0.70 * 0.8 = 0.56
            "display_name": _priority(
                "Di Prince",
                winner_source="oidc",
                conflicting={"ldap": "Diana Prince"},
                confidence=0.56,
            ),
            "primary_email": _unanimous("diana@corp.com", ["ldap", "oidc"], 0.95),
            # department: ldap wins priority over oidc; penalty_applied=True
            # confidence = 0.90 * 0.8 = 0.72
            "department": _priority(
                "Engineering",
                winner_source="ldap",
                conflicting={"oidc": "Marketing"},
                confidence=0.72,
            ),
            "employee_type": _single_source("vendor", ["oidc"], 0.60),
            "groups": _list_merge(["engineering", "oncall", "vpn-users"], 0.90),
        },
        enrichment=_applied_enrichment(cache_hit=False),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Helper: build the six-result list in scene order, aligned to SCENES
# ---------------------------------------------------------------------------


def _six_results() -> list[dict[str, Any]]:
    """Canonical six-result list aligned to SCENES[0..5] order."""
    return [
        _scene1_frank_oidc(),
        _scene2_frank_saml(),
        _scene3_grace_ldap(),
        _scene4_mallory_saml(),
        _scene5_alice_oidc_enriched(),
        _scene6_diana_oidc_conflict(),
    ]


# ---------------------------------------------------------------------------
# Helper: wrap a raw NormalizedAttributes dict into the poll_results row format
# poll_results returns list[dict] with keys: id, protocol, normalized_attributes
# ---------------------------------------------------------------------------


def _wrap_results(
    results: list[dict[str, Any]],
    event_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Wrap NA dicts into DB row format: {id, protocol, normalized_attributes}."""
    ids = event_ids or [f"id-{i}" for i in range(len(results))]
    return [
        {
            "id": ids[i],
            "protocol": results[i]["source_protocol"],
            "normalized_attributes": results[i],
        }
        for i in range(len(results))
    ]


# ===========================================================================
# CLASS 1 — verify_results: narrative verification contract
#
# Contract:
#   verify_results(scenes: list[dict], results: list[dict]) -> list[dict]
#
#   - scenes: list aligned to SCENES (6 dicts with user_id, protocol, etc.)
#   - results: list of DB rows from poll_results
#              (each row: {id, protocol, normalized_attributes: <dict>})
#   - Returns: a list of problem dicts (empty list = all checks passed).
#     Each problem dict must contain at least "scene" (int index or label)
#     and "message" (str describing the failed expectation).
#   - Never raises on invalid payloads — returns problems instead.
#   - Performs NO I/O (no DB, no HTTP): pure function, unit-testable.
# ===========================================================================


class TestVerifyResultsAcceptsConformingPayload:
    """verify_results returns an empty problems list for a fully conforming six-scene set.

    Spec §5.5: the verification function validates narrative expectations derived
    from the known scene design.
    """

    def test_conforming_six_scenes_returns_no_problems(self, demo_mod) -> None:
        """A fully conforming six-scene result set produces zero problems.

        WHY: The happy path must validate cleanly — a false positive would cause
        the demo to report failures when the pipeline is working correctly.
        """
        from demo_normalization_flow import SCENES

        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(SCENES, results)

        assert isinstance(problems, list), (
            f"verify_results must return a list, got {type(problems)!r}"
        )
        assert len(problems) == 0, (
            f"Expected 0 problems for conforming six-scene set, got {len(problems)}: {problems}"
        )

    def test_verify_results_returns_list_type(self, demo_mod) -> None:
        """Return type is always list (never None, never dict, never exception).

        WHY: Callers iterate the return value; a non-list return would crash main().
        """
        from demo_normalization_flow import SCENES

        results = _wrap_results(_six_results())
        out = demo_mod.verify_results(SCENES, results)

        assert isinstance(out, list), (
            f"verify_results must always return list, got {type(out)!r}"
        )


class TestVerifyResultsScene6DisplayNameWinner:
    """verify_results rejects Scene 6 payload with wrong display_name winner.

    Spec §5.5: Scene 6 display_name must have PriorityResolution with winner_source='oidc'.
    OIDC wins display_name conflicts per priority=[oidc,saml,ldap].
    """

    def test_scene6_display_name_winner_not_oidc_is_rejected(self, demo_mod) -> None:
        """Scene 6 with display_name winner_source='ldap' (wrong) produces a problem.

        WHY: display_name priority=[oidc,saml,ldap] means oidc must win on conflict.
        A wrong winner indicates the priority configuration is not being applied.
        The problem message must name 'scene 6' and 'display_name'.
        """
        from demo_normalization_flow import SCENES

        bad_scene6 = _scene6_diana_oidc_conflict()
        # Mutate: flip the display_name winner to ldap (wrong)
        bad_scene6["resolution_details"]["display_name"] = _priority(
            "Diana Prince",
            winner_source="ldap",          # wrong: should be oidc
            conflicting={"oidc": "Di Prince"},
            confidence=0.68,
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected at least one problem when Scene 6 display_name winner is 'ldap' not 'oidc'"
        )
        # Problem must identify scene 6 and the display_name expectation
        combined_msg = " ".join(
            str(p.get("message", "")) + " " + str(p.get("scene", ""))
            for p in problems
        ).lower()
        assert "6" in combined_msg or "diana" in combined_msg or "scene" in combined_msg, (
            f"Problem message must reference Scene 6, got: {problems}"
        )
        assert "display_name" in combined_msg or "display" in combined_msg, (
            f"Problem message must reference 'display_name', got: {problems}"
        )

    def test_scene6_display_name_winner_oidc_produces_no_problem(self, demo_mod) -> None:
        """Scene 6 with display_name winner_source='oidc' (correct) produces no display_name problem.

        WHY: Confirms the check is not a false positive for the correct winner.
        """
        from demo_normalization_flow import SCENES

        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(SCENES, results)

        display_name_problems = [
            p for p in problems
            if "display_name" in str(p.get("message", "")).lower()
            or "display" in str(p.get("message", "")).lower()
        ]
        assert len(display_name_problems) == 0, (
            f"No display_name problem expected for conforming Scene 6, got: {display_name_problems}"
        )


class TestVerifyResultsScene6DepartmentWinner:
    """verify_results rejects Scene 6 payload with wrong department winner.

    Spec §5.5: Scene 6 department must have PriorityResolution with winner_source='ldap'.
    LDAP wins department conflicts per priority=[ldap,oidc,saml].
    """

    def test_scene6_department_winner_not_ldap_is_rejected(self, demo_mod) -> None:
        """Scene 6 with department winner_source='oidc' (wrong) produces a problem.

        WHY: department priority=[ldap,oidc,saml] means ldap must win on conflict.
        A wrong winner indicates the normalization config is not being applied correctly.
        """
        from demo_normalization_flow import SCENES

        bad_scene6 = _scene6_diana_oidc_conflict()
        # Mutate: flip the department winner to oidc (wrong)
        bad_scene6["resolution_details"]["department"] = _priority(
            "Marketing",
            winner_source="oidc",          # wrong: should be ldap
            conflicting={"ldap": "Engineering"},
            confidence=0.56,
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected at least one problem when Scene 6 department winner is 'oidc' not 'ldap'"
        )
        combined_msg = " ".join(
            str(p.get("message", "")) + " " + str(p.get("scene", ""))
            for p in problems
        ).lower()
        assert "department" in combined_msg, (
            f"Problem message must reference 'department', got: {problems}"
        )


class TestVerifyResultsScene6GroupsListMerge:
    """verify_results rejects Scene 6 payload where groups is not list_merge.

    Spec §5.5: Scene 6 has multi-source groups (oidc + ldap enrichment) →
    groups resolution must be 'list_merge'.
    """

    def test_scene6_groups_not_list_merge_is_rejected(self, demo_mod) -> None:
        """Scene 6 groups resolution='single_source' (wrong) produces a problem.

        WHY: With LDAP enrichment applied and groups from two sources, list_merge
        is required. single_source would mean one source was silently ignored.
        """
        from demo_normalization_flow import SCENES

        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["resolution_details"]["groups"] = _single_source(
            "engineering", ["oidc"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 6 groups resolution is 'single_source' not 'list_merge'"
        )


class TestVerifyResultsConfidenceOrdering:
    """verify_results enforces the required confidence ordering across scenes.

    Spec §5.5: C(4) < C(2) < C(1) < C(3)
    Scene indices: scene 4 = index 3 (mallory), scene 2 = index 1 (frank/saml),
                   scene 1 = index 0 (frank/oidc), scene 3 = index 2 (grace/ldap)
    This ordering reflects the design intent:
      - Mallory (unknown dept, no employee_type) has lowest confidence
      - Frank SAML is lower than Frank OIDC (SAML dept weight < OIDC)
      - Grace LDAP is highest (LDAP has highest weights across all attrs)
    """

    def test_confidence_ordering_c4_lt_c2_lt_c1_lt_c3(self, demo_mod) -> None:
        """Conforming payload satisfies C(4)<C(2)<C(1)<C(3) — no ordering problem.

        WHY: Confirms the fixture is constructed correctly for the ordering contract.
        """
        from demo_normalization_flow import SCENES

        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(SCENES, results)

        ordering_problems = [
            p for p in problems
            if "confidence" in str(p.get("message", "")).lower()
            or "ordering" in str(p.get("message", "")).lower()
        ]
        assert len(ordering_problems) == 0, (
            f"No ordering problem expected for conforming fixture, got: {ordering_problems}"
        )

    def test_c4_not_lt_c2_violates_ordering(self, demo_mod) -> None:
        """C(4) >= C(2) violates the ordering — produces a problem naming the violated ordering.

        WHY: If mallory's confidence is not lower than frank/saml's, the penalized-unmapped
        story is not being demonstrated correctly.
        """
        from demo_normalization_flow import SCENES

        results = _six_results()
        # Make C(4) [mallory] equal to C(2) [frank/saml] — violates strict less-than
        results[3]["normalization_confidence"] = results[1]["normalization_confidence"]

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(4) == C(2), violating C(4) < C(2)"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in problems).lower()
        assert "confidence" in combined_msg or "ordering" in combined_msg or "c(4)" in combined_msg, (
            f"Problem must reference the confidence ordering, got: {problems}"
        )

    def test_c1_not_lt_c3_violates_ordering(self, demo_mod) -> None:
        """C(1) >= C(3) violates the ordering — produces a problem.

        WHY: Grace/LDAP should have the highest single-source confidence because
        LDAP has the highest attribute weights. Frank/OIDC beating Grace/LDAP
        would indicate a weight configuration error.
        """
        from demo_normalization_flow import SCENES

        results = _six_results()
        # Make C(1) [frank/oidc] higher than C(3) [grace/ldap] — violates C(1)<C(3)
        results[0]["normalization_confidence"] = 0.99  # too high
        results[2]["normalization_confidence"] = 0.50  # too low

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(1) > C(3), violating C(1) < C(3)"
        )

    def test_c5_gt_c1_required(self, demo_mod) -> None:
        """C(5) > C(1) required — alice/oidc enriched must beat frank/oidc unenriched.

        WHY: LDAP enrichment adds multi-source unanimous agreement, raising confidence.
        If enriched OIDC did not beat unenriched OIDC, the enrichment benefit is not visible.
        """
        from demo_normalization_flow import SCENES

        results = _six_results()
        # Violate C(5) > C(1) by making C(5) <= C(1)
        results[4]["normalization_confidence"] = results[0]["normalization_confidence"]

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(5) <= C(1), violating C(5) > C(1)"
        )

    def test_c6_lt_c5_required(self, demo_mod) -> None:
        """C(6) < C(5) required — diana's priority conflicts lower confidence vs alice's unanimous.

        WHY: Conflicting sources produce PriorityResolution with confidence*0.8,
        whereas unanimous agreement produces higher confidence. The demo must show
        this contrast between Scene 5 and Scene 6.
        """
        from demo_normalization_flow import SCENES

        results = _six_results()
        # Violate C(6) < C(5) by making C(6) >= C(5)
        results[5]["normalization_confidence"] = results[4]["normalization_confidence"] + 0.05

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(6) >= C(5), violating C(6) < C(5)"
        )


class TestVerifyResultsScene5MustBeUnanimous:
    """verify_results rejects Scene 5 payloads containing priority scalar resolutions.

    Spec §5.5: Scene 5 (alice/oidc enriched) has LDAP enrichment that agrees with
    the OIDC source. All scalars must be unanimous, not priority.
    """

    def test_scene5_priority_resolution_in_scalars_is_rejected(self, demo_mod) -> None:
        """Scene 5 with a priority resolution for display_name produces a problem.

        WHY: alice's OIDC and LDAP sources agree on all scalar attributes.
        A priority resolution means they disagreed, which violates the scene design
        and would mean the enrichment scenario is not demonstrating unanimous agreement.
        """
        from demo_normalization_flow import SCENES

        bad_scene5 = _scene5_alice_oidc_enriched()
        # Mutate display_name to priority (wrong for Scene 5)
        bad_scene5["resolution_details"]["display_name"] = _priority(
            "Alice Smith",
            winner_source="oidc",
            conflicting={"ldap": "A. Smith"},
            confidence=0.56,
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 display_name is 'priority' instead of 'unanimous'"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in problems).lower()
        assert "unanimous" in combined_msg or "scene 5" in combined_msg or "5" in combined_msg or "alice" in combined_msg, (
            f"Problem must reference Scene 5 unanimous expectation, got: {problems}"
        )


class TestVerifyResultsScene4UnmappedHandling:
    """verify_results enforces Scene 4 unmapped attribute handling.

    Spec §5.5: Scene 4 (mallory/saml):
    - department 'Sorcery' is retained (unmapped), with penalty_applied in confidence
    - employee_type 'wizard' is discarded to None (not stored in normalized attrs)
    """

    def test_scene4_employee_type_must_be_none(self, demo_mod) -> None:
        """Scene 4 employee_type must be None — 'wizard' was discarded.

        WHY: Non-standard employee_type values are discarded (not stored as a literal).
        If employee_type is non-None, the adapter failed to discard the unknown value.
        """
        from demo_normalization_flow import SCENES

        bad_scene4 = _scene4_mallory_saml()
        bad_scene4["employee_type"] = "FTE"  # wrong: should be None for unmapped "wizard"

        results = _six_results()
        results[3] = bad_scene4
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 4 employee_type is 'FTE' instead of None"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in problems).lower()
        assert "employee_type" in combined_msg or "scene 4" in combined_msg or "4" in combined_msg or "mallory" in combined_msg, (
            f"Problem must reference Scene 4 employee_type, got: {problems}"
        )

    def test_scene4_department_sorcery_must_be_retained(self, demo_mod) -> None:
        """Scene 4 department must be 'Sorcery' — unmapped values are retained with penalty.

        WHY: The normalization policy retains unknown department values (with a confidence
        penalty) rather than discarding them. Discarding would lose information.
        If department is None, the retention policy is not functioning.
        """
        from demo_normalization_flow import SCENES

        bad_scene4 = _scene4_mallory_saml()
        bad_scene4["department"] = None  # wrong: should be retained as "Sorcery"

        results = _six_results()
        results[3] = bad_scene4
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 4 department is None instead of retained 'Sorcery'"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in problems).lower()
        assert "department" in combined_msg or "scene 4" in combined_msg or "4" in combined_msg or "mallory" in combined_msg, (
            f"Problem must reference Scene 4 department retention, got: {problems}"
        )


class TestVerifyResultsScenesOneToFourAllSingleSource:
    """verify_results rejects Scenes 1–4 payloads that lack single_source or have enrichment applied.

    Spec §5.5: Scenes 1–4 have no LDAP enrichment applied; all scalar attributes
    come from a single protocol source.
    """

    def test_scenes_1_to_4_enrichment_must_be_skipped(self, demo_mod) -> None:
        """Scenes 1–4 enrichment.applied must be False — no LDAP enrichment for these scenes.

        WHY: LDAP enrichment is only expected for Scenes 5–6 (alice, diana).
        Scenes 1–4 should have enrichment.applied=False to demonstrate the
        contrast with enriched scenes.
        """
        from demo_normalization_flow import SCENES

        bad_scene1 = _scene1_frank_oidc()
        bad_scene1["enrichment"] = _applied_enrichment().model_dump(mode="json")
        # applied=True is wrong for frank/oidc which has no LDAP enrichment

        results = _six_results()
        results[0] = bad_scene1
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 1 has enrichment.applied=True (should be False)"
        )

    def test_scene3_grace_ldap_enrichment_must_be_ldap_event(self, demo_mod) -> None:
        """Scene 3 (grace/ldap) must have enrichment.skip_reason='ldap_event'.

        WHY: LDAP-native events always skip enrichment with skip_reason='ldap_event'.
        Any other skip_reason or applied=True would indicate incorrect handling of
        the native LDAP event case.
        """
        from demo_normalization_flow import SCENES

        bad_scene3 = _scene3_grace_ldap()
        # Wrong skip_reason for a native ldap event
        bad_scene3["enrichment"] = _skipped_enrichment("ldap_disabled").model_dump(mode="json")

        results = _six_results()
        results[2] = bad_scene3
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 3 enrichment.skip_reason is 'ldap_disabled' not 'ldap_event'"
        )

    def test_scenes_5_6_must_have_enrichment_applied(self, demo_mod) -> None:
        """Scenes 5–6 must have enrichment.applied=True — LDAP enrichment expected.

        WHY: alice and diana are OIDC events where LDAP enrichment should succeed.
        If enrichment is skipped for these scenes, the multi-source resolution
        story cannot be demonstrated.
        """
        from demo_normalization_flow import SCENES

        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["enrichment"] = _skipped_enrichment("no_ldap_match").model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 has enrichment.applied=False (should be True)"
        )


class TestVerifyResultsScene5GroupsListMerge:
    """verify_results rejects Scene 5 groups that are not list_merge.

    Spec §5.5: Scene 5 has LDAP enrichment → groups come from multiple sources
    → groups resolution must be 'list_merge'.
    """

    def test_scene5_groups_must_be_list_merge(self, demo_mod) -> None:
        """Scene 5 groups resolution='single_source' produces a problem.

        WHY: With LDAP enrichment providing groups, the merge must be a list_merge.
        single_source would indicate LDAP groups were not merged in.
        """
        from demo_normalization_flow import SCENES

        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["resolution_details"]["groups"] = _single_source(
            None, ["oidc"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 groups resolution is 'single_source' not 'list_merge'"
        )


class TestVerifyResultsGroupsCorroboration:
    """verify_results rejects Scenes 5–6 group merges with no directory corroboration.

    Spec §5.5: multi-source list_merge confidence is 0.7 + 0.3 × (fraction of
    merged groups present in more than one source). Scenes 5–6 expect 2 of 3
    merged groups corroborated by the directory (fraction ⅔); a token-only
    union (fraction 0, confidence 0.70) means LDAP enrichment merged nothing
    from the directory — e.g. memberOf back-population is broken — and must
    fail verification instead of rendering silently.
    """

    def test_scene5_token_only_union_is_rejected(self, demo_mod) -> None:
        """Scene 5 groups confidence 0.70 (zero corroborated fraction) produces a problem.

        WHY: enrichment.applied=True with a token-only group union is exactly the
        broken-overlay failure mode; the structural list_merge check alone cannot
        detect it.
        """
        from demo_normalization_flow import SCENES

        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["resolution_details"]["groups"] = _list_merge(
            ["engineering", "product-admins", "vpn-users"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert any(
            p["scene"] == 4 and "corroborat" in p["message"] for p in problems
        ), (
            f"Expected a Scene-5 corroboration problem for a token-only group "
            f"union (groups confidence 0.70), got: {problems}"
        )

    def test_scene6_token_only_union_is_rejected(self, demo_mod) -> None:
        """Scene 6 groups confidence 0.70 (zero corroborated fraction) produces a problem.

        WHY: the corroboration requirement applies to both enriched scenes.
        """
        from demo_normalization_flow import SCENES

        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["resolution_details"]["groups"] = _list_merge(
            ["engineering", "oncall", "vpn-users"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert any(
            p["scene"] == 5 and "corroborat" in p["message"] for p in problems
        ), (
            f"Expected a Scene-6 corroboration problem for a token-only group "
            f"union (groups confidence 0.70), got: {problems}"
        )

    def test_half_corroborated_fraction_is_accepted(self, demo_mod) -> None:
        """Scene 5 groups confidence 0.85 (corroborated fraction ½) produces no problem.

        WHY: the threshold is ≥ ½ so the check stays relative — robust to which
        2-of-3 groups corroborate — while still failing the broken-overlay states
        (fraction 0 → 0.70, fraction ⅓ → 0.80).
        """
        from demo_normalization_flow import SCENES

        scene5 = _scene5_alice_oidc_enriched()
        scene5["resolution_details"]["groups"] = _list_merge(
            ["engineering", "product-admins", "vpn-users"], 0.85
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(SCENES, wrapped)

        assert not any("corroborat" in p["message"] for p in problems), (
            f"Expected no corroboration problem at corroborated fraction ½ "
            f"(groups confidence 0.85), got: {problems}"
        )


# ===========================================================================
# CLASS 2 — SQL query constants
#
# demo_normalization.py defines these as module-level constants:
#   POLL_QUERY  — parameterized SELECT for polling normalized results
#   CLEANUP_QUERY — parameterized DELETE for cleanup
#
# Both must use %(ids)s for parameterization — NOT f-strings or % interpolation.
# ===========================================================================


class TestSqlQueryConstants:
    """poll_results and cleanup_events use exact parameterized SQL queries.

    Spec §5.5: The queries must be parameterized to prevent SQL injection.
    The exact strings are asserted here so any drift in column list, table
    name, or parameter style is caught.
    """

    EXPECTED_POLL_QUERY = (
        "SELECT id, protocol, normalized_attributes FROM events WHERE id = ANY(%(ids)s)"
    )
    EXPECTED_CLEANUP_QUERY = "DELETE FROM events WHERE id = ANY(%(ids)s)"

    def test_poll_query_constant_exists(self, demo_mod) -> None:
        """Module must define a POLL_QUERY constant.

        WHY: A named constant documents intent and makes the parameterized query
        inspectable for audits; an inlined string is harder to find and review.
        """
        assert hasattr(demo_mod, "POLL_QUERY"), (
            "demo_normalization.py must define a module-level POLL_QUERY constant "
            "so the parameterized polling query is auditable."
        )

    def test_poll_query_exact_string(self, demo_mod) -> None:
        """POLL_QUERY must be exactly the expected parameterized SELECT string.

        WHY: The column list (id, protocol, normalized_attributes) must be exact
        so poll_results can access the right columns. Any deviation breaks the
        column→dict mapping.
        """
        assert demo_mod.POLL_QUERY == self.EXPECTED_POLL_QUERY, (
            f"POLL_QUERY mismatch.\n"
            f"Expected: {self.EXPECTED_POLL_QUERY!r}\n"
            f"Got:      {demo_mod.POLL_QUERY!r}"
        )

    def test_cleanup_query_constant_exists(self, demo_mod) -> None:
        """Module must define a CLEANUP_QUERY constant.

        WHY: Same rationale as POLL_QUERY — named constants are auditable.
        """
        assert hasattr(demo_mod, "CLEANUP_QUERY"), (
            "demo_normalization.py must define a module-level CLEANUP_QUERY constant "
            "so the parameterized cleanup query is auditable."
        )

    def test_cleanup_query_exact_string(self, demo_mod) -> None:
        """CLEANUP_QUERY must be exactly the expected parameterized DELETE string.

        WHY: The DELETE must use %(ids)s parameterization, not f-string interpolation
        of the ids list. f-string interpolation would allow SQL injection via a
        crafted event ID.
        """
        assert demo_mod.CLEANUP_QUERY == self.EXPECTED_CLEANUP_QUERY, (
            f"CLEANUP_QUERY mismatch.\n"
            f"Expected: {self.EXPECTED_CLEANUP_QUERY!r}\n"
            f"Got:      {demo_mod.CLEANUP_QUERY!r}"
        )

    def test_poll_query_uses_parameterized_ids_not_fstring(self, demo_mod) -> None:
        """POLL_QUERY must contain '%(ids)s' — not an f-string or %-interpolation placeholder.

        WHY: %(ids)s is the psycopg named-parameter style. Using %s without a name
        would require positional binding and break the execute({ids: ...}) call.
        An f-string would silently interpolate the ids list as a Python string,
        bypassing parameterization entirely.
        """
        query = demo_mod.POLL_QUERY
        assert "%(ids)s" in query, (
            f"POLL_QUERY must use %(ids)s parameterization, got: {query!r}"
        )
        # Must NOT contain bare %s (positional) or f-string braces
        assert "{ids}" not in query, (
            f"POLL_QUERY must not use {{ids}} f-string syntax, got: {query!r}"
        )

    def test_cleanup_query_uses_parameterized_ids_not_fstring(self, demo_mod) -> None:
        """CLEANUP_QUERY must contain '%(ids)s' parameterization.

        WHY: Same rationale as poll query — prevents SQL injection via crafted ids.
        """
        query = demo_mod.CLEANUP_QUERY
        assert "%(ids)s" in query, (
            f"CLEANUP_QUERY must use %(ids)s parameterization, got: {query!r}"
        )
        assert "{ids}" not in query, (
            f"CLEANUP_QUERY must not use {{ids}} f-string syntax, got: {query!r}"
        )


# ===========================================================================
# CLASS 3 — submit_scenes: POST contract
#
# submit_scenes(scenes, ingest_url, args) -> list[str]
#
# Injectable seam: submit_scenes accepts an optional httpx.Client so tests
# can verify the POST contract without network access:
#
#   def submit_scenes(
#       scenes, ingest_url, args, *, http_client=None
#   ) -> list[str]:
#       client = http_client or httpx.Client()
#       ...
#
# Tests use unittest.mock to patch httpx.Client or accept a mock client.
# ===========================================================================


class TestSubmitScenes:
    """submit_scenes POSTs each scene to {INGEST_URL}/events/ingest and collects ids.

    Spec §5.5: submit must POST all six scenes and return the six event IDs in order.
    The HTTP client is injectable so tests run without a live service.
    """

    def _make_mock_response(self, event_id: str) -> MagicMock:
        """Build a mock httpx Response that returns 202 with id + status."""
        resp = MagicMock()
        resp.status_code = 202
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"id": event_id, "status": "accepted"}
        return resp

    def _make_mock_client(self, event_ids: list[str]) -> MagicMock:
        """Build a mock httpx.Client where .post() returns successive responses."""
        client = MagicMock()
        client.post.side_effect = [
            self._make_mock_response(eid) for eid in event_ids
        ]
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    def test_submit_scenes_posts_to_ingest_endpoint(self, demo_mod) -> None:
        """submit_scenes POSTs to {ingest_url}/events/ingest for each scene.

        WHY: The exact endpoint path must match what event-ingestion exposes.
        A different path (e.g. /ingest or /event) would receive a 404.
        """
        from demo_normalization_flow import SCENES

        event_ids = [f"uuid-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)
        args = MagicMock()
        args.pace = 0
        args.step = False

        result = demo_mod.submit_scenes(
            SCENES, "http://localhost:8001", args, http_client=mock_client
        )

        assert mock_client.post.call_count == 6, (
            f"Expected 6 POST calls for 6 scenes, got {mock_client.post.call_count}"
        )
        # Verify endpoint path
        for call_args in mock_client.post.call_args_list:
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            assert "/events/ingest" in str(url), (
                f"POST must target /events/ingest, got url={url!r}"
            )

    def test_submit_scenes_returns_six_ids_in_order(self, demo_mod) -> None:
        """submit_scenes returns the six event IDs in submission order.

        WHY: poll_results and cleanup_events depend on IDs being in scene order.
        Out-of-order IDs would corrupt the scenes→results alignment.
        """
        from demo_normalization_flow import SCENES

        event_ids = ["id-alice", "id-bob", "id-charlie", "id-dave", "id-eve", "id-frank"]
        mock_client = self._make_mock_client(event_ids)
        args = MagicMock()
        args.pace = 0
        args.step = False

        result = demo_mod.submit_scenes(
            SCENES, "http://localhost:8001", args, http_client=mock_client
        )

        assert result == event_ids, (
            f"Expected IDs in submission order {event_ids!r}, got {result!r}"
        )

    def test_submit_scenes_returns_list_of_strings(self, demo_mod) -> None:
        """submit_scenes return value is a list of strings.

        WHY: poll_results and cleanup_events both consume the return value as
        list[str]. A list of UUID objects or mixed types would fail string ops.
        """
        from demo_normalization_flow import SCENES

        event_ids = [f"evt-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)
        args = MagicMock()
        args.pace = 0
        args.step = False

        result = demo_mod.submit_scenes(
            SCENES, "http://localhost:8001", args, http_client=mock_client
        )

        assert isinstance(result, list), f"Expected list, got {type(result)!r}"
        assert len(result) == 6, f"Expected 6 IDs, got {len(result)}"
        for i, item in enumerate(result):
            assert isinstance(item, str), (
                f"Expected result[{i}] to be str, got {type(item)!r}: {item!r}"
            )

    def test_submit_scenes_sends_scene_fields_in_post_body(self, demo_mod) -> None:
        """submit_scenes includes scene user_id and protocol in the POST body.

        WHY: The ingest service validates user_id, protocol, client_ip, source,
        is_synthetic, and raw_attributes. Missing fields trigger a 422 rejection.
        """
        from demo_normalization_flow import SCENES

        event_ids = [f"eid-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)
        args = MagicMock()
        args.pace = 0
        args.step = False

        demo_mod.submit_scenes(
            SCENES, "http://localhost:8001", args, http_client=mock_client
        )

        # Check first call body contains scene 0 fields
        first_call = mock_client.post.call_args_list[0]
        # Accept body as json= or data= kwarg, or as second positional arg
        body = (
            first_call[1].get("json")
            or first_call[1].get("data")
            or (first_call[0][1] if len(first_call[0]) > 1 else None)
        )
        assert body is not None, (
            "POST call must include a request body (json= kwarg expected)"
        )
        assert body.get("user_id") == "frank", (
            f"Expected user_id='frank' in Scene 0 POST body, got {body!r}"
        )
        assert body.get("protocol") == "oidc", (
            f"Expected protocol='oidc' in Scene 0 POST body, got {body!r}"
        )


# ===========================================================================
# CLASS 4 — render_results: Rich output content checks
#
# render_results(scenes, results, verification) -> None
#
# Injectable seam: render_results accepts an optional `console` parameter
# so tests can capture output without stdout:
#
#   def render_results(
#       scenes, results, verification, *, console=None
#   ) -> None:
#       con = console or rich.console.Console()
#       ...
#
# Tests use rich.console.Console(file=io.StringIO(), force_terminal=False)
# to capture rendered text.
# ===========================================================================


def _make_capture_console():
    """Create a Rich Console that writes to an in-memory buffer."""
    try:
        from rich.console import Console

        buf = io.StringIO()
        con = Console(file=buf, force_terminal=False, width=200)
        return con, buf
    except ImportError:
        pytest.skip("rich not installed — render tests require rich")


class TestRenderResultsScene4UnmappedAnnotations:
    """render_results emits both unmapped-handling annotations for Scene 4.

    Spec §5.5: Scene 4 render must note:
    1. department 'Sorcery' was retained with a confidence penalty
    2. employee_type 'wizard' was discarded to None (enum-safe policy)
    """

    def test_scene4_render_notes_department_sorcery_retained_with_penalty(self, demo_mod) -> None:
        """Scene 4 rendering mentions 'Sorcery' retained with a penalty.

        WHY: Without this annotation, the user sees 'Sorcery' in the output
        with no explanation. The annotation makes the normalization policy explicit.
        """
        from demo_normalization_flow import SCENES

        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(SCENES, results, verification=None, console=con)

        output = buf.getvalue().lower()
        assert "sorcery" in output, (
            "Scene 4 render must include 'Sorcery' department value in output"
        )
        # Must indicate the value was retained (not discarded)
        has_retained = any(word in output for word in ["retained", "kept", "preserved", "penalty"])
        assert has_retained, (
            f"Scene 4 render must note that 'Sorcery' was retained (with penalty). "
            f"Output did not contain 'retained'/'kept'/'preserved'/'penalty'. "
            f"Output snippet: {buf.getvalue()[:500]!r}"
        )

    def test_scene4_render_notes_employee_type_wizard_discarded(self, demo_mod) -> None:
        """Scene 4 rendering mentions that employee_type 'wizard' was discarded to null.

        WHY: Without this annotation, employee_type=None looks like missing data
        rather than a deliberate enum-safe discard policy.
        """
        from demo_normalization_flow import SCENES

        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(SCENES, results, verification=None, console=con)

        output = buf.getvalue().lower()
        # wizard must appear (identifying the discarded value)
        assert "wizard" in output, (
            "Scene 4 render must reference 'wizard' employee_type in output"
        )
        # Must indicate it was discarded / null / dropped
        has_discarded = any(
            word in output for word in ["discarded", "dropped", "null", "none", "unknown"]
        )
        assert has_discarded, (
            f"Scene 4 render must note that 'wizard' was discarded to null. "
            f"Output did not contain 'discarded'/'dropped'/'null'/'none'/'unknown'. "
            f"Output snippet: {buf.getvalue()[:500]!r}"
        )


class TestRenderResultsScene6SplitSourceAnnotation:
    """render_results emits the 'Why the split?' annotation for Scene 6.

    Spec §5.5: Scene 6 render must explain that two different sources won
    two different attributes, and convey the reason why a single rule
    cannot capture both.
    """

    def test_scene6_render_mentions_oidc_wins_display_name(self, demo_mod) -> None:
        """Scene 6 rendering conveys that OIDC won display_name (preferred/presented name).

        WHY: The split-source annotation must explain WHY oidc won display_name —
        because it holds the user's current preferred/presented name.
        """
        from demo_normalization_flow import SCENES

        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(SCENES, results, verification=None, console=con)

        output = buf.getvalue().lower()
        # Must mention OIDC winning display_name in context of the split
        has_oidc_display = (
            ("oidc" in output and "display" in output)
            or ("oidc" in output and "name" in output)
        )
        assert has_oidc_display, (
            f"Scene 6 render must convey OIDC winning display_name. "
            f"Output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_mentions_ldap_wins_department(self, demo_mod) -> None:
        """Scene 6 rendering conveys that LDAP won department (org structure facts).

        WHY: The annotation must explain WHY ldap won department —
        because LDAP holds authoritative org directory information.
        """
        from demo_normalization_flow import SCENES

        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(SCENES, results, verification=None, console=con)

        output = buf.getvalue().lower()
        has_ldap_dept = (
            ("ldap" in output and "department" in output)
            or ("ldap" in output and "dept" in output)
            or ("ldap" in output and "org" in output)
        )
        assert has_ldap_dept, (
            f"Scene 6 render must convey LDAP winning department. "
            f"Output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_mentions_split_source_or_two_winners(self, demo_mod) -> None:
        """Scene 6 rendering notes that two different sources won two different attributes.

        WHY: This is the core narrative point for Scene 6 — different sources are
        authoritative for different attribute types. A callout about two winners
        makes this visible to the reader.
        """
        from demo_normalization_flow import SCENES

        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(SCENES, results, verification=None, console=con)

        output = buf.getvalue().lower()
        # Any phrasing that conveys the split: "split", "two sources", "different sources",
        # "why", or the combination of oidc and ldap each winning
        has_split_annotation = any(
            phrase in output
            for phrase in [
                "split",
                "two different",
                "why",
                "neither",
                "single",
                "no single",
                "both oidc",
                "both ldap",
                "oidc wins",
                "ldap wins",
            ]
        )
        assert has_split_annotation, (
            f"Scene 6 render must include a split-source annotation "
            f"(e.g. 'why the split?', 'two different sources won', etc.). "
            f"Output snippet: {buf.getvalue()[:800]!r}"
        )


class TestConfidenceStyleHelper:
    """confidence_style(value) returns the correct Rich color for threshold boundaries.

    Spec §5.5 color thresholds:
      >= 0.80 → green
      0.50 – 0.79 → amber (yellow/orange)
      < 0.50 → red

    confidence_style() is exposed as a module-level helper so tests
    (and other callers) can verify color logic independently.

    Injectable seam: confidence_style(value: float) -> str
      Returns a Rich markup style string, e.g. "green", "yellow", "red",
      or a full Rich style string like "bold green".
    """

    def test_confidence_style_exists_as_callable(self, demo_mod) -> None:
        """Module must expose a callable confidence_style.

        WHY: A named helper is testable in isolation and can be reused
        across the render function without duplicating threshold logic.
        """
        assert hasattr(demo_mod, "confidence_style") and callable(demo_mod.confidence_style), (
            "demo_normalization.py must define a module-level callable "
            "confidence_style(value: float) -> str so the render loop can be "
            "tested independently."
        )

    def test_confidence_style_at_0_80_is_green(self, demo_mod) -> None:
        """confidence_style(0.80) returns a 'green' style (boundary inclusive).

        WHY: 0.80 is the lower bound of the green zone; it must not fall into amber.
        """
        style = demo_mod.confidence_style(0.80)
        assert "green" in str(style).lower(), (
            f"Expected 'green' style for confidence=0.80, got {style!r}"
        )

    def test_confidence_style_at_0_99_is_green(self, demo_mod) -> None:
        """confidence_style(0.99) returns a 'green' style (high confidence)."""
        style = demo_mod.confidence_style(0.99)
        assert "green" in str(style).lower(), (
            f"Expected 'green' style for confidence=0.99, got {style!r}"
        )

    def test_confidence_style_at_0_79_is_amber(self, demo_mod) -> None:
        """confidence_style(0.79) returns an amber/yellow style (boundary).

        WHY: 0.79 is just below the green threshold; it must not be green.
        """
        style = demo_mod.confidence_style(0.79)
        has_amber = any(
            word in str(style).lower() for word in ["yellow", "amber", "orange"]
        )
        assert has_amber, (
            f"Expected amber/yellow style for confidence=0.79, got {style!r}"
        )

    def test_confidence_style_at_0_50_is_amber(self, demo_mod) -> None:
        """confidence_style(0.50) returns an amber/yellow style (boundary inclusive).

        WHY: 0.50 is the lower bound of the amber zone; it must not fall into red.
        """
        style = demo_mod.confidence_style(0.50)
        has_amber = any(
            word in str(style).lower() for word in ["yellow", "amber", "orange"]
        )
        assert has_amber, (
            f"Expected amber/yellow style for confidence=0.50, got {style!r}"
        )

    def test_confidence_style_at_0_49_is_red(self, demo_mod) -> None:
        """confidence_style(0.49) returns a 'red' style (boundary).

        WHY: 0.49 is just below the amber threshold; it must not be amber.
        """
        style = demo_mod.confidence_style(0.49)
        assert "red" in str(style).lower(), (
            f"Expected 'red' style for confidence=0.49, got {style!r}"
        )

    def test_confidence_style_at_0_0_is_red(self, demo_mod) -> None:
        """confidence_style(0.0) returns a 'red' style (minimum confidence)."""
        style = demo_mod.confidence_style(0.0)
        assert "red" in str(style).lower(), (
            f"Expected 'red' style for confidence=0.0, got {style!r}"
        )

    @pytest.mark.parametrize(
        "value, expected_zone",
        [
            (1.0, "green"),
            (0.80, "green"),
            (0.85, "green"),
            (0.79, "amber"),
            (0.65, "amber"),
            (0.50, "amber"),
            (0.49, "red"),
            (0.30, "red"),
            (0.0, "red"),
        ],
    )
    def test_confidence_style_thresholds_parametrized(
        self, demo_mod, value: float, expected_zone: str
    ) -> None:
        """Parametrized threshold coverage for confidence_style.

        WHY: Boundary conditions (0.80, 0.79, 0.50, 0.49) are where off-by-one
        errors hide. Explicit parametrization prevents threshold drift.
        """
        style = str(demo_mod.confidence_style(value)).lower()
        if expected_zone == "green":
            assert "green" in style, (
                f"confidence_style({value}) expected green zone, got {style!r}"
            )
        elif expected_zone == "amber":
            has_amber = any(word in style for word in ["yellow", "amber", "orange"])
            assert has_amber, (
                f"confidence_style({value}) expected amber zone, got {style!r}"
            )
        elif expected_zone == "red":
            assert "red" in style, (
                f"confidence_style({value}) expected red zone, got {style!r}"
            )


# ===========================================================================
# CLASS 5 — cleanup_events: DB execute contract
#
# cleanup_events(event_ids: list[str], db_dsn: str, *, db_execute=None) -> None
#
# Injectable seam: cleanup_events accepts an optional db_execute
# callable so tests can verify the DELETE without a live DB:
#
#   def cleanup_events(
#       event_ids, db_dsn, *, db_execute=None
#   ) -> None:
#       if db_execute is not None:
#           db_execute(CLEANUP_QUERY, {"ids": event_ids})
#       else:
#           with psycopg.connect(db_dsn) as conn:
#               with conn.cursor() as cur:
#                   cur.execute(CLEANUP_QUERY, {"ids": event_ids})
#
# The --keep flag decision is tested at the main() level by checking whether
# cleanup_events is called at all (not by passing a flag to cleanup_events itself).
# ===========================================================================


class TestCleanupEvents:
    """cleanup_events executes the parameterized DELETE with the given event IDs.

    Spec §5.5: cleanup must pass the IDs as a bound parameter, never interpolated.
    """

    def test_cleanup_events_calls_execute_with_ids_as_parameter(self, demo_mod) -> None:
        """cleanup_events calls db_execute with CLEANUP_QUERY and ids as bound parameter.

        WHY: The DELETE must use parameterized %(ids)s binding. Passing the IDs
        as a Python list in the second argument prevents SQL injection.
        """
        mock_execute = MagicMock()
        event_ids = ["id-a", "id-b", "id-c"]

        demo_mod.cleanup_events(event_ids, "host=localhost dbname=naas", db_execute=mock_execute)

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        # First positional arg must be the cleanup query
        query_arg = call_args[0][0] if call_args[0] else call_args[1].get("query", "")
        assert "DELETE FROM events" in query_arg, (
            f"cleanup_events must call db_execute with a DELETE query, got: {query_arg!r}"
        )
        # Second positional or 'params' keyword arg must contain the ids
        params_arg = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("params", call_args[1].get("parameters", {}))
        )
        assert params_arg is not None, (
            f"cleanup_events must pass ids as a bound parameter, call_args: {call_args!r}"
        )
        # ids must be in the params (either as 'ids' key or as the value)
        has_ids = (
            (isinstance(params_arg, dict) and params_arg.get("ids") == event_ids)
            or (isinstance(params_arg, (list, tuple)) and list(event_ids) == list(params_arg))
        )
        assert has_ids, (
            f"cleanup_events must bind ids={event_ids!r} as a parameter. "
            f"Got params: {params_arg!r}"
        )

    def test_cleanup_events_passes_all_ids(self, demo_mod) -> None:
        """cleanup_events passes all provided event IDs to the DELETE.

        WHY: A partial delete would leave ghost events in the database,
        corrupting subsequent demo runs (duplicate-event pollution).
        """
        mock_execute = MagicMock()
        event_ids = ["e1", "e2", "e3", "e4", "e5", "e6"]

        demo_mod.cleanup_events(event_ids, "host=localhost dbname=naas", db_execute=mock_execute)

        mock_execute.assert_called_once()
        call_args = mock_execute.call_args
        params_arg = (
            call_args[0][1]
            if len(call_args[0]) > 1
            else call_args[1].get("params", call_args[1].get("parameters", {}))
        )
        if isinstance(params_arg, dict):
            actual_ids = params_arg.get("ids", [])
        else:
            actual_ids = list(params_arg) if params_arg else []

        assert set(actual_ids) == set(event_ids), (
            f"All {len(event_ids)} IDs must be passed to DELETE. "
            f"Expected {event_ids!r}, got {actual_ids!r}"
        )

    def test_cleanup_events_not_called_when_keep_flag_set(self, demo_mod) -> None:
        """When args.keep=True, cleanup_events is not called.

        WHY: The --keep flag is explicitly designed to retain events for
        post-run inspection. Calling cleanup with --keep would defeat the flag's
        entire purpose.

        The --keep decision lives in main(); this test verifies the integration
        by patching cleanup_events and calling main() with --keep.
        """
        # Patch all I/O functions so main() doesn't attempt real connections
        with (
            patch.object(demo_mod, "run_preflight"),
            patch.object(
                demo_mod,
                "submit_scenes",
                return_value=["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"],
            ),
            patch.object(
                demo_mod,
                "poll_results",
                return_value=_wrap_results(_six_results()),
            ),
            patch.object(
                demo_mod,
                "verify_results",
                return_value=[],
            ),
            patch.object(demo_mod, "render_results"),
            patch.object(demo_mod, "cleanup_events") as mock_cleanup,
        ):
            import argparse

            # Simulate: python demo_normalization.py --keep
            test_args = argparse.Namespace(
                keep=True,
                pace=0,
                step=False,
                timeout=30,
                skip_verify=False,
                ingest_url="http://localhost:8001",
                db_dsn="host=localhost dbname=naas",
            )
            with patch("argparse.ArgumentParser.parse_args", return_value=test_args):
                demo_mod.main()

        mock_cleanup.assert_not_called()

    def test_cleanup_events_called_when_keep_not_set(self, demo_mod) -> None:
        """When args.keep=False (default), cleanup_events is called with the event IDs.

        WHY: The default behavior is to clean up after the demo run.
        If cleanup is accidentally skipped, the database accumulates synthetic
        events that pollute subsequent runs.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]

        with (
            patch.object(demo_mod, "run_preflight"),
            patch.object(demo_mod, "submit_scenes", return_value=submitted_ids),
            patch.object(
                demo_mod,
                "poll_results",
                return_value=_wrap_results(_six_results()),
            ),
            patch.object(
                demo_mod,
                "verify_results",
                return_value=[],
            ),
            patch.object(demo_mod, "render_results"),
            patch.object(demo_mod, "cleanup_events") as mock_cleanup,
        ):
            import argparse

            test_args = argparse.Namespace(
                keep=False,
                pace=0,
                step=False,
                timeout=30,
                skip_verify=False,
                ingest_url="http://localhost:8001",
                db_dsn="host=localhost dbname=naas",
            )
            with patch("argparse.ArgumentParser.parse_args", return_value=test_args):
                demo_mod.main()

        mock_cleanup.assert_called_once()
        call_args = mock_cleanup.call_args
        actual_ids = call_args[0][0] if call_args[0] else call_args[1].get("event_ids", [])
        assert actual_ids == submitted_ids, (
            f"cleanup_events must receive the submitted IDs {submitted_ids!r}, "
            f"got {actual_ids!r}"
        )
