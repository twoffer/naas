"""Shared mapping engine for Identity Normalization protocol adapters.

This module is the single point that converts per-adapter declarative rule tables
into unified-attribute dicts.  It owns all coercion helpers so that attribute-type
guards live in exactly one place rather than being duplicated across oidc.py,
saml.py, and ldap.py.

The engine (apply_field_rules) is also the seam for a future configurable
expression-language that derives a normalized value from one or more raw attributes
(e.g. LDAP primary_email = "[sAMAccountName]@[domain]").  That capability is NOT
built here; the design keeps the door open without re-architecting the adapters, the
ProtocolAdapter port, or any caller.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

# Transform receives the values for its rule's declared source_keys positionally
# and returns the normalized value.  Variadic ON PURPOSE — do NOT narrow to one arg:
# the multi-key form is the seam for a future expression-language that derives a value
# from several raw attributes (e.g. LDAP primary_email = "[sAMAccountName]@[domain]").
Transform = Callable[..., object]


class FieldRule(NamedTuple):
    """Declarative descriptor binding raw-attribute source keys to a transform.

    WHY NamedTuple: rule tables are defined at module level in each adapter.
    Named-attribute access (.source_keys, .transform) makes each rule self-documenting
    and lets future audit or introspection tools inspect the table without fragile
    positional indexing.

    Attributes:
        source_keys: Ordered tuple of raw-attribute keys whose values are fetched
            and passed positionally to the transform.  Always a tuple even for
            single-source rules — the tuple form is the multi-key future seam.
        transform:   A pure, total callable that accepts len(source_keys) positional
            arguments (any may be None when the key is absent) and returns the
            normalized value.
    """

    source_keys: tuple[str, ...]
    transform: Transform


def coerce_str(value: object) -> str | None:
    """Return value unchanged when it is a str; return None for every other type.

    WHY: Protocol adapters use this in single-source FieldRules for scalar string
    fields (display_name, primary_email).  Without the isinstance guard, a non-str
    IdP claim value (int, list, dict) would propagate to NormalizedAttributes and
    cause a downstream Pydantic ValidationError in the risk evaluator.  None is the
    safe-discard sentinel that the resolution layer handles gracefully.
    """
    return value if isinstance(value, str) else None


def coerce_str_list(value: object) -> list[str]:
    """Return a filtered list of str elements when value is a list; return [] otherwise.

    CRITICAL SECURITY INVARIANT: a bare string (e.g. 'admin') must return [],
    NOT ['a', 'd', 'm', 'i', 'n'].  Python strings are iterable, so a naive
    [v for v in value if isinstance(v, str)] applied to a non-list would iterate
    the string character-by-character — each single character is a str and would
    pass the filter.  The spec is deliberately stricter: only list values are iterated.

    WHY this matters for policy evaluation: if a misconfigured IdP sends
    groups='admin' (bare string), character iteration would produce single-char
    entries that never match 'admin', silently causing admin-only policy conditions
    to fail to fire.  Returning [] is the safer, more predictable failure mode.

    Strict list-only: a non-list value yields [] (it is NOT iterated char-by-char).
    """
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def apply_field_rules(raw_attributes: dict, rules: dict[str, FieldRule]) -> dict:
    """Build the unified-attribute dict by applying each rule's transform.

    The engine is the single point that invokes transforms, so it is the seam where
    a future ExpressionRule variety could be dispatched without touching extract(),
    the ProtocolAdapter port, or any caller.  Invariant: transforms must be pure and
    total over their declared arity; the engine guarantees the positional argument
    count equals len(rule.source_keys).

    For a single-key rule, transform(*[value]) == transform(value), so all existing
    one-arg transforms work unchanged.  A multi-key rule simply declares more keys
    and a transform that accepts them positionally.

    Args:
        raw_attributes: Raw claims/attributes dict from the login event record.
        rules:          Ordered dict of unified-field-name → FieldRule.  Output key
            order matches declaration order (Python 3.7+ dict insertion order).

    Returns:
        Dict with exactly one key per rule, each holding the transform's return value.
    """
    return {
        field: rule.transform(*[raw_attributes.get(k) for k in rule.source_keys])
        for field, rule in rules.items()
    }
