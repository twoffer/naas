# Component: NAAS Spec 2 — Chunk 2: adapters/oidc.py (OidcAdapter)
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/app/adapters/__init__.py
#   services/identity-normalization/app/adapters/oidc.py
#
# What these tests validate:
#   - OidcAdapter is importable from app.adapters.oidc
#   - OidcAdapter satisfies the ProtocolAdapter Protocol (has extract method)
#   - Field mapping: name→display_name, email→primary_email,
#                    department→department, employee_type→employee_type, groups→groups
#   - Value normalization applied: 'eng'→'Engineering', 'E'→'FTE', etc.
#   - Full-payload round-trip per spec §6 validation criterion 1
#   - Missing keys handled gracefully (no KeyError; absent field → None/absent)
#   - groups defaults to [] when key absent
#   - Unmapped employee_type → None (field omitted/None on result)
#   - Unmapped department → retained, title-cased (was_mapped=False handled silently)
#
# WHY OidcAdapter matters:
#   OIDC is the default protocol for modern SSO flows. The adapter is the first
#   stage in the normalization pipeline for OIDC events. Incorrect mappings
#   (e.g., storing 'name' as 'display_name' but mapping the wrong key) cause
#   every OIDC login to produce incorrect unified attributes silently, which then
#   propagate through risk scoring and dashboard display.
#
# TDD state:
#   app/adapters/ package and oidc.py do NOT exist yet.
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

        assert callable(adapter.extract), (
            "OidcAdapter().extract must be callable."
        )

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
        ("people ops", "Human Resources"),
        ("it", "Information Technology"),
        ("information technology", "Information Technology"),
        ("infra", "Information Technology"),
        ("sales", "Sales"),
        ("revenue", "Sales"),
        ("mktg", "Marketing"),
        ("marketing", "Marketing"),
    ])
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

    @pytest.mark.parametrize("raw_et,expected_et", [
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
    ])
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
