"""Conflict resolution and confidence scoring for the Identity Normalization Service.

Spec §5.5: given per-attribute source contributions, selects the authoritative
value for each unified attribute, computes per-attribute resolution confidence,
and produces an overall normalization_confidence score.

This module is intentionally PURE — no I/O, no DB/Redis/LDAP, no logging.
All functions are deterministic and safe to call from any thread.
"""

from __future__ import annotations

from typing import Any

from naas_shared.models import (
    EnrichmentMetadata,
    ListMergeResolution,
    NormalizedAttributes,
    PriorityResolution,
    ResolutionDetail,
    SingleSourceResolution,
    UnanimousResolution,
)

from app.normalization_config import NormalizationConfig

# §5.5.2 — Importance weights for normalization_confidence. TRANSCRIBE EXACTLY.
ATTRIBUTE_IMPORTANCE: dict[str, float] = {
    "display_name": 0.15,
    "primary_email": 0.25,
    "department": 0.20,
    "employee_type": 0.25,
    "groups": 0.15,
}

# Attributes that carry a (normalized_str, was_mapped) tuple instead of a plain str.
_DEPT_TUPLE_ATTRS: frozenset[str] = frozenset({"department"})


def resolve(
    attribute_sources: dict[str, dict[str, Any]],
    config: NormalizationConfig,
    source_protocol: str,
    enrichment: EnrichmentMetadata,
) -> NormalizedAttributes:
    """Resolve all unified attributes and compute overall normalization confidence.

    §5.5: for each attribute, selects the winning value from contributing sources
    using unanimous, priority, single-source, or list-merge logic. Applies the
    −0.2 normalization-failure penalty to department resolutions whose winning
    value is unmapped. Computes an importance-weighted normalization_confidence.

    Args:
        attribute_sources: Mapping of unified attribute name → {protocol: value}.
            Only non-null, non-empty values appear. department values are
            (normalized_str, was_mapped) tuples; all others are plain str or list[str].
        config: Loaded NormalizationConfig (accessor methods used for weights/priority).
        source_protocol: The primary event's protocol ("oidc"|"saml"|"ldap"). Set
            as-is on the output regardless of which sources contributed.
        enrichment: EnrichmentApplied or EnrichmentSkipped computed by the service
            layer. Passed through unchanged — resolution does not compute it.

    Returns:
        NormalizedAttributes with all unified fields, resolution_details, and
        normalization_confidence populated.
    """
    resolution_details: dict[str, Any] = {}
    per_attr_conf: dict[str, float] = {}

    # Resolved scalar values
    resolved_display_name: str | None = None
    resolved_primary_email: str | None = None
    resolved_department: str | None = None
    resolved_employee_type: Any = None
    resolved_groups: list[str] = []

    # --- Scalar attributes ---
    for attr in ("display_name", "primary_email", "department", "employee_type"):
        sources_map: dict[str, Any] = attribute_sources.get(attr, {})
        if not sources_map:
            # Zero sources: no entry in resolution_details, 0.0 contribution.
            continue

        if attr in _DEPT_TUPLE_ATTRS:
            detail, conf, resolved_val = _resolve_department(attr, sources_map, config)
        else:
            detail, conf, resolved_val = _resolve_scalar(attr, sources_map, config)

        resolution_details[attr] = detail
        per_attr_conf[attr] = conf

        if attr == "display_name":
            resolved_display_name = resolved_val
        elif attr == "primary_email":
            resolved_primary_email = resolved_val
        elif attr == "department":
            resolved_department = resolved_val
        elif attr == "employee_type":
            resolved_employee_type = resolved_val

    # --- List attribute: groups ---
    groups_map: dict[str, Any] = attribute_sources.get("groups", {})
    if groups_map:
        groups_detail, groups_conf = _resolve_groups(groups_map, config)
        resolution_details["groups"] = groups_detail
        per_attr_conf["groups"] = groups_conf
        resolved_groups = groups_detail.resolved_value

    # --- Overall normalization_confidence (§5.5.2) ---
    confidence = sum(
        ATTRIBUTE_IMPORTANCE[a] * per_attr_conf.get(a, 0.0)
        for a in ATTRIBUTE_IMPORTANCE
    )
    normalization_confidence = max(0.0, min(1.0, confidence))

    return NormalizedAttributes(
        display_name=resolved_display_name,
        primary_email=resolved_primary_email,
        department=resolved_department,
        employee_type=resolved_employee_type,
        groups=resolved_groups,
        source_protocol=source_protocol,
        normalization_confidence=normalization_confidence,
        resolution_details=resolution_details,
        enrichment=enrichment,
    )


def _resolve_scalar(
    attr: str,
    sources_map: dict[str, str],
    config: NormalizationConfig,
) -> tuple[Any, float, str | None]:
    """Resolve a plain-string scalar attribute (display_name, primary_email, employee_type).

    Returns:
        (resolution_detail, confidence, resolved_value)

    No normalization-failure penalty applies to these attributes.
    """
    n = len(sources_map)

    detail: ResolutionDetail
    if n == 1:
        src, val = next(iter(sources_map.items()))
        weight = config.weight_for(attr, src)
        detail = SingleSourceResolution(
            resolution="single_source",
            resolved_value=val,
            confidence=weight,
            sources=[src],
        )
        return detail, weight, val

    # ≥2 sources
    values = list(sources_map.values())
    if len(set(values)) == 1:
        # Unanimous — all agree
        agreed = values[0]
        conf = max(config.weight_for(attr, s) for s in sources_map)
        detail = UnanimousResolution(
            resolution="unanimous",
            resolved_value=agreed,
            confidence=conf,
            sources=sorted(sources_map.keys()),
        )
        return detail, conf, agreed

    # Disagreement → PriorityResolution
    winner_src, winner_val, winner_weight = _pick_winner(attr, sources_map, config)
    conf = winner_weight * 0.8
    conflicting = {s: v for s, v in sources_map.items() if s != winner_src}
    detail = PriorityResolution(
        resolution="priority",
        resolved_value=winner_val,
        confidence=conf,
        winner_source=winner_src,
        conflicting_values=conflicting,
        penalty_applied=True,
    )
    return detail, conf, winner_val


def _resolve_department(
    attr: str,
    sources_map: dict[str, tuple[str, bool]],
    config: NormalizationConfig,
) -> tuple[Any, float, str | None]:
    """Resolve the department attribute which carries (normalized_str, was_mapped) tuples.

    §5.5: applies the −0.2 normalization-failure penalty when the winning (resolved)
    value has was_mapped=False.

    Returns:
        (resolution_detail, confidence, resolved_value)
    """
    n = len(sources_map)

    detail: ResolutionDetail
    if n == 1:
        src, (val, was_mapped) = next(iter(sources_map.items()))
        weight = config.weight_for(attr, src)
        conf = _apply_unmapped_penalty(weight, was_mapped)
        detail = SingleSourceResolution(
            resolution="single_source",
            resolved_value=val,
            confidence=conf,
            sources=[src],
        )
        return detail, conf, val

    # ≥2 sources: compare by normalized string value only
    str_sources: dict[str, str] = {s: v for s, (v, _) in sources_map.items()}
    values = list(str_sources.values())

    if len(set(values)) == 1:
        # Unanimous on the string value
        agreed = values[0]
        # Penalty: the resolved value is unmapped when ANY source reports was_mapped=False.
        # All sources agree on the string; if even one marked it unmapped the canonical
        # mapping failed — the agreed value is an unmapped retention.
        all_mapped = all(wm for _, wm in sources_map.values())
        raw_conf = max(config.weight_for(attr, s) for s in sources_map)
        conf = _apply_unmapped_penalty(raw_conf, all_mapped)
        detail = UnanimousResolution(
            resolution="unanimous",
            resolved_value=agreed,
            confidence=conf,
            sources=sorted(sources_map.keys()),
        )
        return detail, conf, agreed

    # Disagreement → priority
    winner_src, winner_val, winner_weight = _pick_winner(attr, str_sources, config)
    winner_was_mapped = sources_map[winner_src][1]
    raw_conf = winner_weight * 0.8
    conf = _apply_unmapped_penalty(raw_conf, winner_was_mapped)
    conflicting = {s: v for s, v in str_sources.items() if s != winner_src}
    detail = PriorityResolution(
        resolution="priority",
        resolved_value=winner_val,
        confidence=conf,
        winner_source=winner_src,
        conflicting_values=conflicting,
        penalty_applied=True,
    )
    return detail, conf, winner_val


def _apply_unmapped_penalty(confidence: float, was_mapped: bool) -> float:
    """Apply the −0.2 normalization-failure penalty when was_mapped is False.

    §5.5: penalty is applied only when the winning value is unmapped, then
    clamped to [0.0, 1.0].
    """
    if not was_mapped:
        confidence = confidence - 0.2
    return max(0.0, min(1.0, confidence))


def _pick_winner(
    attr: str,
    sources_map: dict[str, str],
    config: NormalizationConfig,
) -> tuple[str, str, float]:
    """Select the winning source for a disagreeing set of sources.

    §5.5: winner = highest-priority source in config.priority_for(attr) that
    HAS a value. If no configured-priority source has a value (or no priority
    is configured), the highest-weight present source wins.

    Returns:
        (winner_source, winner_value, winner_weight)
    """
    priority_list = config.priority_for(attr)

    # Walk priority list; first match that has a value wins
    for proto in priority_list:
        if proto in sources_map:
            return proto, sources_map[proto], config.weight_for(attr, proto)

    # Fallback: highest-weight present source
    best_src = max(sources_map, key=lambda s: config.weight_for(attr, s))
    return best_src, sources_map[best_src], config.weight_for(attr, best_src)


def _resolve_groups(
    groups_map: dict[str, list[str]],
    config: NormalizationConfig,
) -> tuple[ListMergeResolution, float]:
    """Resolve the groups list attribute via the configured merge strategy.

    §5.5: single source → weight_for('groups', src); multiple sources →
    0.7 + 0.3 × (fraction of merged groups present in more than one source).

    Returns:
        (ListMergeResolution, confidence)
    """
    strategy = config.merge_strategy_for("groups")
    priority = config.priority_for("groups")
    n_sources = len(groups_map)

    if n_sources == 1:
        src, grps = next(iter(groups_map.items()))
        merged = sorted(set(grps))
        conf = config.weight_for("groups", src)
        detail = ListMergeResolution(
            resolution="list_merge",
            resolved_value=merged,
            confidence=conf,
            strategy=strategy,
            total_unique_groups=len(merged),
            sources=[src],
        )
        return detail, conf

    # Multiple sources
    merged = _apply_merge_strategy(strategy, groups_map, priority)

    # Confidence: fraction of merged groups present in >1 source
    if merged:
        shared_count = sum(
            1
            for g in merged
            if sum(1 for grp_list in groups_map.values() if g in grp_list) > 1
        )
        fraction = shared_count / len(merged)
    else:
        fraction = 0.0

    conf = 0.7 + 0.3 * fraction

    detail = ListMergeResolution(
        resolution="list_merge",
        resolved_value=merged,
        confidence=conf,
        strategy=strategy,
        total_unique_groups=len(merged),
        sources=sorted(groups_map.keys()),
    )
    return detail, conf


def _apply_merge_strategy(
    strategy: str,
    groups_map: dict[str, list[str]],
    priority: list[str] | None = None,
) -> list[str]:
    """Apply the configured merge strategy to produce a sorted, de-duplicated list.

    §5.5: union (default), intersection, priority are supported.

    For "priority": walks the configured priority list (passed by _resolve_groups)
    and returns the first source that is present with a non-empty list.  Sources not
    in the priority list (or when no priority is configured) fall back to sorted-key
    order for deterministic behaviour.
    """
    if strategy == "intersection":
        sets = [set(grp_list) for grp_list in groups_map.values()]
        result = sets[0].intersection(*sets[1:]) if sets else set()
        return sorted(result)

    if strategy == "priority":
        # Walk configured priority; return first source with a non-empty list.
        for src in priority or []:
            if groups_map.get(src):
                return sorted(set(groups_map[src]))
        # Fallback: sorted-key order (deterministic when no priority configured or
        # all priority sources are absent/empty).
        for src in sorted(groups_map.keys()):
            if groups_map[src]:
                return sorted(set(groups_map[src]))
        return []

    # "union" is the default (and the final catch-all for any unknown strategy,
    # which is unreachable in practice given the Literal type constraint).
    all_groups: set[str] = set()
    for grp_list in groups_map.values():
        all_groups.update(grp_list)
    return sorted(all_groups)
