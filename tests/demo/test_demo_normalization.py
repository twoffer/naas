# Verifies demo/demo_normalization.py scaffold and its companion files
# (demo/requirements.txt, demo/README.md).
#
# Spec §: demo CLI scaffold — SCENES constant, CLI flags, static file content,
# naas_shared soft-import, and absence of meta-language tokens.
#
# The module-level symbol holding the six crafted login events is SCENES —
# a list of six dicts, each with keys: user_id, protocol, client_ip, source,
# is_synthetic, raw_attributes, and optionally caption.

# stdlib
import ast
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find docs/architecture/ — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
DEMO_DIR = REPO_ROOT / "demo"
DEMO_SCRIPT = DEMO_DIR / "demo_normalization.py"
DEMO_REQUIREMENTS = DEMO_DIR / "requirements.txt"
DEMO_README = DEMO_DIR / "README.md"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_source() -> str:
    """Raw source text of demo_normalization.py."""
    if not DEMO_SCRIPT.exists():
        pytest.fail(f"demo_normalization.py not found at {DEMO_SCRIPT}")
    return DEMO_SCRIPT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def requirements_text() -> str:
    """Raw text of demo/requirements.txt."""
    if not DEMO_REQUIREMENTS.exists():
        pytest.fail(f"demo/requirements.txt not found at {DEMO_REQUIREMENTS}")
    return DEMO_REQUIREMENTS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text() -> str:
    """Raw text of demo/README.md."""
    if not DEMO_README.exists():
        pytest.fail(f"demo/README.md not found at {DEMO_README}")
    return DEMO_README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def demo_module():
    """Import demo_normalization as a module so we can inspect SCENES directly."""
    if not DEMO_SCRIPT.exists():
        pytest.fail(f"demo_normalization.py not found at {DEMO_SCRIPT}")
    spec = importlib.util.spec_from_file_location("demo_normalization", DEMO_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def help_result() -> subprocess.CompletedProcess:
    """Run `python demo_normalization.py --help` once and share the result.

    Module-scoped so all help-text tests share a single subprocess launch.
    """
    return subprocess.run(
        [sys.executable, str(DEMO_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Class: valid Python syntax
# ---------------------------------------------------------------------------


class TestValidPython:
    """demo_normalization.py must be importable — no syntax errors."""

    def test_ast_parse_succeeds(self, demo_source: str) -> None:
        """ast.parse must succeed without raising SyntaxError."""
        try:
            ast.parse(demo_source)
        except SyntaxError as exc:
            pytest.fail(f"demo_normalization.py has a syntax error: {exc}")


# ---------------------------------------------------------------------------
# Class: CLI flags via --help
# ---------------------------------------------------------------------------


class TestCliHelp:
    """python demo/demo_normalization.py --help exits 0 and lists all flags."""

    EXPECTED_FLAGS = [
        "--keep",
        "--pace",
        "--step",
        "--timeout",
        "--skip-verify",
        "--ingest-url",
        "--db-dsn",
    ]

    def test_help_exits_zero(self, help_result: subprocess.CompletedProcess) -> None:
        """--help must exit with code 0."""
        assert help_result.returncode == 0, (
            f"--help exited {help_result.returncode}.\n"
            f"stdout: {help_result.stdout}\nstderr: {help_result.stderr}"
        )

    @pytest.mark.parametrize("flag", EXPECTED_FLAGS)
    def test_help_lists_flag(
        self, help_result: subprocess.CompletedProcess, flag: str
    ) -> None:
        """--help output must contain the flag string."""
        combined = help_result.stdout + help_result.stderr
        assert flag in combined, (
            f"Flag '{flag}' not found in --help output.\nOutput: {combined}"
        )

    def test_pace_default_is_1_5(
        self, help_result: subprocess.CompletedProcess
    ) -> None:
        """--pace option description must show 1.5 as the default value.

        Searches the options section for the --pace descriptor line (preceded by
        two or more spaces, as argparse formats it) so a bare occurrence of '--pace'
        in the usage summary does not satisfy the check.
        """
        combined = help_result.stdout + help_result.stderr
        # Match the --pace option descriptor in the options listing: the line starts
        # with two or more spaces then '--pace'.  Capture from there to the next
        # option line or end-of-string.
        pace_match = re.search(r"  --pace\b(.*?)(?=\n  --|\Z)", combined, re.DOTALL)
        assert pace_match, (
            f"'--pace' option descriptor not found in --help options section.\n"
            f"Output: {combined}"
        )
        pace_block = pace_match.group(0)
        assert "1.5" in pace_block, (
            f"Default 1.5 for --pace not found in the --pace option descriptor.\n"
            f"--pace block: {pace_block!r}\nFull output: {combined}"
        )

    def test_timeout_default_is_30(
        self, help_result: subprocess.CompletedProcess
    ) -> None:
        """--timeout option description must show 30 as the default value.

        Searches the options section for the --timeout descriptor line (preceded
        by two or more spaces) so a bare '--timeout' in the usage summary does not
        satisfy the check.
        """
        combined = help_result.stdout + help_result.stderr
        # Match the --timeout option descriptor in the options listing.
        timeout_match = re.search(
            r"  --timeout\b(.*?)(?=\n  --|\Z)", combined, re.DOTALL
        )
        assert timeout_match, (
            f"'--timeout' option descriptor not found in --help options section.\n"
            f"Output: {combined}"
        )
        timeout_block = timeout_match.group(0)
        assert "30" in timeout_block, (
            f"Default 30 for --timeout not found in the --timeout option descriptor.\n"
            f"--timeout block: {timeout_block!r}\nFull output: {combined}"
        )


# ---------------------------------------------------------------------------
# Class: SCENES constant — structure and count
# ---------------------------------------------------------------------------


class TestScenesConstant:
    """SCENES must be a module-level list of exactly six event dicts."""

    def test_scenes_attribute_exists(self, demo_module) -> None:
        """Module must expose a SCENES attribute."""
        assert hasattr(demo_module, "SCENES"), (
            "demo_normalization.py must define a module-level constant named SCENES"
        )

    def test_scenes_is_list(self, demo_module) -> None:
        """SCENES must be a list."""
        scenes = demo_module.SCENES
        assert isinstance(scenes, list), (
            f"SCENES must be a list, got {type(scenes).__name__}"
        )

    def test_scenes_has_six_entries(self, demo_module) -> None:
        """SCENES must contain exactly six entries."""
        scenes = demo_module.SCENES
        assert len(scenes) == 6, (
            f"SCENES must have exactly 6 entries, got {len(scenes)}"
        )

    @pytest.mark.parametrize("idx", range(6))
    def test_scene_is_dict(self, demo_module, idx: int) -> None:
        """Each scene must be a dict."""
        scene = demo_module.SCENES[idx]
        assert isinstance(scene, dict), (
            f"SCENES[{idx}] must be a dict, got {type(scene).__name__}"
        )

    @pytest.mark.parametrize("idx", range(6))
    def test_scene_has_required_keys(self, demo_module, idx: int) -> None:
        """Each scene dict must have user_id, protocol, client_ip, source, is_synthetic, raw_attributes."""
        scene = demo_module.SCENES[idx]
        required = {
            "user_id",
            "protocol",
            "client_ip",
            "source",
            "is_synthetic",
            "raw_attributes",
        }
        missing = required - set(scene.keys())
        assert not missing, f"SCENES[{idx}] is missing keys: {missing}"

    @pytest.mark.parametrize("idx", range(6))
    def test_scene_source_is_api(self, demo_module, idx: int) -> None:
        """Each scene must have source == 'api'."""
        scene = demo_module.SCENES[idx]
        assert scene["source"] == "api", (
            f"SCENES[{idx}] source must be 'api', got {scene['source']!r}"
        )

    @pytest.mark.parametrize("idx", range(6))
    def test_scene_is_synthetic_true(self, demo_module, idx: int) -> None:
        """Each scene must have is_synthetic == True."""
        scene = demo_module.SCENES[idx]
        assert scene["is_synthetic"] is True, (
            f"SCENES[{idx}] is_synthetic must be True, got {scene['is_synthetic']!r}"
        )

    @pytest.mark.parametrize("idx", range(6))
    def test_scene_client_ip_is_documentation_range(
        self, demo_module, idx: int
    ) -> None:
        """Each scene client_ip must be in the 203.0.113.x documentation range (RFC 5737)."""
        scene = demo_module.SCENES[idx]
        ip = scene["client_ip"]
        assert ip.startswith("203.0.113."), (
            f"SCENES[{idx}] client_ip must start with '203.0.113.', got {ip!r}"
        )


# ---------------------------------------------------------------------------
# Class: SCENES — per-scene identity and protocol correctness
# ---------------------------------------------------------------------------

# Shared ground-truth table: (scene_index, user_id, protocol, client_ip).
# Single source of truth consumed by all three field assertions below.
_SCENE_IDENTITY_TABLE = [
    (0, "frank", "oidc", "203.0.113.10"),
    (1, "frank", "saml", "203.0.113.10"),
    (2, "grace", "ldap", "203.0.113.11"),
    (3, "mallory", "saml", "203.0.113.12"),
    (4, "alice", "oidc", "203.0.113.20"),
    (5, "diana", "oidc", "203.0.113.21"),
]


class TestScenesIdentity:
    """Each scene carries the correct user_id, protocol, and client_ip."""

    @pytest.mark.parametrize("idx, user_id, protocol, client_ip", _SCENE_IDENTITY_TABLE)
    def test_scene_identity(
        self,
        demo_module,
        idx: int,
        user_id: str,
        protocol: str,
        client_ip: str,
    ) -> None:
        """Scene at index idx must have the correct user_id, protocol, and client_ip."""
        scene = demo_module.SCENES[idx]
        assert scene["user_id"] == user_id, (
            f"SCENES[{idx}] user_id must be {user_id!r}, got {scene['user_id']!r}"
        )
        assert scene["protocol"] == protocol, (
            f"SCENES[{idx}] protocol must be {protocol!r}, got {scene['protocol']!r}"
        )
        assert scene["client_ip"] == client_ip, (
            f"SCENES[{idx}] client_ip must be {client_ip!r}, got {scene['client_ip']!r}"
        )


# ---------------------------------------------------------------------------
# Class: SCENES — raw_attributes ground-truth values
# ---------------------------------------------------------------------------


class TestScenesRawAttributes:
    """raw_attributes must use protocol-native keys and exact ground-truth values."""

    def test_scene0_frank_oidc_raw_attributes(self, demo_module) -> None:
        """Scene 0: frank/oidc uses OIDC native keys with exact values."""
        ra = demo_module.SCENES[0]["raw_attributes"]
        assert ra.get("name") == "Frank Castle", f"Got name={ra.get('name')!r}"
        assert ra.get("email") == "frank@corp.com", f"Got email={ra.get('email')!r}"
        assert ra.get("department") == "eng", f"Got department={ra.get('department')!r}"
        assert ra.get("employee_type") == "E", (
            f"Got employee_type={ra.get('employee_type')!r}"
        )
        assert ra.get("groups") == ["engineering", "vpn-users"], (
            f"Got groups={ra.get('groups')!r}"
        )
        # Must NOT use SAML or LDAP keys
        assert "displayName" not in ra, "OIDC scene must not have 'displayName' key"
        assert "dept" not in ra, "OIDC scene must not have 'dept' key"
        assert "cn" not in ra, "OIDC scene must not have 'cn' key"

    def test_scene1_frank_saml_raw_attributes(self, demo_module) -> None:
        """Scene 1: frank/saml uses SAML native keys with exact values."""
        ra = demo_module.SCENES[1]["raw_attributes"]
        assert ra.get("displayName") == "Frank Castle", (
            f"Got displayName={ra.get('displayName')!r}"
        )
        assert ra.get("email") == "frank@corp.com", f"Got email={ra.get('email')!r}"
        assert ra.get("dept") == "Engineering", f"Got dept={ra.get('dept')!r}"
        assert ra.get("employeeType") == "FTE", (
            f"Got employeeType={ra.get('employeeType')!r}"
        )
        assert ra.get("groups") == ["engineering", "vpn-users"], (
            f"Got groups={ra.get('groups')!r}"
        )
        # Must NOT use OIDC or LDAP keys
        assert "name" not in ra, "SAML scene must not have 'name' key"
        assert "department" not in ra, "SAML scene must not have 'department' key"
        assert "cn" not in ra, "SAML scene must not have 'cn' key"

    def test_scene2_grace_ldap_raw_attributes(self, demo_module) -> None:
        """Scene 2: grace/ldap uses LDAP native keys with exact values."""
        ra = demo_module.SCENES[2]["raw_attributes"]
        assert ra.get("cn") == "Grace Hopper", f"Got cn={ra.get('cn')!r}"
        assert ra.get("mail") == "grace@corp.com", f"Got mail={ra.get('mail')!r}"
        assert ra.get("departmentNumber") == "r&d", (
            f"Got departmentNumber={ra.get('departmentNumber')!r}"
        )
        assert ra.get("employeeType") == "C", (
            f"Got employeeType={ra.get('employeeType')!r}"
        )
        expected_member_of = [
            "cn=engineering,ou=groups,dc=corp,dc=com",
            "cn=admins,ou=groups,dc=corp,dc=com",
        ]
        assert ra.get("memberOf") == expected_member_of, (
            f"Got memberOf={ra.get('memberOf')!r}"
        )
        # Must NOT use OIDC or SAML keys
        assert "name" not in ra, "LDAP scene must not have 'name' key"
        assert "displayName" not in ra, "LDAP scene must not have 'displayName' key"
        assert "groups" not in ra, "LDAP scene must not have 'groups' key"

    def test_scene3_mallory_saml_raw_attributes(self, demo_module) -> None:
        """Scene 3: mallory/saml uses SAML native keys with exact values."""
        ra = demo_module.SCENES[3]["raw_attributes"]
        assert ra.get("displayName") == "Mallory Quinn", (
            f"Got displayName={ra.get('displayName')!r}"
        )
        assert ra.get("email") == "mallory@corp.com", f"Got email={ra.get('email')!r}"
        assert ra.get("dept") == "Sorcery", f"Got dept={ra.get('dept')!r}"
        assert ra.get("employeeType") == "wizard", (
            f"Got employeeType={ra.get('employeeType')!r}"
        )
        assert ra.get("groups") == ["temp-access"], f"Got groups={ra.get('groups')!r}"

    def test_scene4_alice_oidc_raw_attributes(self, demo_module) -> None:
        """Scene 4: alice/oidc uses OIDC native keys with exact values."""
        ra = demo_module.SCENES[4]["raw_attributes"]
        assert ra.get("name") == "Alice Smith", f"Got name={ra.get('name')!r}"
        assert ra.get("email") == "alice@corp.com", f"Got email={ra.get('email')!r}"
        assert ra.get("department") == "eng", f"Got department={ra.get('department')!r}"
        assert ra.get("employee_type") == "FTE", (
            f"Got employee_type={ra.get('employee_type')!r}"
        )
        assert ra.get("groups") == ["engineering", "vpn-users", "product-admins"], (
            f"Got groups={ra.get('groups')!r}"
        )

    def test_scene5_diana_oidc_raw_attributes(self, demo_module) -> None:
        """Scene 5: diana/oidc uses OIDC native keys with exact values."""
        ra = demo_module.SCENES[5]["raw_attributes"]
        assert ra.get("name") == "Di Prince", f"Got name={ra.get('name')!r}"
        assert ra.get("email") == "diana@corp.com", f"Got email={ra.get('email')!r}"
        assert ra.get("department") == "Marketing", (
            f"Got department={ra.get('department')!r}"
        )
        assert ra.get("employee_type") == "vendor", (
            f"Got employee_type={ra.get('employee_type')!r}"
        )
        assert ra.get("groups") == ["engineering", "oncall"], (
            f"Got groups={ra.get('groups')!r}"
        )


# ---------------------------------------------------------------------------
# Class: soft naas_shared import contract
# ---------------------------------------------------------------------------


class TestNaasSharedSoftImport:
    """naas_shared import must be wrapped in try/except so its absence does not raise.

    Behavioral tests: exercise the import guard in a subprocess where naas_shared
    is (or is not) importable, then check the NAAS_SHARED_AVAILABLE flag.  This
    approach tests the actual runtime behaviour rather than AST shape.
    """

    _DRIVER_UNAVAILABLE = """\
import sys
# Clear any naas_shared sub-modules already cached, then block the package.
for key in list(sys.modules):
    if key == "naas_shared" or key.startswith("naas_shared."):
        del sys.modules[key]
sys.modules["naas_shared"] = None  # None sentinel causes ImportError on import
# Also block common submodule paths
sys.modules["naas_shared.models"] = None
import importlib
import importlib.util
spec = importlib.util.spec_from_file_location("demo_normalization", r"{script}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
flag = mod.NAAS_SHARED_AVAILABLE
print("NAAS_SHARED_AVAILABLE=" + str(flag))
assert flag is False, f"Expected NAAS_SHARED_AVAILABLE=False, got {{flag!r}}"
"""

    _DRIVER_AVAILABLE = """\
import importlib
import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("demo_normalization", r"{script}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
flag = mod.NAAS_SHARED_AVAILABLE
print("NAAS_SHARED_AVAILABLE=" + str(flag))
assert flag is True, f"Expected NAAS_SHARED_AVAILABLE=True, got {{flag!r}}"
"""

    def test_module_still_imports_when_naas_shared_unavailable(self) -> None:
        """demo_normalization must import without error and set NAAS_SHARED_AVAILABLE=False
        when naas_shared is blocked from importing.

        Uses a subprocess driver that injects None into sys.modules for naas_shared
        before loading the demo module — this reliably simulates an absent package
        without needing to manipulate the installed environment.
        """
        driver = self._DRIVER_UNAVAILABLE.format(script=str(DEMO_SCRIPT))
        result = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"demo_normalization failed to import when naas_shared is absent.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "NAAS_SHARED_AVAILABLE=False" in result.stdout, (
            f"Expected NAAS_SHARED_AVAILABLE=False when naas_shared is blocked.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_module_sets_available_true_when_naas_shared_importable(self) -> None:
        """NAAS_SHARED_AVAILABLE is True when naas_shared is importable.

        Skipped when naas_shared is not installed in this venv (the flag would be
        False and the assertion would fail — that is correct behaviour but it is not
        a test of this scenario).
        """
        # Pre-check: can we actually import naas_shared in this process?
        import importlib.util as _ilu

        if _ilu.find_spec("naas_shared") is None:
            pytest.skip(
                "naas_shared not installed in this venv — skipping the 'available=True' direction"
            )

        driver = self._DRIVER_AVAILABLE.format(script=str(DEMO_SCRIPT))
        result = subprocess.run(
            [sys.executable, "-c", driver],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"demo_normalization unexpectedly failed to import with naas_shared available.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "NAAS_SHARED_AVAILABLE=True" in result.stdout, (
            f"Expected NAAS_SHARED_AVAILABLE=True when naas_shared is importable.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Class: requirements.txt content
# ---------------------------------------------------------------------------


class TestRequirementsTxt:
    """demo/requirements.txt lists rich, httpx, psycopg[binary] with pinned versions."""

    def test_requirements_file_exists(self) -> None:
        """demo/requirements.txt must exist."""
        assert DEMO_REQUIREMENTS.exists(), (
            f"demo/requirements.txt not found at {DEMO_REQUIREMENTS}"
        )

    def test_rich_is_listed(self, requirements_text: str) -> None:
        """requirements.txt must list rich with a pinned version."""
        assert re.search(r"^rich[>=<!\[]", requirements_text, re.MULTILINE), (
            f"'rich' with a version pin not found in requirements.txt:\n{requirements_text}"
        )

    def test_httpx_is_listed(self, requirements_text: str) -> None:
        """requirements.txt must list httpx with a pinned version."""
        assert re.search(r"^httpx[>=<!\[]", requirements_text, re.MULTILINE), (
            f"'httpx' with a version pin not found in requirements.txt:\n{requirements_text}"
        )

    def test_psycopg_binary_is_listed(self, requirements_text: str) -> None:
        """requirements.txt must list psycopg[binary] with a pinned version."""
        # Accept psycopg[binary]==... or psycopg[binary]>=... etc.
        assert re.search(r"^psycopg\[binary\]", requirements_text, re.MULTILINE), (
            f"'psycopg[binary]' not found in requirements.txt:\n{requirements_text}"
        )

    def test_naas_shared_not_listed(self, requirements_text: str) -> None:
        """requirements.txt must NOT list naas_shared — it is a soft optional import."""
        lines = [ln.strip() for ln in requirements_text.splitlines()]
        naas_lines = [
            ln
            for ln in lines
            if ln.startswith("naas_shared") or ln.startswith("naas-shared")
        ]
        assert not naas_lines, (
            f"naas_shared must not appear in requirements.txt (soft import only), "
            f"found: {naas_lines}"
        )


# ---------------------------------------------------------------------------
# Class: README.md content
# ---------------------------------------------------------------------------


class TestReadme:
    """demo/README.md documents the five required items."""

    def test_readme_file_exists(self) -> None:
        """demo/README.md must exist."""
        assert DEMO_README.exists(), f"demo/README.md not found at {DEMO_README}"

    def test_readme_mentions_docker_compose_up(self, readme_text: str) -> None:
        """README must include the docker compose up -d stack-start command."""
        assert "docker compose up" in readme_text, (
            "README must include 'docker compose up' start command"
        )

    def test_readme_mentions_pip_install_requirements(self, readme_text: str) -> None:
        """README must include pip install -r demo/requirements.txt."""
        assert "pip install" in readme_text and "requirements.txt" in readme_text, (
            "README must include pip install -r demo/requirements.txt"
        )

    def test_readme_mentions_run_command(self, readme_text: str) -> None:
        """README must include the python demo/demo_normalization.py run command."""
        assert "demo_normalization.py" in readme_text, (
            "README must include 'python demo/demo_normalization.py' run command"
        )

    def test_readme_mentions_flags(self, readme_text: str) -> None:
        """README must document at least one of the CLI flags (e.g. --pace)."""
        flag_mentions = sum(
            1
            for flag in [
                "--keep",
                "--pace",
                "--step",
                "--timeout",
                "--skip-verify",
                "--ingest-url",
                "--db-dsn",
            ]
            if flag in readme_text
        )
        assert flag_mentions > 0, "README must document the CLI flags"

    def test_readme_mentions_postgres_direct_read_honesty_note(
        self, readme_text: str
    ) -> None:
        """README must include the honesty note that the demo reads PostgreSQL directly."""
        # The note must reference PostgreSQL (or postgres/pg) and the reason
        # (query API not yet built / direct read).
        has_postgres = bool(re.search(r"[Pp]ostgres", readme_text))
        has_direct = bool(
            re.search(
                r"direct(ly)?|reads?\s+[Pp]ostgres|PostgreSQL\s+direct",
                readme_text,
                re.IGNORECASE,
            )
        )
        assert has_postgres and has_direct, (
            "README must contain the honesty note that the demo reads PostgreSQL directly "
            "because the query API is not yet built.\n"
            f"has_postgres={has_postgres}, has_direct={has_direct}"
        )


# ---------------------------------------------------------------------------
# Class: no meta/promotional language in demo files
# ---------------------------------------------------------------------------


class TestNoMetaLanguage:
    """Demo files must not contain promotional or audience-targeting language."""

    BANNED_TOKENS = [
        "money shot",
        "hiring",
        "recruiter",
        "senior engineer",
    ]

    @pytest.mark.parametrize("token", BANNED_TOKENS)
    def test_banned_token_absent(self, token: str) -> None:
        """No demo file may contain the banned token.

        Requires the demo directory to exist — fails (not skips) if it is absent,
        because absent files cannot be verified clean.
        """
        if not DEMO_DIR.exists():
            pytest.fail(
                f"demo/ directory not found at {DEMO_DIR}; "
                "cannot verify absence of banned token"
            )
        target_files = [DEMO_SCRIPT, DEMO_REQUIREMENTS, DEMO_README]
        for fpath in target_files:
            assert fpath.exists(), f"Expected demo file {fpath} to exist"
            text = fpath.read_text(encoding="utf-8")
            assert token.lower() not in text.lower(), (
                f"Banned token {token!r} found in {fpath}"
            )
