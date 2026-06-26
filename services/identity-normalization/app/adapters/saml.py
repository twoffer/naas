"""SAML protocol adapter for the Identity Normalization Service.

Maps SAML assertion attributes to the unified attribute schema (spec §5.2).
SAML is used by legacy IdPs and enterprise SSO federations. The attribute names
differ from OIDC (displayName vs name, dept vs department, employeeType vs
employee_type) — wrong mappings silently break cross-protocol resolution.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  displayName  → display_name
  email        → primary_email
  dept         → department   (value-normalized via normalize_department_value)
  employeeType → employee_type (value-normalized via normalize_employee_type)
  groups       → groups        (list; default [])
"""

from __future__ import annotations

from app.adapters._mapping import (
    FieldRule,
    apply_field_rules,
    coerce_str,
    coerce_str_list,
)
from app.normalization_values import normalize_department_value, normalize_employee_type

SAML_FIELD_RULES: dict[str, FieldRule] = {
    "display_name": FieldRule(("displayName",), coerce_str),
    "primary_email": FieldRule(("email",), coerce_str),
    "department": FieldRule(("dept",), normalize_department_value),
    "employee_type": FieldRule(("employeeType",), normalize_employee_type),
    "groups": FieldRule(("groups",), coerce_str_list),
}


class SamlAdapter:
    """Extracts and normalizes SAML assertion attributes to the unified schema.

    Satisfies the ProtocolAdapter port (§5.2). Stateless — a single instance
    may be reused across events without coordination.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map SAML attribute names to unified field names with value normalization.

        Absent scalar keys produce None in the result. The 'groups' field always
        returns a list ([] when absent or when a non-list value is supplied) so
        the resolution engine can iterate it without a None guard.

        Note: SAML uses 'displayName' (not 'name'), 'dept' (not 'department'),
        and 'employeeType' (not 'employee_type'). Mapping from OIDC key names
        would silently break SAML event normalization.

        Args:
            raw_attributes: Raw SAML assertion attributes dict from the login
                event record.

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        return apply_field_rules(raw_attributes, SAML_FIELD_RULES)
