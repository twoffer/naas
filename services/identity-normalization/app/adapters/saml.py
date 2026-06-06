"""SAML protocol adapter for the Identity Normalization Service.

Maps SAML assertion attributes to the unified attribute schema (spec §5.2).
SAML is used by legacy IdPs and enterprise SSO federations. The attribute names
differ from OIDC (displayName vs name, dept vs department, employeeType vs
employee_type) — wrong mappings silently break cross-protocol resolution.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  displayName  → display_name
  email        → primary_email
  dept         → department   (value-normalized via normalize_department)
  employeeType → employee_type (value-normalized via normalize_employee_type)
  groups       → groups        (list; default [])
"""

from __future__ import annotations

from app.normalization_values import normalize_department, normalize_employee_type
from naas_shared.logging import get_logger

_logger = get_logger(__name__)


class SamlAdapter:
    """Extracts and normalizes SAML assertion attributes to the unified schema.

    Satisfies the ProtocolAdapter port (§5.2). Stateless — a single instance
    may be reused across events without coordination.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map SAML attribute names to unified field names with value normalization.

        Absent scalar keys produce None in the result. The 'groups' field always
        returns a list ([] when absent) so the resolution engine can iterate it
        without a None guard.

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
        raw_dept = raw_attributes.get("dept")
        if raw_dept is not None:
            dept_value, _ = normalize_department(raw_dept)
        else:
            dept_value = None

        raw_et = raw_attributes.get("employeeType")
        if raw_et is not None:
            et_value = normalize_employee_type(raw_et)
        else:
            et_value = None

        return {
            "display_name": raw_attributes.get("displayName"),
            "primary_email": raw_attributes.get("email"),
            "department": dept_value,
            "employee_type": et_value,
            "groups": list(raw_attributes.get("groups") or []),
        }
