"""OidcAdapter: extract() attribute mapping, field normalization, and protocol label."""

# third-party
import pytest


# ===========================================================================
# CLASS 1 — Import
# ===========================================================================


class TestOidcAdapterImport:
    """OidcAdapter must be importable from app.adapters.oidc."""

    def test_adapters_package_is_importable(self) -> None:
        """from app.adapters import ... must not raise.

        WHY: app/adapters/__init__.py must exist for the package to be importable.
        Without it, all adapter imports raise ModuleNotFoundError, preventing the
        composition root from wiring adapters into NormalizationService.
        """
        import app.adapters  # noqa: F401

    def test_oidc_adapter_is_importable(self) -> None:
        """from app.adapters.oidc import OidcAdapter must not raise."""
        from app.adapters.oidc import OidcAdapter  # noqa: F401

    def test_oidc_adapter_is_exposed_on_adapters_package(self) -> None:
        """OidcAdapter should be importable from app.adapters directly.

        WHY: The composition root (main.py) and service.py import adapters at
        the package level. If OidcAdapter is not re-exported from the package
        __init__, the wiring code must change its import path.
        Note: this test checks availability via app.adapters.oidc as a minimum
        — __init__ re-export is preferred but not strictly required.
        """
        from app.adapters import oidc as oidc_mod

        assert hasattr(oidc_mod, "OidcAdapter"), (
            "app.adapters.oidc must define OidcAdapter."
        )


# ===========================================================================
# CLASS 2 — Protocol conformance
# ===========================================================================


class TestOidcAdapterProtocolConformance:
    """OidcAdapter must satisfy the ProtocolAdapter port interface.

    WHY: The NormalizationService is typed to accept ProtocolAdapter instances.
    If OidcAdapter is missing the extract() method, the service raises AttributeError
    on the first OIDC event and that event goes unprocessed (and unACKed, causing
    infinite redelivery).
    """

    def test_oidc_adapter_has_extract_method(self) -> None:
        """OidcAdapter must define an extract method."""
        from app.adapters.oidc import OidcAdapter

        assert hasattr(OidcAdapter, "extract"), (
            "OidcAdapter must define 'extract'. "
            "Spec §5.2: adapters must implement the ProtocolAdapter port."
        )

    def test_oidc_adapter_extract_is_callable(self) -> None:
        """OidcAdapter().extract must be callable."""
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()

        assert callable(adapter.extract), "OidcAdapter().extract must be callable."

    def test_oidc_adapter_extract_accepts_dict(self) -> None:
        """OidcAdapter().extract({}) must not raise TypeError.

        WHY: extract() must accept a dict (the raw_attributes payload).
        If it does not, the NormalizationService's call to extract(record.raw_attributes)
        fails with TypeError for every OIDC event.
        """
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()

        # Should not raise — empty dict is valid (all keys absent)
        result = adapter.extract({})

        assert isinstance(result, dict), (
            f"OidcAdapter().extract({{}}) must return a dict, got {type(result).__name__!r}."
        )


# ===========================================================================
# CLASS 3 — Field mapping contract (spec §5.2 mapping table)
# ===========================================================================


class TestOidcAdapterFieldMapping:
    """OidcAdapter.extract must map OIDC claim names to unified field names.

    Mapping table (spec §5.2, [TRANSCRIBE EXACTLY]):
      name          → display_name
      email         → primary_email
      department    → department   (value-normalized)
      employee_type → employee_type (value-normalized)
      groups        → groups
    """

    def test_name_maps_to_display_name(self) -> None:
        """extract({'name': 'Alice Smith'}) must include display_name='Alice Smith'."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"name": "Alice Smith"})

        assert result.get("display_name") == "Alice Smith", (
            f"Expected display_name='Alice Smith', got {result.get('display_name')!r}. "
            "Spec §5.2 mapping: OIDC 'name' → unified 'display_name'."
        )

    def test_email_maps_to_primary_email(self) -> None:
        """extract({'email': 'alice@corp.com'}) must include primary_email='alice@corp.com'."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"email": "alice@corp.com"})

        assert result.get("primary_email") == "alice@corp.com", (
            f"Expected primary_email='alice@corp.com', got {result.get('primary_email')!r}. "
            "Spec §5.2 mapping: OIDC 'email' → unified 'primary_email'."
        )

    def test_department_maps_to_department_with_value_normalization(self) -> None:
        """extract({'department': 'eng'}) must include department='Engineering'."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"department": "eng"})

        assert result.get("department") == "Engineering", (
            f"Expected department='Engineering' for input 'eng', "
            f"got {result.get('department')!r}. "
            "Spec §5.2: OIDC 'department' → 'department' with value normalization."
        )

    def test_employee_type_maps_to_employee_type_with_value_normalization(self) -> None:
        """extract({'employee_type': 'E'}) must include employee_type='FTE'."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"employee_type": "E"})

        assert result.get("employee_type") == "FTE", (
            f"Expected employee_type='FTE' for input 'E', "
            f"got {result.get('employee_type')!r}. "
            "Spec §5.2 validation criterion 2: employee_type 'E' → 'FTE'."
        )

    def test_groups_maps_to_groups(self) -> None:
        """extract({'groups': ['admin']}) must include groups=['admin']."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"groups": ["admin"]})

        assert result.get("groups") == ["admin"], (
            f"Expected groups=['admin'], got {result.get('groups')!r}. "
            "Spec §5.2 mapping: OIDC 'groups' → unified 'groups'."
        )


# ===========================================================================
# CLASS 4 — Full-payload round-trip (spec §6 validation criterion 1)
# ===========================================================================


class TestOidcAdapterFullPayload:
    """Full extract round-trip must match the spec §6 criterion exactly.

    WHY: Spec §6 criterion 1 states the exact expected output for the given input.
    This is the authoritative integration test for the OIDC adapter. If this test
    passes but any individual mapping test above fails, there is an inconsistency
    in the implementation.
    """

    def test_full_payload_matches_spec_criterion_1(self) -> None:
        """OidcAdapter().extract(full_input) == expected_output per spec §6 criterion 1.

        Input (from task validation criteria):
          {"name":"Alice Smith","email":"alice@corp.com","department":"eng",
           "employee_type":"E","groups":["admin"]}

        Expected (from task validation criteria):
          {"display_name":"Alice Smith","primary_email":"alice@corp.com",
           "department":"Engineering","employee_type":"FTE","groups":["admin"]}
        """
        from app.adapters.oidc import OidcAdapter

        raw = {
            "name": "Alice Smith",
            "email": "alice@corp.com",
            "department": "eng",
            "employee_type": "E",
            "groups": ["admin"],
        }
        expected = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": ["admin"],
        }

        result = OidcAdapter().extract(raw)

        assert result == expected, (
            f"OidcAdapter().extract did not match spec §6 criterion 1.\n"
            f"Expected: {expected}\n"
            f"Got:      {result}"
        )


# ===========================================================================
# CLASS 5 — Value normalization variants through the adapter
# ===========================================================================


class TestOidcAdapterValueNormalization:
    """OidcAdapter.extract must apply value normalization for department and employee_type.

    These tests verify the normalization contract from multiple angles,
    including case variants and whitespace stripping.
    """

    @pytest.mark.parametrize(
        "raw_dept,expected_dept",
        [
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
            ("people ops", "Human Resources"),
            ("it", "Information Technology"),
            ("information technology", "Information Technology"),
            ("infra", "Information Technology"),
            ("sales", "Sales"),
            ("revenue", "Sales"),
            ("mktg", "Marketing"),
            ("marketing", "Marketing"),
        ],
    )
    def test_department_normalization_variants(
        self, raw_dept: str, expected_dept: str
    ) -> None:
        """OidcAdapter normalizes all recognized department aliases to the canonical string."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"department": raw_dept})

        assert result.get("department") == expected_dept, (
            f"OidcAdapter.extract(department={raw_dept!r}) expected {expected_dept!r}, "
            f"got {result.get('department')!r}."
        )

    @pytest.mark.parametrize(
        "raw_et,expected_et",
        [
            ("fte", "FTE"),
            ("E", "FTE"),
            ("e", "FTE"),
            ("employee", "FTE"),
            ("full-time", "FTE"),
            ("Full-Time", "FTE"),
            ("full time", "FTE"),
            ("regular", "FTE"),
            ("contractor", "contractor"),
            ("c", "contractor"),
            ("contract", "contractor"),
            ("contingent", "contractor"),
            ("temp", "contractor"),
            ("vendor", "vendor"),
            ("v", "vendor"),
            ("external", "vendor"),
            ("partner", "vendor"),
            ("third-party", "vendor"),
        ],
    )
    def test_employee_type_normalization_variants(
        self, raw_et: str, expected_et: str
    ) -> None:
        """OidcAdapter normalizes all recognized employee_type aliases to the canonical string."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"employee_type": raw_et})

        assert result.get("employee_type") == expected_et, (
            f"OidcAdapter.extract(employee_type={raw_et!r}) expected {expected_et!r}, "
            f"got {result.get('employee_type')!r}."
        )

    def test_unmapped_department_is_retained_titlecased(self) -> None:
        """OidcAdapter retains unmapped department as title-cased string.

        WHY: Spec §5.2 — unmapped department values are retained (not discarded),
        stored title-cased. The adapter must not silently drop the field.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"department": "astrophysics"})

        assert result.get("department") == "Astrophysics", (
            f"Expected department='Astrophysics' for unmapped 'astrophysics', "
            f"got {result.get('department')!r}. "
            "Spec §5.2: unmapped department is title-cased and retained."
        )

    def test_unmapped_employee_type_is_none_in_result(self) -> None:
        """OidcAdapter sets employee_type to None for unmapped values.

        WHY: Spec §5.2 — unmapped employee_type is DISCARDED. The adapter must
        set the field to None (or omit it). Storing the raw string 'XYZ' would
        cause NormalizedAttributes Pydantic validation to fail.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"employee_type": "XYZ"})

        employee_type_val = result.get("employee_type")
        assert employee_type_val is None, (
            f"Expected employee_type=None for unmapped 'XYZ', "
            f"got {employee_type_val!r}. "
            "Spec §5.2: unmapped employee_type is discarded (None), never stored."
        )


# ===========================================================================
# CLASS 6 — Missing keys / graceful absence
# ===========================================================================


class TestOidcAdapterMissingKeys:
    """OidcAdapter.extract must not raise when keys are absent from raw_attributes.

    WHY: Spec §2.3 — 'Any individual key may be absent; absence is handled by
    single-source resolution (§5.5).' The adapter must return None (or omit the
    key) for absent fields without raising KeyError. The consumer loop must never
    crash on a missing claim.
    """

    def test_missing_name_does_not_raise(self) -> None:
        """extract without 'name' key must not raise and must not include display_name."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"email": "alice@corp.com"})

        assert "display_name" not in result or result.get("display_name") is None, (
            f"Missing 'name' should yield absent/None display_name, "
            f"got display_name={result.get('display_name')!r}."
        )

    def test_missing_email_does_not_raise(self) -> None:
        """extract without 'email' key must not raise and must not include primary_email."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"name": "Alice Smith"})

        assert "primary_email" not in result or result.get("primary_email") is None, (
            f"Missing 'email' should yield absent/None primary_email, "
            f"got primary_email={result.get('primary_email')!r}."
        )

    def test_missing_department_does_not_raise(self) -> None:
        """extract without 'department' key must not raise."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"email": "alice@corp.com"})

        assert "department" not in result or result.get("department") is None, (
            f"Missing 'department' should yield absent/None, "
            f"got department={result.get('department')!r}."
        )

    def test_missing_employee_type_does_not_raise(self) -> None:
        """extract without 'employee_type' key must not raise."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"email": "alice@corp.com"})

        assert "employee_type" not in result or result.get("employee_type") is None, (
            f"Missing 'employee_type' should yield absent/None, "
            f"got employee_type={result.get('employee_type')!r}."
        )

    def test_missing_groups_defaults_to_empty_list(self) -> None:
        """extract without 'groups' key must return groups=[] (not None, not absent).

        WHY: Spec §5.2: groups is a list field. The consumer loop expects a list
        when iterating groups for merge resolution. Returning None or omitting
        the key would cause a TypeError when the resolution engine tries to iterate.
        An empty list is the safe default.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"email": "alice@corp.com"})

        groups_val = result.get("groups", "ABSENT_SENTINEL")
        assert groups_val == [], (
            f"Missing 'groups' key must produce groups=[], "
            f"got {groups_val!r}. "
            "Spec §5.2: groups defaults to [] when absent."
        )

    def test_empty_raw_attributes_does_not_raise(self) -> None:
        """extract({}) must not raise and must return groups=[]."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({})

        assert isinstance(result, dict), (
            f"extract({{}}) must return a dict, got {type(result).__name__!r}."
        )
        assert result.get("groups", "ABSENT") == [], (
            f"Empty raw_attributes must yield groups=[], "
            f"got {result.get('groups', 'ABSENT')!r}."
        )


# ===========================================================================
# CLASS 7 — Bare-string groups behavior (adapter refactor, intentional change)
# ===========================================================================


class TestOidcAdapterBareStringGroups:
    """OidcAdapter.extract must yield groups=[] when 'groups' is a bare string.

    This is the ONE intentional behavior change introduced by the adapter refactor.
    Before the refactor, `list(raw_attributes.get('groups') or [])` on a bare
    string like 'admin' would iterate the string character-by-character, yielding
    ['a', 'd', 'm', 'i', 'n'] — or with the existing [g for g in (...) if isinstance(g, str)]
    guard the same character-by-character list, since each char IS a str.

    After the refactor the OIDC adapter uses coerce_str_list which applies strict
    list-only semantics: if the value is not a list, return [].

    WHY this is a security-relevant behavior change:
      A misconfigured IdP may send groups as a bare string rather than a
      JSON array.  With character iteration, 'admin' becomes ['a','d','m','i','n']
      — none of which equals 'admin', so `"admin" in groups` evaluates False and
      admin-only policy conditions silently never fire.  With strict list-only
      semantics, the groups field is [] and the policy engine correctly denies
      access to admin-only resources pending proper IdP configuration.
      [] is the safer, more predictable failure mode.

    Behavior: a bare-string groups value must yield [] via coerce_str_list,
    never be iterated character-by-character.
    """

    def test_bare_string_groups_yields_empty_list(self) -> None:
        """extract({'groups': 'admin'}) must yield groups=[] (not ['a','d','m','i','n']).

        WHY: See class docstring.  This is the canonical bare-string test case.
        The intent is: if the IdP sends a non-list for groups, the adapter must
        return [] rather than iterating the string.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"groups": "admin"})

        groups = result.get("groups", "ABSENT_SENTINEL")
        assert groups == [], (
            f"extract({{'groups': 'admin'}}) must yield groups=[], got {groups!r}. "
            "A bare string for groups must produce [] (strict list-only semantics). "
            "The refactor replaces the old iteration logic with coerce_str_list."
        )
        # Belt-and-suspenders: explicitly confirm it is not the character list
        assert groups != list("admin"), (
            "groups must NOT be ['a','d','m','i','n'] — "
            "that would be iterating the string character-by-character."
        )

    def test_bare_string_groups_not_iterated_as_chars(self) -> None:
        """extract({'groups': 'engineering'}) must NOT produce individual chars.

        WHY: This test makes the failure mode explicit and distinct from the
        empty-list check.  A reviewer reading a failure report must see clearly
        WHAT went wrong (char-by-char iteration) not just that the result != [].
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"groups": "engineering"})

        groups = result.get("groups", [])
        for char in "engineering":
            assert char not in groups or len(groups[0]) > 1, (
                f"groups={groups!r} contains single-char entry {char!r} — "
                "this indicates character-by-character iteration of the bare string. "
                "coerce_str_list('engineering') must return [], not list('engineering')."
            )
        assert groups == [], (
            f"extract({{'groups': 'engineering'}}) must yield groups=[], got {groups!r}."
        )

    def test_list_groups_still_passes_through(self) -> None:
        """extract({'groups': ['admin', 'vpn']}) must still yield groups=['admin', 'vpn'].

        WHY: The refactor must not break the normal list-of-strings path.
        This is a regression guard ensuring the behavior change is surgical.
        """
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract({"groups": ["admin", "vpn"]})

        assert result.get("groups") == ["admin", "vpn"], (
            f"extract with list groups must still return ['admin', 'vpn'], "
            f"got {result.get('groups')!r}. "
            "The refactor must not regress normal list behavior."
        )
