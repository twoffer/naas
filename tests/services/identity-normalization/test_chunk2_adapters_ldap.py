# Component: NAAS Spec 2 — Chunk 2: adapters/ldap.py (LdapAdapter.extract only)
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/app/adapters/ldap.py
#
# Scope: THIS FILE TESTS extract() ONLY.
# The LdapAdapter.enrich() method (live LDAP query) is implemented in a later chunk.
# Do NOT write enrich() tests here.
#
# What these tests validate:
#   - LdapAdapter is importable from app.adapters.ldap
#   - LdapAdapter satisfies ProtocolAdapter (has extract method)
#   - Field mapping: cn→display_name, mail→primary_email,
#                    departmentNumber→department, employeeType→employee_type,
#                    memberOf→groups (DN-reduced to cn RDN)
#   - Value normalization applied (same canonical targets as OIDC/SAML)
#   - memberOf DN-reduction: 'cn=engineering,ou=groups,dc=corp,dc=com'
#     → groups includes 'engineering' (the cn RDN value)
#   - memberOf with multiple DNs → list of cn RDN values (order may vary;
#     assertions use set membership)
#   - Bare name passthrough: 'engineering' (no commas) → 'engineering' kept as-is
#   - Malformed DN: no cn= prefix → implementation-defined safe fallback
#   - Missing keys handled gracefully; groups defaults to []
#   - Unmapped employee_type → None; unmapped department → retained, title-cased
#   - Canonical targets byte-identical to OIDC/SAML outputs
#
# NOTE on bootstrap.ldif memberOf format:
#   infrastructure/openldap/bootstrap.ldif does NOT include memberOf attributes
#   on any user entry. The seeded test users (alice, bob, charlie, diana, eve)
#   have no group memberships defined via memberOf in the LDIF. The ou=groups
#   organizationalUnit is defined but contains no group objects with 'member'
#   attributes. Therefore, real LDAP queries to the test directory will return
#   memberOf=[] for all users. The DN-reduction tests below use synthetic
#   raw_attributes dicts (not live LDAP) to validate the parsing logic, which
#   the adapter must implement for production deployments where memberOf is
#   populated. The expected DN format (per LDAP convention and spec §5.2 note)
#   is: cn=<groupname>,ou=groups,dc=corp,dc=com
#
# TDD state:
#   app/adapters/ldap.py does NOT exist yet.
#   All tests MUST fail with ModuleNotFoundError until implemented.

# stdlib
import sys
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------

def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


# ===========================================================================
# CLASS 1 — Import
# ===========================================================================


class TestLdapAdapterImport:
    """LdapAdapter must be importable from app.adapters.ldap."""

    def test_ldap_adapter_is_importable(self) -> None:
        """from app.adapters.ldap import LdapAdapter must not raise."""
        from app.adapters.ldap import LdapAdapter  # noqa: F401

    def test_ldap_module_exists(self) -> None:
        """app.adapters.ldap module must exist and define LdapAdapter."""
        from app.adapters import ldap as ldap_mod

        assert hasattr(ldap_mod, "LdapAdapter"), (
            "app.adapters.ldap must define LdapAdapter."
        )


# ===========================================================================
# CLASS 2 — Protocol conformance
# ===========================================================================


class TestLdapAdapterProtocolConformance:
    """LdapAdapter must satisfy both ProtocolAdapter and LdapEnricher ports.

    WHY: The LDAP adapter is special — it satisfies two ports (§5.2, §5.3).
    extract() satisfies ProtocolAdapter; extract() + enrich() together satisfy
    LdapEnricher. Both ports must be present for correct wiring.
    """

    def test_ldap_adapter_has_extract_method(self) -> None:
        """LdapAdapter must define an extract method (ProtocolAdapter port)."""
        from app.adapters.ldap import LdapAdapter

        assert hasattr(LdapAdapter, "extract"), (
            "LdapAdapter must define 'extract'. Spec §5.2."
        )

    def test_ldap_adapter_has_enrich_method(self) -> None:
        """LdapAdapter must define an enrich method (LdapEnricher port).

        WHY: Even though enrich() is tested in a later chunk, the method must
        at minimum be defined (not necessarily implemented) so that the
        composition root can wire LdapAdapter as the LdapEnricher without
        AttributeError at startup.
        """
        from app.adapters.ldap import LdapAdapter

        assert hasattr(LdapAdapter, "enrich"), (
            "LdapAdapter must define 'enrich'. Spec §5.3: the LdapEnricher port "
            "requires both extract() and enrich()."
        )

    def test_ldap_adapter_extract_accepts_dict(self) -> None:
        """LdapAdapter().extract({}) must not raise TypeError."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({})

        assert isinstance(result, dict), (
            f"LdapAdapter().extract({{}}) must return a dict, got {type(result).__name__!r}."
        )


# ===========================================================================
# CLASS 3 — Field mapping contract (spec §5.2 mapping table)
# ===========================================================================


class TestLdapAdapterFieldMapping:
    """LdapAdapter.extract must map LDAP attribute names to unified field names.

    Mapping table (spec §5.2, [TRANSCRIBE EXACTLY]):
      cn               → display_name
      mail             → primary_email
      departmentNumber → department   (value-normalized)
      employeeType     → employee_type (value-normalized)
      memberOf         → groups        (DN-reduced to cn RDN values)

    WHY: LDAP uses distinct attribute names from OIDC/SAML. A wrong mapping
    (e.g., using 'uid' as display_name instead of 'cn') silently produces
    wrong values for every LDAP login, breaking cross-protocol resolution.
    """

    def test_cn_maps_to_display_name(self) -> None:
        """extract({'cn': 'Alice Smith'}) must include display_name='Alice Smith'."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"cn": "Alice Smith"})

        assert result.get("display_name") == "Alice Smith", (
            f"Expected display_name='Alice Smith', got {result.get('display_name')!r}. "
            "Spec §5.2 mapping: LDAP 'cn' → unified 'display_name'."
        )

    def test_mail_maps_to_primary_email(self) -> None:
        """extract({'mail': 'alice@corp.com'}) must include primary_email='alice@corp.com'."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"mail": "alice@corp.com"})

        assert result.get("primary_email") == "alice@corp.com", (
            f"Expected primary_email='alice@corp.com', got {result.get('primary_email')!r}. "
            "Spec §5.2 mapping: LDAP 'mail' → unified 'primary_email'."
        )

    def test_departmentNumber_maps_to_department_with_value_normalization(self) -> None:
        """extract({'departmentNumber': 'eng'}) must include department='Engineering'."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"departmentNumber": "eng"})

        assert result.get("department") == "Engineering", (
            f"Expected department='Engineering' for LDAP 'departmentNumber'='eng', "
            f"got {result.get('department')!r}. "
            "Spec §5.2: LDAP 'departmentNumber' → 'department' with normalization."
        )

    def test_employeeType_maps_to_employee_type_with_value_normalization(self) -> None:
        """extract({'employeeType': 'FTE'}) must include employee_type='FTE'."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"employeeType": "FTE"})

        assert result.get("employee_type") == "FTE", (
            f"Expected employee_type='FTE' for LDAP 'employeeType'='FTE', "
            f"got {result.get('employee_type')!r}. "
            "Spec §5.2 mapping: LDAP 'employeeType' → unified 'employee_type'."
        )

    def test_memberOf_maps_to_groups_as_list(self) -> None:
        """extract({'memberOf': [...]}) must include groups as a list."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": ["cn=engineering,ou=groups,dc=corp,dc=com"]
        })

        assert isinstance(result.get("groups"), list), (
            f"Expected groups to be a list, got {type(result.get('groups')).__name__!r}. "
            "Spec §5.2: memberOf → groups is a list of group names."
        )


# ===========================================================================
# CLASS 4 — memberOf DN reduction (the critical LDAP-specific transform)
# ===========================================================================


class TestLdapAdapterMemberOfDnReduction:
    """LdapAdapter must reduce memberOf DN values to their cn RDN values.

    WHY: Spec §5.2 — 'memberOf values are typically full DNs (e.g.,
    cn=engineering,ou=groups,dc=corp,dc=com). The unified groups is a list of
    group names, so the LDAP adapter must reduce each memberOf DN to its group
    name (the cn RDN).'

    The unified schema stores group names (strings like 'engineering', 'admin')
    not full DNs. If full DNs were stored, cross-protocol comparison with OIDC
    groups (plain strings) would always fail, and group-based policy conditions
    would be broken for all LDAP users.

    NOTE: bootstrap.ldif does NOT include memberOf attributes on user entries.
    These tests use synthetic raw_attributes to verify the DN parsing logic.
    Expected DN format: cn=<groupname>,ou=groups,dc=corp,dc=com
    """

    def test_single_full_dn_is_reduced_to_cn_rdn(self) -> None:
        """memberOf=['cn=engineering,ou=groups,dc=corp,dc=com'] → groups=['engineering'].

        WHY: This is the canonical DN format for the test directory. The adapter
        must extract the value of the first cn= attribute from the DN.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": ["cn=engineering,ou=groups,dc=corp,dc=com"]
        })

        groups = result.get("groups", [])
        assert "engineering" in groups, (
            f"Expected 'engineering' in groups for DN "
            f"'cn=engineering,ou=groups,dc=corp,dc=com', got groups={groups!r}. "
            "Spec §5.2: memberOf DN → cn RDN value."
        )

    def test_multiple_full_dns_both_reduced(self) -> None:
        """memberOf with two DNs produces groups containing both cn RDN values.

        Expected: groups contains 'engineering' and 'admin' (order may vary).

        WHY: Users may belong to multiple groups. Each DN must be individually
        reduced. The spec §6 criterion 3 shows groups from multiple sources merged
        together — the DN reduction is the prerequisite for that to work.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": [
                "cn=engineering,ou=groups,dc=corp,dc=com",
                "cn=admin,ou=groups,dc=corp,dc=com",
            ]
        })

        groups = result.get("groups", [])
        assert "engineering" in groups, (
            f"Expected 'engineering' in groups. Got groups={groups!r}."
        )
        assert "admin" in groups, (
            f"Expected 'admin' in groups. Got groups={groups!r}."
        )
        assert len(groups) == 2, (
            f"Expected exactly 2 group names for 2 DNs, got {len(groups)}: {groups!r}."
        )

    def test_bare_name_passthrough(self) -> None:
        """memberOf=['engineering'] (no commas, no DN format) → groups=['engineering'].

        WHY: Some LDAP implementations or test fixtures may store group names
        directly rather than full DNs (e.g., posixGroup memberOf values). The
        adapter must handle the bare-name case gracefully — treating it as the
        group name itself rather than crashing or dropping it.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"memberOf": ["engineering"]})

        groups = result.get("groups", [])
        assert "engineering" in groups, (
            f"Expected 'engineering' in groups for bare name 'engineering', "
            f"got groups={groups!r}. "
            "Bare names (no DN format) must be passed through as-is."
        )

    def test_empty_memberOf_list_yields_empty_groups(self) -> None:
        """memberOf=[] → groups=[].

        WHY: The seeded bootstrap.ldif users have no memberOf attribute. When
        the LDAP query returns no memberOf values, groups must be an empty list,
        not None, to avoid TypeError in the resolution engine.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"memberOf": []})

        assert result.get("groups") == [], (
            f"Expected groups=[] for empty memberOf, got {result.get('groups')!r}."
        )

    def test_malformed_dn_no_cn_prefix_does_not_raise(self) -> None:
        """memberOf with a malformed DN (no cn= component) must not raise.

        WHY: Production LDAP directories may contain unexpected DN formats (e.g.,
        uid= or o= RDNs). The adapter must not crash on malformed input — it should
        either skip the entry, use the whole string, or use a safe fallback.
        The exact fallback behavior is implementation-defined; the requirement is
        that no exception is raised and the result is a list.
        """
        from app.adapters.ldap import LdapAdapter

        # Should not raise
        result = LdapAdapter().extract({
            "memberOf": ["uid=alice,ou=users,dc=corp,dc=com"]
        })

        assert isinstance(result.get("groups"), list), (
            f"Malformed DN should yield groups as a list (even if empty or with fallback). "
            f"Got groups={result.get('groups')!r}."
        )

    def test_groups_from_dn_are_lowercase_cn_values(self) -> None:
        """Extracted group names must match the cn= value exactly (case-preserving).

        WHY: Group names are compared against policy conditions. If the adapter
        normalizes case on group names (e.g., lowercasing 'Engineering' → 'engineering'),
        policy conditions using the original case would silently fail to match.
        The group name must be extracted verbatim from the cn= part of the DN.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": [
                "cn=engineering,ou=groups,dc=corp,dc=com",
                "cn=admin,ou=groups,dc=corp,dc=com",
            ]
        })

        groups = result.get("groups", [])
        # The cn values in the DNs above are 'engineering' and 'admin'
        assert set(groups) == {"engineering", "admin"}, (
            f"Expected groups={{'engineering', 'admin'}}, got {set(groups)!r}. "
            "Group names must be extracted verbatim from the cn= RDN."
        )


# ===========================================================================
# CLASS 5 — Value normalization variants through the LDAP adapter
# ===========================================================================


class TestLdapAdapterValueNormalization:
    """LdapAdapter.extract must apply the same normalization as OIDC/SAML adapters."""

    @pytest.mark.parametrize("raw_dept,expected_dept", [
        ("eng", "Engineering"),
        ("ENGINEERING", "Engineering"),
        (" Engineering ", "Engineering"),
        ("r&d", "Engineering"),
        ("product development", "Engineering"),
        ("fin", "Finance"),
        ("finance", "Finance"),
        ("accounting", "Finance"),
        ("hr", "Human Resources"),
        ("human resources", "Human Resources"),
        ("it", "Information Technology"),
        ("information technology", "Information Technology"),
        ("infra", "Information Technology"),
        ("sales", "Sales"),
        ("revenue", "Sales"),
        ("mktg", "Marketing"),
        ("marketing", "Marketing"),
    ])
    def test_departmentNumber_normalization_variants(
        self, raw_dept: str, expected_dept: str
    ) -> None:
        """LdapAdapter normalizes recognized departmentNumber aliases."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"departmentNumber": raw_dept})

        assert result.get("department") == expected_dept, (
            f"LdapAdapter.extract(departmentNumber={raw_dept!r}) expected "
            f"{expected_dept!r}, got {result.get('department')!r}."
        )

    @pytest.mark.parametrize("raw_et,expected_et", [
        ("FTE", "FTE"),
        ("fte", "FTE"),
        ("E", "FTE"),
        ("e", "FTE"),
        ("employee", "FTE"),
        ("full-time", "FTE"),
        ("contractor", "contractor"),
        ("c", "contractor"),
        ("temp", "contractor"),
        ("vendor", "vendor"),
        ("v", "vendor"),
        ("external", "vendor"),
        ("partner", "vendor"),
    ])
    def test_employeeType_normalization_variants(
        self, raw_et: str, expected_et: str
    ) -> None:
        """LdapAdapter normalizes recognized employeeType aliases."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"employeeType": raw_et})

        assert result.get("employee_type") == expected_et, (
            f"LdapAdapter.extract(employeeType={raw_et!r}) expected "
            f"{expected_et!r}, got {result.get('employee_type')!r}."
        )

    def test_unmapped_department_is_retained_titlecased(self) -> None:
        """LdapAdapter retains unmapped departmentNumber as title-cased."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"departmentNumber": "astrophysics"})

        assert result.get("department") == "Astrophysics", (
            f"Expected department='Astrophysics' for unmapped 'astrophysics', "
            f"got {result.get('department')!r}."
        )

    def test_unmapped_employee_type_is_none(self) -> None:
        """LdapAdapter sets employee_type=None for unmapped values."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"employeeType": "XYZ"})

        assert result.get("employee_type") is None, (
            f"Expected employee_type=None for unmapped 'XYZ', "
            f"got {result.get('employee_type')!r}."
        )


# ===========================================================================
# CLASS 6 — Cross-protocol canonical identity (LDAP vs OIDC/SAML)
# ===========================================================================


class TestLdapAdapterCrossProtocolCanonicalIdentity:
    """LDAP adapter must produce byte-identical canonical strings to OIDC/SAML.

    WHY: When an OIDC event is enriched with LDAP data, the resolution engine
    compares OIDC-extracted values with LDAP-extracted values using ==. If they
    are not byte-identical, every field will appear to conflict even when both
    sources agree on the logical value.
    """

    def test_ldap_r_and_d_equals_oidc_eng_canonical(self) -> None:
        """LDAP departmentNumber='r&d' and OIDC department='eng' both → 'Engineering'.

        WHY: In realistic deployments, an OIDC token may carry 'eng' while the
        LDAP directory entry has departmentNumber='r&d'. After normalization, both
        must produce the exact string 'Engineering' for the resolution engine to
        recognize them as agreeing.
        """
        from app.adapters.ldap import LdapAdapter
        from app.adapters.oidc import OidcAdapter

        ldap_result = LdapAdapter().extract({"departmentNumber": "r&d"})
        oidc_result = OidcAdapter().extract({"department": "eng"})

        assert ldap_result.get("department") == oidc_result.get("department") == "Engineering", (
            f"LDAP 'r&d' → {ldap_result.get('department')!r}, "
            f"OIDC 'eng' → {oidc_result.get('department')!r}. "
            "Both must equal 'Engineering' byte-for-byte."
        )

    def test_ldap_FTE_equals_oidc_E_canonical(self) -> None:
        """LDAP employeeType='FTE' and OIDC employee_type='E' both → 'FTE'."""
        from app.adapters.ldap import LdapAdapter
        from app.adapters.oidc import OidcAdapter

        ldap_result = LdapAdapter().extract({"employeeType": "FTE"})
        oidc_result = OidcAdapter().extract({"employee_type": "E"})

        assert ldap_result.get("employee_type") == oidc_result.get("employee_type") == "FTE", (
            f"LDAP 'FTE' → {ldap_result.get('employee_type')!r}, "
            f"OIDC 'E' → {oidc_result.get('employee_type')!r}. "
            "Both must equal 'FTE'."
        )

    def test_ldap_r_and_d_equals_saml_eng_canonical(self) -> None:
        """LDAP departmentNumber='r&d' and SAML dept='engineering' both → 'Engineering'."""
        from app.adapters.ldap import LdapAdapter
        from app.adapters.saml import SamlAdapter

        ldap_result = LdapAdapter().extract({"departmentNumber": "r&d"})
        saml_result = SamlAdapter().extract({"dept": "engineering"})

        assert ldap_result.get("department") == saml_result.get("department") == "Engineering", (
            f"LDAP 'r&d' → {ldap_result.get('department')!r}, "
            f"SAML 'engineering' → {saml_result.get('department')!r}. "
            "Both must equal 'Engineering'."
        )


# ===========================================================================
# CLASS 7 — Missing keys / graceful absence
# ===========================================================================


class TestLdapAdapterMissingKeys:
    """LdapAdapter.extract must not raise when LDAP attribute keys are absent."""

    def test_missing_cn_does_not_raise(self) -> None:
        """extract without 'cn' key must not raise."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"mail": "alice@corp.com"})

        assert "display_name" not in result or result.get("display_name") is None, (
            f"Missing 'cn' should yield absent/None display_name, "
            f"got {result.get('display_name')!r}."
        )

    def test_missing_mail_does_not_raise(self) -> None:
        """extract without 'mail' key must not raise."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"cn": "Alice Smith"})

        assert "primary_email" not in result or result.get("primary_email") is None, (
            f"Missing 'mail' should yield absent/None primary_email, "
            f"got {result.get('primary_email')!r}."
        )

    def test_missing_departmentNumber_does_not_raise(self) -> None:
        """extract without 'departmentNumber' key must not raise."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"mail": "alice@corp.com"})

        assert "department" not in result or result.get("department") is None, (
            f"Missing 'departmentNumber' should yield absent/None department, "
            f"got {result.get('department')!r}."
        )

    def test_missing_employeeType_does_not_raise(self) -> None:
        """extract without 'employeeType' key must not raise."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"mail": "alice@corp.com"})

        assert "employee_type" not in result or result.get("employee_type") is None, (
            f"Missing 'employeeType' should yield absent/None employee_type, "
            f"got {result.get('employee_type')!r}."
        )

    def test_missing_memberOf_defaults_to_empty_groups(self) -> None:
        """extract without 'memberOf' key must return groups=[].

        WHY: The seeded test users in bootstrap.ldif have NO memberOf attribute.
        When the LDAP adapter extracts attributes from real queries to the test
        directory, it will not see memberOf in the returned dict. This must
        produce groups=[] (not None or KeyError) for the resolution engine.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"cn": "Alice Smith", "mail": "alice@corp.com"})

        groups_val = result.get("groups", "ABSENT_SENTINEL")
        assert groups_val == [], (
            f"Missing 'memberOf' key must produce groups=[], got {groups_val!r}. "
            "bootstrap.ldif users have no memberOf — this is the common real case."
        )

    def test_empty_raw_attributes_does_not_raise(self) -> None:
        """extract({}) must not raise and must return groups=[]."""
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({})

        assert isinstance(result, dict), (
            f"extract({{}}) must return a dict, got {type(result).__name__!r}."
        )
        assert result.get("groups", "ABSENT") == [], (
            f"Empty raw_attributes must yield groups=[], "
            f"got {result.get('groups', 'ABSENT')!r}."
        )

    def test_ldap_specific_key_uid_not_mapped_to_display_name(self) -> None:
        """LDAP 'uid' key must NOT be mapped to display_name.

        WHY: Spec §2.3 defines the LDAP key shape as:
          cn, sn, mail, uid, departmentNumber, employeeType, memberOf
        Only 'cn' maps to display_name. 'uid' is a login identifier, not a
        display name. Mapping uid → display_name would cause every LDAP user
        to show their login handle instead of their full name.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"uid": "alice", "cn": "Alice Smith"})

        # display_name must come from cn, not uid
        assert result.get("display_name") == "Alice Smith", (
            f"display_name must come from 'cn', not 'uid'. "
            f"Expected 'Alice Smith', got {result.get('display_name')!r}."
        )

    def test_sn_is_not_mapped_to_any_unified_field(self) -> None:
        """LDAP 'sn' (surname) key has no unified field mapping and is ignored.

        WHY: Spec §2.3 and §5.2 define no unified field for surname. The sn attribute
        must be silently ignored — it must not accidentally populate display_name
        or any other unified field.
        """
        from app.adapters.ldap import LdapAdapter

        # Provide only sn and no cn; display_name must be absent/None
        result = LdapAdapter().extract({"sn": "Smith"})

        display_name_val = result.get("display_name")
        assert display_name_val is None or "display_name" not in result, (
            f"LDAP 'sn' must not map to any unified field. "
            f"Got display_name={display_name_val!r}. "
            "Spec §5.2: sn has no entry in the mapping table."
        )


# ===========================================================================
# CLASS 8 — Bare-string memberOf behavior (adapter refactor, intentional change)
# ===========================================================================


class TestLdapAdapterBareStringMemberOf:
    """LdapAdapter.extract must yield groups=[] when 'memberOf' is a bare string.

    This is the LDAP analog of the OIDC/SAML bare-string groups behavior change
    introduced by the adapter refactor.  The new `reduce_member_of` transform
    (introduced in ldap.py as part of the refactor) calls coerce_str_list
    internally to obtain the list of DN strings before applying _reduce_dn_to_group_name.

    Since coerce_str_list applies strict list-only semantics, a bare string memberOf
    value (not a list) returns [] from coerce_str_list, and therefore reduce_member_of
    returns [] with no DN reduction attempted.

    WHY this matters:
      In production LDAP directories, memberOf is always a multi-valued attribute
      returned as a list.  A bare string memberOf would indicate a severely
      misconfigured LDAP client or an injected test payload.  Silently iterating
      the string character-by-character would produce a groups list of single chars
      that pass the isinstance(v, str) filter — meaningless group names that would
      break policy conditions.  Returning [] is the correct safe fallback.

    Contract distinction from the bare-name passthrough test (CLASS 4):
      The bare-name test uses memberOf=['engineering'] (a LIST containing a string)
      — this is a valid list, so coerce_str_list passes it through and
      _reduce_dn_to_group_name handles the bare name within the list.
      THIS test uses memberOf='cn=eng,ou=groups,dc=corp,dc=com' (a STRING, not a list)
      — coerce_str_list returns [] immediately, no DN reduction attempted.

    TDD state:
      These tests describe the post-refactor behavior.  If the current implementation
      already produces [] for a bare string memberOf (e.g., because it calls
      `memberOf or []` which treats a string as truthy then list-wraps it, or uses
      any other non-list-only path), these tests may already pass or already fail
      depending on the exact implementation.  The refactor must ensure they pass.
    """

    def test_bare_string_memberOf_yields_empty_groups(self) -> None:
        """extract({'memberOf': 'cn=eng,ou=groups,dc=corp,dc=com'}) must yield groups=[].

        WHY: See class docstring.  A bare string memberOf (not a list) must return []
        rather than attempting DN reduction on individual characters.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": "cn=eng,ou=groups,dc=corp,dc=com"
        })

        groups = result.get("groups", "ABSENT_SENTINEL")
        assert groups == [], (
            f"LdapAdapter.extract with memberOf as bare string must yield groups=[], "
            f"got {groups!r}. "
            "A non-list memberOf value must produce [] via coerce_str_list strict semantics. "
            "This is the intentional behavior change from the adapter refactor."
        )

    def test_bare_string_memberOf_not_iterated_as_chars(self) -> None:
        """extract({'memberOf': 'engineering'}) must NOT produce chars ['e','n','g',...].

        WHY: Makes the character-iteration failure mode explicitly visible.
        A naive [v for v in value if isinstance(v, str)] on a string would yield
        individual characters — each is a str, so each passes the filter.
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({"memberOf": "engineering"})

        groups = result.get("groups", [])
        # If groups contains single-char strings from 'engineering', that's the bug
        single_chars_from_value = [g for g in groups if isinstance(g, str) and len(g) == 1]
        assert len(single_chars_from_value) == 0, (
            f"groups={groups!r} contains single-char entries: {single_chars_from_value!r}. "
            "This indicates character-by-character iteration of the bare string. "
            "coerce_str_list('engineering') must return [], not list('engineering')."
        )
        assert groups == [], (
            f"extract({{'memberOf': 'engineering'}}) must yield groups=[], got {groups!r}."
        )

    def test_list_memberOf_still_reduces_dns(self) -> None:
        """extract({'memberOf': ['cn=eng,ou=groups,dc=corp,dc=com']}) still works.

        WHY: Regression guard — the refactor must not break the normal list-of-DNs
        path.  A single-element list with a valid DN must still produce ['eng'].
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": ["cn=eng,ou=groups,dc=corp,dc=com"]
        })

        groups = result.get("groups", [])
        assert "eng" in groups, (
            f"LdapAdapter with list memberOf must still reduce DNs to group names. "
            f"Expected 'eng' in groups, got {groups!r}. "
            "The refactor must not regress normal list-of-DNs behavior."
        )


# ===========================================================================
# CLASS 9 — memberOf list containing non-str elements (robustness)
# ===========================================================================


class TestLdapAdapterMemberOfNonStrElements:
    """LdapAdapter.extract must silently drop non-str elements in a memberOf list.

    WHY: coerce_str_list filters to only str elements before DN reduction.
    A mixed list (valid DN + non-str, e.g., an int) must produce groups that
    contain only the reduced names from the valid str DNs.  Non-str elements
    must be dropped rather than raising TypeError in _reduce_dn_to_group_name.

    This asserts byte-identical output to the equivalent single-element list,
    proving the non-str element leaves no trace in the result.
    """

    def test_list_with_non_str_element_drops_non_str_keeps_valid_dn(self) -> None:
        """extract({'memberOf': ['cn=engineering,...', 123]}) yields groups=['engineering'].

        The int 123 is not a str, so coerce_str_list filters it out before
        DN reduction.  The valid DN is reduced to 'engineering' as normal.
        Result must be byte-identical to extract({'memberOf': ['cn=engineering,...']}).
        """
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract({
            "memberOf": [
                "cn=engineering,ou=groups,dc=corp,dc=com",
                123,
            ]
        })

        groups = result.get("groups", [])
        assert groups == ["engineering"], (
            f"Expected groups=['engineering'] when memberOf list contains one valid "
            f"DN and one int (123). Got groups={groups!r}. "
            "Non-str elements must be silently dropped; the int must leave no trace."
        )
