# Verifies infrastructure/keycloak/naas-realm-export.json realm configuration.
#
# Checks: file existence, valid JSON structure, realm properties (name, enabled),
# naas-dashboard client settings (protocol, publicClient, standardFlowEnabled,
# directAccessGrants, redirectUris, webOrigins), three test users (alice/bob/charlie)
# with correct emails/groups/credentials, and top-level groups array.
# stdlib
import json

# third-party
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.helpers import REPO_ROOT

REALM_FILE = REPO_ROOT / "infrastructure" / "keycloak" / "naas-realm-export.json"


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

    @pytest.mark.parametrize(
        "username,expected_email",
        [
            ("alice", "alice@corp.com"),
            ("bob", "bob@corp.com"),
            ("charlie", "charlie@corp.com"),
        ],
    )
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

    @pytest.mark.parametrize(
        "username,expected_group",
        [
            ("alice", "engineering"),
            ("bob", "product"),
            ("charlie", "security"),
        ],
    )
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
