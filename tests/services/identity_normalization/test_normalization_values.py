"""normalization_values.py: department/employee_type canonical maps and normalize helpers."""

from typing import ClassVar

# third-party
import pytest

# ===========================================================================
# CLASS 1 — Module import
# ===========================================================================


class TestNormalizationValuesImport:
    """app.normalization_values must be importable and expose the required names.

    WHY: adapters import from normalization_values at module level. An ImportError
    here means all three protocol adapters crash on import, shutting down the service.
    """

    def test_module_is_importable(self) -> None:
        """from app.normalization_values import ... must not raise.

        WHY: A missing module surfaces as a clear failure rather than a collection error.
        """
        import app.normalization_values  # noqa: F401

    def test_department_canonical_is_defined(self) -> None:
        """DEPARTMENT_CANONICAL must be exposed as a module-level dict."""
        from app import normalization_values

        assert hasattr(normalization_values, "DEPARTMENT_CANONICAL"), (
            "app.normalization_values must define DEPARTMENT_CANONICAL. "
            "Spec §5.2: the dict maps lowercased department aliases to canonical strings."
        )

    def test_employee_type_canonical_is_defined(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL must be exposed as a module-level dict."""
        from app import normalization_values

        assert hasattr(normalization_values, "EMPLOYEE_TYPE_CANONICAL"), (
            "app.normalization_values must define EMPLOYEE_TYPE_CANONICAL. "
            "Spec §5.2: the dict maps lowercased employee_type aliases to canonical values."
        )

    def test_unified_to_ldap_is_defined(self) -> None:
        """UNIFIED_TO_LDAP must be exposed as a module-level dict."""
        from app import normalization_values

        assert hasattr(normalization_values, "UNIFIED_TO_LDAP"), (
            "app.normalization_values must define UNIFIED_TO_LDAP. "
            "Spec §5.2: the reverse map from unified field names to LDAP attribute names."
        )

    def test_normalize_department_is_defined(self) -> None:
        """normalize_department must be a callable in the module."""
        from app import normalization_values

        assert callable(getattr(normalization_values, "normalize_department", None)), (
            "app.normalization_values must define a callable normalize_department. "
            "Spec §5.2: normalize_department(value) -> (str, bool)."
        )

    def test_normalize_employee_type_is_defined(self) -> None:
        """normalize_employee_type must be a callable in the module."""
        from app import normalization_values

        assert callable(
            getattr(normalization_values, "normalize_employee_type", None)
        ), (
            "app.normalization_values must define a callable normalize_employee_type. "
            "Spec §5.2: normalize_employee_type(value) -> str | None."
        )


# ===========================================================================
# CLASS 2 — DEPARTMENT_CANONICAL contents (transcribed from spec §5.2)
# ===========================================================================


class TestDepartmentCanonicalContents:
    """DEPARTMENT_CANONICAL must contain exactly the entries from spec §5.2.

    WHY: These entries are marked [TRANSCRIBE EXACTLY] in the spec. The canonical
    target strings must be byte-identical across all adapters so that cross-protocol
    conflict resolution can compare them with ==. Any typo or missing entry causes
    a value that should resolve as unanimous to instead trigger a conflict penalty.
    """

    # --- Engineering aliases ---

    def test_eng_maps_to_engineering(self) -> None:
        """DEPARTMENT_CANONICAL['eng'] == 'Engineering'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("eng") == "Engineering", (
            f"Expected DEPARTMENT_CANONICAL['eng'] == 'Engineering', "
            f"got {DEPARTMENT_CANONICAL.get('eng')!r}. "
            "Spec §5.2 [TRANSCRIBE EXACTLY]."
        )

    def test_engineering_maps_to_engineering(self) -> None:
        """DEPARTMENT_CANONICAL['engineering'] == 'Engineering'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("engineering") == "Engineering", (
            f"Expected DEPARTMENT_CANONICAL['engineering'] == 'Engineering', "
            f"got {DEPARTMENT_CANONICAL.get('engineering')!r}."
        )

    def test_software_engineering_maps_to_engineering(self) -> None:
        """DEPARTMENT_CANONICAL['software engineering'] == 'Engineering'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("software engineering") == "Engineering", (
            f"Expected 'software engineering' → 'Engineering', "
            f"got {DEPARTMENT_CANONICAL.get('software engineering')!r}."
        )

    def test_r_and_d_maps_to_engineering(self) -> None:
        """DEPARTMENT_CANONICAL['r&d'] == 'Engineering'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("r&d") == "Engineering", (
            f"Expected DEPARTMENT_CANONICAL['r&d'] == 'Engineering', "
            f"got {DEPARTMENT_CANONICAL.get('r&d')!r}. "
            "This is a key cross-protocol test: LDAP 'r&d' must equal OIDC 'eng'."
        )

    def test_product_development_maps_to_engineering(self) -> None:
        """DEPARTMENT_CANONICAL['product development'] == 'Engineering'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("product development") == "Engineering", (
            f"Expected 'product development' → 'Engineering', "
            f"got {DEPARTMENT_CANONICAL.get('product development')!r}."
        )

    # --- Finance aliases ---

    def test_fin_maps_to_finance(self) -> None:
        """DEPARTMENT_CANONICAL['fin'] == 'Finance'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("fin") == "Finance", (
            f"Expected DEPARTMENT_CANONICAL['fin'] == 'Finance', "
            f"got {DEPARTMENT_CANONICAL.get('fin')!r}."
        )

    def test_finance_maps_to_finance(self) -> None:
        """DEPARTMENT_CANONICAL['finance'] == 'Finance'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("finance") == "Finance", (
            f"Expected DEPARTMENT_CANONICAL['finance'] == 'Finance', "
            f"got {DEPARTMENT_CANONICAL.get('finance')!r}."
        )

    def test_accounting_maps_to_finance(self) -> None:
        """DEPARTMENT_CANONICAL['accounting'] == 'Finance'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("accounting") == "Finance", (
            f"Expected DEPARTMENT_CANONICAL['accounting'] == 'Finance', "
            f"got {DEPARTMENT_CANONICAL.get('accounting')!r}."
        )

    # --- Human Resources aliases ---

    def test_hr_maps_to_human_resources(self) -> None:
        """DEPARTMENT_CANONICAL['hr'] == 'Human Resources'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("hr") == "Human Resources", (
            f"Expected DEPARTMENT_CANONICAL['hr'] == 'Human Resources', "
            f"got {DEPARTMENT_CANONICAL.get('hr')!r}."
        )

    def test_human_resources_maps_to_human_resources(self) -> None:
        """DEPARTMENT_CANONICAL['human resources'] == 'Human Resources'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("human resources") == "Human Resources", (
            f"Expected 'human resources' → 'Human Resources', "
            f"got {DEPARTMENT_CANONICAL.get('human resources')!r}."
        )

    def test_people_ops_maps_to_human_resources(self) -> None:
        """DEPARTMENT_CANONICAL['people ops'] == 'Human Resources'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("people ops") == "Human Resources", (
            f"Expected 'people ops' → 'Human Resources', "
            f"got {DEPARTMENT_CANONICAL.get('people ops')!r}."
        )

    # --- Information Technology aliases ---

    def test_it_maps_to_information_technology(self) -> None:
        """DEPARTMENT_CANONICAL['it'] == 'Information Technology'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("it") == "Information Technology", (
            f"Expected DEPARTMENT_CANONICAL['it'] == 'Information Technology', "
            f"got {DEPARTMENT_CANONICAL.get('it')!r}."
        )

    def test_information_technology_maps_to_information_technology(self) -> None:
        """DEPARTMENT_CANONICAL['information technology'] == 'Information Technology'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert (
            DEPARTMENT_CANONICAL.get("information technology")
            == "Information Technology"
        ), (
            f"Expected 'information technology' → 'Information Technology', "
            f"got {DEPARTMENT_CANONICAL.get('information technology')!r}."
        )

    def test_infra_maps_to_information_technology(self) -> None:
        """DEPARTMENT_CANONICAL['infra'] == 'Information Technology'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("infra") == "Information Technology", (
            f"Expected DEPARTMENT_CANONICAL['infra'] == 'Information Technology', "
            f"got {DEPARTMENT_CANONICAL.get('infra')!r}."
        )

    # --- Sales aliases ---

    def test_sales_maps_to_sales(self) -> None:
        """DEPARTMENT_CANONICAL['sales'] == 'Sales'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("sales") == "Sales", (
            f"Expected DEPARTMENT_CANONICAL['sales'] == 'Sales', "
            f"got {DEPARTMENT_CANONICAL.get('sales')!r}."
        )

    def test_revenue_maps_to_sales(self) -> None:
        """DEPARTMENT_CANONICAL['revenue'] == 'Sales'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("revenue") == "Sales", (
            f"Expected DEPARTMENT_CANONICAL['revenue'] == 'Sales', "
            f"got {DEPARTMENT_CANONICAL.get('revenue')!r}."
        )

    # --- Marketing aliases ---

    def test_mktg_maps_to_marketing(self) -> None:
        """DEPARTMENT_CANONICAL['mktg'] == 'Marketing'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("mktg") == "Marketing", (
            f"Expected DEPARTMENT_CANONICAL['mktg'] == 'Marketing', "
            f"got {DEPARTMENT_CANONICAL.get('mktg')!r}."
        )

    def test_marketing_maps_to_marketing(self) -> None:
        """DEPARTMENT_CANONICAL['marketing'] == 'Marketing'."""
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL.get("marketing") == "Marketing", (
            f"Expected DEPARTMENT_CANONICAL['marketing'] == 'Marketing', "
            f"got {DEPARTMENT_CANONICAL.get('marketing')!r}."
        )


# ===========================================================================
# CLASS 3 — EMPLOYEE_TYPE_CANONICAL contents (transcribed from spec §5.2)
# ===========================================================================


class TestEmployeeTypeCanonicalContents:
    """EMPLOYEE_TYPE_CANONICAL must contain exactly the entries from spec §5.2.

    WHY: [TRANSCRIBE EXACTLY] — the canonical targets are 'FTE', 'contractor',
    'vendor'. These are the three Literal values allowed by the NormalizedAttributes
    model. Any deviation would fail Pydantic validation when the model is constructed.
    """

    # --- FTE aliases ---

    def test_fte_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['fte'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("fte") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['fte'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('fte')!r}."
        )

    def test_e_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['e'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("e") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['e'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('e')!r}."
        )

    def test_employee_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['employee'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("employee") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['employee'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('employee')!r}."
        )

    def test_full_time_hyphen_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['full-time'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("full-time") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['full-time'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('full-time')!r}."
        )

    def test_full_time_space_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['full time'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("full time") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['full time'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('full time')!r}."
        )

    def test_regular_maps_to_FTE(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['regular'] == 'FTE'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("regular") == "FTE", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['regular'] == 'FTE', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('regular')!r}."
        )

    # --- contractor aliases ---

    def test_contractor_maps_to_contractor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['contractor'] == 'contractor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("contractor") == "contractor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['contractor'] == 'contractor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('contractor')!r}."
        )

    def test_c_maps_to_contractor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['c'] == 'contractor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("c") == "contractor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['c'] == 'contractor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('c')!r}."
        )

    def test_contract_maps_to_contractor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['contract'] == 'contractor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("contract") == "contractor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['contract'] == 'contractor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('contract')!r}."
        )

    def test_contingent_maps_to_contractor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['contingent'] == 'contractor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("contingent") == "contractor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['contingent'] == 'contractor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('contingent')!r}."
        )

    def test_temp_maps_to_contractor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['temp'] == 'contractor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("temp") == "contractor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['temp'] == 'contractor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('temp')!r}."
        )

    # --- vendor aliases ---

    def test_vendor_maps_to_vendor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['vendor'] == 'vendor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("vendor") == "vendor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['vendor'] == 'vendor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('vendor')!r}."
        )

    def test_v_maps_to_vendor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['v'] == 'vendor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("v") == "vendor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['v'] == 'vendor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('v')!r}."
        )

    def test_external_maps_to_vendor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['external'] == 'vendor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("external") == "vendor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['external'] == 'vendor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('external')!r}."
        )

    def test_partner_maps_to_vendor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['partner'] == 'vendor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("partner") == "vendor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['partner'] == 'vendor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('partner')!r}."
        )

    def test_third_party_maps_to_vendor(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL['third-party'] == 'vendor'."""
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL.get("third-party") == "vendor", (
            f"Expected EMPLOYEE_TYPE_CANONICAL['third-party'] == 'vendor', "
            f"got {EMPLOYEE_TYPE_CANONICAL.get('third-party')!r}."
        )


# ===========================================================================
# CLASS 4 — UNIFIED_TO_LDAP reverse-map (spec §5.2 mapping table)
# ===========================================================================


class TestUnifiedToLdapContents:
    """UNIFIED_TO_LDAP must equal the reverse of the spec §5.2 mapping table.

    WHY: Spec §5.2 table defines the LDAP attribute for each unified field.
    UNIFIED_TO_LDAP is the single source of truth used by the LDAP enrichment
    adapter (§5.3) to build LDAP search filters and to reverse-map unified
    correlation fields to LDAP attributes. An incorrect entry here silently
    causes the enrichment adapter to search on the wrong LDAP attribute,
    yielding zero matches and disabling enrichment for all events.
    """

    def test_unified_to_ldap_has_display_name_to_cn(self) -> None:
        """UNIFIED_TO_LDAP['display_name'] == 'cn'."""
        from app.normalization_values import UNIFIED_TO_LDAP

        assert UNIFIED_TO_LDAP.get("display_name") == "cn", (
            f"Expected UNIFIED_TO_LDAP['display_name'] == 'cn', "
            f"got {UNIFIED_TO_LDAP.get('display_name')!r}. "
            "Spec §5.2 mapping table: display_name ↔ cn."
        )

    def test_unified_to_ldap_has_primary_email_to_mail(self) -> None:
        """UNIFIED_TO_LDAP['primary_email'] == 'mail'."""
        from app.normalization_values import UNIFIED_TO_LDAP

        assert UNIFIED_TO_LDAP.get("primary_email") == "mail", (
            f"Expected UNIFIED_TO_LDAP['primary_email'] == 'mail', "
            f"got {UNIFIED_TO_LDAP.get('primary_email')!r}. "
            "Spec §5.2 mapping table: primary_email ↔ mail."
        )

    def test_unified_to_ldap_has_department_to_departmentNumber(self) -> None:
        """UNIFIED_TO_LDAP['department'] == 'departmentNumber'."""
        from app.normalization_values import UNIFIED_TO_LDAP

        assert UNIFIED_TO_LDAP.get("department") == "departmentNumber", (
            f"Expected UNIFIED_TO_LDAP['department'] == 'departmentNumber', "
            f"got {UNIFIED_TO_LDAP.get('department')!r}. "
            "Spec §5.2 mapping table: department ↔ departmentNumber."
        )

    def test_unified_to_ldap_has_employee_type_to_employeeType(self) -> None:
        """UNIFIED_TO_LDAP['employee_type'] == 'employeeType'."""
        from app.normalization_values import UNIFIED_TO_LDAP

        assert UNIFIED_TO_LDAP.get("employee_type") == "employeeType", (
            f"Expected UNIFIED_TO_LDAP['employee_type'] == 'employeeType', "
            f"got {UNIFIED_TO_LDAP.get('employee_type')!r}. "
            "Spec §5.2 mapping table: employee_type ↔ employeeType."
        )

    def test_unified_to_ldap_has_groups_to_memberOf(self) -> None:
        """UNIFIED_TO_LDAP['groups'] == 'memberOf'."""
        from app.normalization_values import UNIFIED_TO_LDAP

        assert UNIFIED_TO_LDAP.get("groups") == "memberOf", (
            f"Expected UNIFIED_TO_LDAP['groups'] == 'memberOf', "
            f"got {UNIFIED_TO_LDAP.get('groups')!r}. "
            "Spec §5.2 mapping table: groups ↔ memberOf."
        )

    def test_unified_to_ldap_has_exactly_five_keys(self) -> None:
        """UNIFIED_TO_LDAP must have exactly 5 entries (one per unified field).

        WHY: Extra entries could allow unintended unified field names to be used
        as correlation keys, bypassing the startup validation guard in §5.6. Fewer
        entries means some unified fields cannot be used as correlation keys.
        """
        from app.normalization_values import UNIFIED_TO_LDAP

        expected_keys = {
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        }
        assert set(UNIFIED_TO_LDAP.keys()) == expected_keys, (
            f"UNIFIED_TO_LDAP must have exactly these keys: {expected_keys}. "
            f"Got: {set(UNIFIED_TO_LDAP.keys())}."
        )


# ===========================================================================
# CLASS 5 — normalize_department helper
# ===========================================================================


class TestNormalizeDepartment:
    """normalize_department(value) -> (canonical_str, was_mapped: bool).

    WHY: Spec §5.2 — 'miss → (value.title(), False)'. The tuple return lets callers
    distinguish a recognized alias (was_mapped=True) from a pass-through
    (was_mapped=False). The pass-through case carries the 0.2 confidence penalty
    in §5.5 when the unmapped value wins resolution.
    """

    def test_known_alias_returns_canonical_and_true(self) -> None:
        """normalize_department('eng') == ('Engineering', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("eng")

        assert result == ("Engineering", True), (
            f"Expected ('Engineering', True) for 'eng', got {result!r}. "
            "Spec §5.2: recognized alias → (canonical, True)."
        )

    def test_known_alias_case_insensitive_upper(self) -> None:
        """normalize_department('ENGINEERING') == ('Engineering', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("ENGINEERING")

        assert result == ("Engineering", True), (
            f"Expected ('Engineering', True) for 'ENGINEERING', got {result!r}. "
            "Spec §5.2: lookups are case-insensitive."
        )

    def test_known_alias_case_insensitive_mixed(self) -> None:
        """normalize_department('Engineering') == ('Engineering', True) (mixed case)."""
        from app.normalization_values import normalize_department

        result = normalize_department("Engineering")

        assert result == ("Engineering", True), (
            f"Expected ('Engineering', True) for 'Engineering', got {result!r}."
        )

    def test_known_alias_strips_leading_trailing_whitespace(self) -> None:
        """normalize_department(' Engineering ') == ('Engineering', True) (strip)."""
        from app.normalization_values import normalize_department

        result = normalize_department(" Engineering ")

        assert result == ("Engineering", True), (
            f"Expected ('Engineering', True) for ' Engineering ' (with whitespace), "
            f"got {result!r}. Spec §5.2: strip whitespace before lookup."
        )

    def test_r_and_d_returns_engineering_true(self) -> None:
        """normalize_department('r&d') == ('Engineering', True).

        WHY: Cross-protocol equality check. LDAP sources may send 'r&d' while
        OIDC sends 'eng'. Both must normalize to 'Engineering' for unanimous
        resolution to fire instead of a priority conflict.
        """
        from app.normalization_values import normalize_department

        result = normalize_department("r&d")

        assert result == ("Engineering", True), (
            f"Expected ('Engineering', True) for 'r&d', got {result!r}. "
            "r&d must equal Engineering to enable cross-protocol unanimous resolution."
        )

    def test_hr_returns_human_resources_true(self) -> None:
        """normalize_department('hr') == ('Human Resources', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("hr")

        assert result == ("Human Resources", True), (
            f"Expected ('Human Resources', True) for 'hr', got {result!r}."
        )

    def test_it_returns_information_technology_true(self) -> None:
        """normalize_department('it') == ('Information Technology', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("it")

        assert result == ("Information Technology", True), (
            f"Expected ('Information Technology', True) for 'it', got {result!r}."
        )

    def test_unmapped_value_returns_titlecased_and_false(self) -> None:
        """normalize_department('Astrophysics') == ('Astrophysics', False).

        WHY: Spec §5.2 — 'an unrecognized value is retained, stored as-is and
        title-cased.' The False flag lets the resolution engine apply the 0.2
        penalty when this unmapped value is the winning resolved value.
        """
        from app.normalization_values import normalize_department

        result = normalize_department("Astrophysics")

        assert result == ("Astrophysics", False), (
            f"Expected ('Astrophysics', False) for unmapped 'Astrophysics', "
            f"got {result!r}. "
            "Spec §5.2: unmapped department is title-cased and retained with was_mapped=False."
        )

    def test_unmapped_value_is_titlecased(self) -> None:
        """normalize_department('astrophysics') == ('Astrophysics', False) (title-cased)."""
        from app.normalization_values import normalize_department

        result = normalize_department("astrophysics")

        assert result == ("Astrophysics", False), (
            f"Expected ('Astrophysics', False) for 'astrophysics', got {result!r}. "
            "Unmapped values are title-cased per spec §5.2."
        )

    def test_unmapped_multi_word_value_is_titlecased(self) -> None:
        """normalize_department('quantum computing') == ('Quantum Computing', False)."""
        from app.normalization_values import normalize_department

        result = normalize_department("quantum computing")

        assert result == ("Quantum Computing", False), (
            f"Expected ('Quantum Computing', False) for 'quantum computing', "
            f"got {result!r}."
        )

    def test_finance_returns_finance_true(self) -> None:
        """normalize_department('Finance') == ('Finance', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("Finance")

        assert result == ("Finance", True), (
            f"Expected ('Finance', True) for 'Finance', got {result!r}."
        )

    def test_sales_returns_sales_true(self) -> None:
        """normalize_department('sales') == ('Sales', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("sales")

        assert result == ("Sales", True), (
            f"Expected ('Sales', True) for 'sales', got {result!r}."
        )

    def test_marketing_returns_marketing_true(self) -> None:
        """normalize_department('mktg') == ('Marketing', True)."""
        from app.normalization_values import normalize_department

        result = normalize_department("mktg")

        assert result == ("Marketing", True), (
            f"Expected ('Marketing', True) for 'mktg', got {result!r}."
        )


# ===========================================================================
# CLASS 6 — normalize_employee_type helper
# ===========================================================================


class TestNormalizeEmployeeType:
    """normalize_employee_type(value) -> 'FTE' | 'contractor' | 'vendor' | None.

    WHY: Spec §5.2 — 'an unrecognized value is discarded (the field becomes None
    for that source)'. The return type is constrained to the three Literal values
    or None. A non-None return must be one of the three Literal strings or
    NormalizedAttributes validation will fail at model construction time.
    """

    def test_E_maps_to_FTE(self) -> None:
        """normalize_employee_type('E') == 'FTE' (uppercase single char from OIDC)."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("E")

        assert result == "FTE", (
            f"Expected normalize_employee_type('E') == 'FTE', got {result!r}. "
            "Spec §5.2 validation criterion: employee_type 'E' → 'FTE'."
        )

    def test_fte_lowercase_maps_to_FTE(self) -> None:
        """normalize_employee_type('fte') == 'FTE'."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("fte")

        assert result == "FTE", (
            f"Expected normalize_employee_type('fte') == 'FTE', got {result!r}."
        )

    def test_full_time_hyphen_maps_to_FTE(self) -> None:
        """normalize_employee_type('Full-Time') == 'FTE' (mixed case from SAML)."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("Full-Time")

        assert result == "FTE", (
            f"Expected normalize_employee_type('Full-Time') == 'FTE', got {result!r}. "
            "Spec §5.2 validation criterion: employee_type 'Full-Time' → 'FTE'."
        )

    def test_contractor_maps_to_contractor(self) -> None:
        """normalize_employee_type('contractor') == 'contractor'."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("contractor")

        assert result == "contractor", (
            f"Expected normalize_employee_type('contractor') == 'contractor', "
            f"got {result!r}."
        )

    def test_c_maps_to_contractor(self) -> None:
        """normalize_employee_type('c') == 'contractor'."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("c")

        assert result == "contractor", (
            f"Expected normalize_employee_type('c') == 'contractor', got {result!r}."
        )

    def test_vendor_maps_to_vendor(self) -> None:
        """normalize_employee_type('vendor') == 'vendor'."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("vendor")

        assert result == "vendor", (
            f"Expected normalize_employee_type('vendor') == 'vendor', got {result!r}."
        )

    def test_v_maps_to_vendor(self) -> None:
        """normalize_employee_type('v') == 'vendor'."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("v")

        assert result == "vendor", (
            f"Expected normalize_employee_type('v') == 'vendor', got {result!r}."
        )

    def test_unmapped_xyz_returns_none(self) -> None:
        """normalize_employee_type('XYZ') == None (unmapped is discarded).

        WHY: Spec §5.2 — 'an unrecognized value is discarded (the field becomes None
        for that source)'. It must NEVER be stored as the raw string 'XYZ' because
        'XYZ' is not one of the Literal values and would fail NormalizedAttributes
        model validation. Returning None signals to the adapter to omit this field.
        """
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("XYZ")

        assert result is None, (
            f"Expected normalize_employee_type('XYZ') == None, got {result!r}. "
            "Unmapped employee_type must be discarded (None), never stored as raw string. "
            "Spec §5.2: 'a non-Literal value would fail NormalizedAttributes validation'."
        )

    def test_unmapped_returns_none_not_raw_string(self) -> None:
        """normalize_employee_type('Consultant') == None (arbitrary unmapped string).

        WHY: The return value is stored directly in NormalizedAttributes.employee_type.
        If a non-Literal string were returned, model construction raises ValidationError.
        None is the only safe discard sentinel.
        """
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("Consultant")

        assert result is None, (
            f"Expected None for unmapped 'Consultant', got {result!r}. "
            "Non-Literal employee_type values must be discarded to None."
        )

    def test_case_insensitive_FTE_uppercase_input(self) -> None:
        """normalize_employee_type('FTE') == 'FTE' (already canonical, round-trip safe)."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("FTE")

        assert result == "FTE", (
            f"Expected normalize_employee_type('FTE') == 'FTE', got {result!r}."
        )

    def test_strips_whitespace_before_lookup(self) -> None:
        """normalize_employee_type(' fte ') == 'FTE' (strip whitespace)."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type(" fte ")

        assert result == "FTE", (
            f"Expected 'FTE' for ' fte ' (with whitespace), got {result!r}. "
            "Spec §5.2: strip whitespace before lookup."
        )

    def test_return_value_is_always_literal_or_none(self) -> None:
        """normalize_employee_type returns only 'FTE'/'contractor'/'vendor'/None.

        WHY: NormalizedAttributes.employee_type is typed as
        Literal['FTE', 'contractor', 'vendor'] | None. Any other return value
        causes a Pydantic ValidationError when the model is constructed. This is
        a security-relevant invariant: an invalid employee_type could escalate
        privileges if the authorization system treats unknown types permissively.
        """
        from app.normalization_values import normalize_employee_type

        allowed_values = {"FTE", "contractor", "vendor", None}
        test_inputs = [
            "FTE",
            "fte",
            "E",
            "e",
            "employee",
            "full-time",
            "full time",
            "regular",
            "contractor",
            "c",
            "contract",
            "contingent",
            "temp",
            "vendor",
            "v",
            "external",
            "partner",
            "third-party",
            "XYZ",
            "Consultant",
            "intern",
            "unknown_type",
        ]
        for inp in test_inputs:
            result = normalize_employee_type(inp)
            assert result in allowed_values, (
                f"normalize_employee_type({inp!r}) returned {result!r}, "
                f"which is not in the allowed set {allowed_values}. "
                "Every return value must be a Literal or None."
            )


# ===========================================================================
# CLASS 7 — Cross-protocol canonical identity (byte-identical targets)
# ===========================================================================


class TestCrossProtocolCanonicalIdentity:
    """The same logical value must produce byte-identical canonical strings
    regardless of which protocol it came from.

    WHY: Conflict resolution (§5.5) compares normalized values with ==. If OIDC
    returns 'Engineering' and LDAP returns 'engineering', they compare unequal and
    trigger a spurious priority conflict instead of a unanimous resolution. The
    canonical strings must be identical byte-for-byte so value-equal sources are
    recognized as agreeing.
    """

    def test_oidc_eng_and_ldap_r_and_d_normalize_to_same_canonical(self) -> None:
        """normalize_department('eng') == normalize_department('r&d').

        WHY: An OIDC event may have department='eng' while the LDAP directory
        entry has departmentNumber='r&d'. After normalization both must be
        'Engineering' (byte-for-byte equal) so unanimous resolution fires.
        """
        from app.normalization_values import normalize_department

        oidc_result, _ = normalize_department("eng")
        ldap_result, _ = normalize_department("r&d")

        assert oidc_result == ldap_result, (
            f"OIDC 'eng' normalizes to {oidc_result!r} but LDAP 'r&d' normalizes "
            f"to {ldap_result!r}. Both must equal 'Engineering' for cross-protocol "
            "unanimous resolution to fire."
        )

    def test_oidc_E_and_ldap_FTE_normalize_to_same_canonical(self) -> None:
        """normalize_employee_type('E') == normalize_employee_type('FTE') == 'FTE'.

        WHY: OIDC sends 'E' while LDAP sends 'FTE'. After normalization both must
        produce 'FTE' (byte-for-byte equal) for unanimous resolution to detect
        they agree. Otherwise a spurious conflict downgrades confidence.
        """
        from app.normalization_values import normalize_employee_type

        oidc_result = normalize_employee_type("E")
        ldap_result = normalize_employee_type("FTE")

        assert oidc_result == ldap_result == "FTE", (
            f"OIDC 'E' normalizes to {oidc_result!r} and LDAP 'FTE' normalizes "
            f"to {ldap_result!r}. Both must equal 'FTE'."
        )


# ===========================================================================
# CLASS 8 — normalize_department_value wrapper (adapter refactor)
# ===========================================================================


class TestNormalizeDepartmentValue:
    """normalize_department_value(value) -> str | None.

    This is a new wrapper introduced by the adapter refactor.  It delegates to
    the existing normalize_department(value) -> (str|None, bool) and returns
    ONLY the string component (the was_mapped flag is dropped).

    WHY this wrapper exists:
      FieldRule transforms are defined as Callable[..., object].  The adapters
      use a single function per field; they cannot unpack a tuple return in a
      lambda without the 'was_mapped' flag leaking into the result dict.
      normalize_department_value is the adapter-facing interface; the resolution
      layer continues to call normalize_department directly when it needs the
      confidence-penalty flag.

    Contract:
      normalize_department_value('eng')          == 'Engineering'   (canonical hit)
      normalize_department_value('astrophysics') == 'Astrophysics'  (title-case fallback)
      normalize_department_value(None)           is None            (None passthrough)
      normalize_department_value(123)            is None            (non-str → None)
      NOT a tuple — must return str | None, never (str, bool).

    """

    def test_normalize_department_value_is_importable(self) -> None:
        """from app.normalization_values import normalize_department_value must not raise.

        WHY: All three adapters import this at module level.  An ImportError here
        shuts down the service.
        """
        from app.normalization_values import normalize_department_value  # noqa: F401

    def test_canonical_hit_returns_string(self) -> None:
        """normalize_department_value('eng') == 'Engineering'.

        WHY: This is the happy path — a recognized alias maps to its canonical
        department string.  The adapter stores this string directly in the result
        dict for the NormalizationService.
        """
        from app.normalization_values import normalize_department_value

        result = normalize_department_value("eng")

        assert result == "Engineering", (
            f"normalize_department_value('eng') must return 'Engineering', got {result!r}. "
            "It delegates to normalize_department('eng') which returns ('Engineering', True) "
            "and the wrapper returns only the first element."
        )

    def test_title_case_fallback_on_unrecognized_alias(self) -> None:
        """normalize_department_value('Unknown Dept') == 'Unknown Dept' (title-cased fallback).

        WHY: normalize_department for an unrecognized str returns (value.title(), False).
        The wrapper must return the title-cased string — NOT None and NOT the tuple.
        Dropping unmapped departments to None would silently discard real department
        information from IdPs that use non-standard names.
        """
        from app.normalization_values import normalize_department_value

        result = normalize_department_value("Unknown Dept")

        assert result == "Unknown Dept", (
            f"normalize_department_value('Unknown Dept') must return 'Unknown Dept' "
            f"(title-case fallback preserved), got {result!r}. "
            "The wrapper must return the fallback string for unrecognized aliases, not None."
        )

    def test_unrecognized_lowercase_is_titlecased(self) -> None:
        """normalize_department_value('astrophysics') == 'Astrophysics'.

        WHY: Verifies title-casing is applied to the unrecognized value before return.
        """
        from app.normalization_values import normalize_department_value

        result = normalize_department_value("astrophysics")

        assert result == "Astrophysics", (
            f"normalize_department_value('astrophysics') must return 'Astrophysics', "
            f"got {result!r}."
        )

    def test_none_input_returns_none(self) -> None:
        """normalize_department_value(None) is None.

        WHY: apply_field_rules calls the transform with raw_attributes.get(key),
        which returns None when the key is absent.  The wrapper must handle None
        gracefully and return None so the department field is absent/None in the
        result dict (not a string like 'None').
        """
        from app.normalization_values import normalize_department_value

        result = normalize_department_value(None)

        assert result is None, (
            f"normalize_department_value(None) must return None, got {result!r}. "
            "A None input means the department key was absent from raw_attributes."
        )

    def test_non_str_int_returns_none(self) -> None:
        """normalize_department_value(123) is None.

        WHY: normalize_department(123) returns (None, False) per the non-str guard.
        The wrapper must propagate the None, not the tuple.
        """
        from app.normalization_values import normalize_department_value

        result = normalize_department_value(123)

        assert result is None, (
            f"normalize_department_value(123) must return None for non-str int input, "
            f"got {result!r}. "
            "Non-str inputs are guarded by normalize_department; wrapper propagates None."
        )

    def test_non_str_list_returns_none(self) -> None:
        """normalize_department_value(['eng']) is None (list is not str)."""
        from app.normalization_values import normalize_department_value

        result = normalize_department_value(["eng"])

        assert result is None, (
            f"normalize_department_value(['eng']) must return None for list input, "
            f"got {result!r}."
        )

    def test_return_value_is_never_a_tuple(self) -> None:
        """normalize_department_value must NEVER return a tuple.

        WHY: normalize_department returns (str, bool).  If the wrapper accidentally
        returns the tuple directly (e.g., by returning normalize_department(value)
        instead of normalize_department(value)[0]), the result dict entry would be
        ('Engineering', True) — a non-str value that causes NormalizedAttributes
        Pydantic validation to fail with a type error on the 'department' field.

        This is the critical correctness invariant of the wrapper.
        """
        from app.normalization_values import normalize_department_value

        test_inputs = ["eng", "astrophysics", "fin", "hr", "sales", "mktg"]
        for inp in test_inputs:
            result = normalize_department_value(inp)
            assert not isinstance(result, tuple), (
                f"normalize_department_value({inp!r}) returned a tuple {result!r}. "
                "The wrapper must return str | None, never the (str, bool) tuple from "
                "normalize_department(). "
                "Likely bug: returning normalize_department(value) directly."
            )

    def test_return_type_is_str_or_none(self) -> None:
        """normalize_department_value always returns str or None, never other types.

        WHY: NormalizedAttributes.department is typed as str | None. Any other return
        type (e.g., tuple, int) would cause Pydantic ValidationError at model
        construction time.
        """
        from app.normalization_values import normalize_department_value

        test_inputs = [
            "eng",
            "ENGINEERING",
            " Engineering ",
            "r&d",
            "fin",
            "hr",
            "it",
            "sales",
            "mktg",
            "astrophysics",
            "quantum computing",
            None,
            123,
            ["eng"],
            {"dept": "eng"},
        ]
        for inp in test_inputs:
            result = normalize_department_value(inp)
            assert result is None or isinstance(result, str), (
                f"normalize_department_value({inp!r}) must return str or None. "
                f"Got {type(result).__name__!r}: {result!r}."
            )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("eng", "Engineering"),
            ("ENGINEERING", "Engineering"),
            ("r&d", "Engineering"),
            ("fin", "Finance"),
            ("hr", "Human Resources"),
            ("it", "Information Technology"),
            ("sales", "Sales"),
            ("mktg", "Marketing"),
            ("astrophysics", "Astrophysics"),
            ("Unknown Dept", "Unknown Dept"),
            (None, None),
            (123, None),
        ],
    )
    def test_normalize_department_value_parametrized(
        self, raw: object, expected
    ) -> None:
        """Parametrized contract verification for normalize_department_value."""
        from app.normalization_values import normalize_department_value

        result = normalize_department_value(raw)

        assert result == expected, (
            f"normalize_department_value({raw!r}) expected {expected!r}, got {result!r}."
        )


# ===========================================================================
# CLASS 9 — Exact-equality guards for DEPARTMENT_CANONICAL and EMPLOYEE_TYPE_CANONICAL
# ===========================================================================


class TestDepartmentCanonicalExactEquality:
    """DEPARTMENT_CANONICAL must equal EXACTLY the dict transcribed from spec §5.2.

    WHY: The spec marks these dicts [TRANSCRIBE EXACTLY].  Any rogue added alias,
    removed alias, or changed canonical value is a security-relevant deviation —
    it could cause two protocols that should agree ('eng' vs 'r&d') to disagree,
    or a canonical value that should match one department to match a different one.

    A rogue alias fails this test immediately, prompting review of whether it was
    intentional and spec-compliant.
    """

    _EXPECTED_DEPARTMENT_CANONICAL: ClassVar[dict[str, str]] = {
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

    def test_department_canonical_exact_equality(self) -> None:
        """DEPARTMENT_CANONICAL must equal the exact spec §5.2 dict.

        WHY: Any extra or missing alias would cause cross-protocol canonical-value
        mismatches, silently flipping unanimous resolutions to priority-conflict
        resolutions with a confidence penalty.  The exact set is the spec contract.
        """
        from app.normalization_values import DEPARTMENT_CANONICAL

        assert DEPARTMENT_CANONICAL == self._EXPECTED_DEPARTMENT_CANONICAL, (
            "DEPARTMENT_CANONICAL does not match spec §5.2 [TRANSCRIBE EXACTLY]. "
            f"Extra keys: {set(DEPARTMENT_CANONICAL) - set(self._EXPECTED_DEPARTMENT_CANONICAL)}. "
            f"Missing keys: {set(self._EXPECTED_DEPARTMENT_CANONICAL) - set(DEPARTMENT_CANONICAL)}. "
            "Changed values: "
            + repr(
                {
                    k: (DEPARTMENT_CANONICAL[k], self._EXPECTED_DEPARTMENT_CANONICAL[k])
                    for k in self._EXPECTED_DEPARTMENT_CANONICAL
                    if k in DEPARTMENT_CANONICAL
                    and DEPARTMENT_CANONICAL[k] != self._EXPECTED_DEPARTMENT_CANONICAL[k]
                }
            )
        )


class TestEmployeeTypeCanonicalExactEquality:
    """EMPLOYEE_TYPE_CANONICAL must equal EXACTLY the dict transcribed from spec §5.2.

    WHY: The canonical targets are 'FTE', 'contractor', 'vendor' — these are the
    Literal values in NormalizedAttributes.employee_type.  Any rogue added alias
    mapping to an unexpected string would produce a non-Literal value that fails
    Pydantic model construction.  Any removed alias would cause a known employee type
    to be discarded to None, potentially bypassing access controls that check the field.
    """

    _EXPECTED_EMPLOYEE_TYPE_CANONICAL: ClassVar[dict[str, str]] = {
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

    def test_employee_type_canonical_exact_equality(self) -> None:
        """EMPLOYEE_TYPE_CANONICAL must equal the exact spec §5.2 dict.

        WHY: Any deviation (rogue alias, missing alias, wrong canonical target) is
        a security-relevant change — an employee type that should map to 'contractor'
        might map to 'FTE' (privilege escalation) or be discarded (access denial).
        The exact dict is the spec contract; any change requires a spec review.
        """
        from app.normalization_values import EMPLOYEE_TYPE_CANONICAL

        assert EMPLOYEE_TYPE_CANONICAL == self._EXPECTED_EMPLOYEE_TYPE_CANONICAL, (
            "EMPLOYEE_TYPE_CANONICAL does not match spec §5.2 [TRANSCRIBE EXACTLY]. "
            f"Extra keys: {set(EMPLOYEE_TYPE_CANONICAL) - set(self._EXPECTED_EMPLOYEE_TYPE_CANONICAL)}. "
            f"Missing keys: {set(self._EXPECTED_EMPLOYEE_TYPE_CANONICAL) - set(EMPLOYEE_TYPE_CANONICAL)}. "
            "Changed values: "
            + repr(
                {
                    k: (
                        EMPLOYEE_TYPE_CANONICAL[k],
                        self._EXPECTED_EMPLOYEE_TYPE_CANONICAL[k],
                    )
                    for k in self._EXPECTED_EMPLOYEE_TYPE_CANONICAL
                    if k in EMPLOYEE_TYPE_CANONICAL
                    and EMPLOYEE_TYPE_CANONICAL[k]
                    != self._EXPECTED_EMPLOYEE_TYPE_CANONICAL[k]
                }
            )
        )


# ===========================================================================
# CLASS 10 — _was_department_mapped round-trip invariant
# ===========================================================================


class TestWasDepartmentMappedRoundTrip:
    """DEPARTMENT_CANONICAL values satisfy the round-trip invariant that _was_department_mapped depends on.

    service.py:_was_department_mapped(normalized_value) works by running
    DEPARTMENT_CANONICAL.get(normalized_value.strip().lower()) and checking if the
    result equals normalized_value.  This requires every canonical VALUE in
    DEPARTMENT_CANONICAL to be present as a KEY when lowercased.

    Example: 'Engineering' is a value; 'engineering' is a key → round-trip works.
    Violation example: adding a value 'ENG' with no 'eng' key would cause
    _was_department_mapped('ENG') to return False even for a mapped canonical value.

    WHY: If this invariant is violated, the _was_department_mapped derivation in
    _build_attribute_sources silently returns was_mapped=False for a value that WAS
    a recognized canonical, incorrectly applying the -0.2 confidence penalty to
    correctly normalized department values.  This degrades confidence scoring without
    any visible error and would be very hard to diagnose.
    """

    def test_every_canonical_department_value_round_trips(self) -> None:
        """Every VALUE in DEPARTMENT_CANONICAL satisfies CANONICAL.get(value.lower()) == value.

        This asserts the property that _was_department_mapped silently depends on.
        Adding a new canonical value that violates it would corrupt confidence scoring
        for any event whose department normalizes to that value.
        """
        from app.normalization_values import DEPARTMENT_CANONICAL

        for alias_key, canonical_value in DEPARTMENT_CANONICAL.items():
            lookup_key = canonical_value.strip().lower()
            round_trip = DEPARTMENT_CANONICAL.get(lookup_key)
            assert round_trip == canonical_value, (
                f"Round-trip invariant violated: DEPARTMENT_CANONICAL[{alias_key!r}] = "
                f"{canonical_value!r}, but DEPARTMENT_CANONICAL.get({lookup_key!r}) = "
                f"{round_trip!r} != {canonical_value!r}. "
                f"The canonical value {canonical_value!r} must have its own lowercase key "
                f"({lookup_key!r}) in DEPARTMENT_CANONICAL so that "
                f"_was_department_mapped({canonical_value!r}) correctly returns True. "
                "Adding a canonical value that violates this would silently apply the "
                "-0.2 confidence penalty to correctly normalized department values, "
                "corrupting normalization_confidence scores without any visible error."
            )
