# Verifies infrastructure/openldap group entries in bootstrap.ldif,
# memberof-overlay.sh existence and content, the Dockerfile COPY line
# for memberof-overlay.sh, and the SPEC_0 §5.3 mirror of those additions.
#
# Spec §5.3: four groupOfNames entries (engineering, product, security,
# vpn-users) under ou=groups,dc=corp,dc=com, each with objectClass:
# groupOfNames and member DNs of the form uid=<user>,ou=users,dc=corp,dc=com.
# All five pre-existing users remain present. Group entries appear after all
# user entries. Member DNs reference user entries defined earlier in the file.

# stdlib
import re
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery (consistent with tests/infrastructure/test_openldap_ldif.py)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find docs/architecture/ — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Could not locate repo root (looked for docs/architecture/ sentinel)")


REPO_ROOT = _find_repo_root()
LDIF_FILE = REPO_ROOT / "infrastructure" / "openldap" / "bootstrap.ldif"
OVERLAY_SCRIPT = REPO_ROOT / "infrastructure" / "openldap" / "memberof-overlay.sh"
DOCKERFILE = REPO_ROOT / "infrastructure" / "openldap" / "Dockerfile"
SPEC0_DOC = REPO_ROOT / "docs" / "architecture" / "SPEC_0_Project_Scaffold_and_Shared_Foundation.md"


# ---------------------------------------------------------------------------
# LDIF parser (reused from parent test file, local copy to keep this file
# self-contained under tests/infrastructure/openldap/)
# ---------------------------------------------------------------------------


def _load_ldif_lines() -> list[str]:
    """Return every line from the LDIF file, with newlines stripped."""
    return LDIF_FILE.read_text(encoding="utf-8").splitlines()


def _parse_ldif_blocks(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """Parse LDIF lines into blocks keyed by dn value.

    Returns a dict mapping dn_value -> {attr_name: [value, ...]}.
    Simple structural parser: handles single-valued and multi-valued
    attribute:value pairs separated by blank lines.
    """
    blocks: dict[str, dict[str, list[str]]] = {}
    current_dn: str | None = None
    current_block: dict[str, list[str]] = {}

    for line in lines:
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            if current_dn is not None:
                blocks[current_dn] = current_block
                current_dn = None
                current_block = {}
            continue

        # Continuation lines (start with a space) — skip for our purposes
        if line.startswith(" ") and current_dn is not None:
            continue

        if ":" not in stripped:
            continue

        attr, _, value = stripped.partition(":")
        attr = attr.strip().lower()
        value = value.strip()

        if attr == "dn":
            if current_dn is not None:
                blocks[current_dn] = current_block
            current_dn = value
            current_block = {"dn": [value]}
        elif current_dn is not None:
            current_block.setdefault(attr, []).append(value)

    if current_dn is not None:
        blocks[current_dn] = current_block

    return blocks


def _get_line_index(lines: list[str], dn_value: str) -> int | None:
    """Return the line index of the first 'dn: <dn_value>' line, or None."""
    pattern = re.compile(
        r"^\s*dn\s*:\s*" + re.escape(dn_value) + r"\s*$",
        re.IGNORECASE,
    )
    for i, ln in enumerate(lines):
        if pattern.match(ln):
            return i
    return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def ldif_lines() -> list[str]:
    assert LDIF_FILE.exists(), (
        f"bootstrap.ldif not found at {LDIF_FILE}. "
        "This file must exist before running these tests."
    )
    return _load_ldif_lines()


@pytest.fixture(scope="module")
def ldif_blocks(ldif_lines) -> dict[str, dict[str, list[str]]]:
    return _parse_ldif_blocks(ldif_lines)


# ---------------------------------------------------------------------------
# Class: group entries exist
# ---------------------------------------------------------------------------


class TestLdifGroupEntries:
    """Tests that bootstrap.ldif contains exactly four groupOfNames entries
    under ou=groups,dc=corp,dc=com with the correct cn values.

    Spec §5.3: engineering, product, security, vpn-users.
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    def test_exactly_four_group_dn_entries(self, ldif_lines):
        """bootstrap.ldif must contain exactly 4 cn=...,ou=groups,dc=corp,dc=com dn lines.

        The spec defines engineering, product, security, and vpn-users.
        Extra groups are not expected and would indicate scope creep.
        """
        pattern = re.compile(
            r"^\s*dn\s*:\s*cn=[^,]+,ou=groups,dc=corp,dc=com\s*$",
            re.IGNORECASE,
        )
        group_dns = [ln.strip() for ln in ldif_lines if pattern.match(ln)]
        assert len(group_dns) == 4, (
            f"Expected exactly 4 group dn: entries, got {len(group_dns)}: {group_dns!r}"
        )

    @pytest.mark.parametrize("cn", ["engineering", "product", "security", "vpn-users"])
    def test_group_dn_present(self, ldif_blocks, cn):
        """Each expected group must have a dn: cn=<cn>,ou=groups,dc=corp,dc=com entry.

        Missing groups cause LDAP memberOf queries (e.g., from the identity
        normalization service) to return empty group lists for users.
        """
        key = f"cn={cn},ou=groups,dc=corp,dc=com"
        assert key in ldif_blocks, (
            f"No LDIF block found for dn: {key}. "
            f"Available group DNs: {[k for k in ldif_blocks if 'ou=groups' in k]!r}"
        )

    @pytest.mark.parametrize("cn", ["engineering", "product", "security", "vpn-users"])
    def test_group_has_objectclass_groupofnames(self, ldif_blocks, cn):
        """Each group entry must declare objectClass: groupOfNames.

        groupOfNames requires at least one member attribute and enables the
        memberof overlay to back-link member entries. Without this objectClass
        the overlay cannot operate on the entry.
        """
        key = f"cn={cn},ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.skip(f"Group {cn!r} not yet in LDIF — covered by test_group_dn_present")
        block = ldif_blocks[key]
        objectclasses = [oc.lower() for oc in block.get("objectclass", [])]
        assert "groupofnames" in objectclasses, (
            f"Group {cn!r}: expected objectClass: groupOfNames, "
            f"got objectClass={block.get('objectclass', [])!r}"
        )

    @pytest.mark.parametrize("cn", ["engineering", "product", "security", "vpn-users"])
    def test_group_has_at_least_one_member(self, ldif_blocks, cn):
        """Each group entry must have at least one member: attribute.

        groupOfNames is STRUCTURAL and requires at least one member value.
        An empty group violates the schema and causes LDAP to reject the entry
        with 'Object class violation'.
        """
        key = f"cn={cn},ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.skip(f"Group {cn!r} not yet in LDIF")
        block = ldif_blocks[key]
        members = block.get("member", [])
        assert len(members) >= 1, (
            f"Group {cn!r}: must have at least one member: attribute, got {members!r}"
        )

    @pytest.mark.parametrize("cn", ["engineering", "product", "security", "vpn-users"])
    def test_group_member_dns_have_correct_form(self, ldif_blocks, cn):
        """All member DNs in each group must be uid=<user>,ou=users,dc=corp,dc=com.

        Malformed member DNs (e.g., missing the base DC) cause LDAP referential
        integrity errors when the refint overlay validates the member attribute.
        """
        key = f"cn={cn},ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.skip(f"Group {cn!r} not yet in LDIF")
        block = ldif_blocks[key]
        member_pattern = re.compile(
            r"^uid=[^,]+,ou=users,dc=corp,dc=com$", re.IGNORECASE
        )
        for member_dn in block.get("member", []):
            assert member_pattern.match(member_dn), (
                f"Group {cn!r}: member DN {member_dn!r} does not match "
                "expected form uid=<user>,ou=users,dc=corp,dc=com"
            )


# ---------------------------------------------------------------------------
# Class: exact members per group
# ---------------------------------------------------------------------------


class TestLdifGroupMembership:
    """Tests that each group has exactly the members specified in Spec §5.3.

    engineering: alice, diana
    product: bob
    security: charlie
    vpn-users: alice, diana
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    def _member_uids(self, ldif_blocks: dict, cn: str) -> set[str]:
        """Extract uid values from member DNs in a group block."""
        key = f"cn={cn},ou=groups,dc=corp,dc=com"
        block = ldif_blocks.get(key, {})
        uids: set[str] = set()
        uid_pattern = re.compile(r"^uid=([^,]+),", re.IGNORECASE)
        for member_dn in block.get("member", []):
            m = uid_pattern.match(member_dn)
            if m:
                uids.add(m.group(1))
        return uids

    @pytest.mark.parametrize("cn,expected_uids", [
        ("engineering", {"alice", "diana"}),
        ("product", {"bob"}),
        ("security", {"charlie"}),
        ("vpn-users", {"alice", "diana"}),
    ])
    def test_group_has_exact_member_set(self, ldif_blocks, cn, expected_uids):
        """Each group must contain exactly the uid set specified in Spec §5.3.

        Extra members would grant unintended group membership. Missing members
        would cause the identity normalization service to return incomplete
        groups for affected users, silently degrading policy evaluation.
        """
        actual_uids = self._member_uids(ldif_blocks, cn)
        assert actual_uids == expected_uids, (
            f"Group {cn!r}: expected members={expected_uids!r}, "
            f"got members={actual_uids!r}"
        )

    def test_engineering_member_alice(self, ldif_blocks):
        """cn=engineering must have uid=alice,ou=users,dc=corp,dc=com as a member.

        Alice is an Engineering FTE — she must appear in the engineering group
        for the normalization service to return 'engineering' in her groups list.
        """
        key = "cn=engineering,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'engineering' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=alice,ou=users,dc=corp,dc=com" in members, (
            f"cn=engineering: alice must be a member, got members={members!r}"
        )

    def test_engineering_member_diana(self, ldif_blocks):
        """cn=engineering must have uid=diana,ou=users,dc=corp,dc=com as a member.

        Diana is an Engineering vendor — she must appear in the engineering group.
        """
        key = "cn=engineering,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'engineering' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=diana,ou=users,dc=corp,dc=com" in members, (
            f"cn=engineering: diana must be a member, got members={members!r}"
        )

    def test_product_member_bob(self, ldif_blocks):
        """cn=product must have uid=bob,ou=users,dc=corp,dc=com as its sole member."""
        key = "cn=product,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'product' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=bob,ou=users,dc=corp,dc=com" in members, (
            f"cn=product: bob must be a member, got members={members!r}"
        )

    def test_security_member_charlie(self, ldif_blocks):
        """cn=security must have uid=charlie,ou=users,dc=corp,dc=com as its sole member."""
        key = "cn=security,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'security' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=charlie,ou=users,dc=corp,dc=com" in members, (
            f"cn=security: charlie must be a member, got members={members!r}"
        )

    def test_vpn_users_member_alice(self, ldif_blocks):
        """cn=vpn-users must have uid=alice,ou=users,dc=corp,dc=com as a member."""
        key = "cn=vpn-users,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'vpn-users' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=alice,ou=users,dc=corp,dc=com" in members, (
            f"cn=vpn-users: alice must be a member, got members={members!r}"
        )

    def test_vpn_users_member_diana(self, ldif_blocks):
        """cn=vpn-users must have uid=diana,ou=users,dc=corp,dc=com as a member."""
        key = "cn=vpn-users,ou=groups,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.fail(f"Group 'vpn-users' not found in LDIF (key={key!r})")
        members = ldif_blocks[key].get("member", [])
        assert "uid=diana,ou=users,dc=corp,dc=com" in members, (
            f"cn=vpn-users: diana must be a member, got members={members!r}"
        )


# ---------------------------------------------------------------------------
# Class: ordering — users before groups
# ---------------------------------------------------------------------------


class TestLdifGroupOrdering:
    """Tests that all group entries appear after all user entries in the LDIF.

    LDIF is processed top-to-bottom. The ou=groups OU must precede group entries.
    User entries must all precede the first group entry so that member references
    can be resolved by LDAP in a single-pass import. The refint overlay also
    validates member DNs at add-time, so the referenced entries must exist first.
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    def test_all_user_entries_precede_first_group_entry(self, ldif_lines):
        """Every uid=...,ou=users dn: line must appear before any cn=...,ou=groups dn: line.

        If a group entry precedes a user entry, LDAP cannot resolve the member DN
        at import time, causing the group entry to be rejected (or the member
        attribute to be ignored when refint is active).
        """
        user_dn_pattern = re.compile(
            r"^\s*dn\s*:\s*uid=[^,]+,ou=users,dc=corp,dc=com\s*$", re.IGNORECASE
        )
        group_dn_pattern = re.compile(
            r"^\s*dn\s*:\s*cn=[^,]+,ou=groups,dc=corp,dc=com\s*$", re.IGNORECASE
        )

        user_lines = [i for i, ln in enumerate(ldif_lines) if user_dn_pattern.match(ln)]
        group_lines = [i for i, ln in enumerate(ldif_lines) if group_dn_pattern.match(ln)]

        assert user_lines, "No user dn: entries found in LDIF"
        assert group_lines, (
            "No group dn: entries (cn=...,ou=groups,dc=corp,dc=com) found in LDIF — "
            "group entries have not been added yet"
        )

        last_user_line = max(user_lines)
        first_group_line = min(group_lines)

        assert last_user_line < first_group_line, (
            f"Last user entry is at line {last_user_line} but first group entry "
            f"is at line {first_group_line}. All user entries must precede all "
            "group entries so member DNs exist at import time."
        )

    def test_ou_groups_before_first_group_entry(self, ldif_lines):
        """dn: ou=groups,dc=corp,dc=com must appear before any cn=...,ou=groups entry.

        The OU parent must exist before children can be added. This is already
        verified for users in the parent test file; this test extends it to groups.
        """
        ou_groups_dn = "dn: ou=groups,dc=corp,dc=com"
        group_dn_pattern = re.compile(
            r"^\s*dn\s*:\s*cn=[^,]+,ou=groups,dc=corp,dc=com\s*$", re.IGNORECASE
        )

        ou_groups_line = next(
            (i for i, ln in enumerate(ldif_lines) if ln.strip() == ou_groups_dn), None
        )
        group_lines = [i for i, ln in enumerate(ldif_lines) if group_dn_pattern.match(ln)]

        assert ou_groups_line is not None, (
            f"'{ou_groups_dn}' not found in LDIF"
        )
        assert group_lines, (
            "No group dn: entries found — group entries have not been added yet"
        )

        first_group_line = min(group_lines)
        assert ou_groups_line < first_group_line, (
            f"'{ou_groups_dn}' appears at line {ou_groups_line} but first group "
            f"entry appears at line {first_group_line}. The OU must precede its children."
        )


# ---------------------------------------------------------------------------
# Class: member DNs reference user entries defined earlier in the file
# ---------------------------------------------------------------------------


class TestLdifMemberDnResolution:
    """Tests that every member DN in every group references a user entry
    defined earlier in the same LDIF file.

    Static parse — we check that:
    (a) the referenced uid exists as a dn: uid=...,ou=users,dc=corp,dc=com entry
    (b) that entry appears at an earlier line than the group entry referencing it

    This guards against copy-paste errors (wrong uid) or reordering (user
    entry moved after group entry) that would cause LDAP import failures when
    the refint overlay is active.
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    @pytest.mark.parametrize("group_cn,member_uid", [
        ("engineering", "alice"),
        ("engineering", "diana"),
        ("product", "bob"),
        ("security", "charlie"),
        ("vpn-users", "alice"),
        ("vpn-users", "diana"),
    ])
    def test_member_dn_references_earlier_user_entry(self, ldif_lines, group_cn, member_uid):
        """member DN uid=<uid>,ou=users must appear in the LDIF before the group entry.

        This enforces the ordering contract: group entries must come after all
        their referenced user entries so LDAP can resolve member attributes at
        import time (refint overlay validates these at add time).
        """
        group_dn = f"cn={group_cn},ou=groups,dc=corp,dc=com"
        user_dn = f"uid={member_uid},ou=users,dc=corp,dc=com"

        group_line = _get_line_index(ldif_lines, group_dn)
        user_line = _get_line_index(ldif_lines, user_dn)

        assert user_line is not None, (
            f"User entry 'dn: {user_dn}' not found in LDIF — "
            f"referenced by group {group_cn!r}"
        )
        assert group_line is not None, (
            f"Group entry 'dn: {group_dn}' not found in LDIF — "
            "group entries have not been added yet"
        )
        assert user_line < group_line, (
            f"User 'dn: {user_dn}' at line {user_line} must appear before "
            f"group 'dn: {group_dn}' at line {group_line}"
        )


# ---------------------------------------------------------------------------
# Class: pre-existing users unchanged
# ---------------------------------------------------------------------------


class TestLdifExistingUsersPreserved:
    """Tests that all five pre-existing user entries remain present and unmodified
    after group entries are added.

    The group entries are appended to the file — they must not cause any of the
    five user entries to be removed or their required attributes to disappear.
    This is a regression guard.
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_entry_still_present(self, ldif_blocks, uid):
        """All five users must still have dn: uid=<uid>,ou=users,dc=corp,dc=com entries.

        Adding group entries must not remove or displace user entries.
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in ldif_blocks, (
            f"User entry for {uid!r} missing from LDIF after group additions. "
            f"Available DNs: {[k for k in ldif_blocks if 'ou=users' in k]!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_still_has_objectclass_inetorgperson(self, ldif_blocks, uid):
        """Each user must still have objectClass: inetOrgPerson after group additions."""
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.skip(f"User {uid!r} not in LDIF — covered by test_user_entry_still_present")
        objectclasses = [oc.lower() for oc in ldif_blocks[key].get("objectclass", [])]
        assert "inetorgperson" in objectclasses, (
            f"User {uid!r}: objectClass: inetOrgPerson missing after group additions"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_still_has_mail(self, ldif_blocks, uid):
        """Each user must still have a mail: attribute after group additions."""
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        if key not in ldif_blocks:
            pytest.skip(f"User {uid!r} not in LDIF")
        assert "mail" in ldif_blocks[key] and ldif_blocks[key]["mail"], (
            f"User {uid!r}: mail attribute missing after group additions"
        )

    def test_total_dn_count_includes_ous_users_and_groups(self, ldif_blocks):
        """LDIF must have at least 11 blocks: 2 OUs + 5 users + 4 groups.

        This composite check catches accidental truncation of the file.
        """
        assert len(ldif_blocks) >= 11, (
            f"Expected at least 11 LDIF blocks (2 OUs + 5 users + 4 groups), "
            f"got {len(ldif_blocks)}: {list(ldif_blocks.keys())!r}"
        )


# ---------------------------------------------------------------------------
# Class: memberof-overlay.sh
# ---------------------------------------------------------------------------


class TestMemberofOverlayScript:
    """Tests that infrastructure/openldap/memberof-overlay.sh exists and
    contains a valid ldapmodify invocation targeting cn=config over ldapi:///
    referencing both the memberof and refint overlays.

    The memberof overlay provides reverse-link attributes on user entries
    (memberOf: cn=engineering,...). The refint overlay maintains referential
    integrity when members are renamed or deleted.
    """

    def test_script_file_exists(self):
        """memberof-overlay.sh must exist at infrastructure/openldap/memberof-overlay.sh.

        Without this script, the overlay is never loaded into slapd and
        LDAP memberOf queries return no results.
        """
        assert OVERLAY_SCRIPT.exists(), (
            f"memberof-overlay.sh not found at {OVERLAY_SCRIPT}. "
            "The file must be created as part of this chunk."
        )

    def test_script_has_shell_shebang(self):
        """memberof-overlay.sh must start with a shell shebang line (e.g., #!/bin/sh).

        A missing shebang causes the osixia bootstrap runner to either skip the
        script or execute it incorrectly depending on the host shell environment.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        first_line = OVERLAY_SCRIPT.read_text(encoding="utf-8").splitlines()[0]
        assert first_line.startswith("#!"), (
            f"memberof-overlay.sh first line must be a shebang (e.g., #!/bin/sh), "
            f"got: {first_line!r}"
        )
        assert "/sh" in first_line or "/bash" in first_line, (
            f"Shebang must reference sh or bash, got: {first_line!r}"
        )

    def test_script_contains_ldapmodify(self):
        """memberof-overlay.sh must invoke ldapmodify.

        ldapmodify is the LDAP tool used to apply LDIF-format configuration
        changes to the cn=config DIT (online config). Without ldapmodify, the
        overlay cannot be activated at runtime.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        content = OVERLAY_SCRIPT.read_text(encoding="utf-8")
        assert "ldapmodify" in content, (
            "memberof-overlay.sh must contain an 'ldapmodify' invocation. "
            f"Script content (first 200 chars): {content[:200]!r}"
        )

    def test_script_targets_cn_config(self):
        """The ldapmodify invocation must target cn=config.

        OpenLDAP online configuration lives in the cn=config DIT (OLC). Overlay
        configuration must be applied there — not to the main data DIT — so that
        slapd loads the overlay without requiring a restart.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        content = OVERLAY_SCRIPT.read_text(encoding="utf-8")
        assert "cn=config" in content, (
            "memberof-overlay.sh must reference 'cn=config' (OpenLDAP OLC target). "
            f"Script content (first 400 chars): {content[:400]!r}"
        )

    def test_script_uses_ldapi_socket(self):
        """The ldapmodify invocation must use ldapi:/// (Unix socket connection).

        Within the osixia/openldap container, the cn=config DIT is only
        accessible over ldapi:/// (the local Unix socket). Using ldap:// would
        require the server to be fully started and port-accessible, which is
        not guaranteed during bootstrap.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        content = OVERLAY_SCRIPT.read_text(encoding="utf-8")
        assert "ldapi:///" in content, (
            "memberof-overlay.sh must use 'ldapi:///' for the cn=config connection. "
            f"Script content (first 400 chars): {content[:400]!r}"
        )

    def test_script_references_memberof_overlay(self):
        """The script must reference the 'memberof' overlay by name.

        The memberof overlay module is 'memberof' in OpenLDAP module terminology.
        Without this reference, the overlay is never loaded and LDAP memberOf
        attributes are not populated on user entries.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        content = OVERLAY_SCRIPT.read_text(encoding="utf-8")
        assert "memberof" in content.lower(), (
            "memberof-overlay.sh must reference the 'memberof' overlay. "
            f"Script content (first 400 chars): {content[:400]!r}"
        )

    def test_script_references_refint_overlay(self):
        """The script must reference the 'refint' overlay by name.

        The refint (referential integrity) overlay ensures that when a user entry
        is deleted or renamed, all group member: attributes referencing that user
        are automatically updated. Without refint, stale member DNs accumulate.
        """
        assert OVERLAY_SCRIPT.exists(), f"Script missing: {OVERLAY_SCRIPT}"
        content = OVERLAY_SCRIPT.read_text(encoding="utf-8")
        assert "refint" in content.lower(), (
            "memberof-overlay.sh must reference the 'refint' overlay. "
            f"Script content (first 400 chars): {content[:400]!r}"
        )


# ---------------------------------------------------------------------------
# Class: Dockerfile additions for memberof-overlay.sh
# ---------------------------------------------------------------------------


class TestDockerfileMemberofCopy:
    """Tests that infrastructure/openldap/Dockerfile retains existing content
    and adds a COPY line for memberof-overlay.sh into the osixia custom-bootstrap
    directory.

    Spec §5.3: The Dockerfile copies bootstrap.ldif and memberof-overlay.sh into
    /container/service/slapd/assets/config/bootstrap/. Both files must be COPY'd
    so they are baked into the image and available at container startup.
    """

    @pytest.fixture(autouse=True)
    def _require_dockerfile(self):
        assert DOCKERFILE.exists(), f"Dockerfile not found at {DOCKERFILE}"

    @pytest.fixture(scope="class")
    def dockerfile_content(self) -> str:
        return DOCKERFILE.read_text(encoding="utf-8")

    def test_dockerfile_retains_from_osixia_openldap(self, dockerfile_content):
        """Dockerfile must retain 'FROM osixia/openldap:1.5.0'.

        The base image must not be changed — all overlay configuration depends on
        the osixia/openldap:1.5.0 bootstrap mechanism and directory layout.
        """
        assert "FROM osixia/openldap:1.5.0" in dockerfile_content, (
            "Dockerfile must retain 'FROM osixia/openldap:1.5.0'. "
            f"Dockerfile content:\n{dockerfile_content}"
        )

    def test_dockerfile_retains_bootstrap_ldif_copy(self, dockerfile_content):
        """Dockerfile must retain the COPY line for bootstrap.ldif.

        This COPY bakes the user and group entries into the image. Removing it
        would cause the OpenLDAP container to start with no users or groups.
        """
        # The existing COPY line: bootstrap.ldif → osixia custom bootstrap dir
        assert "COPY bootstrap.ldif" in dockerfile_content, (
            "Dockerfile must retain the existing 'COPY bootstrap.ldif ...' line. "
            f"Dockerfile content:\n{dockerfile_content}"
        )

    def test_dockerfile_adds_copy_for_memberof_overlay_sh(self, dockerfile_content):
        """Dockerfile must add a COPY line for memberof-overlay.sh.

        The overlay script must be copied into the osixia custom-bootstrap
        directory so it is executed automatically during container startup.
        Without this COPY, the script exists in the repo but never runs inside
        the container.
        """
        assert "COPY memberof-overlay.sh" in dockerfile_content, (
            "Dockerfile must add 'COPY memberof-overlay.sh ...' for the overlay script. "
            f"Dockerfile content:\n{dockerfile_content}"
        )

    def test_dockerfile_memberof_overlay_sh_copy_targets_bootstrap_dir(self, dockerfile_content):
        """The memberof-overlay.sh COPY must target the osixia custom-bootstrap directory.

        The osixia/openldap entrypoint executes scripts found in
        /container/service/slapd/assets/config/bootstrap/. The COPY destination
        must include this path so the script runs at startup.
        """
        # Find the COPY line for memberof-overlay.sh and check it targets the bootstrap dir
        copy_lines = [
            ln for ln in dockerfile_content.splitlines()
            if ln.strip().startswith("COPY") and "memberof-overlay.sh" in ln
        ]
        assert copy_lines, (
            "No COPY line for memberof-overlay.sh found in Dockerfile. "
            f"Dockerfile content:\n{dockerfile_content}"
        )
        # The destination must reference the osixia bootstrap assets path
        copy_line = copy_lines[0]
        assert "/container/service/slapd/assets/config/bootstrap/" in copy_line, (
            f"COPY line for memberof-overlay.sh must target "
            "'/container/service/slapd/assets/config/bootstrap/'. "
            f"Found: {copy_line!r}"
        )


# ---------------------------------------------------------------------------
# Class: SPEC_0 §5.3 doc mirror
# ---------------------------------------------------------------------------


def _extract_section_53(doc_text: str) -> str:
    """Extract the text of §5.3 from the SPEC_0 document.

    Returns everything from the '### 5.3 ' heading line up to (but not
    including) the next heading at the same or higher level ('### 5.' or '## ').
    Returns an empty string if the section is not found.
    """
    lines = doc_text.splitlines()
    section_start: int | None = None
    section_end: int | None = None

    for i, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+5\.3\b", line):
            section_start = i
        elif section_start is not None:
            # Stop at next heading of depth <= 3 that is NOT §5.3
            if re.match(r"^#{1,3}\s+", line) and not re.match(r"^#{1,3}\s+5\.3\b", line):
                section_end = i
                break

    if section_start is None:
        return ""
    if section_end is None:
        return "\n".join(lines[section_start:])
    return "\n".join(lines[section_start:section_end])


class TestSpec0Section53Mirror:
    """Tests that SPEC_0 §5.3 mirrors the four group entries from bootstrap.ldif
    and includes a paragraph describing the overlay configuration.

    The doc mirror requirement: §5.3 must be updated to show the group entries
    and explain the memberof/refint overlay so that the spec remains the
    authoritative reference for what the OpenLDAP bootstrap contains.

    Scope is limited to §5.3 — no other section should be modified.
    """

    @pytest.fixture(autouse=True)
    def _require_spec(self):
        assert SPEC0_DOC.exists(), f"SPEC_0 document not found at {SPEC0_DOC}"

    @pytest.fixture(scope="class")
    def section_53(self) -> str:
        doc_text = SPEC0_DOC.read_text(encoding="utf-8")
        text = _extract_section_53(doc_text)
        return text

    def test_section_53_exists(self, section_53):
        """SPEC_0 must contain a §5.3 heading.

        This test fails if the section heading was accidentally removed or
        the section numbering was changed.
        """
        assert section_53, (
            "Could not find §5.3 heading in SPEC_0. "
            f"Document path: {SPEC0_DOC}"
        )

    @pytest.mark.parametrize("group_cn", ["engineering", "product", "security", "vpn-users"])
    def test_section_53_contains_group_entry(self, section_53, group_cn):
        """§5.3 must include the LDIF dn: line for each group.

        The spec must mirror the four group entries in bootstrap.ldif so that
        it remains the authoritative reference for the OpenLDAP bootstrap data.
        Missing group entries mean the spec is out of sync with the implementation.
        """
        expected_dn = f"cn={group_cn},ou=groups,dc=corp,dc=com"
        assert expected_dn in section_53, (
            f"§5.3 must include 'cn={group_cn},ou=groups,dc=corp,dc=com' "
            f"to mirror bootstrap.ldif. Section content (first 800 chars):\n"
            f"{section_53[:800]!r}"
        )

    def test_section_53_contains_groupofnames_objectclass(self, section_53):
        """§5.3 must show objectClass: groupOfNames in the group LDIF snippet.

        The spec's code block should reproduce enough of each group entry for
        a reader to understand the schema. objectClass is the most critical line.
        """
        assert "groupOfNames" in section_53 or "groupofnames" in section_53.lower(), (
            "§5.3 must include 'objectClass: groupOfNames' in the LDIF example. "
            f"Section content (first 800 chars):\n{section_53[:800]!r}"
        )

    def test_section_53_contains_overlay_description(self, section_53):
        """§5.3 must contain a paragraph describing the overlay configuration.

        The spec must explain the memberof and refint overlays so developers
        understand why the Dockerfile and bootstrap include overlay configuration.
        A one-line mention is sufficient; absence means the spec is incomplete.
        """
        # Check for overlay-related terminology in the section
        overlay_terms = ["memberof", "overlay", "refint"]
        found = [term for term in overlay_terms if term in section_53.lower()]
        assert len(found) >= 2, (
            f"§5.3 must describe the overlay configuration (memberof/refint). "
            f"Found overlay terms: {found!r}. "
            f"Section content (first 800 chars):\n{section_53[:800]!r}"
        )

    def test_section_53_contains_member_dn_for_alice(self, section_53):
        """§5.3 must include a member DN example containing alice.

        The member DN format uid=alice,ou=users,dc=corp,dc=com (or an equivalent
        representation) must appear in the §5.3 LDIF block so the spec shows
        the full structure of a group entry including member references.
        """
        assert "uid=alice" in section_53, (
            "§5.3 must include at least one member: uid=alice,... DN example. "
            f"Section content (first 800 chars):\n{section_53[:800]!r}"
        )
