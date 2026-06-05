"""LDAP protocol adapter for the Identity Normalization Service.

Maps LDAP directory attributes to the unified attribute schema (spec §5.2).
Also satisfies the LdapEnricher port (§5.3); the enrich() method (live LDAP
query with connection pool and Redis cache) is implemented in a later chunk.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  cn               → display_name
  mail             → primary_email
  departmentNumber → department   (value-normalized via normalize_department)
  employeeType     → employee_type (value-normalized via normalize_employee_type)
  memberOf         → groups        (DN-reduced to cn RDN values; default [])

DN reduction: memberOf values are full DNs in production LDAP directories
(e.g., 'cn=engineering,ou=groups,dc=corp,dc=com'). The unified groups field
stores only the group name (the cn RDN value). Bare names pass through as-is.
"""

from __future__ import annotations

import re

from app.normalization_values import normalize_department, normalize_employee_type
from naas_shared.logging import get_logger

_logger = get_logger(__name__)

# Matches the cn= RDN at the start or after a comma in an LDAP DN.
# Captures the attribute value verbatim (case-preserving, per spec §5.2 note).
_CN_RDN_RE = re.compile(r"(?:^|,)\s*cn=([^,]+)", re.IGNORECASE)


def _reduce_dn_to_group_name(dn: str) -> str | None:
    """Extract the cn RDN value from an LDAP DN string.

    WHY: The unified groups field stores group names (plain strings), not full
    DNs. If full DNs were stored, cross-protocol comparison with OIDC groups
    would always fail and group-based policy conditions would be broken for
    all LDAP users.

    For a bare name (no ',' separator, no '=' assignment), the input is
    returned as-is — some LDAP implementations store group names directly.

    For a malformed DN that contains '=' but no 'cn=' component, returns None
    so the caller can skip the entry safely.

    Args:
        dn: A memberOf value, either a full LDAP DN or a bare group name.

    Returns:
        The extracted group name string, or None if the DN is malformed and
        has no cn= component.
    """
    # If the string contains no ',' and no '=', treat it as a bare name.
    if "=" not in dn:
        return dn.strip() if dn.strip() else None

    match = _CN_RDN_RE.search(dn)
    if match:
        return match.group(1).strip()

    # DN has '=' but no cn= — malformed; return None to skip safely.
    _logger.warning(
        "ldap_dn_reduction_no_cn_rdn",
        dn=dn,
    )
    return None


class LdapAdapter:
    """Extracts and normalizes LDAP directory attributes to the unified schema.

    Satisfies both ProtocolAdapter (§5.2) via extract() and LdapEnricher (§5.3)
    via extract() + enrich(). The enrich() method — which performs a live LDAP
    query with async connection pool and Redis cache — is added in a later chunk.
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map LDAP attribute names to unified field names with value normalization.

        Absent scalar keys produce None in the result. The 'groups' field always
        returns a list ([] when absent or when memberOf is empty) so the resolution
        engine can iterate it without a None guard.

        The bootstrap.ldif seeded users carry no memberOf attributes, so real
        queries to the test directory will produce groups=[]; the DN-reduction
        logic is exercised only against production directories or synthetic test data.

        Args:
            raw_attributes: Raw LDAP attribute dict (cn, mail, departmentNumber,
                employeeType, memberOf, uid, sn, ...).

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        raw_dept = raw_attributes.get("departmentNumber")
        if raw_dept is not None:
            dept_value, _ = normalize_department(raw_dept)
        else:
            dept_value = None

        raw_et = raw_attributes.get("employeeType")
        if raw_et is not None:
            et_value = normalize_employee_type(raw_et)
        else:
            et_value = None

        member_of: list[str] = raw_attributes.get("memberOf") or []
        groups: list[str] = []
        for dn in member_of:
            name = _reduce_dn_to_group_name(dn)
            if name is not None:
                groups.append(name)

        return {
            "display_name": raw_attributes.get("cn"),
            "primary_email": raw_attributes.get("mail"),
            "department": dept_value,
            "employee_type": et_value,
            "groups": groups,
        }

    async def enrich(
        self,
        correlation_field: str,
        lookup_value: str,
    ) -> dict | None:
        """Perform an active LDAP directory query and return normalized attributes.

        WHY: Spec §5.3 — used by NormalizationService to merge directory attributes
        with OIDC/SAML token claims. This method is implemented in a later chunk
        (connection pool, asyncio.to_thread wrapping, Redis cache). The signature
        is declared here so the composition root can wire LdapAdapter as the
        LdapEnricher port without AttributeError at startup.

        Args:
            correlation_field: Unified schema field used as the LDAP search key
                (e.g., 'primary_email'). Reverse-mapped to LDAP attribute via
                UNIFIED_TO_LDAP.
            lookup_value: The value to search for (e.g., 'alice@corp.com').

        Returns:
            Normalized attribute dict on success; None if no LDAP match found.
        """
        raise NotImplementedError(
            "LdapAdapter.enrich() is implemented in a later chunk (§5.3)."
        )
