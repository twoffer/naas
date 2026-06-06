"""OIDC protocol adapter for the Identity Normalization Service.

Maps OIDC token claims to the unified attribute schema (spec §5.2).
OIDC is the default protocol for modern SSO flows; correct mapping here
is critical because errors silently propagate to every OIDC login's
risk score and dashboard display.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  name          → display_name
  email         → primary_email
  department    → department   (value-normalized via normalize_department)
  employee_type → employee_type (value-normalized via normalize_employee_type)
  groups        → groups        (list; default [])
"""

from __future__ import annotations

from app.normalization_values import normalize_department, normalize_employee_type
from naas_shared.logging import get_logger

_logger = get_logger(__name__)


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
        returns a list ([] when absent) so the resolution engine can iterate it
        without a None guard.

        Args:
            raw_attributes: Raw OIDC claims dict from the login event record.

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        raw_dept = raw_attributes.get("department")
        if raw_dept is not None:
            dept_value, _ = normalize_department(raw_dept)
        else:
            dept_value = None

        raw_et = raw_attributes.get("employee_type")
        if raw_et is not None:
            et_value = normalize_employee_type(raw_et)
        else:
            et_value = None

        return {
            "display_name": (
                v if isinstance(v := raw_attributes.get("name"), str) else None
            ),
            "primary_email": (
                v if isinstance(v := raw_attributes.get("email"), str) else None
            ),
            "department": dept_value,
            "employee_type": et_value,
            "groups": [
                g for g in (raw_attributes.get("groups") or []) if isinstance(g, str)
            ],
        }
