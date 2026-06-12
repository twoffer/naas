# Verifies infrastructure/openldap/bootstrap.ldif structure and user data.
#
# Checks: file existence, no base-DN entry, required OU entries, OU-before-user
# ordering, exactly 5 user entries with correct uid set, per-user required attributes
# (objectClass, mail, uid, userPassword, departmentNumber, employeeType),
# employeeType coverage (FTE/contractor/vendor), and cross-protocol email correlation
# with Keycloak users. Optional deep-parse test using python-ldap if available.
# stdlib
import re

# third-party
import pytest

from tests.helpers import REPO_ROOT
from tests.infrastructure.ldif_helpers import load_ldif_lines as _ldif_load
from tests.infrastructure.ldif_helpers import parse_ldif_blocks as _ldif_parse

LDIF_FILE = REPO_ROOT / "infrastructure" / "openldap" / "bootstrap.ldif"


# ---------------------------------------------------------------------------
# Shared helpers — delegated to tests/infrastructure/ldif_helpers.py
# ---------------------------------------------------------------------------


def _load_ldif_lines() -> list[str]:
    """Return every line from the LDIF file, with newlines stripped."""
    return _ldif_load(LDIF_FILE)


# ---------------------------------------------------------------------------
# Keycloak realm — file existence and basic JSON validity
# ---------------------------------------------------------------------------


class TestLdifFileExists:
    """Tests that the LDIF file exists at the expected path."""

    def test_ldif_file_exists(self):
        """The bootstrap LDIF must exist at infrastructure/openldap/bootstrap.ldif.

        osixia/openldap mounts this path in docker-compose.yml. If the file is
        absent, the container starts with no custom users or OUs.
        """
        assert LDIF_FILE.exists(), (
            f"OpenLDAP bootstrap LDIF not found at {LDIF_FILE}. "
            "Implementer must create infrastructure/openldap/bootstrap.ldif."
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — structural safety (no base DN)
# ---------------------------------------------------------------------------


class TestLdifNoBadBaseDn:
    """Tests that the LDIF does NOT include the base DC entry.

    This is the #1 LDIF hazard for osixia/openldap: the image auto-creates
    dc=corp,dc=com from LDAP_DOMAIN. Including it in the bootstrap LDIF causes
    an 'Already exists' LDAP error (code 68) which causes osixia/openldap to
    skip all subsequent entries in the file silently.
    """

    def test_no_base_dn_entry(self):
        """LDIF must NOT contain 'dn: dc=corp,dc=com' (case-insensitive).

        Pattern: a line that is 'dn:' followed by optional whitespace and
        'dc=corp,dc=com' (with optional trailing whitespace or end of line).
        Space normalisation is applied to handle 'dn:  dc=corp,dc=com'.
        """
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        lines = _load_ldif_lines()
        # Match 'dn:' + optional spaces + 'dc=corp,dc=com', case-insensitive
        pattern = re.compile(r"^\s*dn\s*:\s*dc=corp,dc=com\s*$", re.IGNORECASE)
        matching = [ln for ln in lines if pattern.match(ln)]
        assert matching == [], (
            f"LDIF must NOT include 'dn: dc=corp,dc=com' — osixia/openldap auto-creates "
            f"this entry and a duplicate causes it to silently skip the rest of the file. "
            f"Found {len(matching)} matching line(s): {matching!r}"
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — required OU entries
# ---------------------------------------------------------------------------


class TestLdifOrganizationalUnits:
    """Tests that both required OU entries are present."""

    @pytest.mark.parametrize(
        "expected_dn",
        [
            "dn: ou=users,dc=corp,dc=com",
            "dn: ou=groups,dc=corp,dc=com",
        ],
    )
    def test_ou_dn_entry_present(self, expected_dn):
        """LDIF must contain the specified OU dn: line.

        Both OUs must exist before user and group entries can be added under them.
        Missing OUs cause child entry insertions to fail with 'No such object'.
        The check is exact-match on a trimmed line (no partial-match false positives).
        """
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        lines = _load_ldif_lines()
        stripped_lines = [ln.strip() for ln in lines]
        assert expected_dn in stripped_lines, (
            f"Expected to find '{expected_dn}' in LDIF but it was not found. "
            f"This OU entry is required for child entries to be created."
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — ordering: OUs before users
# ---------------------------------------------------------------------------


class TestLdifOrdering:
    """Tests that parent (OU) entries appear before child (user) entries.

    LDIF is processed strictly top-to-bottom. If a user entry appears before
    its parent OU, the server returns 'No such object' (code 32) and the user
    is not created. This is an easy mistake when editing bootstrap files.
    """

    def test_ou_users_before_first_user_entry(self):
        """dn: ou=users,dc=corp,dc=com must appear before any uid=...,ou=users entry."""
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        lines = _load_ldif_lines()

        ou_users_dn = "dn: ou=users,dc=corp,dc=com"
        user_dn_pattern = re.compile(
            r"^\s*dn\s*:\s*uid=[^,]+,ou=users,dc=corp,dc=com\s*$", re.IGNORECASE
        )

        ou_users_line = next(
            (i for i, ln in enumerate(lines) if ln.strip() == ou_users_dn), None
        )
        first_user_line = next(
            (i for i, ln in enumerate(lines) if user_dn_pattern.match(ln)), None
        )

        assert ou_users_line is not None, f"'{ou_users_dn}' not found in LDIF"
        assert first_user_line is not None, (
            "No user DN entries (uid=...,ou=users,dc=corp,dc=com) found in LDIF"
        )
        assert ou_users_line < first_user_line, (
            f"'{ou_users_dn}' appears at line {ou_users_line} but first user entry "
            f"appears at line {first_user_line}. OUs must precede their children."
        )

    def test_ou_groups_before_first_user_entry(self):
        """dn: ou=groups,dc=corp,dc=com must appear before any uid=...,ou=users entry.

        Both OUs should be declared together at the top before any user entries,
        per the ordering convention in spec §5.3.
        """
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        lines = _load_ldif_lines()

        ou_groups_dn = "dn: ou=groups,dc=corp,dc=com"
        user_dn_pattern = re.compile(
            r"^\s*dn\s*:\s*uid=[^,]+,ou=users,dc=corp,dc=com\s*$", re.IGNORECASE
        )

        ou_groups_line = next(
            (i for i, ln in enumerate(lines) if ln.strip() == ou_groups_dn), None
        )
        first_user_line = next(
            (i for i, ln in enumerate(lines) if user_dn_pattern.match(ln)), None
        )

        assert ou_groups_line is not None, f"'{ou_groups_dn}' not found in LDIF"
        assert first_user_line is not None, "No user DN entries found in LDIF"
        assert ou_groups_line < first_user_line, (
            f"'{ou_groups_dn}' appears at line {ou_groups_line} but first user entry "
            f"appears at line {first_user_line}. OUs must precede their children."
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — user entries: count and uid set
# ---------------------------------------------------------------------------


def _extract_user_dns(lines: list[str]) -> list[str]:
    """Return all 'dn: uid=<x>,ou=users,dc=corp,dc=com' values from the LDIF lines."""
    pattern = re.compile(
        r"^\s*dn\s*:\s*(uid=[^,]+,ou=users,dc=corp,dc=com)\s*$", re.IGNORECASE
    )
    return [m.group(1) for ln in lines if (m := pattern.match(ln))]


def _extract_uid_from_dn(dn: str) -> str:
    """Extract the uid value from a DN like 'uid=alice,ou=users,dc=corp,dc=com'."""
    m = re.match(r"uid=([^,]+),", dn, re.IGNORECASE)
    return m.group(1) if m else dn


class TestLdifUserEntries:
    """Tests for the 5 inetOrgPerson user entries."""

    @pytest.fixture
    def lines(self) -> list[str]:
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        return _load_ldif_lines()

    @pytest.fixture
    def user_dns(self, lines) -> list[str]:
        return _extract_user_dns(lines)

    def test_exactly_five_user_entries(self, user_dns):
        """LDIF must contain exactly 5 uid=...,ou=users,dc=corp,dc=com dn: lines.

        Spec §5.3 specifies 5 users (alice/bob/charlie/diana/eve) to demonstrate
        varied employeeType values. Extra or missing entries break the normalization
        test matrix.
        """
        uids = [_extract_uid_from_dn(dn) for dn in user_dns]
        assert len(user_dns) == 5, (
            f"Expected exactly 5 user dn: entries, got {len(user_dns)}: {uids!r}"
        )

    def test_user_uid_set_is_correct(self, user_dns):
        """The uid values across all user entries must equal {alice, bob, charlie, diana, eve}.

        Exact uid set validates both count and identity. An incorrect set (e.g.
        {alice, bob, charlie, david, eve}) would pass the count test but break
        correlation logic that references specific usernames.
        """
        uids = {_extract_uid_from_dn(dn) for dn in user_dns}
        expected = {"alice", "bob", "charlie", "diana", "eve"}
        assert uids == expected, f"Expected uid set={expected!r}, got {uids!r}"


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — per-user required attributes
# ---------------------------------------------------------------------------


def _parse_ldif_blocks(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """Parse LDIF lines into blocks keyed by dn value (RFC-2849 correct).

    Delegates to the shared implementation in tests/infrastructure/ldif_helpers.py
    which handles blank lines, comments, and RFC-2849 continuation lines.
    """
    return _ldif_parse(lines)


class TestLdifUserAttributes:
    """Tests that each user entry contains all required LDIF attributes."""

    @pytest.fixture
    def blocks(self) -> dict[str, dict[str, list[str]]]:
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        return _parse_ldif_blocks(_load_ldif_lines())

    def _user_block(self, blocks: dict, uid: str) -> dict[str, list[str]]:
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in blocks, (
            f"No LDIF block found for dn: {key}. Available DNs: {list(blocks.keys())!r}"
        )
        return blocks[key]

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_objectclass_inetorgperson(self, blocks, uid):
        """Each user entry must declare objectClass: inetOrgPerson.

        inetOrgPerson provides the schema for mail, uid, cn, sn attributes used
        by the identity normalization service. Without it, LDAP will reject the
        entry or the attribute lookups will return no results.
        """
        block = self._user_block(blocks, uid)
        objectclasses = [oc.lower() for oc in block.get("objectclass", [])]
        assert "inetorgperson" in objectclasses, (
            f"User {uid!r}: expected objectClass: inetOrgPerson, "
            f"got objectClass={block.get('objectclass', [])!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_mail_attribute(self, blocks, uid):
        """Each user entry must have a mail: attribute.

        The identity normalization service correlates OIDC/SAML events with LDAP
        entries via primary_email → mail. A missing mail attribute causes
        cross-protocol enrichment to fail for that user.
        """
        block = self._user_block(blocks, uid)
        assert "mail" in block and block["mail"], (
            f"User {uid!r}: missing or empty 'mail' attribute"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_uid_attribute(self, blocks, uid):
        """Each user entry must have a uid: attribute matching its DN uid value.

        The uid attribute is the RDN value. It should be present as an explicit
        attribute as required by inetOrgPerson schema.
        """
        block = self._user_block(blocks, uid)
        assert "uid" in block and block["uid"], (
            f"User {uid!r}: missing or empty 'uid' attribute"
        )
        assert uid in block["uid"], (
            f"User {uid!r}: uid attribute value {block['uid']!r} does not contain {uid!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_userpassword(self, blocks, uid):
        """Each user entry must have a userPassword: attribute.

        Required for LDAP BIND authentication. Without it, ldap_bind() attempts
        for this user will fail with 'Invalid credentials'.
        """
        block = self._user_block(blocks, uid)
        assert "userpassword" in block and block["userpassword"], (
            f"User {uid!r}: missing or empty 'userPassword' attribute"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_password_is_password123(self, blocks, uid):
        """Each user's userPassword value must be 'password123'.

        Consistent with Keycloak users and all integration test documentation.
        """
        block = self._user_block(blocks, uid)
        passwords = block.get("userpassword", [])
        assert "password123" in passwords, (
            f"User {uid!r}: expected userPassword='password123', got {passwords!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_departmentnumber(self, blocks, uid):
        """Each user entry must have a departmentNumber: attribute.

        departmentNumber feeds into the normalization layer's unified attributes
        for access-control policy evaluation. Missing values degrade policy accuracy.
        """
        block = self._user_block(blocks, uid)
        assert "departmentnumber" in block and block["departmentnumber"], (
            f"User {uid!r}: missing or empty 'departmentNumber' attribute"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_employeetype(self, blocks, uid):
        """Each user entry must have an employeeType: attribute.

        employeeType is a key discriminator in the normalization layer — it affects
        risk scoring and policy conditions. Missing values default to unknown,
        which triggers a confidence penalty and degrades risk signal quality.
        """
        block = self._user_block(blocks, uid)
        assert "employeetype" in block and block["employeetype"], (
            f"User {uid!r}: missing or empty 'employeeType' attribute"
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — employeeType coverage
# ---------------------------------------------------------------------------


class TestLdifEmployeeTypeCoverage:
    """Tests that the full set of employeeType values covers FTE, contractor, vendor.

    Spec §5.3 intentionally uses 5 users to demonstrate variety.  Coverage of all
    three types is required to exercise the normalization layer's type-handling paths.
    """

    @pytest.fixture
    def blocks(self) -> dict[str, dict[str, list[str]]]:
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        return _parse_ldif_blocks(_load_ldif_lines())

    def test_employee_type_set_covers_fte_contractor_vendor(self, blocks):
        """The set of all employeeType values across all 5 users must include
        FTE, contractor, and vendor.

        Per spec §5.3: alice=FTE, bob=FTE, charlie=contractor, diana=vendor,
        eve=contractor. The test requires coverage (not exact values) to remain
        robust if spec adds additional types in future.
        """
        all_employee_types: set[str] = set()
        user_dn_pattern = re.compile(
            r"uid=[^,]+,ou=users,dc=corp,dc=com", re.IGNORECASE
        )
        for dn, block in blocks.items():
            if user_dn_pattern.search(dn):
                for et in block.get("employeetype", []):
                    all_employee_types.add(et)

        required = {"FTE", "contractor", "vendor"}
        missing = required - all_employee_types
        assert not missing, (
            f"employeeType coverage missing: {missing!r}. "
            f"Found types: {all_employee_types!r}. "
            "All three types (FTE, contractor, vendor) must appear across the 5 users."
        )

    @pytest.mark.parametrize(
        "uid,expected_type",
        [
            ("alice", "FTE"),
            ("bob", "FTE"),
            ("charlie", "contractor"),
            ("diana", "vendor"),
            ("eve", "contractor"),
        ],
    )
    def test_specific_user_employee_type(self, blocks, uid, expected_type):
        """Each user's employeeType must match the value in spec §5.3.

        Exact per-user values matter for regression testing: if the implementer
        accidentally sets alice=contractor, the normalization cross-protocol tests
        would still see 'some FTE' but alice's attribute resolution would be wrong.
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in blocks, f"No LDIF block for {key}"
        block = blocks[key]
        actual_types = block.get("employeetype", [])
        assert expected_type in actual_types, (
            f"User {uid!r}: expected employeeType={expected_type!r}, "
            f"got employeeType={actual_types!r}"
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — cross-protocol correlation: shared emails
# ---------------------------------------------------------------------------


class TestLdifCrossProtocolCorrelation:
    """Tests that alice/bob/charlie have the same emails in LDAP as in Keycloak.

    The identity normalization service's LDAP enrichment path correlates OIDC
    events to LDAP entries by matching the OIDC 'email' claim against the LDAP
    'mail' attribute (default correlation key: primary_email → mail).  If the
    emails differ between Keycloak and LDAP, enrichment silently returns no match
    and cross-protocol attributes are missing from normalized identities.
    """

    @pytest.fixture
    def blocks(self) -> dict[str, dict[str, list[str]]]:
        assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"
        return _parse_ldif_blocks(_load_ldif_lines())

    @pytest.mark.parametrize(
        "uid,expected_email",
        [
            ("alice", "alice@corp.com"),
            ("bob", "bob@corp.com"),
            ("charlie", "charlie@corp.com"),
        ],
    )
    def test_shared_user_email_matches_keycloak(self, blocks, uid, expected_email):
        """alice/bob/charlie must have the same email in LDAP as in Keycloak.

        This test verifies the cross-protocol correlation contract. The email is
        the bridge between OIDC tokens (email claim) and LDAP records (mail attr).
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in blocks, (
            f"No LDIF block for {key}. Available DNs: {list(blocks.keys())!r}"
        )
        block = blocks[key]
        mail_values = block.get("mail", [])
        assert expected_email in mail_values, (
            f"User {uid!r}: expected mail={expected_email!r} in LDAP, "
            f"got mail={mail_values!r}. This breaks cross-protocol correlation."
        )

    @pytest.mark.parametrize(
        "uid,expected_email",
        [
            ("diana", "diana@corp.com"),
            ("eve", "eve@partner.com"),
        ],
    )
    def test_ldap_only_user_email(self, blocks, uid, expected_email):
        """diana and eve (LDAP-only users) must have the emails specified in spec §5.3.

        These users do not appear in Keycloak. Their presence tests the normalization
        layer's handling of LDAP-sourced identities without OIDC counterparts.
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in blocks, (
            f"No LDIF block for {key}. Available DNs: {list(blocks.keys())!r}"
        )
        block = blocks[key]
        mail_values = block.get("mail", [])
        assert expected_email in mail_values, (
            f"User {uid!r}: expected mail={expected_email!r}, got mail={mail_values!r}"
        )


# ---------------------------------------------------------------------------
# Optional: deep LDIF parse via python-ldap (skipped if not installed)
# ---------------------------------------------------------------------------


def test_ldif_deep_parse_via_python_ldap_if_available():
    """Optional: if the 'ldif' package is available, use it to deep-parse the LDIF.

    This test is intentionally skipped when python-ldap / ldif is not installed
    (which is the expected case per the task spec). It serves as a supplementary
    check if the dev environment adds python-ldap in future.

    The structural checks in the other test classes are always unconditional and
    do NOT depend on this test passing.
    """
    ldif_mod = pytest.importorskip(
        "ldif", reason="python-ldap/ldif not installed — skip deep parse"
    )
    assert LDIF_FILE.exists(), f"File missing: {LDIF_FILE}"

    import io

    content = LDIF_FILE.read_text(encoding="utf-8")
    # Filter comment lines (ldif parser may choke on them depending on version)
    non_comment_lines = [ln for ln in content.splitlines() if not ln.startswith("#")]
    clean_content = "\n".join(non_comment_lines) + "\n"

    parser = ldif_mod.LDIFRecordList(io.BytesIO(clean_content.encode("utf-8")))
    parser.parse()
    records = parser.all_records
    assert len(records) >= 7, (
        f"Expected at least 7 LDIF records (2 OUs + 5 users), got {len(records)}"
    )
