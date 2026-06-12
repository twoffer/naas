# Verifies infrastructure/openldap group entries in bootstrap.ldif,
# the 00-memberof-overlay.ldif overlay reconfiguration, the Dockerfile
# COPY lines, and the SPEC_0 §5.3 documentation mirror.
#
# Spec §5.3: four groupOfNames entries (engineering, product, security,
# vpn-users) under ou=groups,dc=corp,dc=com, each with objectClass:
# groupOfNames and member DNs of the form uid=<user>,ou=users,dc=corp,dc=com.
# All five pre-existing users remain present. Group entries appear after all
# user entries. Member DNs reference user entries defined earlier in the file.

# stdlib
import re

# third-party
import pytest

from tests.helpers import REPO_ROOT
from tests.infrastructure.ldif_helpers import load_ldif_lines as _load_ldif_lines_impl
from tests.infrastructure.ldif_helpers import (
    parse_ldif_blocks as _parse_ldif_blocks_impl,
)

LDIF_FILE = REPO_ROOT / "infrastructure" / "openldap" / "bootstrap.ldif"
OVERLAY_LDIF = REPO_ROOT / "infrastructure" / "openldap" / "00-memberof-overlay.ldif"
DOCKERFILE = REPO_ROOT / "infrastructure" / "openldap" / "Dockerfile"
SPEC0_DOC = (
    REPO_ROOT
    / "docs"
    / "architecture"
    / "SPEC_0_Project_Scaffold_and_Shared_Foundation.md"
)


# ---------------------------------------------------------------------------
# LDIF parser — delegated to tests/infrastructure/ldif_helpers.py
# ---------------------------------------------------------------------------


def _load_ldif_lines() -> list[str]:
    """Return every line from the LDIF file, with newlines stripped."""
    return _load_ldif_lines_impl(LDIF_FILE)


def _parse_ldif_blocks(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """Parse LDIF lines into blocks keyed by dn value (RFC-2849 correct).

    Delegates to the shared implementation in tests/infrastructure/ldif_helpers.py.
    """
    return _parse_ldif_blocks_impl(lines)


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
        "The OpenLDAP container cannot seed users or groups without it."
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
        assert key in ldif_blocks, f"Group entry 'dn: {key}' missing from LDIF"
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
        assert key in ldif_blocks, f"Group entry 'dn: {key}' missing from LDIF"
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
        assert key in ldif_blocks, f"Group entry 'dn: {key}' missing from LDIF"
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

    @pytest.mark.parametrize(
        "cn,expected_uids",
        [
            ("engineering", {"alice", "diana"}),
            ("product", {"bob"}),
            ("security", {"charlie"}),
            ("vpn-users", {"alice", "diana"}),
        ],
    )
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
        group_lines = [
            i for i, ln in enumerate(ldif_lines) if group_dn_pattern.match(ln)
        ]

        assert user_lines, "No user dn: entries found in LDIF"
        assert group_lines, (
            "No group dn: entries (cn=...,ou=groups,dc=corp,dc=com) found in LDIF"
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
        group_lines = [
            i for i, ln in enumerate(ldif_lines) if group_dn_pattern.match(ln)
        ]

        assert ou_groups_line is not None, f"'{ou_groups_dn}' not found in LDIF"
        assert group_lines, (
            "No group dn: entries (cn=...,ou=groups,dc=corp,dc=com) found in LDIF"
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

    @pytest.mark.parametrize(
        "group_cn,member_uid",
        [
            ("engineering", "alice"),
            ("engineering", "diana"),
            ("product", "bob"),
            ("security", "charlie"),
            ("vpn-users", "alice"),
            ("vpn-users", "diana"),
        ],
    )
    def test_member_dn_references_earlier_user_entry(
        self, ldif_lines, group_cn, member_uid
    ):
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
        assert group_line is not None, f"Group entry 'dn: {group_dn}' not found in LDIF"
        assert user_line < group_line, (
            f"User 'dn: {user_dn}' at line {user_line} must appear before "
            f"group 'dn: {group_dn}' at line {group_line}"
        )


# ---------------------------------------------------------------------------
# Class: pre-existing users unchanged
# ---------------------------------------------------------------------------


class TestLdifUserEntriesIntact:
    """Tests that all five user entries are present with their required
    attributes alongside the group entries.

    Users and groups share one file — a bad edit to the group section could
    remove a user entry or its required attributes. This is a regression guard.
    """

    @pytest.fixture(autouse=True)
    def _require_ldif(self):
        assert LDIF_FILE.exists(), f"bootstrap.ldif missing at {LDIF_FILE}"

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_entry_present(self, ldif_blocks, uid):
        """All five users must have dn: uid=<uid>,ou=users,dc=corp,dc=com entries.

        Group entries in the same file must never remove or displace user entries.
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in ldif_blocks, (
            f"User entry for {uid!r} missing from LDIF. "
            f"Available DNs: {[k for k in ldif_blocks if 'ou=users' in k]!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_objectclass_inetorgperson(self, ldif_blocks, uid):
        """Each user entry must declare objectClass: inetOrgPerson."""
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in ldif_blocks, f"User entry 'dn: {key}' missing from LDIF"
        objectclasses = [oc.lower() for oc in ldif_blocks[key].get("objectclass", [])]
        assert "inetorgperson" in objectclasses, (
            f"User {uid!r}: objectClass: inetOrgPerson missing, "
            f"got objectClass={ldif_blocks[key].get('objectclass', [])!r}"
        )

    @pytest.mark.parametrize("uid", ["alice", "bob", "charlie", "diana", "eve"])
    def test_user_has_mail(self, ldif_blocks, uid):
        """Each user entry must have a mail: attribute.

        mail is the LDAP correlation attribute for cross-protocol enrichment —
        a user without it cannot be matched by primary_email.
        """
        key = f"uid={uid},ou=users,dc=corp,dc=com"
        assert key in ldif_blocks, f"User entry 'dn: {key}' missing from LDIF"
        assert "mail" in ldif_blocks[key] and ldif_blocks[key]["mail"], (
            f"User {uid!r}: mail attribute missing"
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
# Class: 00-memberof-overlay.ldif (overlay reconfiguration)
# ---------------------------------------------------------------------------


class TestMemberofOverlayLdif:
    """Tests that infrastructure/openldap/00-memberof-overlay.ldif reconfigures
    the image-default memberof overlay for the groupOfNames/member schema.

    osixia/openldap:1.5.0 ships a default memberof overlay configured for
    groupOfUniqueNames/uniqueMember. bootstrap.ldif uses groupOfNames/member,
    so without this reconfiguration the default overlay never fires and
    memberOf back-links are never populated on user entries.
    """

    @pytest.fixture(scope="class")
    def overlay_ldif_lines(self) -> list[str]:
        """Non-comment, non-blank lines of 00-memberof-overlay.ldif, stripped."""
        assert OVERLAY_LDIF.exists(), (
            f"00-memberof-overlay.ldif not found at {OVERLAY_LDIF}. "
            "Without it the image-default memberof overlay stays configured for "
            "groupOfUniqueNames/uniqueMember and memberOf is never populated."
        )
        return [
            ln.strip()
            for ln in OVERLAY_LDIF.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]

    def test_filename_sorts_before_bootstrap_ldif(self):
        """The '00-' prefix must keep the file sorted before bootstrap.ldif.

        osixia processes ldif/custom/*.ldif via `find | sort`, so the overlay
        reconfiguration must sort first to be active before the group entries
        from bootstrap.ldif are loaded.
        """
        assert OVERLAY_LDIF.name < LDIF_FILE.name, (
            f"{OVERLAY_LDIF.name!r} must sort before {LDIF_FILE.name!r} so the "
            "overlay is reconfigured before bootstrap.ldif adds the group entries."
        )

    def test_targets_default_memberof_overlay_dn(self, overlay_ldif_lines):
        """The modify must target the image-default memberof overlay entry.

        dn: olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config is where the
        osixia image pre-configures the overlay; modifying any other DN leaves
        the active overlay untouched.
        """
        expected_dn = "dn: olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config"
        assert expected_dn in overlay_ldif_lines, (
            f"Expected '{expected_dn}' in 00-memberof-overlay.ldif, "
            f"got lines: {overlay_ldif_lines!r}"
        )

    def test_uses_changetype_modify(self, overlay_ldif_lines):
        """The LDIF must use changetype: modify, never changetype: add.

        The image already has a memberof overlay entry — an add would collide
        with it. modify/replace is also idempotent across container restarts.
        """
        assert "changetype: modify" in overlay_ldif_lines, (
            f"Expected 'changetype: modify' in 00-memberof-overlay.ldif, "
            f"got lines: {overlay_ldif_lines!r}"
        )
        assert "changetype: add" not in overlay_ldif_lines, (
            "00-memberof-overlay.ldif must not use 'changetype: add' — the "
            "image-default overlay entry already exists and an add would collide."
        )

    def test_replaces_group_oc_with_groupofnames(self, overlay_ldif_lines):
        """olcMemberOfGroupOC must be replaced with groupOfNames.

        This is the objectClass the overlay watches for group entries; left at
        the image default (groupOfUniqueNames) it ignores bootstrap.ldif groups.
        """
        assert "replace: olcMemberOfGroupOC" in overlay_ldif_lines, (
            f"Expected 'replace: olcMemberOfGroupOC', got lines: {overlay_ldif_lines!r}"
        )
        assert "olcMemberOfGroupOC: groupOfNames" in overlay_ldif_lines, (
            f"Expected 'olcMemberOfGroupOC: groupOfNames', got lines: {overlay_ldif_lines!r}"
        )

    def test_replaces_member_ad_with_member(self, overlay_ldif_lines):
        """olcMemberOfMemberAD must be replaced with member.

        This is the attribute the overlay reads member DNs from; left at the
        image default (uniqueMember) the groups' member: values are ignored.
        """
        assert "replace: olcMemberOfMemberAD" in overlay_ldif_lines, (
            f"Expected 'replace: olcMemberOfMemberAD', got lines: {overlay_ldif_lines!r}"
        )
        assert "olcMemberOfMemberAD: member" in overlay_ldif_lines, (
            f"Expected 'olcMemberOfMemberAD: member', got lines: {overlay_ldif_lines!r}"
        )


# ---------------------------------------------------------------------------
# Class: Dockerfile COPY lines
# ---------------------------------------------------------------------------


class TestDockerfileMemberofCopy:
    """Tests the infrastructure/openldap/Dockerfile COPY lines: bootstrap.ldif
    and 00-memberof-overlay.ldif must both be baked into the osixia
    custom-bootstrap directory.

    Spec §5.3: The Dockerfile copies these files into
    /container/service/slapd/assets/config/bootstrap/ so they are part of the
    image and available at container startup.
    """

    @pytest.fixture(autouse=True)
    def _require_dockerfile(self):
        assert DOCKERFILE.exists(), f"Dockerfile not found at {DOCKERFILE}"

    @pytest.fixture(scope="class")
    def dockerfile_content(self) -> str:
        return DOCKERFILE.read_text(encoding="utf-8")

    def test_dockerfile_from_osixia_openldap(self, dockerfile_content):
        """Dockerfile must use 'FROM osixia/openldap:1.5.0'.

        All overlay configuration depends on the osixia/openldap:1.5.0
        bootstrap mechanism and directory layout.
        """
        assert "FROM osixia/openldap:1.5.0" in dockerfile_content, (
            "Dockerfile must use 'FROM osixia/openldap:1.5.0'. "
            f"Dockerfile content:\n{dockerfile_content}"
        )

    def test_dockerfile_copies_bootstrap_ldif(self, dockerfile_content):
        """Dockerfile must contain a COPY line for bootstrap.ldif.

        This COPY bakes the user and group entries into the image. Without it
        the OpenLDAP container starts with no users or groups.
        """
        assert "COPY bootstrap.ldif" in dockerfile_content, (
            "Dockerfile must contain a 'COPY bootstrap.ldif ...' line. "
            f"Dockerfile content:\n{dockerfile_content}"
        )

    def test_dockerfile_copies_00_memberof_overlay_ldif_into_ldif_custom(
        self, dockerfile_content
    ):
        """Dockerfile must COPY 00-memberof-overlay.ldif into ldif/custom/.

        The overlay reconfiguration only takes effect if the file lands in the
        osixia ldif/custom/ directory, where `find | sort` picks it up before
        bootstrap.ldif.
        """
        copy_lines = [
            ln
            for ln in dockerfile_content.splitlines()
            if ln.strip().startswith("COPY") and "00-memberof-overlay.ldif" in ln
        ]
        assert copy_lines, (
            "Dockerfile must contain a 'COPY 00-memberof-overlay.ldif ...' line. "
            f"Dockerfile content:\n{dockerfile_content}"
        )
        assert (
            "/container/service/slapd/assets/config/bootstrap/ldif/custom/"
            in copy_lines[0]
        ), (
            "COPY line for 00-memberof-overlay.ldif must target "
            "'/container/service/slapd/assets/config/bootstrap/ldif/custom/'. "
            f"Found: {copy_lines[0]!r}"
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
            if re.match(r"^#{1,3}\s+", line) and not re.match(
                r"^#{1,3}\s+5\.3\b", line
            ):
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

    The doc mirror requirement: §5.3 must show the group entries and explain
    the memberof/refint overlay so that the spec remains the authoritative
    reference for what the OpenLDAP bootstrap contains.
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
            f"Could not find §5.3 heading in SPEC_0. Document path: {SPEC0_DOC}"
        )

    @pytest.mark.parametrize(
        "group_cn", ["engineering", "product", "security", "vpn-users"]
    )
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
