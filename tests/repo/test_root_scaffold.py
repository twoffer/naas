"""Root scaffold: .env.example, directory structure, and required configuration files."""

import re
from pathlib import Path

# third-party
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from tests.helpers import REPO_ROOT

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def env_example_path() -> Path:
    return REPO_ROOT / ".env.example"


@pytest.fixture(scope="module")
def env_example_text(env_example_path) -> str:
    """Read .env.example content once for the whole module."""
    if not env_example_path.exists():
        pytest.skip(".env.example not found")
    return env_example_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# .env.example — existence
# ---------------------------------------------------------------------------


class TestEnvExampleExists:
    """Verify .env.example is present in the repo root."""

    def test_env_example_file_exists(self, env_example_path):
        """
        .env.example must exist so developers can bootstrap their local .env
        without committing secrets.
        """
        assert env_example_path.exists(), (
            f".env.example not found at {env_example_path}"
        )

    def test_env_example_is_a_file_not_directory(self, env_example_path):
        """Guard against accidental creation of an .env.example/ directory."""
        assert env_example_path.is_file(), (
            f"{env_example_path} exists but is not a regular file"
        )


# ---------------------------------------------------------------------------
# .env.example — required key=value lines
# ---------------------------------------------------------------------------


class TestEnvExampleRequiredVars:
    """
    Every variable listed here is consumed by at least one downstream service.
    Missing or wrong values cause runtime failures that are hard to diagnose.
    Tests are intentionally granular so a partial implementation can flip
    individual tests green.
    """

    # --- Infrastructure anchors ---

    def test_env_example_contains_postgres_host(self, env_example_text):
        """POSTGRES_HOST must be set to 'postgres' (Docker service name)."""
        assert "POSTGRES_HOST=postgres" in env_example_text, (
            "Expected 'POSTGRES_HOST=postgres' in .env.example"
        )

    def test_env_example_contains_ldap_pool_size(self, env_example_text):
        """LDAP_POOL_SIZE=3 controls the OpenLDAP connection pool in the
        identity-normalization service.  Wrong value → pool exhaustion under load."""
        assert "LDAP_POOL_SIZE=3" in env_example_text, (
            "Expected 'LDAP_POOL_SIZE=3' in .env.example"
        )

    def test_env_example_contains_llm_provider(self, env_example_text):
        """LLM_PROVIDER=mock ensures the persona-simulator starts without
        requiring any external API keys in development."""
        assert "LLM_PROVIDER=mock" in env_example_text, (
            "Expected 'LLM_PROVIDER=mock' in .env.example"
        )

    def test_env_example_contains_keycloak_realm(self, env_example_text):
        """KEYCLOAK_REALM=naas-demo must match the exported realm config
        shipped with the project."""
        assert "KEYCLOAK_REALM=naas-demo" in env_example_text, (
            "Expected 'KEYCLOAK_REALM=naas-demo' in .env.example"
        )

    # --- Service port variables (all eight, exact values) ---

    def test_env_example_contains_api_gateway_port(self, env_example_text):
        """API_GATEWAY_PORT=8000 — port 8000 is the public-facing entry point."""
        assert "API_GATEWAY_PORT=8000" in env_example_text, (
            "Expected 'API_GATEWAY_PORT=8000' in .env.example"
        )

    def test_env_example_contains_event_ingestion_port(self, env_example_text):
        """EVENT_INGESTION_PORT=8001."""
        assert "EVENT_INGESTION_PORT=8001" in env_example_text, (
            "Expected 'EVENT_INGESTION_PORT=8001' in .env.example"
        )

    def test_env_example_contains_identity_normalization_port(self, env_example_text):
        """IDENTITY_NORMALIZATION_PORT=8002."""
        assert "IDENTITY_NORMALIZATION_PORT=8002" in env_example_text, (
            "Expected 'IDENTITY_NORMALIZATION_PORT=8002' in .env.example"
        )

    def test_env_example_contains_signal_enrichment_port(self, env_example_text):
        """SIGNAL_ENRICHMENT_PORT=8003."""
        assert "SIGNAL_ENRICHMENT_PORT=8003" in env_example_text, (
            "Expected 'SIGNAL_ENRICHMENT_PORT=8003' in .env.example"
        )

    def test_env_example_contains_policy_management_port(self, env_example_text):
        """POLICY_MANAGEMENT_PORT=8004."""
        assert "POLICY_MANAGEMENT_PORT=8004" in env_example_text, (
            "Expected 'POLICY_MANAGEMENT_PORT=8004' in .env.example"
        )

    def test_env_example_contains_risk_evaluator_port(self, env_example_text):
        """RISK_EVALUATOR_PORT=8005."""
        assert "RISK_EVALUATOR_PORT=8005" in env_example_text, (
            "Expected 'RISK_EVALUATOR_PORT=8005' in .env.example"
        )

    def test_env_example_contains_alert_service_port(self, env_example_text):
        """ALERT_SERVICE_PORT=8006."""
        assert "ALERT_SERVICE_PORT=8006" in env_example_text, (
            "Expected 'ALERT_SERVICE_PORT=8006' in .env.example"
        )

    def test_env_example_contains_persona_simulator_port(self, env_example_text):
        """PERSONA_SIMULATOR_PORT=8007 — last service port in the sequence."""
        assert "PERSONA_SIMULATOR_PORT=8007" in env_example_text, (
            "Expected 'PERSONA_SIMULATOR_PORT=8007' in .env.example"
        )


# ---------------------------------------------------------------------------
# .env.example — coverage of docker-compose ${VAR} references
# ---------------------------------------------------------------------------
#
# Note: we deliberately do NOT assert anything about the local .env file.
# .env is gitignored (it does not exist on a fresh clone) and is expected to
# drift from .env.example — e.g. POSTGRES_HOST=localhost for bare-metal runs,
# per SPEC_0's "Docker network DNS" note.  Pinning .env to equal .env.example
# would punish exactly the documented local-override workflow.  The real
# anti-staleness invariant lives below: the committed template must cover
# everything docker compose interpolates.


@pytest.fixture(scope="module")
def env_example_keys(env_example_text) -> set:
    """Variable names defined as `KEY=...` lines in .env.example."""
    keys = set()
    for line in env_example_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


@pytest.fixture(scope="module")
def compose_env_references() -> set:
    """Every variable interpolated via ${VAR} (incl. ${VAR:-default}) in
    docker-compose.yml — i.e. the values docker compose substitutes from the
    environment (sourced from .env)."""
    compose_path = REPO_ROOT / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip("docker-compose.yml not found")
    text = compose_path.read_text(encoding="utf-8")
    return set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", text))


class TestEnvExampleCoversComposeReferences:
    """
    .env.example must define every variable that docker-compose.yml
    interpolates via ${VAR}.  This is the real anti-staleness guard: it fails
    when a new compose interpolation is added without a matching .env.example
    entry, which would silently break `docker compose up` after a fresh
    `cp .env.example .env` (compose would substitute an empty string).
    """

    def test_compose_has_env_references(self, compose_env_references):
        """Sanity check so the coverage assertion below is never vacuous: if
        the regex stops matching any ${VAR}, fail loudly rather than pass."""
        assert compose_env_references, (
            "No ${VAR} interpolations found in docker-compose.yml — the "
            "coverage check would be vacuously true."
        )

    def test_env_example_covers_all_compose_references(
        self, compose_env_references, env_example_keys
    ):
        """Every ${VAR} in docker-compose.yml must have a KEY= line in
        .env.example."""
        missing = sorted(compose_env_references - env_example_keys)
        assert not missing, (
            "docker-compose.yml interpolates variables with no entry in "
            f".env.example: {missing}. Add them to .env.example so a fresh "
            "`cp .env.example .env` yields a working stack."
        )


# ---------------------------------------------------------------------------
# services/<name>/README.md — existence and required content
# ---------------------------------------------------------------------------

EXPECTED_SERVICES = [
    "api-gateway",
    "event-ingestion",
    "identity-normalization",
    "signal-enrichment",
    "risk-evaluator",
    "policy-management",
    "alert-service",
    "persona-simulator",
]

# Application services whose directories now contain implementation code (not just
# a README) because their spec has landed.  Append here as future specs land so the
# "only README" guard keeps protecting un-implemented services without flagging the
# implemented ones.  README existence/is-file still apply to all eight; the canonical
# scaffold-marker phrase is required only for the scaffold-only services, while the
# implemented services carry substantive, hand-written READMEs instead.
IMPLEMENTED_APP_SERVICES = {
    "event-ingestion",
    "identity-normalization",
}  # Spec 1, Spec 2

# Services still expected to be scaffold-only (README.md and nothing else).
SCAFFOLD_ONLY_SERVICES = [
    s for s in EXPECTED_SERVICES if s not in IMPLEMENTED_APP_SERVICES
]

REQUIRED_README_PHRASE = "Part of the NAAS system."


class TestServiceReadmeFiles:
    """
    Each service directory must contain a README.md. Scaffold-only services must
    carry the canonical phrase, which confirms the README was created intentionally
    (not accidentally empty or copied from somewhere else). Implemented services
    instead carry substantive, hand-written READMEs (guarded for non-triviality).
    """

    @pytest.mark.parametrize("service_name", EXPECTED_SERVICES)
    def test_service_readme_exists(self, service_name):
        """services/<name>/README.md must exist for every one of the eight services."""
        readme = REPO_ROOT / "services" / service_name / "README.md"
        assert readme.exists(), (
            f"README.md not found for service '{service_name}' at {readme}"
        )

    @pytest.mark.parametrize("service_name", EXPECTED_SERVICES)
    def test_service_readme_is_file(self, service_name):
        """README.md must be a regular file, not a directory."""
        readme = REPO_ROOT / "services" / service_name / "README.md"
        assert readme.is_file(), (
            f"services/{service_name}/README.md exists but is not a regular file"
        )

    @pytest.mark.parametrize("service_name", SCAFFOLD_ONLY_SERVICES)
    def test_scaffold_service_readme_contains_required_phrase(self, service_name):
        """
        Each scaffold-only service README.md must contain 'Part of the NAAS system.'
        — the canonical phrase that marks the file as intentionally scaffolded.
        Implemented services are exempt (they carry real READMEs); see
        test_implemented_service_readme_is_substantive.
        """
        readme = REPO_ROOT / "services" / service_name / "README.md"
        if not readme.exists():
            pytest.fail(
                f"services/{service_name}/README.md does not exist — cannot check content"
            )
        content = readme.read_text(encoding="utf-8")
        assert REQUIRED_README_PHRASE in content, (
            f"services/{service_name}/README.md does not contain "
            f"'{REQUIRED_README_PHRASE}'. Actual content: {content!r}"
        )

    @pytest.mark.parametrize("service_name", sorted(IMPLEMENTED_APP_SERVICES))
    def test_implemented_service_readme_is_substantive(self, service_name):
        """
        Each implemented service README.md must be a real, hand-written document —
        not the scaffold stub and not accidentally empty. Guards non-triviality
        (a meaningful length and a title heading) without pinning exact prose.
        """
        readme = REPO_ROOT / "services" / service_name / "README.md"
        content = readme.read_text(encoding="utf-8")
        assert len(content) > 400, (
            f"services/{service_name}/README.md looks like a stub "
            f"({len(content)} chars) — implemented services need a real README"
        )
        assert content.lstrip().startswith("# "), (
            f"services/{service_name}/README.md must open with a top-level heading"
        )


# ---------------------------------------------------------------------------
# services/<name>/ — directory must contain ONLY README.md
# ---------------------------------------------------------------------------


class TestServiceDirectoryContents:
    """
    Not-yet-implemented services have placeholder directories with exactly one
    file each (README.md).  Any additional file (Dockerfile, app/,
    requirements.txt) belongs to a later spec and must not appear here.
    Enforcing this prevents accidental scope creep from contaminating the test
    baseline.  Once a service's spec lands it is moved to
    IMPLEMENTED_APP_SERVICES and excluded from this guard (its code is then
    covered by that spec's own test suite).
    """

    @pytest.mark.parametrize("service_name", SCAFFOLD_ONLY_SERVICES)
    def test_service_directory_contains_only_readme(self, service_name):
        """
        services/<name>/ must contain exactly one entry: README.md.
        No Dockerfiles, no app/ subdirectories, no requirements.txt.
        """
        service_dir = REPO_ROOT / "services" / service_name
        if not service_dir.exists():
            pytest.fail(f"services/{service_name}/ directory does not exist")

        # Collect all entries (files and dirs) directly inside the service dir.
        # We do NOT recurse — a nested structure inside README.md/ would be
        # caught by the is_file test above.
        entries = {entry.name for entry in service_dir.iterdir()}

        assert entries == {"README.md"}, (
            f"services/{service_name}/ must contain only 'README.md', "
            f"but found: {sorted(entries)}"
        )


# ---------------------------------------------------------------------------
# config/ and scripts/ — directories exist, specific files do NOT
# ---------------------------------------------------------------------------


class TestConfigAndScriptsDirs:
    """
    config/ and scripts/ directories exist (initialized via .gitkeep
    placeholders).  Their real content (normalization.yaml,
    train_bootstrap_model.py) is created by their respective specs.
    """

    def test_config_directory_exists(self):
        """config/ must exist."""
        config_dir = REPO_ROOT / "config"
        assert config_dir.exists(), f"config/ directory not found at {config_dir}"
        assert config_dir.is_dir(), f"{config_dir} exists but is not a directory"

    def test_scripts_directory_exists(self):
        """scripts/ must exist."""
        scripts_dir = REPO_ROOT / "scripts"
        assert scripts_dir.exists(), f"scripts/ directory not found at {scripts_dir}"
        assert scripts_dir.is_dir(), f"{scripts_dir} exists but is not a directory"

    def test_normalization_yaml_exists(self):
        """
        config/normalization.yaml must exist and be a valid YAML file with the
        top-level keys defined by Spec 2 (attributes, defaults, enrichment).

        This test started as a negative guard that flipped to a positive assertion
        when Spec 2 (Identity Normalization Service) legitimately created the file —
        the same kind of registry maintenance applied to IMPLEMENTED_APP_SERVICES
        when each new spec lands.
        """
        import yaml  # lazy function-scoped import: yaml is third-party; deferred to avoid module-level dep

        normalization_yaml = REPO_ROOT / "config" / "normalization.yaml"
        assert normalization_yaml.exists(), (
            f"config/normalization.yaml not found at {normalization_yaml} — "
            f"expected to be created by Spec 2."
        )
        assert normalization_yaml.is_file(), (
            f"{normalization_yaml} exists but is not a regular file"
        )
        content = yaml.safe_load(normalization_yaml.read_text(encoding="utf-8"))
        assert isinstance(content, dict), (
            "config/normalization.yaml must parse as a YAML mapping"
        )
        expected_keys = {"attributes", "defaults", "enrichment"}
        missing = expected_keys - content.keys()
        assert not missing, (
            f"config/normalization.yaml is missing top-level keys: {missing}"
        )

    def test_train_bootstrap_model_does_not_exist(self):
        """
        scripts/train_bootstrap_model.py must NOT exist yet.
        The script is created by Spec 3.
        """
        bootstrap_script = REPO_ROOT / "scripts" / "train_bootstrap_model.py"
        assert not bootstrap_script.exists(), (
            f"scripts/train_bootstrap_model.py must not exist — "
            f"it belongs to Spec 3.  Found at: {bootstrap_script}"
        )


# ---------------------------------------------------------------------------
# .gitignore — required lines
# ---------------------------------------------------------------------------


class TestGitignoreLines:
    """
    .gitignore must contain specific entries that protect secrets and generated
    artifacts from accidental commits.  Each line is tested independently so
    a partial implementation still gives useful signal.
    """

    @pytest.fixture(scope="class")
    def gitignore_lines(self):
        gitignore_path = REPO_ROOT / ".gitignore"
        assert gitignore_path.exists(), f".gitignore not found at {gitignore_path}"
        # Split into lines, strip trailing whitespace per line, keep blank lines
        # as-is so line-presence checks match regardless of trailing spaces.
        return [
            line.rstrip()
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
        ]

    def test_gitignore_contains_dot_env(self, gitignore_lines):
        """
        .env must be gitignored to prevent accidental secret commit.
        This is a security requirement.
        """
        assert ".env" in gitignore_lines, (
            "'.env' line not found in .gitignore — secrets could be committed"
        )

    def test_gitignore_contains_pycache(self, gitignore_lines):
        """__pycache__/ must be gitignored — Python bytecode cache directories."""
        assert "__pycache__/" in gitignore_lines, (
            "'__pycache__/' not found in .gitignore"
        )

    def test_gitignore_contains_postgres_data(self, gitignore_lines):
        """postgres-data/ must be gitignored — Docker volume mount for PostgreSQL."""
        assert "postgres-data/" in gitignore_lines, (
            "'postgres-data/' not found in .gitignore"
        )

    def test_gitignore_contains_redis_data(self, gitignore_lines):
        """redis-data/ must be gitignored — Docker volume mount for Redis."""
        assert "redis-data/" in gitignore_lines, "'redis-data/' not found in .gitignore"

    def test_gitignore_contains_pkl_pattern(self, gitignore_lines):
        """
        *.pkl must be gitignored — trained ML model artifacts can be hundreds
        of MB and must never be committed to the repository.
        """
        assert "*.pkl" in gitignore_lines, (
            "'*.pkl' not found in .gitignore — ML model artifacts could be committed"
        )


# ---------------------------------------------------------------------------
# README.md — tagline preservation
# ---------------------------------------------------------------------------


class TestRootReadme:
    """
    README.md must exist and preserve its project tagline.  Any operation
    that silently overwrites README.md would break this test.
    """

    def test_readme_exists(self):
        """README.md must exist at the repo root."""
        readme = REPO_ROOT / "README.md"
        assert readme.exists(), f"README.md not found at {readme}"

    def test_readme_contains_tagline(self):
        """
        README.md must contain 'Normalized Adaptive Access System' — the
        project tagline that identifies the repo purpose.
        """
        readme = REPO_ROOT / "README.md"
        assert readme.exists(), "README.md does not exist — cannot check tagline"
        content = readme.read_text(encoding="utf-8")
        assert "Normalized Adaptive Access System" in content, (
            "README.md does not contain 'Normalized Adaptive Access System'. "
            f"Actual content: {content!r}"
        )
