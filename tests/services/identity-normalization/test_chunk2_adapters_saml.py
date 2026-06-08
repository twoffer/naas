# Component: NAAS Spec 2 — Chunk 2: adapters/saml.py (SamlAdapter)
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/app/adapters/saml.py
#
# What these tests validate:
#   - SamlAdapter is importable from app.adapters.saml
#   - SamlAdapter satisfies the ProtocolAdapter Protocol (has extract method)
#   - Field mapping: displayName→display_name, email→primary_email,
#                    dept→department, employeeType→employee_type, groups→groups
#   - Value normalization applied (same canonical targets as OIDC and LDAP)
#   - Missing keys handled gracefully; groups defaults to []
#   - Unmapped employee_type → None; unmapped department → retained, title-cased
#   - Canonical target strings are byte-identical to those from OIDC/LDAP
#
# WHY SamlAdapter matters:
#   SAML is used by legacy IdPs and enterprise SSO federations. The adapter's
#   claim-name differences (displayName instead of name, dept instead of
#   department, employeeType instead of employee_type) are the key risk vector:
#   a wrong mapping silently stores every SAML login under wrong unified fields,
#   making cross-protocol resolution impossible.
#
# TDD state:
#   app/adapters/saml.py does NOT exist yet.
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


class TestSamlAdapterImport:
    """SamlAdapter must be importable from app.adapters.saml."""

    def test_saml_adapter_is_importable(self) -> None:
        """from app.adapters.saml import SamlAdapter must not raise."""
        from app.adapters.saml import SamlAdapter  # noqa: F401

    def test_saml_module_exists(self) -> None:
        """app.adapters.saml module must exist."""
        from app.adapters import saml as saml_mod

        assert hasattr(saml_mod, "SamlAdapter"), (
            "app.adapters.saml must define SamlAdapter."
        )


# ===========================================================================
# CLASS 2 — Protocol conformance
# ===========================================================================


class TestSamlAdapterProtocolConformance:
    """SamlAdapter must satisfy the ProtocolAdapter port interface."""

    def test_saml_adapter_has_extract_method(self) -> None:
        """SamlAdapter must define an extract method."""
        from app.adapters.saml import SamlAdapter

        assert hasattr(SamlAdapter, "extract"), (
            "SamlAdapter must define 'extract'. Spec §5.2."
        )

    def test_saml_adapter_extract_accepts_dict(self) -> None:
        """SamlAdapter().extract({}) must not raise TypeError."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({})

        assert isinstance(result, dict), (
            f"SamlAdapter().extract({{}}) must return a dict, got {type(result).__name__!r}."
        )


# ===========================================================================
# CLASS 3 — Field mapping contract (spec §5.2 mapping table)
# ===========================================================================


class TestSamlAdapterFieldMapping:
    """SamlAdapter.extract must map SAML attribute names to unified field names.

    Mapping table (spec §5.2, [TRANSCRIBE EXACTLY]):
      displayName  → display_name
      email        → primary_email
      dept         → department   (value-normalized)
      employeeType → employee_type (value-normalized)
      groups       → groups
    """

    def test_displayName_maps_to_display_name(self) -> None:
        """extract({'displayName': 'Bob Jones'}) must include display_name='Bob Jones'.

        WHY: SAML IdPs use 'displayName' (camelCase) as the attribute name. If
        the adapter maps from 'name' (OIDC convention) instead of 'displayName',
        every SAML event will have display_name=None silently.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"displayName": "Bob Jones"})

        assert result.get("display_name") == "Bob Jones", (
            f"Expected display_name='Bob Jones', got {result.get('display_name')!r}. "
            "Spec §5.2 mapping: SAML 'displayName' → unified 'display_name'."
        )

    def test_email_maps_to_primary_email(self) -> None:
        """extract({'email': 'bob@corp.com'}) must include primary_email='bob@corp.com'."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"email": "bob@corp.com"})

        assert result.get("primary_email") == "bob@corp.com", (
            f"Expected primary_email='bob@corp.com', got {result.get('primary_email')!r}. "
            "Spec §5.2 mapping: SAML 'email' → unified 'primary_email'."
        )

    def test_dept_maps_to_department_with_value_normalization(self) -> None:
        """extract({'dept': 'eng'}) must include department='Engineering'.

        WHY: SAML uses 'dept' (short form) while OIDC uses 'department'. The
        adapter must map from 'dept', not 'department'. Both must produce the
        same canonical 'Engineering' string for cross-protocol resolution.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"dept": "eng"})

        assert result.get("department") == "Engineering", (
            f"Expected department='Engineering' for SAML 'dept'='eng', "
            f"got {result.get('department')!r}. "
            "Spec §5.2 mapping: SAML 'dept' → unified 'department' with normalization."
        )

    def test_employeeType_maps_to_employee_type_with_value_normalization(self) -> None:
        """extract({'employeeType': 'E'}) must include employee_type='FTE'.

        WHY: SAML uses 'employeeType' (camelCase) while OIDC uses 'employee_type'
        (snake_case). Both must produce the same canonical 'FTE' string.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"employeeType": "E"})

        assert result.get("employee_type") == "FTE", (
            f"Expected employee_type='FTE' for SAML 'employeeType'='E', "
            f"got {result.get('employee_type')!r}. "
            "Spec §5.2 mapping: SAML 'employeeType' → unified 'employee_type'."
        )

    def test_groups_maps_to_groups(self) -> None:
        """extract({'groups': ['admin', 'vpn']}) must include groups=['admin', 'vpn']."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"groups": ["admin", "vpn"]})

        assert result.get("groups") == ["admin", "vpn"], (
            f"Expected groups=['admin', 'vpn'], got {result.get('groups')!r}. "
            "Spec §5.2 mapping: SAML 'groups' → unified 'groups'."
        )


# ===========================================================================
# CLASS 4 — Canonical target string identity with OIDC (cross-protocol)
# ===========================================================================


class TestSamlAdapterCrossProtocolCanonicalIdentity:
    """SAML adapter must produce the same canonical strings as OIDC adapter.

    WHY: Conflict resolution (§5.5) compares values from multiple sources with ==.
    If SAML and OIDC produce different strings for the same logical value
    (e.g., OIDC 'Engineering' vs SAML 'engineering'), they will never resolve
    as unanimous and every enriched event will get a spurious priority conflict.
    """

    def test_saml_eng_equals_oidc_eng(self) -> None:
        """SAML dept='eng' and OIDC department='eng' produce the same department string."""
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter

        oidc_result = OidcAdapter().extract({"department": "eng"})
        saml_result = SamlAdapter().extract({"dept": "eng"})

        assert oidc_result.get("department") == saml_result.get("department"), (
            f"OIDC 'eng' → {oidc_result.get('department')!r} but "
            f"SAML 'eng' → {saml_result.get('department')!r}. "
            "Both must equal 'Engineering' for cross-protocol unanimous resolution."
        )

    def test_saml_E_equals_oidc_E_for_employee_type(self) -> None:
        """SAML employeeType='E' and OIDC employee_type='E' produce the same string."""
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter

        oidc_result = OidcAdapter().extract({"employee_type": "E"})
        saml_result = SamlAdapter().extract({"employeeType": "E"})

        assert oidc_result.get("employee_type") == saml_result.get("employee_type") == "FTE", (
            f"OIDC 'E' → {oidc_result.get('employee_type')!r}, "
            f"SAML 'E' → {saml_result.get('employee_type')!r}. "
            "Both must equal 'FTE'."
        )


# ===========================================================================
# CLASS 5 — Value normalization variants
# ===========================================================================


class TestSamlAdapterValueNormalization:
    """SamlAdapter.extract must apply the same value normalization as OidcAdapter."""

    @pytest.mark.parametrize("raw_dept,expected_dept", [
        ("eng", "Engineering"),
        ("ENGINEERING", "Engineering"),
        (" Engineering ", "Engineering"),
        ("r&d", "Engineering"),
        ("fin", "Finance"),
        ("hr", "Human Resources"),
        ("it", "Information Technology"),
        ("sales", "Sales"),
        ("mktg", "Marketing"),
    ])
    def test_department_normalization_via_dept_key(
        self, raw_dept: str, expected_dept: str
    ) -> None:
        """SamlAdapter normalizes recognized department aliases via 'dept' key."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"dept": raw_dept})

        assert result.get("department") == expected_dept, (
            f"SamlAdapter.extract(dept={raw_dept!r}) expected {expected_dept!r}, "
            f"got {result.get('department')!r}."
        )

    def test_unmapped_department_is_retained_titlecased(self) -> None:
        """SamlAdapter retains unmapped dept as title-cased."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"dept": "astrophysics"})

        assert result.get("department") == "Astrophysics", (
            f"Expected department='Astrophysics' for unmapped 'astrophysics', "
            f"got {result.get('department')!r}."
        )

    def test_unmapped_employee_type_is_none(self) -> None:
        """SamlAdapter sets employee_type=None for unmapped values."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"employeeType": "XYZ"})

        assert result.get("employee_type") is None, (
            f"Expected employee_type=None for unmapped 'XYZ', "
            f"got {result.get('employee_type')!r}."
        )


# ===========================================================================
# CLASS 6 — Missing keys / graceful absence
# ===========================================================================


class TestSamlAdapterMissingKeys:
    """SamlAdapter.extract must not raise when SAML attribute keys are absent."""

    def test_missing_displayName_does_not_raise(self) -> None:
        """extract without 'displayName' key must not raise."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"email": "alice@corp.com"})

        assert "display_name" not in result or result.get("display_name") is None, (
            f"Missing 'displayName' should yield absent/None display_name, "
            f"got {result.get('display_name')!r}."
        )

    def test_missing_email_does_not_raise(self) -> None:
        """extract without 'email' key must not raise."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"displayName": "Alice Smith"})

        assert "primary_email" not in result or result.get("primary_email") is None, (
            f"Missing 'email' should yield absent/None primary_email, "
            f"got {result.get('primary_email')!r}."
        )

    def test_missing_dept_does_not_raise(self) -> None:
        """extract without 'dept' key must not raise."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"email": "alice@corp.com"})

        assert "department" not in result or result.get("department") is None, (
            f"Missing 'dept' should yield absent/None department, "
            f"got {result.get('department')!r}."
        )

    def test_missing_employeeType_does_not_raise(self) -> None:
        """extract without 'employeeType' key must not raise."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"email": "alice@corp.com"})

        assert "employee_type" not in result or result.get("employee_type") is None, (
            f"Missing 'employeeType' should yield absent/None employee_type, "
            f"got {result.get('employee_type')!r}."
        )

    def test_missing_groups_defaults_to_empty_list(self) -> None:
        """extract without 'groups' key must return groups=[].

        WHY: Same reasoning as OIDC adapter — the resolution engine iterates
        the groups list; None would cause TypeError.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"email": "alice@corp.com"})

        groups_val = result.get("groups", "ABSENT_SENTINEL")
        assert groups_val == [], (
            f"Missing 'groups' key must produce groups=[], got {groups_val!r}. "
            "Spec §5.2: groups defaults to [] when absent."
        )

    def test_oidc_key_names_do_not_accidentally_work_for_saml(self) -> None:
        """SAML adapter must NOT pick up OIDC key 'name' for display_name.

        WHY: Spec §2.3 defines distinct key shapes per protocol. If the SAML
        adapter accidentally maps 'name' (OIDC) to display_name instead of
        'displayName' (SAML), it would silently populate display_name from
        the wrong source when raw_attributes happen to contain 'name'.
        """
        from app.adapters.saml import SamlAdapter

        # Provide OIDC-style 'name' key — SAML adapter must NOT pick it up
        result = SamlAdapter().extract({"name": "Should Not Appear"})

        # display_name must NOT be populated from OIDC 'name' key in SAML adapter
        assert result.get("display_name") is None or "display_name" not in result, (
            f"SAML adapter must not map OIDC 'name' key to display_name. "
            f"Got display_name={result.get('display_name')!r}. "
            "Spec §2.3: SAML uses 'displayName', not 'name'."
        )

    def test_oidc_department_key_does_not_work_for_saml(self) -> None:
        """SAML adapter must NOT pick up OIDC key 'department' for department.

        WHY: SAML uses 'dept', not 'department'. An adapter that maps both would
        silently use OIDC raw_attributes format, masking mapping bugs.
        """
        from app.adapters.saml import SamlAdapter

        # Provide OIDC-style 'department' key — SAML adapter must NOT pick it up
        result = SamlAdapter().extract({"department": "eng"})

        # department must be None/absent since SAML uses 'dept'
        dept_val = result.get("department")
        assert dept_val is None or "department" not in result, (
            f"SAML adapter must not map OIDC 'department' key to department. "
            f"Got department={dept_val!r}. "
            "Spec §2.3: SAML uses 'dept', not 'department'."
        )


# ===========================================================================
# CLASS 7 — Bare-string groups behavior (adapter refactor, intentional change)
# ===========================================================================


class TestSamlAdapterBareStringGroups:
    """SamlAdapter.extract must yield groups=[] when 'groups' is a bare string.

    This is the ONE intentional behavior change introduced by the adapter refactor.
    The SAML adapter uses the same coerce_str_list transform for the 'groups' key
    as the OIDC adapter.  The strict list-only semantics apply: a non-list value
    (including a bare string) returns [].

    WHY this is a security-relevant behavior change:
      SAML assertions may send groups as a single string attribute value rather
      than a multi-valued list (this is common with older SAML IdPs that do not
      support multi-value attributes).  With the old iteration logic, 'admin'
      becomes ['a','d','m','i','n'] — no policy condition checking
      `"admin" in groups` would match.  With strict list-only semantics, the
      result is [] and the policy engine sees no groups.  Both are secure; []
      is the more predictable and explicit failure mode.

    TDD state:
      These tests describe the post-refactor behavior.  They WILL FAIL against
      the current implementation if it uses `list(...)` or iteration that
      processes bare strings.  The implementer must switch to coerce_str_list.
    """

    def test_bare_string_groups_yields_empty_list(self) -> None:
        """extract({'groups': 'admin'}) must yield groups=[] (not ['a','d','m','i','n']).

        WHY: See class docstring.  SAML bare-string groups must produce [].
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"groups": "admin"})

        groups = result.get("groups", "ABSENT_SENTINEL")
        assert groups == [], (
            f"SamlAdapter.extract({{'groups': 'admin'}}) must yield groups=[], "
            f"got {groups!r}. "
            "A bare string for groups must produce [] (strict list-only semantics). "
            "The refactor replaces the old iteration logic with coerce_str_list."
        )
        # Belt-and-suspenders: explicitly confirm it is not the character list
        assert groups != list("admin"), (
            "groups must NOT be ['a','d','m','i','n'] — "
            "that would be iterating the string character-by-character."
        )

    def test_bare_string_groups_not_iterated_as_chars(self) -> None:
        """extract({'groups': 'staff'}) must NOT produce individual chars.

        WHY: Makes the character-iteration failure mode explicitly visible in test
        output, distinguishing it from the empty-list check.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"groups": "staff"})

        groups = result.get("groups", [])
        for char in "staff":
            assert char not in groups or len(groups[0]) > 1, (
                f"groups={groups!r} contains single-char entry {char!r} — "
                "this indicates character-by-character iteration. "
                "coerce_str_list('staff') must return [], not list('staff')."
            )
        assert groups == [], (
            f"extract({{'groups': 'staff'}}) must yield groups=[], got {groups!r}."
        )

    def test_list_groups_still_passes_through(self) -> None:
        """extract({'groups': ['admin', 'vpn']}) must still yield groups=['admin', 'vpn'].

        WHY: Regression guard — the refactor must not break the normal list path.
        """
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract({"groups": ["admin", "vpn"]})

        assert result.get("groups") == ["admin", "vpn"], (
            f"SamlAdapter.extract with list groups must return ['admin', 'vpn'], "
            f"got {result.get('groups')!r}. "
            "The refactor must not regress normal list behavior."
        )
