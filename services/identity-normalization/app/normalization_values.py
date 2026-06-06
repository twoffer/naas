"""Canonical value maps and normalization helpers for the Identity Normalization Service.

This module is the single source of truth for all protocol-agnostic value mappings.
All three protocol adapters (OIDC, SAML, LDAP) import from here so that cross-protocol
normalization produces byte-identical canonical strings — a prerequisite for the
unanimous-resolution path in §5.5.

Spec §5.2 [TRANSCRIBE EXACTLY]:
  DEPARTMENT_CANONICAL, EMPLOYEE_TYPE_CANONICAL, UNIFIED_TO_LDAP
"""

from __future__ import annotations

from naas_shared.logging import get_logger

# ---------------------------------------------------------------------------
# Canonical value maps (spec §5.2 [TRANSCRIBE EXACTLY])
# ---------------------------------------------------------------------------

DEPARTMENT_CANONICAL: dict[str, str] = {
    "eng": "Engineering",
    "engineering": "Engineering",
    "software engineering": "Engineering",
    "r&d": "Engineering",
    "product development": "Engineering",
    "fin": "Finance",
    "finance": "Finance",
    "accounting": "Finance",
    "hr": "Human Resources",
    "human resources": "Human Resources",
    "people ops": "Human Resources",
    "it": "Information Technology",
    "information technology": "Information Technology",
    "infra": "Information Technology",
    "sales": "Sales",
    "revenue": "Sales",
    "mktg": "Marketing",
    "marketing": "Marketing",
}

EMPLOYEE_TYPE_CANONICAL: dict[str, str] = {
    "fte": "FTE",
    "e": "FTE",
    "employee": "FTE",
    "full-time": "FTE",
    "full time": "FTE",
    "regular": "FTE",
    "contractor": "contractor",
    "c": "contractor",
    "contract": "contractor",
    "contingent": "contractor",
    "temp": "contractor",
    "vendor": "vendor",
    "v": "vendor",
    "external": "vendor",
    "partner": "vendor",
    "third-party": "vendor",
}

# ---------------------------------------------------------------------------
# Unified-to-LDAP attribute reverse map (spec §5.2 mapping table).
# Used by the LDAP enrichment adapter (§5.3) to build search filters.
# ---------------------------------------------------------------------------

UNIFIED_TO_LDAP: dict[str, str] = {
    "display_name": "cn",
    "primary_email": "mail",
    "department": "departmentNumber",
    "employee_type": "employeeType",
    "groups": "memberOf",
}

# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------

_logger = get_logger(__name__)


def normalize_department(value: object) -> tuple[str | None, bool]:
    """Map a raw department string to its canonical form.

    WHY: Enables cross-protocol unanimous resolution (§5.5). OIDC 'eng', SAML 'eng',
    and LDAP 'r&d' must all produce the identical string 'Engineering' so the
    resolution engine treats them as agreeing rather than conflicting.

    Non-string inputs (e.g., integer or list from a mis-configured IdP claim) are
    returned as (None, False) immediately — callers treat None department as absent,
    so the bad value is dropped safely without crashing the normalization pipeline.

    Returns:
        (canonical_string, was_mapped) where was_mapped=True indicates a recognized
        alias was found. was_mapped=False means the value was not in the table; the
        caller (resolution layer, §5.5) applies a 0.2 confidence penalty in that case.
        On a miss the value is title-cased and retained — it is NEVER discarded.
        Returns (None, False) for any non-str input.
    """
    if not isinstance(value, str):
        return None, False

    key = value.strip().lower()
    canonical = DEPARTMENT_CANONICAL.get(key)
    if canonical is not None:
        return canonical, True

    _logger.warning(
        "unmapped_attribute_value",
        attribute="department",
        raw_value=value,
    )
    return value.strip().title(), False


def normalize_employee_type(value: object) -> str | None:
    """Map a raw employee_type string to its canonical Literal form.

    WHY: NormalizedAttributes.employee_type is typed as
    Literal['FTE', 'contractor', 'vendor'] | None. Any non-Literal value
    causes Pydantic ValidationError at model construction. Returning None
    signals to the adapter that this field should be omitted/set to None.

    Non-string inputs (e.g., a list or integer from a mis-configured IdP claim)
    return None immediately — the field is treated as absent, not as an error.

    Returns:
        One of 'FTE', 'contractor', 'vendor' on a hit; None on a miss or non-str input.
        A miss is discarded — the raw string is NEVER returned.
    """
    if not isinstance(value, str):
        return None

    key = value.strip().lower()
    canonical = EMPLOYEE_TYPE_CANONICAL.get(key)
    if canonical is not None:
        return canonical

    _logger.warning(
        "unmapped_attribute_value",
        attribute="employee_type",
        raw_value=value,
    )
    return None
