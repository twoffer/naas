# Component: NAAS Spec 0 — Chunk 4: Keycloak realm export JSON and OpenLDAP bootstrap LDIF
# Mode: TDD — all tests MUST fail until the chunk is implemented
#
# What these tests validate:
#   - infrastructure/keycloak/naas-realm-export.json is valid JSON with the correct
#     realm name, client config, users, and groups per spec §5.2
#   - infrastructure/openldap/bootstrap.ldif is structurally valid LDIF per spec §5.3,
#     with no base-DN entry, correct OU entries before user entries, exactly 5 inetOrgPerson
#     users (alice/bob/charlie/diana/eve), and employeeType coverage for FTE/contractor/vendor
#   - alice/bob/charlie exist in BOTH files with matching emails (cross-protocol correlation)
#
# Why this matters:
#   The Keycloak realm file is the OIDC identity source for the dashboard and all three
#   test users. The LDAP bootstrap provides the directory data that the identity-normalization
#   service enriches OIDC/SAML events with (via cross-protocol correlation on primary_email).
#   Wrong client config (e.g. missing publicClient) breaks the SPA login flow entirely.
#   Including dc=corp,dc=com in the LDIF causes osixia/openldap to error and silently skip
#   the entire file — the most common LDAP bootstrap pitfall noted in spec §5.3 ADR.
#   Ordering (OUs before users) is mandatory because LDIF is processed top-to-bottom and
#   parent entries must exist before their children can be created.
#
# LDIF parsing approach:
#   STRUCTURAL (dependency-free plain string/line processing).
#   python-ldap and the `ldif` package are NOT guaranteed to be present in the dev venv.
#   All critical structural checks (dn: presence, ordering, attribute presence) are done
#   with pure stdlib string operations.  An optional deep-parse test using pytest.importorskip
#   is provided at the end but is NOT relied upon for any of the numbered validation criteria.

# stdlib
import json
import re
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery (consistent with other spec_0 test files)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory that contains
    docs/architecture/ — that is the repo root.  Avoids hardcoding absolute
    paths so tests are portable across machines and CI environments.
    """
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Could not locate repo root (looked for docs/architecture/ sentinel)")


REPO_ROOT = _find_repo_root()
REALM_FILE = REPO_ROOT / "infrastructure" / "keycloak" / "naas-realm-export.json"
LDIF_FILE = REPO_ROOT / "infrastructure" / "openldap" / "bootstrap.ldif"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _load_realm() -> dict:
    """Load and parse the Keycloak realm export JSON.  Callers should only
    call this after asserting the file exists (pytest will give a clearer
    message if called directly rather than relying on json.load's FileNotFoundError).
    """
    with REALM_FILE.open() as fh:
        return json.load(fh)


def _load_ldif_lines() -> list[str]:
    """Return every line from the LDIF file, with newlines stripped."""
    return LDIF_FILE.read_text(encoding="utf-8").splitlines()


def _find_client(realm: dict, client_id: str) -> dict:
    """Locate a client in the realm's clients list by clientId.  Returns the
    first match or raises KeyError to produce an informative test failure.
    """
    for client in realm.get("clients", []):
        if client.get("clientId") == client_id:
            return client
    raise KeyError(f"No client with clientId={client_id!r} in realm")


def _find_user(realm: dict, username: str) -> dict:
    """Locate a user in the realm's users list by username."""
    for user in realm.get("users", []):
        if user.get("username") == username:
            return user
    raise KeyError(f"No user with username={username!r} in realm")


# ---------------------------------------------------------------------------
# Keycloak realm — file existence and basic JSON validity
# ---------------------------------------------------------------------------


class TestKeycloakRealmFile:
    """Tests that the realm export file exists and is well-formed JSON."""

    def test_realm_file_exists(self):
        """The realm export file must exist at the specified infrastructure path.

        This is the minimal gate: if the file is absent, all downstream realm
        tests will fail with misleading FileNotFoundError messages instead of a
        clear 'file not found' assertion.
        """
        assert REALM_FILE.exists(), (
            f"Keycloak realm export not found at {REALM_FILE}. "
            "Implementer must create infrastructure/keycloak/naas-realm-export.json."
        )

    def test_realm_file_is_valid_json(self):
        """The realm export file must parse successfully via json.load with no exceptions.

        Keycloak --import-realm silently skips malformed JSON; a parse error here
        surfaces the problem early, before the container is even started.
        """
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        try:
            data = _load_realm()
        except json.JSONDecodeError as exc:
            pytest.fail(f"naas-realm-export.json is not valid JSON: {exc}")
        assert isinstance(data, dict), "JSON root must be a dict (realm object)"

    def test_realm_file_is_dict_not_list(self):
        """Keycloak realm imports expect a single JSON object, not a list of realms.

        Wrapping the realm in an array is a common mistake when adapting export
        samples; this guard catches it early.
        """
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        data = _load_realm()
        assert isinstance(data, dict), (
            f"Expected JSON root to be a dict, got {type(data).__name__}. "
            "Keycloak --import-realm expects a single realm object."
        )


# ---------------------------------------------------------------------------
# Keycloak realm — top-level realm properties
# ---------------------------------------------------------------------------


class TestKeycloakRealmProperties:
    """Tests for top-level realm configuration fields."""

    def test_realm_name_is_naas_demo(self):
        """Top-level 'realm' field must equal 'naas-demo'.

        This is the realm identifier used by all services in .env.example under
        KEYCLOAK_REALM=naas-demo and the OIDC discovery URL path.
        """
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        data = _load_realm()
        assert data.get("realm") == "naas-demo", (
            f"Expected realm='naas-demo', got realm={data.get('realm')!r}. "
            "All services reference naas-demo by name."
        )

    def test_realm_enabled_is_true(self):
        """Realm must have 'enabled': true.

        A disabled realm causes all OIDC flows to return 403; this is a
        non-obvious failure mode that surfaces only at runtime.
        """
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        data = _load_realm()
        assert data.get("enabled") is True, (
            f"Expected enabled=true, got enabled={data.get('enabled')!r}. "
            "Disabled realm blocks all OIDC logins."
        )


# ---------------------------------------------------------------------------
# Keycloak realm — naas-dashboard client configuration
# ---------------------------------------------------------------------------


class TestKeycloakDashboardClient:
    """Tests for the naas-dashboard OIDC client configuration.

    The SPA uses a public OIDC flow (no client secret). Wrong settings here
    prevent the dashboard from obtaining tokens entirely.
    """

    @pytest.fixture
    def client(self) -> dict:
        """Load and return the naas-dashboard client entry."""
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        data = _load_realm()
        return _find_client(data, "naas-dashboard")

    def test_naas_dashboard_client_exists(self):
        """A client with clientId='naas-dashboard' must be present in the clients array.

        Located by clientId (not array index) to be robust against additional
        clients added to the realm in future.
        """
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        data = _load_realm()
        # Will raise KeyError (caught by pytest as failure) if not found
        client = _find_client(data, "naas-dashboard")
        assert client is not None

    def test_dashboard_client_protocol_is_openid_connect(self, client):
        """Client protocol must be 'openid-connect'.

        Spec §5.2 specifies Client Protocol: openid-connect. A SAML client would
        break the dashboard's OAuth2 token acquisition.
        """
        assert client.get("protocol") == "openid-connect", (
            f"Expected protocol='openid-connect', got {client.get('protocol')!r}"
        )

    def test_dashboard_client_is_public(self, client):
        """publicClient must be true (no client secret required).

        The React SPA is a public client — it cannot keep a client secret. If
        publicClient is false, token requests without a secret will be rejected.
        """
        assert client.get("publicClient") is True, (
            f"Expected publicClient=true, got publicClient={client.get('publicClient')!r}. "
            "SPA cannot hold a client secret."
        )

    def test_dashboard_client_standard_flow_enabled(self, client):
        """standardFlowEnabled must be true (authorization code flow).

        The dashboard uses the authorization code flow with PKCE. Disabling
        standardFlowEnabled breaks the interactive login redirect.
        """
        assert client.get("standardFlowEnabled") is True, (
            f"Expected standardFlowEnabled=true, got {client.get('standardFlowEnabled')!r}"
        )

    def test_dashboard_client_direct_access_grants_enabled(self, client):
        """directAccessGrantsEnabled must be true (resource owner password grant).

        Required for the persona simulator to obtain tokens programmatically when
        generating synthetic login events without a browser.
        """
        assert client.get("directAccessGrantsEnabled") is True, (
            f"Expected directAccessGrantsEnabled=true, got "
            f"{client.get('directAccessGrantsEnabled')!r}"
        )

    def test_dashboard_client_redirect_uris(self, client):
        """redirectUris must equal ['http://localhost:3000/*'].

        Keycloak validates the redirect_uri on callback; if the actual SPA origin
        is not in the allowlist, the login flow returns an 'invalid_redirect_uri'
        error and the user is stuck on the Keycloak login page.
        """
        expected = ["http://localhost:3000/*"]
        actual = client.get("redirectUris")
        assert actual == expected, (
            f"Expected redirectUris={expected!r}, got {actual!r}. "
            "Keycloak rejects callbacks not in the allowlist."
        )

    def test_dashboard_client_web_origins(self, client):
        """webOrigins must equal ['http://localhost:3000'].

        Controls the CORS Access-Control-Allow-Origin header that Keycloak returns
        on token endpoint responses. Wrong origin → CORS error in the SPA.
        """
        expected = ["http://localhost:3000"]
        actual = client.get("webOrigins")
        assert actual == expected, (
            f"Expected webOrigins={expected!r}, got {actual!r}. "
            "Incorrect webOrigins causes CORS failures in the dashboard."
        )


# ---------------------------------------------------------------------------
# Keycloak realm — users
# ---------------------------------------------------------------------------


class TestKeycloakRealmUsers:
    """Tests for the three test users (alice, bob, charlie)."""

    @pytest.fixture
    def realm(self) -> dict:
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        return _load_realm()

    def test_users_array_has_exactly_three_entries(self, realm):
        """The users array must contain exactly 3 entries (alice, bob, charlie).

        Spec §5.2 specifies 3 test users minimum. Extra unexpected users could
        indicate an export from a live environment leaking real user data.
        """
        users = realm.get("users", [])
        assert len(users) == 3, (
            f"Expected exactly 3 users, got {len(users)}: "
            f"{[u.get('username') for u in users]}"
        )

    def test_user_set_is_alice_bob_charlie(self, realm):
        """The set of usernames must be exactly {alice, bob, charlie}.

        Tests identity, not just count: a file with {alice, bob, dave} would
        pass the count test but break LDAP cross-protocol correlation.
        """
        usernames = {u.get("username") for u in realm.get("users", [])}
        expected = {"alice", "bob", "charlie"}
        assert usernames == expected, (
            f"Expected usernames={expected!r}, got {usernames!r}"
        )

    @pytest.mark.parametrize("username,expected_email", [
        ("alice", "alice@corp.com"),
        ("bob", "bob@corp.com"),
        ("charlie", "charlie@corp.com"),
    ])
    def test_user_email(self, realm, username, expected_email):
        """Each user must have the email address specified in spec §5.2 table.

        Email is the cross-protocol correlation key — alice@corp.com in Keycloak
        must match alice@corp.com as the LDAP 'mail' attribute so the identity
        normalization service can merge attributes from both sources.
        """
        user = _find_user(realm, username)
        assert user.get("email") == expected_email, (
            f"User {username!r}: expected email={expected_email!r}, "
            f"got {user.get('email')!r}"
        )

    @pytest.mark.parametrize("username", ["alice", "bob", "charlie"])
    def test_user_is_enabled(self, realm, username):
        """Each user must have enabled=true.

        A disabled user can be imported successfully but will receive a 401 on
        login. This is a silent gotcha when testing.
        """
        user = _find_user(realm, username)
        assert user.get("enabled") is True, (
            f"User {username!r}: expected enabled=true, got {user.get('enabled')!r}"
        )

    @pytest.mark.parametrize("username", ["alice", "bob", "charlie"])
    def test_user_has_password_credential(self, realm, username):
        """Each user must have a credentials entry with type='password'.

        Without a credential entry, Keycloak imports the user but they cannot
        log in — the import succeeds silently but authentication fails.
        """
        user = _find_user(realm, username)
        credentials = user.get("credentials", [])
        password_creds = [c for c in credentials if c.get("type") == "password"]
        assert len(password_creds) >= 1, (
            f"User {username!r}: no credentials entry with type='password' found. "
            f"credentials={credentials!r}"
        )

    @pytest.mark.parametrize("username", ["alice", "bob", "charlie"])
    def test_user_password_value_is_password123(self, realm, username):
        """Each user's password credential value must equal 'password123'.

        All integration docs and the LDIF use 'password123' as the consistent
        test credential. Inconsistency causes hard-to-diagnose login failures
        when testing cross-protocol flows.
        """
        user = _find_user(realm, username)
        credentials = user.get("credentials", [])
        password_creds = [c for c in credentials if c.get("type") == "password"]
        assert password_creds, f"User {username!r}: no password credential"
        cred = password_creds[0]
        assert cred.get("value") == "password123", (
            f"User {username!r}: expected credential value='password123', "
            f"got {cred.get('value')!r}"
        )

    @pytest.mark.parametrize("username", ["alice", "bob", "charlie"])
    def test_user_password_is_not_temporary(self, realm, username):
        """Each user's password credential must have temporary=false.

        temporary=true forces a password-change flow on first login, which
        breaks automated testing and the persona simulator's direct-grant flows.
        """
        user = _find_user(realm, username)
        credentials = user.get("credentials", [])
        password_creds = [c for c in credentials if c.get("type") == "password"]
        assert password_creds, f"User {username!r}: no password credential"
        cred = password_creds[0]
        assert cred.get("temporary") is False, (
            f"User {username!r}: expected temporary=false, got {cred.get('temporary')!r}. "
            "Temporary passwords force a change flow that breaks automated logins."
        )

    @pytest.mark.parametrize("username,expected_group", [
        ("alice", "engineering"),
        ("bob", "product"),
        ("charlie", "security"),
    ])
    def test_user_group_membership(self, realm, username, expected_group):
        """Each user must belong to the group specified in spec §5.2 table.

        Group membership is propagated into OIDC tokens as the 'groups' claim.
        The risk evaluator and normalization layer use this for access decisions.
        Incorrect group assignment causes wrong policy outcomes.
        """
        user = _find_user(realm, username)
        groups = user.get("groups", [])
        assert expected_group in groups, (
            f"User {username!r}: expected group {expected_group!r} in groups={groups!r}"
        )


# ---------------------------------------------------------------------------
# Keycloak realm — top-level groups
# ---------------------------------------------------------------------------


class TestKeycloakRealmGroups:
    """Tests for the top-level groups array."""

    @pytest.fixture
    def realm(self) -> dict:
        assert REALM_FILE.exists(), f"File missing: {REALM_FILE}"
        return _load_realm()

    def test_groups_array_exists(self, realm):
        """A top-level 'groups' array must be present in the realm JSON.

        Without it, Keycloak will not create the groups and user group membership
        references in users[].groups will fail to resolve, causing import errors.
        """
        assert "groups" in realm, (
            "Top-level 'groups' key missing from realm JSON. "
            "Keycloak requires groups to be pre-declared for user group references."
        )
        assert isinstance(realm["groups"], list), (
            f"Expected 'groups' to be a list, got {type(realm['groups']).__name__}"
        )

    @pytest.mark.parametrize("expected_group", ["engineering", "product", "security"])
    def test_realm_group_exists(self, realm, expected_group):
        """Top-level groups array must include each of: engineering, product, security.

        These correspond to the three users' group memberships. A missing group
        entry causes the user import to fail with a 'Group not found' error in
        Keycloak's import processor.
        """
        group_names = {g.get("name") for g in realm.get("groups", [])}
        assert expected_group in group_names, (
            f"Expected group {expected_group!r} in top-level groups array. "
            f"Found: {group_names!r}"
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — file existence
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

    @pytest.mark.parametrize("expected_dn", [
        "dn: ou=users,dc=corp,dc=com",
        "dn: ou=groups,dc=corp,dc=com",
    ])
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

        assert ou_users_line is not None, (
            f"'{ou_users_dn}' not found in LDIF"
        )
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

        assert ou_groups_line is not None, (
            f"'{ou_groups_dn}' not found in LDIF"
        )
        assert first_user_line is not None, (
            "No user DN entries found in LDIF"
        )
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
        assert uids == expected, (
            f"Expected uid set={expected!r}, got {uids!r}"
        )


# ---------------------------------------------------------------------------
# OpenLDAP LDIF — per-user required attributes
# ---------------------------------------------------------------------------


def _parse_ldif_blocks(lines: list[str]) -> dict[str, dict[str, list[str]]]:
    """Parse LDIF lines into blocks keyed by dn value.

    Returns a dict mapping dn_value -> {attr_name: [value, ...]}. This is a
    structural parser only — it handles simple attribute:value pairs and
    blank-line-separated blocks.  It does NOT handle base64-encoded values
    (::), continuation lines (space-prefixed), or multi-valued attributes
    beyond accumulating them into a list.  Sufficient for spec §5.3 validation.
    """
    blocks: dict[str, dict[str, list[str]]] = {}
    current_dn: str | None = None
    current_block: dict[str, list[str]] = {}

    for line in lines:
        stripped = line.strip()

        # Blank line or comment ends the current block
        if not stripped or stripped.startswith("#"):
            if current_dn is not None:
                blocks[current_dn] = current_block
                current_dn = None
                current_block = {}
            continue

        # Handle continuation lines (wrapped attribute values start with a space)
        if line.startswith(" ") and current_dn is not None:
            # Append continuation to last attribute value — simplified handling
            continue

        if ":" not in stripped:
            continue

        attr, _, value = stripped.partition(":")
        attr = attr.strip().lower()
        value = value.strip()

        if attr == "dn":
            # Start of a new block
            if current_dn is not None:
                blocks[current_dn] = current_block
            current_dn = value
            current_block = {"dn": [value]}
        elif current_dn is not None:
            current_block.setdefault(attr, []).append(value)

    # Flush last block (file may not end with a blank line)
    if current_dn is not None:
        blocks[current_dn] = current_block

    return blocks


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

    @pytest.mark.parametrize("uid,expected_type", [
        ("alice", "FTE"),
        ("bob", "FTE"),
        ("charlie", "contractor"),
        ("diana", "vendor"),
        ("eve", "contractor"),
    ])
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

    @pytest.mark.parametrize("uid,expected_email", [
        ("alice", "alice@corp.com"),
        ("bob", "bob@corp.com"),
        ("charlie", "charlie@corp.com"),
    ])
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

    @pytest.mark.parametrize("uid,expected_email", [
        ("diana", "diana@corp.com"),
        ("eve", "eve@partner.com"),
    ])
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
            f"User {uid!r}: expected mail={expected_email!r}, "
            f"got mail={mail_values!r}"
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
    ldif_mod = pytest.importorskip("ldif", reason="python-ldap/ldif not installed — skip deep parse")
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
