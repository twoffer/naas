# Tests for demo/demo_normalization.py — flow functions:
# submit_scenes, poll_results, verify_results, render_results, cleanup_events,
# SQL query constants, confidence_style, and the module-level run_preflight.
#
# All functions are exercised through injectable seams (http_client, console,
# db_execute, db_fetch) — no live services required.

from __future__ import annotations

import argparse
import importlib.util
import io
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
    spec = importlib.util.spec_from_file_location(
        "demo_normalization_flow", DEMO_SCRIPT
    )
    mod = importlib.util.module_from_spec(spec)
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
#                           strategy, total_unique_groups, sources
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
    sources: list[str] | None = None,
) -> ListMergeResolution:
    return ListMergeResolution(
        resolution="list_merge",
        resolved_value=groups,
        confidence=confidence,
        strategy=strategy,  # type: ignore[arg-type]
        total_unique_groups=len(groups),
        sources=sources or [],  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Scene 1 (index 0) — frank/oidc: single source, no LDAP enrichment
# OIDC only; enrichment skipped because ldap is not yet enriching in this scene.
# Scalar resolution_details must be single_source; groups is a list_merge with
# exactly one contributing source (Check 1 in verify_results).
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
            # The pipeline resolves groups as list_merge even for one source;
            # verify_results Check 1 requires exactly one contributing source.
            "groups": _list_merge(
                ["engineering", "vpn-users"], 0.80, sources=["oidc"]
            ),
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
            # Single-source groups are still a list_merge (see Scene 1 note).
            "groups": _list_merge(
                ["engineering", "vpn-users"], 0.60, sources=["saml"]
            ),
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
            # Single-source groups are still a list_merge (see Scene 1 note).
            "groups": _list_merge(
                ["admins", "engineering"], 0.70, sources=["ldap"]
            ),
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
        employee_type=None,  # wizard discarded to None
        groups=["temp-access"],
        source_protocol="saml",
        normalization_confidence=0.52,  # penalized: dept confidence low, employee_type=0
        resolution_details={
            "display_name": _single_source("Mallory Quinn", ["saml"], 0.75),
            "primary_email": _single_source("mallory@corp.com", ["saml"], 0.75),
            # department single_source with penalty applied: saml weight=0.50 − 0.20 = 0.30
            "department": _single_source("Sorcery", ["saml"], 0.30),
            # employee_type absent: "wizard" was discarded to None upstream
            # Single-source groups are still a list_merge (see Scene 1 note).
            "groups": _list_merge(["temp-access"], 0.60, sources=["saml"]),
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
            "groups": _list_merge(
                ["engineering", "product-admins", "vpn-users"],
                0.90,
                sources=["ldap", "oidc"],
            ),
        },
        enrichment=_applied_enrichment(cache_hit=False),
    )
    return na.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Scene 6 (index 5) — diana/oidc with LDAP enrichment applied.
# display_name: priority winner=oidc; department: priority winner=ldap;
# groups: list_merge — token omits vpn-users, directory back-populates it
# (merged set is a strict superset of the token; 1 of 3 corroborated → 0.80,
# below Scene 5's 0.90); C(6) < C(5).
# ---------------------------------------------------------------------------


def _scene6_diana_oidc_conflict() -> dict[str, Any]:
    """diana/oidc — LDAP enrichment; display_name priority winner=oidc; department priority winner=ldap."""
    na = NormalizedAttributes(
        display_name="Di Prince",  # oidc wins (priority=[oidc,saml,ldap])
        primary_email="diana@corp.com",
        department="Engineering",  # ldap wins (priority=[ldap,oidc,saml])
        employee_type="vendor",
        groups=["engineering", "oncall", "vpn-users"],
        source_protocol="oidc",
        normalization_confidence=0.74,  # priority resolutions + partial group overlap lower confidence
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
            "groups": _list_merge(
                ["engineering", "oncall", "vpn-users"], 0.80, sources=["ldap", "oidc"]
            ),
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
#     Each problem dict must contain at least "scene" (1-based int; -1 for
#     internal errors) and "message" (str, self-contained — no scene prefix).
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
        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(demo_mod.SCENES, results)

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
        results = _wrap_results(_six_results())
        out = demo_mod.verify_results(demo_mod.SCENES, results)

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
        The problem must have scene=6 and reference 'display_name'.
        """
        bad_scene6 = _scene6_diana_oidc_conflict()
        # Mutate: flip the display_name winner to ldap (wrong)
        bad_scene6["resolution_details"]["display_name"] = _priority(
            "Diana Prince",
            winner_source="ldap",  # wrong: should be oidc
            conflicting={"oidc": "Di Prince"},
            confidence=0.68,
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected at least one problem when Scene 6 display_name winner is 'ldap' not 'oidc'"
        )
        # Problem must have scene=6 (1-based) and reference display_name
        dn_problems = [p for p in problems if p.get("scene") == 6]
        assert dn_problems, (
            f"Problem must have scene=6 (1-based), got scenes: "
            f"{[p.get('scene') for p in problems]}"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in dn_problems).lower()
        assert "display_name" in combined_msg or "display" in combined_msg, (
            f"Problem message must reference 'display_name', got: {dn_problems}"
        )

    def test_scene6_display_name_winner_oidc_produces_no_problem(
        self, demo_mod
    ) -> None:
        """Scene 6 with display_name winner_source='oidc' (correct) produces no display_name problem.

        WHY: Confirms the check is not a false positive for the correct winner.
        """
        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(demo_mod.SCENES, results)

        display_name_problems = [
            p
            for p in problems
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
        bad_scene6 = _scene6_diana_oidc_conflict()
        # Mutate: flip the department winner to oidc (wrong)
        bad_scene6["resolution_details"]["department"] = _priority(
            "Marketing",
            winner_source="oidc",  # wrong: should be ldap
            conflicting={"ldap": "Engineering"},
            confidence=0.56,
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected at least one problem when Scene 6 department winner is 'oidc' not 'ldap'"
        )
        combined_msg = " ".join(
            str(p.get("message", "")) + " " + str(p.get("scene", "")) for p in problems
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
        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["resolution_details"]["groups"] = _single_source(
            "engineering", ["oidc"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

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
        results = _wrap_results(_six_results())
        problems = demo_mod.verify_results(demo_mod.SCENES, results)

        ordering_problems = [
            p
            for p in problems
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
        results = _six_results()
        # Make C(4) [mallory] equal to C(2) [frank/saml] — violates strict less-than
        results[3]["normalization_confidence"] = results[1]["normalization_confidence"]

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(4) == C(2), violating C(4) < C(2)"
        )
        combined_msg = " ".join(str(p.get("message", "")) for p in problems).lower()
        assert (
            "confidence" in combined_msg
            or "ordering" in combined_msg
            or "c(4)" in combined_msg
        ), f"Problem must reference the confidence ordering, got: {problems}"

    def test_c1_not_lt_c3_violates_ordering(self, demo_mod) -> None:
        """C(1) >= C(3) violates the ordering — produces a problem.

        WHY: Grace/LDAP should have the highest single-source confidence because
        LDAP has the highest attribute weights. Frank/OIDC beating Grace/LDAP
        would indicate a weight configuration error.
        """
        results = _six_results()
        # Make C(1) [frank/oidc] higher than C(3) [grace/ldap] — violates C(1)<C(3)
        results[0]["normalization_confidence"] = 0.99  # too high
        results[2]["normalization_confidence"] = 0.50  # too low

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(1) > C(3), violating C(1) < C(3)"
        )

    def test_c5_gt_c1_required(self, demo_mod) -> None:
        """C(5) > C(1) required — alice/oidc enriched must beat frank/oidc unenriched.

        WHY: LDAP enrichment adds multi-source unanimous agreement, raising confidence.
        If enriched OIDC did not beat unenriched OIDC, the enrichment benefit is not visible.
        """
        results = _six_results()
        # Violate C(5) > C(1) by making C(5) <= C(1)
        results[4]["normalization_confidence"] = results[0]["normalization_confidence"]

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when C(5) <= C(1), violating C(5) > C(1)"
        )

    def test_c6_lt_c5_required(self, demo_mod) -> None:
        """C(6) < C(5) required — diana's priority conflicts lower confidence vs alice's unanimous.

        WHY: Conflicting sources produce PriorityResolution with confidence*0.8,
        whereas unanimous agreement produces higher confidence. The demo must show
        this contrast between Scene 5 and Scene 6.
        """
        results = _six_results()
        # Violate C(6) < C(5) by making C(6) >= C(5)
        results[5]["normalization_confidence"] = (
            results[4]["normalization_confidence"] + 0.05
        )

        wrapped = _wrap_results(results)
        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

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
        The problem must have scene=5 (1-based) and reference 'unanimous'.
        """
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

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 display_name is 'priority' instead of 'unanimous'"
        )
        # Problem must have scene=5 (1-based) and mention unanimous
        scene5_problems = [p for p in problems if p.get("scene") == 5]
        assert scene5_problems, (
            f"Problem must have scene=5 (1-based), got scenes: "
            f"{[p.get('scene') for p in problems]}"
        )
        combined_msg = " ".join(
            str(p.get("message", "")) for p in scene5_problems
        ).lower()
        assert "unanimous" in combined_msg, (
            f"Problem must reference 'unanimous' expectation, got: {scene5_problems}"
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
        The problem must have scene=4 (1-based) and reference 'employee_type'.
        """
        bad_scene4 = _scene4_mallory_saml()
        bad_scene4["employee_type"] = (
            "FTE"  # wrong: should be None for unmapped "wizard"
        )

        results = _six_results()
        results[3] = bad_scene4
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 4 employee_type is 'FTE' instead of None"
        )
        scene4_problems = [p for p in problems if p.get("scene") == 4]
        assert scene4_problems, (
            f"Problem must have scene=4 (1-based), got scenes: "
            f"{[p.get('scene') for p in problems]}"
        )
        combined_msg = " ".join(
            str(p.get("message", "")) for p in scene4_problems
        ).lower()
        assert "employee_type" in combined_msg, (
            f"Problem must reference 'employee_type', got: {scene4_problems}"
        )

    def test_scene4_department_sorcery_must_be_retained(self, demo_mod) -> None:
        """Scene 4 department must be 'Sorcery' — unmapped values are retained with penalty.

        WHY: The normalization policy retains unknown department values (with a confidence
        penalty) rather than discarding them. Discarding would lose information.
        If department is None, the retention policy is not functioning.
        The problem must have scene=4 (1-based) and reference 'department'.
        """
        bad_scene4 = _scene4_mallory_saml()
        bad_scene4["department"] = None  # wrong: should be retained as "Sorcery"

        results = _six_results()
        results[3] = bad_scene4
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 4 department is None instead of retained 'Sorcery'"
        )
        scene4_problems = [p for p in problems if p.get("scene") == 4]
        assert scene4_problems, (
            f"Problem must have scene=4 (1-based), got scenes: "
            f"{[p.get('scene') for p in problems]}"
        )
        combined_msg = " ".join(
            str(p.get("message", "")) for p in scene4_problems
        ).lower()
        assert "department" in combined_msg, (
            f"Problem must reference 'department', got: {scene4_problems}"
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
        bad_scene1 = _scene1_frank_oidc()
        bad_scene1["enrichment"] = _applied_enrichment().model_dump(mode="json")
        # applied=True is wrong for frank/oidc which has no LDAP enrichment

        results = _six_results()
        results[0] = bad_scene1
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 1 has enrichment.applied=True (should be False)"
        )

    def test_scene3_grace_ldap_enrichment_must_be_ldap_event(self, demo_mod) -> None:
        """Scene 3 (grace/ldap) must have enrichment.skip_reason='ldap_event'.

        WHY: LDAP-native events always skip enrichment with skip_reason='ldap_event'.
        Any other skip_reason or applied=True would indicate incorrect handling of
        the native LDAP event case.
        """
        bad_scene3 = _scene3_grace_ldap()
        # Wrong skip_reason for a native ldap event
        bad_scene3["enrichment"] = _skipped_enrichment("ldap_disabled").model_dump(
            mode="json"
        )

        results = _six_results()
        results[2] = bad_scene3
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 3 enrichment.skip_reason is 'ldap_disabled' not 'ldap_event'"
        )

    def test_scenes_5_6_must_have_enrichment_applied(self, demo_mod) -> None:
        """Scenes 5–6 must have enrichment.applied=True — LDAP enrichment expected.

        WHY: alice and diana are OIDC events where LDAP enrichment should succeed.
        If enrichment is skipped for these scenes, the multi-source resolution
        story cannot be demonstrated.
        """
        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["enrichment"] = _skipped_enrichment("no_ldap_match").model_dump(
            mode="json"
        )

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 has enrichment.applied=False (should be True)"
        )

    def test_scene1_scalar_resolved_multi_source_is_rejected(self, demo_mod) -> None:
        """A non-single_source scalar in Scenes 1–4 must produce a problem.

        WHY: Scenes 1–4 submit one protocol with no directory match, so a
        unanimous/priority scalar means enrichment merged data it should not
        have — the single-source narrative would be false.
        """
        bad_scene1 = _scene1_frank_oidc()
        bad_scene1["resolution_details"]["department"] = _unanimous(
            "Engineering", ["oidc", "ldap"], 0.90
        ).model_dump(mode="json")

        results = _six_results()
        results[0] = bad_scene1
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(
            p["scene"] == 1 and "single_source" in p["message"] for p in problems
        ), f"Expected a Scene 1 single_source problem for department, got: {problems}"

    def test_scene1_groups_with_two_sources_is_rejected(self, demo_mod) -> None:
        """Groups merged from more than one source in Scenes 1–4 must produce a problem.

        WHY: The pipeline resolves groups as a list_merge even for a single
        source, so the resolution type alone cannot distinguish 'no merge
        happened' — Check 1 requires at most one contributing source.
        """
        bad_scene1 = _scene1_frank_oidc()
        bad_scene1["resolution_details"]["groups"] = _list_merge(
            ["engineering", "vpn-users"], 0.85, sources=["ldap", "oidc"]
        ).model_dump(mode="json")

        results = _six_results()
        results[0] = bad_scene1
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(
            p["scene"] == 1 and "single-source list_merge" in p["message"]
            for p in problems
        ), f"Expected a Scene 1 single-source groups problem, got: {problems}"


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
        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["resolution_details"]["groups"] = _single_source(
            None, ["oidc"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert len(problems) > 0, (
            "Expected a problem when Scene 5 groups resolution is 'single_source' not 'list_merge'"
        )


class TestVerifyResultsGroupsCorroboration:
    """verify_results rejects Scenes 5–6 group merges with no directory corroboration.

    Spec §5.5: multi-source list_merge confidence is 0.7 + 0.3 × (fraction of
    merged groups present in more than one source). Scene 5 expects 2 of 3
    merged groups corroborated (fraction ⅔, threshold ≥ ½); Scene 6's token
    omits vpn-users so only 1 of 3 corroborates (fraction ⅓, threshold ≥ ¼).
    A token-only union (fraction 0, confidence 0.70) means LDAP enrichment
    merged nothing from the directory — e.g. memberOf back-population is
    broken — and must fail verification instead of rendering silently.
    Scene 6 must additionally show back-population: merged groups a strict
    superset of the token groups, and groups confidence < Scene 5's.
    """

    def test_scene5_token_only_union_is_rejected(self, demo_mod) -> None:
        """Scene 5 groups confidence 0.70 (zero corroborated fraction) produces a problem.

        WHY: enrichment.applied=True with a token-only group union is exactly the
        broken-overlay failure mode; the structural list_merge check alone cannot
        detect it. The problem must have scene=5 (1-based) and mention 'corroborat'.
        """
        bad_scene5 = _scene5_alice_oidc_enriched()
        bad_scene5["resolution_details"]["groups"] = _list_merge(
            ["engineering", "product-admins", "vpn-users"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = bad_scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(
            p["scene"] == 5 and "corroborat" in p["message"] for p in problems
        ), (
            f"Expected a Scene-5 corroboration problem (scene=5, 1-based) for a "
            f"token-only group union (groups confidence 0.70), got: {problems}"
        )

    def test_scene6_token_only_union_is_rejected(self, demo_mod) -> None:
        """Scene 6 groups confidence 0.70 (zero corroborated fraction) produces a problem.

        WHY: the corroboration requirement applies to both enriched scenes.
        The problem must have scene=6 (1-based) and mention 'corroborat'.
        """
        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["resolution_details"]["groups"] = _list_merge(
            ["engineering", "oncall", "vpn-users"], 0.70
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(
            p["scene"] == 6 and "corroborat" in p["message"] for p in problems
        ), (
            f"Expected a Scene-6 corroboration problem (scene=6, 1-based) for a "
            f"token-only group union (groups confidence 0.70), got: {problems}"
        )

    def test_half_corroborated_fraction_is_accepted(self, demo_mod) -> None:
        """Scene 5 groups confidence 0.85 (corroborated fraction ½) produces no problem.

        WHY: the threshold is ≥ ½ so the check stays relative — robust to which
        2-of-3 groups corroborate — while still failing the broken-overlay states
        (fraction 0 → 0.70, fraction ⅓ → 0.80).
        """
        scene5 = _scene5_alice_oidc_enriched()
        scene5["resolution_details"]["groups"] = _list_merge(
            ["engineering", "product-admins", "vpn-users"], 0.85
        ).model_dump(mode="json")

        results = _six_results()
        results[4] = scene5
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert not any("corroborat" in p["message"] for p in problems), (
            f"Expected no corroboration problem at corroborated fraction ½ "
            f"(groups confidence 0.85), got: {problems}"
        )

    def test_scene6_one_third_fraction_is_accepted(self, demo_mod) -> None:
        """Scene 6 groups confidence 0.80 (corroborated fraction ⅓) produces no problem.

        WHY: Scene 6's token omits vpn-users, so only engineering corroborates —
        fraction ⅓ is the expected healthy value and must pass the ≥ ¼ threshold.
        """
        results = _six_results()
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert not any(
            p["scene"] == 6 and "corroborat" in p["message"] for p in problems
        ), (
            f"Expected no Scene-6 corroboration problem (scene=6, 1-based) at fraction ⅓ "
            f"(groups confidence 0.80), got: {problems}"
        )

    def test_scene6_groups_confidence_not_below_scene5_is_rejected(
        self, demo_mod
    ) -> None:
        """Scene 6 groups confidence equal to Scene 5's produces a problem.

        WHY: Scene 6's token only partially matches the directory, so its merge
        confidence must sit strictly below Scene 5's fuller-overlap merge.
        The problem must have scene=6 (1-based) and mention 'groups confidence'.
        """
        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["resolution_details"]["groups"] = _list_merge(
            ["engineering", "oncall", "vpn-users"], 0.90, sources=["ldap", "oidc"]
        ).model_dump(mode="json")

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(
            p["scene"] == 6 and "groups confidence" in p["message"] for p in problems
        ), (
            f"Expected a Scene-6 problem (scene=6, 1-based) when groups confidence "
            f"(0.90) is not below Scene 5's (0.90), got: {problems}"
        )

    def test_scene6_non_superset_groups_rejected(self, demo_mod) -> None:
        """Scene 6 merged groups equal to the token groups produces a problem.

        WHY: the directory must back-populate vpn-users (absent from the token);
        a merged set that matches the token exactly means enrichment added nothing.
        The problem must have scene=6 (1-based) and mention 'superset'.
        """
        bad_scene6 = _scene6_diana_oidc_conflict()
        bad_scene6["groups"] = ["engineering", "oncall"]

        results = _six_results()
        results[5] = bad_scene6
        wrapped = _wrap_results(results)

        problems = demo_mod.verify_results(demo_mod.SCENES, wrapped)

        assert any(p["scene"] == 6 and "superset" in p["message"] for p in problems), (
            f"Expected a Scene-6 strict-superset problem (scene=6, 1-based) when "
            f"merged groups equal the token groups, got: {problems}"
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
    """poll_results and cleanup_events use parameterized SQL queries.

    Spec §5.5: The queries must be parameterized to prevent SQL injection.
    The valuable property is %(ids)s parameterization (asserted below);
    the exact query text is free to evolve (column additions, ORDER BY)
    without breaking these tests.
    """

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
        # Must NOT contain f-string braces
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
# submit_scenes(scenes, ingest_url, *, http_client=None) -> list[str]
#
# Injectable seam: submit_scenes accepts an optional httpx.Client so tests
# can verify the POST contract without network access.
# Error messages are 1-based: "Failed to submit scene {i+1} ({user_id}): ..."
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
        client.post.side_effect = [self._make_mock_response(eid) for eid in event_ids]
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    def test_submit_scenes_posts_to_ingest_endpoint(self, demo_mod) -> None:
        """submit_scenes POSTs to {ingest_url}/events/ingest for each scene.

        WHY: The exact endpoint path must match what event-ingestion exposes.
        A different path (e.g. /ingest or /event) would receive a 404.
        """
        event_ids = [f"uuid-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)

        demo_mod.submit_scenes(
            demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
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
        event_ids = [
            "id-alice",
            "id-bob",
            "id-charlie",
            "id-dave",
            "id-eve",
            "id-frank",
        ]
        mock_client = self._make_mock_client(event_ids)

        result = demo_mod.submit_scenes(
            demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
        )

        assert result == event_ids, (
            f"Expected IDs in submission order {event_ids!r}, got {result!r}"
        )

    def test_submit_scenes_returns_list_of_strings(self, demo_mod) -> None:
        """submit_scenes return value is a list of strings.

        WHY: poll_results and cleanup_events both consume the return value as
        list[str]. A list of UUID objects or mixed types would fail string ops.
        """
        event_ids = [f"evt-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)

        result = demo_mod.submit_scenes(
            demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
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
        event_ids = [f"eid-{i}" for i in range(6)]
        mock_client = self._make_mock_client(event_ids)

        demo_mod.submit_scenes(
            demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
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
# CLASS 3b — TestSubmitScenesErrors: error path for submit_scenes
#
# A failing POST must raise SystemExit whose message names the 1-based scene
# number and the user_id of the failing scene.
# ===========================================================================


class TestSubmitScenesErrors:
    """submit_scenes exits with a 1-based scene reference on POST failure.

    WHY: The error message must name the failing scene number (1-based) and
    user_id so the operator can immediately identify which scene caused the
    failure without parsing ambiguous 0-based indices.
    """

    def test_submit_scenes_http_error_exits_with_scene_and_user(self, demo_mod) -> None:
        """A POST that raises on raise_for_status exits with 1-based scene + user_id.

        WHY: The revised error format "Failed to submit scene {i+1} ({user_id}): ..."
        must reference 1-based numbering. Scene index 0 is Scene 1 in the message.
        """
        import httpx

        bad_resp = MagicMock()
        bad_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=MagicMock()
        )
        mock_client = MagicMock()
        mock_client.post.return_value = bad_resp
        mock_client.close = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.submit_scenes(
                demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
            )

        msg = str(exc_info.value)
        # The first scene (index 0) must be reported as "scene 1"
        assert "1" in msg, f"Error must name 1-based scene number, got: {msg!r}"
        assert "frank" in msg.lower(), (
            f"Error must name the user_id of the failing scene, got: {msg!r}"
        )

    def test_submit_scenes_network_error_exits_with_scene_and_user(
        self, demo_mod
    ) -> None:
        """A POST that raises a network exception exits with 1-based scene + user_id.

        WHY: Any exception from client.post (network failure, timeout) must be caught
        and reported with the same 1-based scene format.
        """
        mock_client = MagicMock()
        mock_client.post.side_effect = ConnectionError("refused")
        mock_client.close = MagicMock()

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.submit_scenes(
                demo_mod.SCENES, "http://localhost:8001", http_client=mock_client
            )

        msg = str(exc_info.value)
        assert "1" in msg, f"Error must name 1-based scene number, got: {msg!r}"
        assert "frank" in msg.lower(), (
            f"Error must name the user_id of the failing scene, got: {msg!r}"
        )


# ===========================================================================
# CLASS 4 — poll_results: db_fetch seam coverage
#
# poll_results(event_ids, db_dsn, timeout, *, db_fetch=None) -> list[dict]
#
# If db_fetch(query, params) -> rows is provided, no psycopg needed.
# Rows are tuples: (id, protocol, normalized_attributes).
# str-typed normalized_attributes are json.loads-ed.
# Results are returned in event_ids submission order.
# On timeout: prints unprocessed ids and sys.exit(1).
# Live DB error: sys.exit with "Database error during polling".
# ===========================================================================


class TestPollResults:
    """poll_results exercises the db_fetch injectable seam.

    WHY: Using the db_fetch seam lets tests verify parse/ordering/timeout logic
    without a live PostgreSQL connection.
    """

    def test_poll_returns_parsed_results_dict_passthrough(self, demo_mod) -> None:
        """poll_results returns parsed results when all rows are present as dicts.

        WHY: When normalized_attributes is already a dict (psycopg JSONB), it must
        pass through without double-parsing.
        """
        event_ids = ["id-0", "id-1", "id-2"]
        na_dicts = [_scene1_frank_oidc(), _scene2_frank_saml(), _scene3_grace_ldap()]
        rows = [
            (event_ids[i], na_dicts[i]["source_protocol"], na_dicts[i])
            for i in range(3)
        ]

        def db_fetch(query: str, params: dict) -> list:
            return rows

        results = demo_mod.poll_results(event_ids, "unused", 10.0, db_fetch=db_fetch)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result["id"] == event_ids[i]
            assert isinstance(result["normalized_attributes"], dict)

    def test_poll_returns_parsed_results_json_string(self, demo_mod) -> None:
        """poll_results json.loads str-typed normalized_attributes.

        WHY: Some DB drivers return JSONB columns as strings. The function must
        deserialize them so callers always receive dict-typed normalized_attributes.
        """
        import json

        event_ids = ["id-0", "id-1"]
        na_dicts = [_scene1_frank_oidc(), _scene2_frank_saml()]
        rows = [
            (event_ids[i], na_dicts[i]["source_protocol"], json.dumps(na_dicts[i]))
            for i in range(2)
        ]

        def db_fetch(query: str, params: dict) -> list:
            return rows

        results = demo_mod.poll_results(event_ids, "unused", 10.0, db_fetch=db_fetch)

        assert len(results) == 2
        for result in results:
            assert isinstance(result["normalized_attributes"], dict), (
                "normalized_attributes must be deserialized from JSON string"
            )

    def test_poll_returns_results_in_submission_order(self, demo_mod) -> None:
        """poll_results returns results in event_ids submission order even when db returns different order.

        WHY: render_results aligns scenes[i] with results[i] by index; out-of-order
        results would swap scenes in the output.
        """
        event_ids = ["id-a", "id-b", "id-c"]
        na_dicts = [_scene1_frank_oidc(), _scene2_frank_saml(), _scene3_grace_ldap()]
        # DB returns rows in reverse order
        rows = [
            ("id-c", na_dicts[2]["source_protocol"], na_dicts[2]),
            ("id-a", na_dicts[0]["source_protocol"], na_dicts[0]),
            ("id-b", na_dicts[1]["source_protocol"], na_dicts[1]),
        ]

        def db_fetch(query: str, params: dict) -> list:
            return rows

        results = demo_mod.poll_results(event_ids, "unused", 10.0, db_fetch=db_fetch)

        assert [r["id"] for r in results] == event_ids, (
            f"Results must be in submission order {event_ids!r}, "
            f"got {[r['id'] for r in results]!r}"
        )

    def test_poll_retries_until_all_complete(self, demo_mod, monkeypatch) -> None:
        """Rows with NULL normalized_attributes are not complete; second poll completes.

        WHY: The poll loop retries on partial results (rows with NULL
        normalized_attributes are present but not ready). The sleep between
        polls is monkeypatched to avoid slowing the test.
        """
        event_ids = ["id-0", "id-1"]
        na_dict = _scene1_frank_oidc()

        call_count = 0

        def db_fetch(query: str, params: dict) -> list:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: id-0 ready, id-1 not ready (NULL)
                return [("id-0", "oidc", na_dict)]
            # Second call: both ready
            return [
                ("id-0", "oidc", na_dict),
                ("id-1", "saml", _scene2_frank_saml()),
            ]

        monkeypatch.setattr(demo_mod.time, "sleep", lambda _: None)

        results = demo_mod.poll_results(event_ids, "unused", 30.0, db_fetch=db_fetch)

        assert call_count == 2, f"Expected 2 db_fetch calls, got {call_count}"
        assert len(results) == 2

    def test_poll_timeout_exits_with_code_1_and_prints_unprocessed(
        self, demo_mod, monkeypatch, capsys
    ) -> None:
        """Timeout with incomplete rows exits with code 1 and prints the unprocessed ids.

        WHY: A timeout must be distinguishable from a clean finish. sys.exit(1)
        propagates to main()'s finally block for cleanup. The printed message
        must name the stuck ids so the operator can investigate.
        """
        event_ids = ["id-0", "id-1", "id-2"]
        # db_fetch always returns only id-0 — id-1 and id-2 never complete
        na_dict = _scene1_frank_oidc()

        def db_fetch(query: str, params: dict) -> list:
            return [("id-0", "oidc", na_dict)]

        monkeypatch.setattr(demo_mod.time, "sleep", lambda _: None)

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.poll_results(event_ids, "unused", 0.0, db_fetch=db_fetch)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "id-1" in captured.out or "id-2" in captured.out, (
            f"Timeout output must list unprocessed ids, got: {captured.out!r}"
        )

    def test_poll_live_path_db_error_exits_with_message(
        self, demo_mod, monkeypatch
    ) -> None:
        """psycopg.connect raising exits with a message containing 'Database error during polling'.

        WHY: The live-path error handler translates the raw exception into a clear
        operator message. Without it, a DB failure surfaces as an uncaught stack trace.
        """
        import psycopg

        monkeypatch.setattr(
            psycopg, "connect", MagicMock(side_effect=Exception("connection refused"))
        )

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.poll_results(["id-0"], "host=bad", 5.0)

        msg = str(exc_info.value)
        assert "Database error during polling" in msg, (
            f"Exit message must contain 'Database error during polling', got: {msg!r}"
        )


# ===========================================================================
# CLASS 4b — render_results: Rich output content checks
#
# render_results(scenes, results, *, console=None, pace=0.0, step=False) -> None
#
# Injectable seam: render_results accepts an optional `console` parameter
# so tests can capture output without stdout.
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

    def test_scene4_render_notes_department_sorcery_retained_with_penalty(
        self, demo_mod
    ) -> None:
        """Scene 4 rendering mentions 'Sorcery' retained with a penalty.

        WHY: Without this annotation, the user sees 'Sorcery' in the output
        with no explanation. The annotation makes the normalization policy explicit.
        """
        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(demo_mod.SCENES, results, console=con)

        output = buf.getvalue().lower()
        assert "sorcery" in output, (
            "Scene 4 render must include 'Sorcery' department value in output"
        )
        # Must indicate the value was retained (not discarded)
        has_retained = any(
            word in output for word in ["retained", "kept", "preserved", "penalty"]
        )
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
        con, buf = _make_capture_console()
        results = _wrap_results(_six_results())

        demo_mod.render_results(demo_mod.SCENES, results, console=con)

        output = buf.getvalue().lower()
        # wizard must appear (identifying the discarded value)
        assert "wizard" in output, (
            "Scene 4 render must reference 'wizard' employee_type in output"
        )
        # Must indicate it was discarded / null / dropped
        has_discarded = any(
            word in output
            for word in ["discarded", "dropped", "null", "none", "unknown"]
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

    These tests render ONLY Scene 6 via _render_scene_panel to avoid false
    positives from keyword matches in earlier scenes (e.g. 'single' appearing
    in Scenes 1–4's single_source rows).
    """

    def test_scene6_render_mentions_why_the_split(self, demo_mod) -> None:
        """Scene 6 rendering includes 'why the split' annotation text.

        WHY: The 'Why the split?' heading is the primary entry point for the
        split-source narrative. If it is absent the entire annotation block is
        missing. Rendering only Scene 6 ensures the match is Scene-6-specific.
        """
        con, buf = _make_capture_console()
        result6 = _wrap_results([_scene6_diana_oidc_conflict()])[0]

        demo_mod._render_scene_panel(5, demo_mod.SCENES[5], result6, con)

        output = buf.getvalue().lower()
        assert "why the split" in output, (
            f"Scene 6 render must contain 'why the split' annotation. "
            f"Output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_explains_oidc_wins_display_name(self, demo_mod) -> None:
        """Scene 6 rendering explains why OIDC won display_name (preferred name rationale).

        WHY: The annotation must state that OIDC holds the user's current
        preferred/presented name — not just assert which source won.
        Rendering only Scene 6 ensures this is the scene-6 annotation, not a
        generic resolution-type row from an earlier scene.
        """
        con, buf = _make_capture_console()
        result6 = _wrap_results([_scene6_diana_oidc_conflict()])[0]

        demo_mod._render_scene_panel(5, demo_mod.SCENES[5], result6, con)

        output = buf.getvalue().lower()
        # Must mention display_name → oidc in the rationale
        assert "display_name" in output or "display" in output, (
            f"Scene 6 annotation must reference display_name, "
            f"output snippet: {buf.getvalue()[:800]!r}"
        )
        assert "oidc" in output, (
            f"Scene 6 annotation must name oidc as the display_name winner, "
            f"output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_explains_ldap_wins_department(self, demo_mod) -> None:
        """Scene 6 rendering explains why LDAP won department (org structure rationale).

        WHY: The annotation must state that LDAP holds authoritative org structure
        facts. Rendering only Scene 6 avoids matching 'ldap' from any earlier panel.
        """
        con, buf = _make_capture_console()
        result6 = _wrap_results([_scene6_diana_oidc_conflict()])[0]

        demo_mod._render_scene_panel(5, demo_mod.SCENES[5], result6, con)

        output = buf.getvalue().lower()
        assert "ldap" in output, (
            f"Scene 6 annotation must name ldap as the department winner, "
            f"output snippet: {buf.getvalue()[:800]!r}"
        )
        # Must reference department and org structure reasoning
        assert "department" in output or "org" in output, (
            f"Scene 6 annotation must reference department/org rationale, "
            f"output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_punchline_no_single_rule(self, demo_mod) -> None:
        """Scene 6 rendering states that no single rule can capture both sources.

        WHY: This is the core IAM insight in Scene 6 — identity presentation and
        org hierarchy come from different authoritative sources. The script's
        scene6_note contains 'No single OIDC-or-LDAP rule could capture both'.
        """
        con, buf = _make_capture_console()
        result6 = _wrap_results([_scene6_diana_oidc_conflict()])[0]

        demo_mod._render_scene_panel(5, demo_mod.SCENES[5], result6, con)

        output = buf.getvalue().lower()
        # "no single" is the distinctive punchline phrase
        assert "no single" in output or "neither" in output or "split" in output, (
            f"Scene 6 annotation must contain the 'no single rule' punchline, "
            f"output snippet: {buf.getvalue()[:800]!r}"
        )

    def test_scene6_render_groups_merge_mentions_vpn_users(self, demo_mod) -> None:
        """Scene 6 rendering mentions 'vpn-users' in the groups-merge note.

        WHY: The annotation explicitly notes that the token omitted vpn-users and
        the directory back-populated it. If this line is absent, the groups
        back-population story is not rendered.
        """
        con, buf = _make_capture_console()
        result6 = _wrap_results([_scene6_diana_oidc_conflict()])[0]

        demo_mod._render_scene_panel(5, demo_mod.SCENES[5], result6, con)

        output = buf.getvalue().lower()
        assert "vpn-users" in output, (
            f"Scene 6 annotation must mention vpn-users (back-populated by directory). "
            f"Output snippet: {buf.getvalue()[:800]!r}"
        )


# ===========================================================================
# CLASS 5 — TestRunPreflight: preflight check branches
#
# run_preflight(ingest_url, norm_url, db_dsn) -> None
#
# Each failure branch exits non-zero. Monkeypatch httpx.get and psycopg.connect
# on the real modules (both installed).
# ===========================================================================


class TestRunPreflight:
    """run_preflight exits non-zero on any failure; returns None on success.

    WHY: Preflight guards the demo from submitting events to a degraded
    service. Each failure branch must be verified so regressions are caught
    before the demo is run against a real environment.
    """

    def test_ingestion_health_non_200_exits(self, demo_mod, monkeypatch) -> None:
        """Ingestion /health returning non-200 triggers sys.exit.

        WHY: A 503 from event-ingestion means events will not be accepted.
        """
        import httpx

        def mock_get(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "503", request=MagicMock(), response=MagicMock()
            )
            return resp

        monkeypatch.setattr(httpx, "get", mock_get)

        with pytest.raises(SystemExit):
            demo_mod.run_preflight(
                "http://ingest:8001", "http://norm:8002", "host=localhost"
            )

    def test_ingestion_health_unhealthy_status_exits(
        self, demo_mod, monkeypatch
    ) -> None:
        """Ingestion /health returning status != 'healthy' triggers sys.exit.

        WHY: An unhealthy status means the service is up but degraded — events
        may be silently dropped or misprocessed.
        """
        import httpx

        call_count = 0

        def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            # First call (ingestion) returns unhealthy
            if call_count == 1:
                resp.json.return_value = {"status": "degraded"}
            else:
                resp.json.return_value = {"status": "healthy"}
            return resp

        monkeypatch.setattr(httpx, "get", mock_get)

        with pytest.raises(SystemExit):
            demo_mod.run_preflight(
                "http://ingest:8001", "http://norm:8002", "host=localhost"
            )

    def test_normalization_health_unreachable_exits(
        self, demo_mod, monkeypatch
    ) -> None:
        """Normalization /health unreachable triggers sys.exit.

        WHY: An unreachable normalization service means events will pile up
        without ever being processed.
        """
        import httpx

        call_count = 0

        def mock_get(url: str, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Ingestion is healthy
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = {"status": "healthy"}
                return resp
            # Normalization is unreachable
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "get", mock_get)

        with pytest.raises(SystemExit):
            demo_mod.run_preflight(
                "http://ingest:8001", "http://norm:8002", "host=localhost"
            )

    def test_db_connect_failure_exits(self, demo_mod, monkeypatch) -> None:
        """psycopg.connect failure triggers sys.exit.

        WHY: If PostgreSQL is unreachable, poll_results will fail immediately
        after scenes are submitted — cleanup may be impossible.
        """
        import httpx
        import psycopg

        def mock_get(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"status": "healthy"}
            return resp

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(
            psycopg, "connect", MagicMock(side_effect=Exception("no pg"))
        )

        with pytest.raises(SystemExit):
            demo_mod.run_preflight(
                "http://ingest:8001", "http://norm:8002", "host=localhost"
            )

    def test_all_healthy_returns_none(self, demo_mod, monkeypatch) -> None:
        """All health checks passing and DB connecting successfully returns None.

        WHY: Verifies the success path does not accidentally call sys.exit.
        """
        import httpx
        import psycopg

        def mock_get(url: str, **kwargs: Any) -> MagicMock:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {"status": "healthy"}
            return resp

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        monkeypatch.setattr(httpx, "get", mock_get)
        monkeypatch.setattr(psycopg, "connect", MagicMock(return_value=mock_conn))

        result = demo_mod.run_preflight(
            "http://ingest:8001", "http://norm:8002", "host=localhost"
        )

        assert result is None


# ===========================================================================
# CLASS 6 — TestMainFailurePaths: main() cleanup/exit integration
#
# Tests patch the module-level flow functions on demo_mod and verify that:
# - cleanup_events is called (or not with --keep) after verification failure
# - verification failure exits with code 1 and prints "Verification failed"
# - --skip-verify bypasses verify_results and calls render_results
# - render_results raising RuntimeError still triggers cleanup
# - poll_results raising SystemExit(1) (timeout) still triggers cleanup
# ===========================================================================


class TestMainFailurePaths:
    """main() try/finally ensures cleanup on every exit path after submission.

    WHY: The finally block is load-bearing — it prevents ghost events from
    accumulating in the DB across repeated demo runs. Every exit path after
    submit_scenes must be covered.
    """

    def _run_main(
        self,
        demo_mod: Any,
        monkeypatch: Any,
        *,
        keep: bool = False,
        skip_verify: bool = False,
        extra_argv: list[str] | None = None,
    ) -> None:
        """Invoke demo_mod.main() with controlled sys.argv and env."""
        argv = ["demo_normalization.py", "--db-dsn", "host=localhost dbname=naas"]
        if keep:
            argv.append("--keep")
        if skip_verify:
            argv.append("--skip-verify")
        if extra_argv:
            argv.extend(extra_argv)
        monkeypatch.setattr(sys, "argv", argv)

    def test_verification_failure_calls_cleanup_and_exits_1(
        self, demo_mod, monkeypatch, capsys
    ) -> None:
        """Verification problems → cleanup_events called once, exits with code 1.

        WHY: If cleanup is skipped on verification failure, repeated runs accumulate
        orphaned events. The exit code must be 1 (not 0) to signal failure to callers.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]
        problems = [{"scene": 6, "message": "(diana/oidc) display_name wrong winner"}]

        mock_cleanup = MagicMock()
        monkeypatch.setattr(demo_mod, "run_preflight", MagicMock())
        monkeypatch.setattr(
            demo_mod, "submit_scenes", MagicMock(return_value=submitted_ids)
        )
        monkeypatch.setattr(
            demo_mod,
            "poll_results",
            MagicMock(return_value=_wrap_results(_six_results())),
        )
        monkeypatch.setattr(
            demo_mod, "verify_results", MagicMock(return_value=problems)
        )
        monkeypatch.setattr(demo_mod, "render_results", MagicMock())
        monkeypatch.setattr(demo_mod, "cleanup_events", mock_cleanup)

        self._run_main(demo_mod, monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.main()

        assert exc_info.value.code == 1
        mock_cleanup.assert_called_once()
        captured = capsys.readouterr()
        assert "Verification failed" in captured.out, (
            f"Expected 'Verification failed' in output, got: {captured.out!r}"
        )

    def test_verification_failure_with_keep_skips_cleanup(
        self, demo_mod, monkeypatch, capsys
    ) -> None:
        """Verification failure with --keep does NOT call cleanup_events; prints 'Retained'.

        WHY: --keep is an explicit operator request to preserve events for debugging.
        Even on verification failure, the flag must be honoured.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]
        problems = [{"scene": 4, "message": "department missing"}]

        mock_cleanup = MagicMock()
        monkeypatch.setattr(demo_mod, "run_preflight", MagicMock())
        monkeypatch.setattr(
            demo_mod, "submit_scenes", MagicMock(return_value=submitted_ids)
        )
        monkeypatch.setattr(
            demo_mod,
            "poll_results",
            MagicMock(return_value=_wrap_results(_six_results())),
        )
        monkeypatch.setattr(
            demo_mod, "verify_results", MagicMock(return_value=problems)
        )
        monkeypatch.setattr(demo_mod, "render_results", MagicMock())
        monkeypatch.setattr(demo_mod, "cleanup_events", mock_cleanup)

        self._run_main(demo_mod, monkeypatch, keep=True)

        with pytest.raises(SystemExit):
            demo_mod.main()

        mock_cleanup.assert_not_called()
        captured = capsys.readouterr()
        assert "Retained" in captured.out, (
            f"Expected 'Retained' in output with --keep, got: {captured.out!r}"
        )

    def test_skip_verify_bypasses_verify_calls_render(
        self, demo_mod, monkeypatch
    ) -> None:
        """--skip-verify bypasses verify_results entirely and calls render_results.

        WHY: The --skip-verify flag is for running the render path without pipeline
        validation — useful during development. It must not call verify_results.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]

        mock_verify = MagicMock()
        mock_render = MagicMock()
        monkeypatch.setattr(demo_mod, "run_preflight", MagicMock())
        monkeypatch.setattr(
            demo_mod, "submit_scenes", MagicMock(return_value=submitted_ids)
        )
        monkeypatch.setattr(
            demo_mod,
            "poll_results",
            MagicMock(return_value=_wrap_results(_six_results())),
        )
        monkeypatch.setattr(demo_mod, "verify_results", mock_verify)
        monkeypatch.setattr(demo_mod, "render_results", mock_render)
        monkeypatch.setattr(demo_mod, "cleanup_events", MagicMock())

        self._run_main(demo_mod, monkeypatch, skip_verify=True)
        demo_mod.main()

        mock_verify.assert_not_called()
        mock_render.assert_called_once()

    def test_render_error_still_calls_cleanup(self, demo_mod, monkeypatch) -> None:
        """render_results raising RuntimeError still triggers cleanup_events.

        WHY: An exception in the render path must not prevent cleanup — the
        try/finally in main() must cover this case.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]

        mock_cleanup = MagicMock()
        monkeypatch.setattr(demo_mod, "run_preflight", MagicMock())
        monkeypatch.setattr(
            demo_mod, "submit_scenes", MagicMock(return_value=submitted_ids)
        )
        monkeypatch.setattr(
            demo_mod,
            "poll_results",
            MagicMock(return_value=_wrap_results(_six_results())),
        )
        monkeypatch.setattr(demo_mod, "verify_results", MagicMock(return_value=[]))
        monkeypatch.setattr(
            demo_mod,
            "render_results",
            MagicMock(side_effect=RuntimeError("render boom")),
        )
        monkeypatch.setattr(demo_mod, "cleanup_events", mock_cleanup)

        self._run_main(demo_mod, monkeypatch)

        with pytest.raises(RuntimeError, match="render boom"):
            demo_mod.main()

        mock_cleanup.assert_called_once()

    def test_poll_timeout_still_calls_cleanup(self, demo_mod, monkeypatch) -> None:
        """poll_results raising SystemExit(1) (simulating timeout) still triggers cleanup.

        WHY: A poll timeout calls sys.exit(1) internally. main()'s finally block
        must catch the SystemExit and still run cleanup before re-raising.
        """
        submitted_ids = ["id-0", "id-1", "id-2", "id-3", "id-4", "id-5"]

        mock_cleanup = MagicMock()
        monkeypatch.setattr(demo_mod, "run_preflight", MagicMock())
        monkeypatch.setattr(
            demo_mod, "submit_scenes", MagicMock(return_value=submitted_ids)
        )
        monkeypatch.setattr(
            demo_mod, "poll_results", MagicMock(side_effect=SystemExit(1))
        )
        monkeypatch.setattr(demo_mod, "cleanup_events", mock_cleanup)

        self._run_main(demo_mod, monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            demo_mod.main()

        assert exc_info.value.code == 1
        mock_cleanup.assert_called_once()


# ===========================================================================
# CLASS 7 — confidence_style: color threshold helper
# ===========================================================================


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
        assert hasattr(demo_mod, "confidence_style") and callable(
            demo_mod.confidence_style
        ), (
            "demo_normalization.py must define a module-level callable "
            "confidence_style(value: float) -> str so the render loop can be "
            "tested independently."
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
# CLASS 8 — cleanup_events: DB execute contract
#
# cleanup_events(event_ids: list[str], db_dsn: str, *, db_execute=None) -> None
#
# Injectable seam: cleanup_events accepts an optional db_execute
# callable so tests can verify the DELETE without a live DB.
# The --keep flag decision is tested at the main() level.
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

        demo_mod.cleanup_events(
            event_ids, "host=localhost dbname=naas", db_execute=mock_execute
        )

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
            isinstance(params_arg, dict) and params_arg.get("ids") == event_ids
        ) or (
            isinstance(params_arg, (list, tuple))
            and list(event_ids) == list(params_arg)
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

        demo_mod.cleanup_events(
            event_ids, "host=localhost dbname=naas", db_execute=mock_execute
        )

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
        actual_ids = (
            call_args[0][0] if call_args[0] else call_args[1].get("event_ids", [])
        )
        assert actual_ids == submitted_ids, (
            f"cleanup_events must receive the submitted IDs {submitted_ids!r}, "
            f"got {actual_ids!r}"
        )
