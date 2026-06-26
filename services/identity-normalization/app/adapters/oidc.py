"""OIDC protocol adapter for the Identity Normalization Service.

Maps OIDC token claims to the unified attribute schema (spec §5.2).
OIDC is the default protocol for modern SSO flows; correct mapping here
is critical because errors silently propagate to every OIDC login's
risk score and dashboard display.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  name          → display_name
  email         → primary_email
  department    → department   (value-normalized via normalize_department_value)
  employee_type → employee_type (value-normalized via normalize_employee_type)
  groups        → groups        (list; default [])
"""

from __future__ import annotations

from app.adapters._mapping import (
    FieldRule,
    apply_field_rules,
    coerce_str,
    coerce_str_list,
)
from app.normalization_values import normalize_department_value, normalize_employee_type

OIDC_FIELD_RULES: dict[str, FieldRule] = {
    "display_name": FieldRule(("name",), coerce_str),
    "primary_email": FieldRule(("email",), coerce_str),
    "department": FieldRule(("department",), normalize_department_value),
    "employee_type": FieldRule(("employee_type",), normalize_employee_type),
    "groups": FieldRule(("groups",), coerce_str_list),
}


class OidcAdapter:
    """Extracts and normalizes OIDC token claims to the unified attribute schema.

    Satisfies the ProtocolAdapter port (§5.2). Stateless — a single instance
    may be reused across events without coordination.

    The was_mapped flag from normalize_department is not embedded in the extract
    return dict; the resolution layer (chunk 6) calls normalize_department directly
    when it needs the confidence-penalty flag.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map OIDC claim names to unified field names with value normalization.

        Absent scalar keys produce None in the result. The 'groups' field always
        returns a list ([] when absent or when a non-list value is supplied) so
        the resolution engine can iterate it without a None guard.

        Args:
            raw_attributes: Raw OIDC claims dict from the login event record.

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        return apply_field_rules(raw_attributes, OIDC_FIELD_RULES)
