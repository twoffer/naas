"""Input type-coercion hardening for identity-normalization adapters and helpers.

Verifies that normalize_department, normalize_employee_type, and all three
adapter extract() methods handle non-string inputs (int, list, dict) without
raising, coercing to None instead.  Also verifies that groups fields filter
non-string entries to strings-only.
"""

from __future__ import annotations

from tests.services.identity_normalization.conftest import (
    inject_fake_ldap as _inject_fake_ldap,
)


# ===========================================================================
# normalize_department / normalize_employee_type — non-string inputs
# ===========================================================================


class TestNormalizeHelperNonString:
    """normalize_department and normalize_employee_type must handle non-str inputs gracefully.

    WHY: raw_attributes come from untrusted external token claims. A field that is
    normally a string may arrive as an integer, list, or dict (e.g., Azure AD
    returning ``department: 123``). Passing a non-str to `.strip().lower()` raises
    AttributeError which would crash the normalization pipeline for that login event.
    The fix: guard at the top of each helper — return (None, False) / None respectively.
    """

    def test_normalize_department_with_int_returns_none_false(self) -> None:
        """normalize_department(123) must return (None, False), not raise."""
        from app.normalization_values import normalize_department

        result = normalize_department(123)

        assert result == (None, False), (
            f"normalize_department(123) must return (None, False) for a non-str input, "
            f"got {result!r}"
        )

    def test_normalize_department_with_list_returns_none_false(self) -> None:
        """normalize_department(['x']) must return (None, False), not raise."""
        from app.normalization_values import normalize_department

        result = normalize_department(["x"])

        assert result == (None, False), (
            f"normalize_department(['x']) must return (None, False), got {result!r}"
        )

    def test_normalize_department_with_dict_returns_none_false(self) -> None:
        """normalize_department({'a': 1}) must return (None, False), not raise."""
        from app.normalization_values import normalize_department

        result = normalize_department({"a": 1})

        assert result == (None, False), (
            f"normalize_department({{'a': 1}}) must return (None, False), got {result!r}"
        )

    def test_normalize_department_str_miss_returns_title_false(self) -> None:
        """normalize_department with an unrecognized str still title-cases and returns False."""
        from app.normalization_values import normalize_department

        result = normalize_department("WidgetCorp")

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)!r}"
        assert len(result) == 2
        val, was_mapped = result
        assert was_mapped is False, (
            f"Unrecognized str must return was_mapped=False, got {was_mapped!r}"
        )
        assert isinstance(val, str), (
            f"Unrecognized str must return a str value (title-cased), got {val!r}"
        )

    def test_normalize_department_str_hit_returns_canonical_true(self) -> None:
        """normalize_department('eng') returns ('Engineering', True) — baseline regression."""
        from app.normalization_values import normalize_department

        result = normalize_department("eng")

        assert result == ("Engineering", True), (
            f"normalize_department('eng') must return ('Engineering', True), got {result!r}"
        )

    def test_normalize_employee_type_with_int_returns_none(self) -> None:
        """normalize_employee_type(42) must return None, not raise."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type(42)

        assert result is None, (
            f"normalize_employee_type(42) must return None for a non-str input, "
            f"got {result!r}"
        )

    def test_normalize_employee_type_with_list_returns_none(self) -> None:
        """normalize_employee_type(['x']) must return None, not raise."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type(["x"])

        assert result is None, (
            f"normalize_employee_type(['x']) must return None, got {result!r}"
        )

    def test_normalize_employee_type_str_hit_unchanged(self) -> None:
        """normalize_employee_type('fte') returns 'FTE' — baseline regression."""
        from app.normalization_values import normalize_employee_type

        result = normalize_employee_type("fte")

        assert result == "FTE", (
            f"normalize_employee_type('fte') must return 'FTE', got {result!r}"
        )


# ===========================================================================
# Adapter extract() — non-string department/employee_type/groups
# ===========================================================================


class TestAdapterExtractNonStringInputs:
    """All three adapter extract() methods must handle non-str field values without raising.

    WHY: The adapters call normalize_department and normalize_employee_type. Once those
    helpers guard non-str inputs, the adapters become safe too. But the groups field is
    a separate concern: if groups contains non-str items (e.g., ints), the adapter must
    filter them to strings only — non-str items must be dropped silently.

    Key names per spec §5.2 mapping:
      OIDC:  name, email, department, employee_type, groups
      SAML:  displayName, email, dept, employeeType, groups
      LDAP:  cn, mail, departmentNumber, employeeType, memberOf
    """

    def test_oidc_extract_with_nonstr_department_does_not_raise(self) -> None:
        """OidcAdapter.extract() with department=123 must not raise."""
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        result = adapter.extract(
            {
                "name": "Alice",
                "email": "alice@corp.com",
                "department": 123,
                "employee_type": "fte",
                "groups": ["admin"],
            }
        )

        assert result["department"] is None, (
            f"OIDC extract with department=123 (non-str) must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_oidc_extract_with_nonstr_employee_type_does_not_raise(self) -> None:
        """OidcAdapter.extract() with employee_type=['x'] must not raise."""
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        result = adapter.extract(
            {
                "name": "Alice",
                "email": "alice@corp.com",
                "department": "eng",
                "employee_type": ["x"],
                "groups": ["admin"],
            }
        )

        assert result["employee_type"] is None, (
            f"OIDC extract with employee_type=['x'] must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_oidc_extract_groups_filters_to_strings_only(self) -> None:
        """OidcAdapter.extract() with groups=[1, 2, 'real-group'] keeps only strings."""
        from app.adapters.oidc import OidcAdapter

        adapter = OidcAdapter()
        result = adapter.extract(
            {
                "name": "Alice",
                "email": "alice@corp.com",
                "groups": [1, 2, "real-group"],
            }
        )

        assert result["groups"] == ["real-group"], (
            f"OIDC extract groups with mixed types must keep only strings. "
            f"Expected ['real-group'], got {result['groups']!r}"
        )

    def test_saml_extract_with_nonstr_dept_does_not_raise(self) -> None:
        """SamlAdapter.extract() with dept=123 must not raise."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract(
            {
                "displayName": "Bob",
                "email": "bob@corp.com",
                "dept": 123,
                "employeeType": "fte",
                "groups": ["staff"],
            }
        )

        assert result["department"] is None, (
            f"SAML extract with dept=123 must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_saml_extract_with_nonstr_employee_type_does_not_raise(self) -> None:
        """SamlAdapter.extract() with employeeType={'code': 'fte'} must not raise."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract(
            {
                "displayName": "Bob",
                "email": "bob@corp.com",
                "dept": "eng",
                "employeeType": {"code": "fte"},
                "groups": [],
            }
        )

        assert result["employee_type"] is None, (
            f"SAML extract with employeeType=dict must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_saml_extract_groups_filters_to_strings_only(self) -> None:
        """SamlAdapter.extract() with groups=[1, 2, 'real-group'] keeps only strings."""
        from app.adapters.saml import SamlAdapter

        adapter = SamlAdapter()
        result = adapter.extract(
            {
                "displayName": "Bob",
                "email": "bob@corp.com",
                "groups": [1, 2, "real-group"],
            }
        )

        assert result["groups"] == ["real-group"], (
            f"SAML extract groups with mixed types must keep only strings. "
            f"Expected ['real-group'], got {result['groups']!r}"
        )

    def test_ldap_extract_with_nonstr_department_number_does_not_raise(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with departmentNumber=999 must not raise."""
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract(
            {
                "cn": "Charlie",
                "mail": "charlie@corp.com",
                "departmentNumber": 999,
                "employeeType": "fte",
                "memberOf": [],
            }
        )

        assert result["department"] is None, (
            f"LDAP extract with departmentNumber=999 (non-str) must produce department=None, "
            f"got {result['department']!r}"
        )

    def test_ldap_extract_with_nonstr_employee_type_does_not_raise(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with employeeType=['fte'] must not raise."""
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract(
            {
                "cn": "Charlie",
                "mail": "charlie@corp.com",
                "departmentNumber": "eng",
                "employeeType": ["fte"],
                "memberOf": [],
            }
        )

        assert result["employee_type"] is None, (
            f"LDAP extract with employeeType=['fte'] must produce employee_type=None, "
            f"got {result['employee_type']!r}"
        )

    def test_ldap_extract_member_of_filters_non_strings(self, monkeypatch) -> None:
        """LdapAdapter.extract() with memberOf=[1, 2, 'cn=engineering,...'] returns only 'engineering'.

        WHY: _reduce_dn_to_group_name calls ldap.dn.str2dn on the DN string; passing
        an int would cause AttributeError. Non-str memberOf entries must be dropped.
        The one valid DN string 'cn=engineering,ou=groups,dc=corp,dc=com' must be
        reduced to its cn value 'engineering' via str2dn.

        Previously the fake ldap.dn was a bare MagicMock so str2dn returned an empty-
        iterating MagicMock, every DN reduced to None, groups == [], and the assertion
        loop ran zero times — the test passed vacuously.  Now that the canonical fake
        provides a functional str2dn, this test asserts the actual expected output.
        """
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.extract(
            {
                "cn": "Charlie",
                "mail": "charlie@corp.com",
                "departmentNumber": None,
                "employeeType": None,
                "memberOf": [1, 2, "cn=engineering,ou=groups,dc=corp,dc=com"],
            }
        )

        # Non-str entries (1, 2) must be dropped.
        for g in result["groups"]:
            assert isinstance(g, str), (
                f"All entries in groups must be strings; got {g!r} ({type(g).__name__})"
            )

        # The valid DN must resolve to its cn component value 'engineering'.
        assert result["groups"] == ["engineering"], (
            f"The valid DN 'cn=engineering,...' must reduce to group name 'engineering'. "
            f"Got groups={result['groups']!r}. "
            "Check that non-str items are filtered AND that str2dn parses the valid DN."
        )


# ===========================================================================
# Adapter extract() — non-string display_name / primary_email
# ===========================================================================


class TestAdapterExtractNonStringNameEmail:
    """All three adapter extract() methods must return None for non-str name/email fields.

    WHY (security gap): The existing adapters return whatever the dict holds — including
    non-str values such as an integer or a nested dict. A non-str primary_email
    propagates into NormalizedAttributes and causes downstream Pydantic ValidationError
    when model_validate() is called on the stored JSONB payload.

    The fix: at the top of each extract() method, check each scalar field with
    isinstance(v, str); if not a str, substitute None.
    """

    # --- OIDC ---

    def test_oidc_extract_with_nonstr_name_returns_display_name_none(self) -> None:
        """OidcAdapter.extract() with name=42 must return display_name=None, not 42."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract(
            {
                "name": 42,
                "email": "alice@corp.com",
                "groups": [],
            }
        )

        assert result["display_name"] is None, (
            f"OidcAdapter.extract() with name=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str scalar in name must be coerced to None, not passed through."
        )

    def test_oidc_extract_with_nonstr_email_returns_primary_email_none(self) -> None:
        """OidcAdapter.extract() with email={\"x\":1} must return primary_email=None."""
        from app.adapters.oidc import OidcAdapter

        result = OidcAdapter().extract(
            {
                "name": "Alice",
                "email": {"x": 1},
                "groups": [],
            }
        )

        assert result["primary_email"] is None, (
            f'OidcAdapter.extract() with email={{"x":1}} (non-str) must return '
            f"primary_email=None, got {result['primary_email']!r}. "
            "A dict in the email field must be coerced to None."
        )

    # --- SAML ---

    def test_saml_extract_with_nonstr_display_name_returns_display_name_none(
        self,
    ) -> None:
        """SamlAdapter.extract() with displayName=42 must return display_name=None."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract(
            {
                "displayName": 42,
                "email": "bob@corp.com",
                "groups": [],
            }
        )

        assert result["display_name"] is None, (
            f"SamlAdapter.extract() with displayName=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str displayName must be coerced to None."
        )

    def test_saml_extract_with_nonstr_email_returns_primary_email_none(self) -> None:
        """SamlAdapter.extract() with email=[\"a@b.com\"] must return primary_email=None."""
        from app.adapters.saml import SamlAdapter

        result = SamlAdapter().extract(
            {
                "displayName": "Bob",
                "email": ["a@b.com"],
                "groups": [],
            }
        )

        assert result["primary_email"] is None, (
            f'SamlAdapter.extract() with email=["a@b.com"] (non-str) must return '
            f"primary_email=None, got {result['primary_email']!r}. "
            "A list in the email field must be coerced to None."
        )

    # --- LDAP ---

    def test_ldap_extract_with_nonstr_cn_returns_display_name_none(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with cn=42 must return display_name=None."""
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract(
            {
                "cn": 42,
                "mail": "charlie@corp.com",
                "departmentNumber": None,
                "employeeType": None,
                "memberOf": [],
            }
        )

        assert result["display_name"] is None, (
            f"LdapAdapter.extract() with cn=42 (non-str) must return "
            f"display_name=None, got {result['display_name']!r}. "
            "Non-str cn must be coerced to None."
        )

    def test_ldap_extract_with_nonstr_mail_returns_primary_email_none(
        self, monkeypatch
    ) -> None:
        """LdapAdapter.extract() with mail={\"x\":1} must return primary_email=None."""
        _inject_fake_ldap(monkeypatch)
        from app.adapters.ldap import LdapAdapter

        result = LdapAdapter().extract(
            {
                "cn": "Charlie",
                "mail": {"x": 1},
                "departmentNumber": None,
                "employeeType": None,
                "memberOf": [],
            }
        )

        assert result["primary_email"] is None, (
            f'LdapAdapter.extract() with mail={{"x":1}} (non-str) must return '
            f"primary_email=None, got {result['primary_email']!r}. "
            "A dict in the mail field must be coerced to None."
        )
