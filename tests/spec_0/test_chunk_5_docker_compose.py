# Component: NAAS Spec 0 — Chunk 5: docker-compose.yml orchestration
# Mode: TDD — all tests MUST fail until docker-compose.yml is created
#
# What these tests validate (STATIC only — no containers started):
#   - docker-compose.yml exists at repo root
#   - It is valid YAML (PyYAML safe_load) and passes `docker compose config -q`
#   - Services mapping contains EXACTLY {postgres, redis, keycloak, openldap} —
#     this simultaneously enforces "no application service containers yet"
#   - Per-service image tags, bind-mount sources, named volumes, network membership
#   - Keycloak has NO KC_DB* env vars (H2 dev mode per Architect's Note §3.1)
#   - Keycloak command contains `start-dev` AND `--import-realm`
#   - Top-level networks: naas-network with driver: bridge
#   - Top-level volumes: exactly the four named volumes required
#   - Compose source files from Chunks 1/3/4 exist on disk (bind-mounted for
#     postgres/redis/keycloak; a Dockerfile COPY source for openldap)
#   - Explicit negative assertion: no application-layer service names present
#
# Why this matters:
#   docker-compose.yml is the runtime contract for the entire infrastructure stack.
#   Missing or wrong images break downstream service connectivity. Extra service
#   containers in this file violate the Spec 0 scope boundary (§1 "no application
#   services yet"). The KC_DB* absence is a security / correctness invariant: any
#   KC_DB var causes Keycloak to attempt PG connection which fails, hanging the
#   entire stack on startup. The compose source paths must match the exact files
#   created in Chunks 1/3/4, otherwise container startup silently creates empty
#   directories in place of the expected bind-mounted files (or, for openldap,
#   the image build fails because the Dockerfile COPY source is missing).
#
# PyYAML availability:
#   PyYAML (pyyaml 6.0+) was installed into the project venv during test authoring
#   (`pip install pyyaml`). All YAML-parse tests use `pytest.importorskip("yaml")`
#   so they skip cleanly on any CI environment where the package is absent rather
#   than erroring with an ImportError. The `docker compose config` subprocess test
#   is provided as an independent cross-check and skips if the `docker` CLI is not
#   on PATH.
#
# TDD contract:
#   Tests that depend on docker-compose.yml MUST FAIL until it is created.
#   Tests that assert bind-mount source files exist (from prior chunks) MAY PASS
#   right now — this is intentional and noted inline. The suite as a whole fails
#   because docker-compose.yml is absent.

# stdlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo root discovery (same pattern used across all spec_0 test files)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory containing
    docs/architecture/ — the canonical repo root marker.  Capped at 10
    levels to prevent runaway traversal.
    """
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        "Could not locate repo root (expected a directory containing "
        f"docs/architecture/).  Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# Infrastructure services that MUST always be present.
REQUIRED_SERVICES = {"postgres", "redis", "keycloak", "openldap"}

# Application services implemented by specs that have landed since Spec 0 — these
# now legitimately appear in docker-compose.yml.  As each future spec adds its
# service, append its name here so the scope-boundary guards below keep protecting
# the not-yet-implemented services without flagging the implemented ones.
IMPLEMENTED_APP_SERVICES = {"event-ingestion"}  # Spec 1

# Every application service name (none of which exist at Spec 0 stage).
ALL_APP_SERVICES = {
    "api-gateway",
    "event-ingestion",
    "identity-normalization",
    "signal-enrichment",
    "risk-evaluator",
    "policy-management",
    "alert-service",
    "persona-simulator",
    "dashboard",
}

# Application service names that must NOT appear yet (not implemented).
FORBIDDEN_SERVICES = ALL_APP_SERVICES - IMPLEMENTED_APP_SERVICES

# Named volumes required at top level
REQUIRED_VOLUMES = {"postgres-data", "redis-data", "ldap-data", "ldap-config"}

# Source files (relative to repo root) from Chunks 1/3/4 that the compose stack
# depends on existing. The first three are bind-mounted at runtime; the openldap
# bootstrap.ldif is a Dockerfile COPY source baked into naas-openldap:local
# (see TestOpenLdapService). Either way, each must exist on disk.
REQUIRED_SOURCE_FILES = [
    Path("infrastructure/postgres/init.sql"),
    Path("infrastructure/redis/redis.conf"),
    Path("infrastructure/keycloak/naas-realm-export.json"),
    Path("infrastructure/openldap/bootstrap.ldif"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_compose() -> dict[str, Any]:
    """Parse docker-compose.yml with yaml.safe_load.

    Raises FileNotFoundError if the file is absent (allowing tests that call
    this to fail immediately with a clear message rather than an AttributeError).
    Returns the parsed dict.
    """
    yaml = pytest.importorskip("yaml")
    if not COMPOSE_FILE.exists():
        pytest.fail(
            f"docker-compose.yml not found at {COMPOSE_FILE}. "
            "This file must be created by the Chunk 5 implementer."
        )
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _extract_bind_mounts(service_cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (source, target) pairs from a service's `volumes` list.

    Handles both:
      - Short string syntax: "./src:/dest"  or  "./src:/dest:ro"
      - Long dict syntax:    {type: bind, source: ..., target: ...}

    Named volume references (e.g. "postgres-data:/var/lib/...") are excluded
    because they start with a volume name, not a relative ./path.
    """
    mounts = []
    for entry in service_cfg.get("volumes", []):
        if isinstance(entry, str):
            # Skip named-volume shorthand (no leading './' or '/')
            if entry.startswith("./") or entry.startswith("/"):
                parts = entry.split(":")
                if len(parts) >= 2:
                    mounts.append((parts[0], parts[1]))
        elif isinstance(entry, dict) and entry.get("type") == "bind":
            source = entry.get("source", "")
            target = entry.get("target", "")
            if source and target:
                mounts.append((source, target))
    return mounts


def _get_env_keys(service_cfg: dict[str, Any]) -> list[str]:
    """Extract environment variable names from a service config.

    Handles both list form  (["KEY=value", "KEY2"])
    and   dict form   ({KEY: value, KEY2: null}).
    """
    env = service_cfg.get("environment", {})
    if isinstance(env, list):
        keys = []
        for item in env:
            if isinstance(item, str):
                keys.append(item.split("=")[0])
            else:
                keys.append(str(item))
        return keys
    if isinstance(env, dict):
        return list(env.keys())
    return []


def _command_as_string(service_cfg: dict[str, Any]) -> str:
    """Return the service command as a single string for substring checks.

    Docker Compose accepts `command` as either a string or a list.
    """
    cmd = service_cfg.get("command", "")
    if isinstance(cmd, list):
        return " ".join(str(tok) for tok in cmd)
    return str(cmd)


def _service_networks(service_cfg: dict[str, Any]) -> list[str]:
    """Return the network names a service is attached to."""
    nets = service_cfg.get("networks", [])
    if isinstance(nets, list):
        return nets
    if isinstance(nets, dict):
        return list(nets.keys())
    return []


def _service_volume_refs(service_cfg: dict[str, Any]) -> list[str]:
    """Return all volume reference strings from a service's volumes list."""
    refs = []
    for entry in service_cfg.get("volumes", []):
        if isinstance(entry, str):
            refs.append(entry)
        elif isinstance(entry, dict):
            refs.append(entry.get("source", ""))
    return refs


# ---------------------------------------------------------------------------
# Fixture: parsed compose document (shared across all YAML tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    """Parsed docker-compose.yml document.

    Fails fast if the file is absent (the expected TDD state) or unparseable.
    """
    return _load_compose()


# ===========================================================================
# CLASS 1 — File Existence and Parseability
# ===========================================================================


class TestComposeFileExistence:
    """docker-compose.yml must exist and be parseable before any structural
    checks can run.  These are the gating tests for the entire suite."""

    def test_docker_compose_file_exists_at_repo_root(self) -> None:
        """docker-compose.yml must be present at the repo root.

        WHY: Every other test in this suite depends on this file. Its absence
        confirms we are in the TDD-initial state where the implementer has not
        yet created the file.
        """
        assert COMPOSE_FILE.exists(), (
            f"docker-compose.yml not found at {COMPOSE_FILE}. "
            "The Chunk 5 implementer must create this file."
        )

    def test_docker_compose_is_valid_yaml(self) -> None:
        """docker-compose.yml must parse without error via yaml.safe_load.

        WHY: Malformed YAML causes all Docker Compose commands to fail with
        cryptic parse errors. Catching this statically is faster than a live
        `docker compose config` call.
        """
        yaml = pytest.importorskip("yaml")
        assert COMPOSE_FILE.exists(), (
            f"Cannot parse: {COMPOSE_FILE} does not exist yet."
        )
        try:
            doc = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            pytest.fail(
                f"docker-compose.yml failed YAML parse: {exc}"
            )
        assert doc is not None, "yaml.safe_load returned None — file is empty"
        assert isinstance(doc, dict), (
            f"Expected YAML root to be a mapping, got {type(doc).__name__}"
        )

    def test_docker_compose_validates_via_docker_compose_config(self) -> None:
        """docker compose config -q must exit 0 for a valid compose file.

        WHY: PyYAML only validates YAML syntax; `docker compose config`
        validates Compose-specific semantics (image references, network
        definitions, volume names, etc.) that pure YAML parsing cannot catch.
        This test provides an independent second-opinion check.

        SKIP: If the `docker` binary is not on PATH (portable CI without
        Docker daemon).  NOTE: This test needs docker-compose.yml to exist;
        while the file is absent it will FAIL (not skip) — which is correct
        for TDD.
        """
        if shutil.which("docker") is None:
            pytest.skip("docker CLI not available — skipping compose config validation")

        if not COMPOSE_FILE.exists():
            pytest.fail(
                f"docker-compose.yml not found at {COMPOSE_FILE}. "
                "Cannot run `docker compose config` without the file."
            )

        result = subprocess.run(
            ["docker", "compose", "config", "-q"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"`docker compose config -q` exited {result.returncode}.\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ===========================================================================
# CLASS 2 — Top-Level Structure
# ===========================================================================


class TestComposeTopLevelStructure:
    """Validates the top-level keys and their required sub-keys."""

    def test_services_key_present(self, compose: dict[str, Any]) -> None:
        """The `services` key must be present.

        WHY: Without it Docker Compose treats the file as having no services
        and silently does nothing on `docker compose up`.
        """
        assert "services" in compose, (
            "docker-compose.yml is missing the top-level `services` key"
        )

    def test_networks_key_present(self, compose: dict[str, Any]) -> None:
        """The `networks` key must be present.

        WHY: Services reference naas-network by name; if the top-level
        declaration is absent, Docker Compose raises a validation error.
        """
        assert "networks" in compose, (
            "docker-compose.yml is missing the top-level `networks` key"
        )

    def test_volumes_key_present(self, compose: dict[str, Any]) -> None:
        """The `volumes` key must be present.

        WHY: Named volumes (postgres-data, redis-data, etc.) must be declared
        at the top level for Docker to manage their lifecycle.
        """
        assert "volumes" in compose, (
            "docker-compose.yml is missing the top-level `volumes` key"
        )


# ===========================================================================
# CLASS 3 — Services: Exact Set (no more, no fewer)
# ===========================================================================


class TestComposeServiceSet:
    """The services mapping must contain EXACTLY the four infrastructure
    services — no application containers, no extras.
    """

    def test_services_contains_exactly_the_four_required_services(
        self, compose: dict[str, Any]
    ) -> None:
        """Services must be exactly the infra services plus any implemented app services.

        WHY: The Spec 0 §1 scope boundary was 'no application services yet'. As
        specs land they add their service to compose; IMPLEMENTED_APP_SERVICES
        tracks those so this guard still catches an implementer overstepping into
        a not-yet-built service, without flagging the ones that legitimately exist.
        Fewer than the expected set means infrastructure or a landed spec is incomplete.
        """
        actual = set(compose.get("services", {}).keys())
        expected = REQUIRED_SERVICES | IMPLEMENTED_APP_SERVICES
        assert actual == expected, (
            f"Expected services == {expected}, got {actual}.\n"
            f"Missing: {expected - actual}\n"
            f"Extra: {actual - expected}"
        )

    @pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_SERVICES))
    def test_application_service_not_present(
        self, compose: dict[str, Any], forbidden: str
    ) -> None:
        """No application-layer service name may appear in services.

        WHY: Explicit negative assertion documents the scope boundary for
        future maintainers and provides an unambiguous failure message if an
        implementer accidentally adds an app container.
        """
        actual_services = set(compose.get("services", {}).keys())
        assert forbidden not in actual_services, (
            f"Application service '{forbidden}' must not be present in "
            "docker-compose.yml at Spec 0 stage. "
            "Spec 0 contains infrastructure services only."
        )


# ===========================================================================
# CLASS 4 — postgres Service
# ===========================================================================


class TestPostgresService:
    """Validates the postgres service configuration."""

    def test_postgres_image_starts_with_postgres_17(
        self, compose: dict[str, Any]
    ) -> None:
        """postgres image must be postgres:17-alpine (or any postgres:17* tag).

        WHY: The spec §5.1 requires postgres:17-alpine. Using an earlier major
        version risks schema incompatibilities (e.g., missing pg_crypto behavior
        changes). The version anchor is the major version prefix.
        """
        svc = compose["services"]["postgres"]
        image = svc.get("image", "")
        assert image.startswith("postgres:17"), (
            f"postgres service image must start with 'postgres:17', got '{image}'"
        )

    def test_postgres_bind_mount_init_sql_source(
        self, compose: dict[str, Any]
    ) -> None:
        """postgres must bind-mount ./infrastructure/postgres/init.sql.

        WHY: This is the DDL script that creates all tables, indexes, and the
        default policy seed row. Without it, the database starts empty and all
        downstream service tests fail immediately.
        """
        svc = compose["services"]["postgres"]
        mounts = _extract_bind_mounts(svc)
        sources = [m[0] for m in mounts]
        assert "./infrastructure/postgres/init.sql" in sources, (
            f"postgres service must bind-mount './infrastructure/postgres/init.sql'. "
            f"Found bind mounts: {sources}"
        )

    def test_postgres_bind_mount_init_sql_target_under_initdb(
        self, compose: dict[str, Any]
    ) -> None:
        """init.sql target must be under /docker-entrypoint-initdb.d/.

        WHY: The postgres official image only auto-executes .sql files placed
        in /docker-entrypoint-initdb.d/. Any other target path is silently
        ignored — the database starts empty with no error message.
        """
        svc = compose["services"]["postgres"]
        mounts = _extract_bind_mounts(svc)
        init_sql_targets = [
            target
            for source, target in mounts
            if source == "./infrastructure/postgres/init.sql"
        ]
        assert init_sql_targets, (
            "No bind mount found for './infrastructure/postgres/init.sql'"
        )
        target = init_sql_targets[0]
        assert target.startswith("/docker-entrypoint-initdb.d/"), (
            f"init.sql must be mounted under /docker-entrypoint-initdb.d/, "
            f"got target '{target}'"
        )

    def test_postgres_declares_postgres_data_volume(
        self, compose: dict[str, Any]
    ) -> None:
        """postgres must declare the postgres-data named volume.

        WHY: Without a named volume, database contents are stored in the
        container writable layer and lost on every `docker compose down`.
        """
        svc = compose["services"]["postgres"]
        refs = _service_volume_refs(svc)
        assert any("postgres-data" in ref for ref in refs), (
            f"postgres service must reference the 'postgres-data' named volume. "
            f"Volume refs found: {refs}"
        )

    def test_postgres_attached_to_naas_network(
        self, compose: dict[str, Any]
    ) -> None:
        """postgres must be on naas-network.

        WHY: All services communicate over naas-network. A postgres container
        not on this network is unreachable by name from the application services
        added in Specs 1–5.
        """
        svc = compose["services"]["postgres"]
        networks = _service_networks(svc)
        assert "naas-network" in networks, (
            f"postgres must be attached to 'naas-network'. "
            f"Networks found: {networks}"
        )


# ===========================================================================
# CLASS 5 — redis Service
# ===========================================================================


class TestRedisService:
    """Validates the redis service configuration."""

    def test_redis_image_starts_with_redis_74(
        self, compose: dict[str, Any]
    ) -> None:
        """redis image must be redis:7.4-alpine (or any redis:7.4* tag).

        WHY: Redis Streams support (XADD/XREADGROUP) was mature by 6.x, but
        the spec pins 7.4 for consistent stream behavior and LRU eviction
        policies used in the NAAS pipeline caching layer.
        """
        svc = compose["services"]["redis"]
        image = svc.get("image", "")
        assert image.startswith("redis:7.4"), (
            f"redis service image must start with 'redis:7.4', got '{image}'"
        )

    def test_redis_bind_mount_redis_conf_source(
        self, compose: dict[str, Any]
    ) -> None:
        """redis must bind-mount ./infrastructure/redis/redis.conf.

        WHY: The custom redis.conf sets maxmemory (256mb) and appendonly (yes).
        Without it, Redis starts with unlimited memory and no persistence,
        violating the operational requirements in §3.2.
        """
        svc = compose["services"]["redis"]
        mounts = _extract_bind_mounts(svc)
        sources = [m[0] for m in mounts]
        assert "./infrastructure/redis/redis.conf" in sources, (
            f"redis service must bind-mount './infrastructure/redis/redis.conf'. "
            f"Found bind mounts: {sources}"
        )

    def test_redis_command_references_redis_server_and_conf(
        self, compose: dict[str, Any]
    ) -> None:
        """redis command must invoke redis-server with the conf file path.

        WHY: The redis image entrypoint ignores redis.conf unless the command
        explicitly passes the path as an argument. Default startup without a
        conf path means the bind-mounted config is silently never read.
        """
        svc = compose["services"]["redis"]
        cmd = _command_as_string(svc)
        assert "redis-server" in cmd, (
            f"redis command must contain 'redis-server', got: '{cmd}'"
        )
        # The command must also reference the mounted conf path
        assert "redis.conf" in cmd, (
            f"redis command must reference 'redis.conf' to load the custom config, "
            f"got: '{cmd}'"
        )

    def test_redis_declares_redis_data_volume(
        self, compose: dict[str, Any]
    ) -> None:
        """redis must declare the redis-data named volume.

        WHY: appendonly=yes persistence is only durable if the AOF file lives
        on a named volume. Container-layer storage loses data on restart.
        """
        svc = compose["services"]["redis"]
        refs = _service_volume_refs(svc)
        assert any("redis-data" in ref for ref in refs), (
            f"redis service must reference the 'redis-data' named volume. "
            f"Volume refs found: {refs}"
        )


# ===========================================================================
# CLASS 6 — keycloak Service
# ===========================================================================


class TestKeycloakService:
    """Validates the keycloak service configuration, with emphasis on the
    H2-dev-mode requirement (no KC_DB* vars) from Architect's Note §3.1.
    """

    def test_keycloak_image_is_correct(self, compose: dict[str, Any]) -> None:
        """keycloak image must be quay.io/keycloak/keycloak:26.0.

        WHY: The spec pins 26.0 for deterministic realm import behavior.
        Different major versions have different import file formats and
        healthcheck endpoint paths.
        """
        svc = compose["services"]["keycloak"]
        image = svc.get("image", "")
        assert image == "quay.io/keycloak/keycloak:26.0", (
            f"keycloak image must be 'quay.io/keycloak/keycloak:26.0', "
            f"got '{image}'"
        )

    def test_keycloak_command_contains_start_dev(
        self, compose: dict[str, Any]
    ) -> None:
        """keycloak command must contain `start-dev`.

        WHY: `start-dev` is the flag that activates development mode with
        embedded H2 storage. Without it, Keycloak starts in production mode
        and REQUIRES an external database, failing immediately.
        """
        svc = compose["services"]["keycloak"]
        cmd = _command_as_string(svc)
        assert "start-dev" in cmd, (
            f"keycloak command must contain 'start-dev' to use H2 dev mode. "
            f"Got: '{cmd}'"
        )

    def test_keycloak_command_contains_import_realm(
        self, compose: dict[str, Any]
    ) -> None:
        """keycloak command must contain `--import-realm`.

        WHY: Without `--import-realm`, the naas-realm-export.json bind mount
        is present but never loaded. The realm, client, and test users won't
        exist at startup, causing OIDC discovery to 404 and all auth flows to
        fail.
        """
        svc = compose["services"]["keycloak"]
        cmd = _command_as_string(svc)
        assert "--import-realm" in cmd, (
            f"keycloak command must contain '--import-realm' to load the realm "
            f"export on startup. Got: '{cmd}'"
        )

    def test_keycloak_has_no_kc_db_environment_variables(
        self, compose: dict[str, Any]
    ) -> None:
        """keycloak must have NO environment variables starting with KC_DB.

        WHY: The Architect's Note in §3.1 explicitly chose Option A (H2 dev
        mode) over Option B (shared PostgreSQL). Any KC_DB* variable causes
        Keycloak to attempt a PostgreSQL connection that cannot succeed in dev
        mode, hanging the entire stack on startup. This is the most common
        misconfiguration and must be caught statically.
        """
        svc = compose["services"]["keycloak"]
        env_keys = _get_env_keys(svc)
        kc_db_keys = [k for k in env_keys if k.startswith("KC_DB")]
        assert kc_db_keys == [], (
            f"keycloak must have NO KC_DB* environment variables "
            f"(use H2 dev mode — see spec §3.1 Architect's Note). "
            f"Found: {kc_db_keys}"
        )

    def test_keycloak_may_have_admin_credentials(
        self, compose: dict[str, Any]
    ) -> None:
        """keycloak KEYCLOAK_ADMIN / KEYCLOAK_ADMIN_PASSWORD are allowed.

        WHY: These credentials are necessary for the admin console and the
        realm import process. Their presence is correct and expected. This test
        documents that the KC_DB* ban does NOT prohibit admin credentials.
        """
        svc = compose["services"]["keycloak"]
        env_keys = _get_env_keys(svc)
        # At minimum one of these should be present — they're part of the spec
        has_admin_creds = any(
            k in ("KEYCLOAK_ADMIN", "KEYCLOAK_ADMIN_PASSWORD") for k in env_keys
        )
        assert has_admin_creds, (
            f"keycloak should have KEYCLOAK_ADMIN and/or KEYCLOAK_ADMIN_PASSWORD "
            f"environment variables for admin console access. "
            f"Found env keys: {env_keys}"
        )

    def test_keycloak_bind_mount_realm_export_source(
        self, compose: dict[str, Any]
    ) -> None:
        """keycloak must bind-mount ./infrastructure/keycloak/naas-realm-export.json.

        WHY: The `--import-realm` flag looks for files in
        /opt/keycloak/data/import/. Without this bind mount, the realm JSON is
        never loaded and the naas-demo realm does not exist on startup.
        """
        svc = compose["services"]["keycloak"]
        mounts = _extract_bind_mounts(svc)
        sources = [m[0] for m in mounts]
        assert "./infrastructure/keycloak/naas-realm-export.json" in sources, (
            f"keycloak must bind-mount "
            f"'./infrastructure/keycloak/naas-realm-export.json'. "
            f"Found bind mounts: {sources}"
        )


# ===========================================================================
# CLASS 7 — openldap Service
# ===========================================================================


class TestOpenLdapService:
    """Validates the openldap service configuration."""

    def test_openldap_uses_locally_built_image(
        self, compose: dict[str, Any]
    ) -> None:
        """openldap must be a locally-built image from ./infrastructure/openldap
        tagged naas-openldap:local, based on osixia/openldap:1.5.0.

        WHY: The bootstrap LDIF is baked into a custom image at build time rather
        than bind-mounted (see test_openldap_bakes_bootstrap_ldif_into_image and
        infrastructure/openldap/Dockerfile for the rationale). The compose service
        therefore declares a `build` context pointing at ./infrastructure/openldap
        and pins the resulting image tag to `naas-openldap:local`. The osixia
        1.5.0 base is still pinned — in the Dockerfile's FROM — because that
        version has the correct bootstrap injection path
        (/container/service/slapd/assets/config/bootstrap/ldif/custom/).
        """
        svc = compose["services"]["openldap"]

        # `build` may be a bare string (the context) or a mapping with `context`.
        build = svc.get("build")
        assert build is not None, (
            "openldap must declare a `build` context (the LDIF is baked into a "
            "custom image, not bind-mounted)."
        )
        context = build if isinstance(build, str) else build.get("context", "")
        assert context == "./infrastructure/openldap", (
            f"openldap build context must be './infrastructure/openldap', "
            f"got '{context}'"
        )

        image = svc.get("image", "")
        assert image == "naas-openldap:local", (
            f"openldap image tag must be 'naas-openldap:local', got '{image}'"
        )

        # The osixia 1.5.0 pin now lives in the Dockerfile's FROM line.
        dockerfile = REPO_ROOT / "infrastructure" / "openldap" / "Dockerfile"
        assert dockerfile.exists(), (
            f"openldap Dockerfile not found at {dockerfile}"
        )
        text = dockerfile.read_text(encoding="utf-8")
        assert "FROM osixia/openldap:1.5.0" in text, (
            "openldap Dockerfile must pin 'FROM osixia/openldap:1.5.0' — that "
            "version has the correct bootstrap injection path."
        )

    def test_openldap_bakes_bootstrap_ldif_into_image(
        self, compose: dict[str, Any]
    ) -> None:
        """openldap must bake bootstrap.ldif into the image, not bind-mount it.

        WHY: The bootstrap LDIF creates the ou=users, ou=groups OUs and five
        test users — without it the directory starts empty and cross-protocol
        enrichment has nothing to look up. It is COPYed into the image at build
        time rather than bind-mounted because the osixia entrypoint runs
        `chown -R`/`sed -i`/`rm -rf` over its assets tree on startup; a
        bind-mounted LDIF would have its host ownership flipped to uid 911 or
        fail with "Device or resource busy". See infrastructure/openldap/Dockerfile.
        """
        svc = compose["services"]["openldap"]

        # The LDIF must NOT be bind-mounted (that's the bug this design avoids).
        sources = [m[0] for m in _extract_bind_mounts(svc)]
        assert "./infrastructure/openldap/bootstrap.ldif" not in sources, (
            "openldap must NOT bind-mount bootstrap.ldif — it is baked into the "
            f"image instead. Found bind mounts: {sources}"
        )

        # The Dockerfile must COPY it into the osixia custom-bootstrap directory.
        dockerfile = REPO_ROOT / "infrastructure" / "openldap" / "Dockerfile"
        assert dockerfile.exists(), (
            f"openldap Dockerfile not found at {dockerfile}"
        )
        text = dockerfile.read_text(encoding="utf-8")
        assert "COPY bootstrap.ldif" in text, (
            "openldap Dockerfile must COPY bootstrap.ldif into the image."
        )
        assert (
            "/container/service/slapd/assets/config/bootstrap/ldif/custom/" in text
        ), (
            "openldap Dockerfile must COPY bootstrap.ldif into the osixia "
            "custom-bootstrap path "
            "(/container/service/slapd/assets/config/bootstrap/ldif/custom/)."
        )

    def test_openldap_declares_ldap_data_volume(
        self, compose: dict[str, Any]
    ) -> None:
        """openldap must declare the ldap-data named volume.

        WHY: /var/lib/ldap contains the LDAP database files. A named volume
        persists the directory between container restarts.
        """
        svc = compose["services"]["openldap"]
        refs = _service_volume_refs(svc)
        assert any("ldap-data" in ref for ref in refs), (
            f"openldap service must reference the 'ldap-data' named volume. "
            f"Volume refs found: {refs}"
        )

    def test_openldap_declares_ldap_config_volume(
        self, compose: dict[str, Any]
    ) -> None:
        """openldap must declare the ldap-config named volume.

        WHY: /etc/ldap/slapd.d contains the OpenLDAP configuration database.
        Persisting it separately from the data directory is the standard
        osixia/openldap deployment pattern for reliable restarts.
        """
        svc = compose["services"]["openldap"]
        refs = _service_volume_refs(svc)
        assert any("ldap-config" in ref for ref in refs), (
            f"openldap service must reference the 'ldap-config' named volume. "
            f"Volume refs found: {refs}"
        )


# ===========================================================================
# CLASS 8 — Networks
# ===========================================================================


class TestNetworkDeclaration:
    """naas-network must be declared at the top level with driver: bridge."""

    def test_naas_network_declared(self, compose: dict[str, Any]) -> None:
        """Top-level networks must include naas-network.

        WHY: Services can only reference a network by name if it is declared
        at the top-level networks key. An undeclared network causes
        `docker compose config` to fail validation.
        """
        networks = compose.get("networks", {})
        assert "naas-network" in networks, (
            f"Top-level networks must declare 'naas-network'. "
            f"Found networks: {list(networks.keys())}"
        )

    def test_naas_network_driver_is_bridge(self, compose: dict[str, Any]) -> None:
        """naas-network must have driver: bridge.

        WHY: The bridge driver provides DNS-based service discovery (services
        reach each other by service name). Omitting the driver field defaults
        to bridge in Docker, but explicit declaration is required by the spec
        and is good documentation practice.
        """
        networks = compose.get("networks", {})
        naas_net = networks.get("naas-network", {})
        driver = (naas_net or {}).get("driver")
        assert driver == "bridge", (
            f"naas-network must have driver: bridge, got driver: '{driver}'"
        )


# ===========================================================================
# CLASS 9 — Named Volumes
# ===========================================================================


class TestTopLevelVolumes:
    """All four required named volumes must be declared at the top level."""

    @pytest.mark.parametrize("vol_name", sorted(REQUIRED_VOLUMES))
    def test_required_named_volume_declared(
        self, compose: dict[str, Any], vol_name: str
    ) -> None:
        """Each required named volume must appear in the top-level volumes map.

        WHY: Named volumes must be declared at the top level for Docker to
        manage their lifecycle (creation, inspection, removal). A service
        referencing an undeclared volume causes a validation error at startup.

        Volumes checked: postgres-data, redis-data, ldap-data, ldap-config
        """
        volumes = compose.get("volumes", {})
        assert vol_name in volumes, (
            f"Top-level volumes must declare '{vol_name}'. "
            f"Found volumes: {list(volumes.keys())}"
        )

    def test_top_level_volumes_contains_all_four_required(
        self, compose: dict[str, Any]
    ) -> None:
        """Top-level volumes must include ALL FOUR required named volumes.

        WHY: A single parametrized test catches individual misses; this test
        provides a consolidated failure message when multiple volumes are absent.
        """
        volumes = set(compose.get("volumes", {}).keys())
        missing = REQUIRED_VOLUMES - volumes
        assert not missing, (
            f"Top-level volumes is missing: {missing}. "
            f"Declared volumes: {volumes}"
        )


# ===========================================================================
# CLASS 10 — Bind-Mount Source Files Exist on Disk
# ===========================================================================


class TestRequiredSourceFilesExist:
    """Assert that each compose source file created by Chunks 1/3/4 is present
    on disk.

    NOTE: These assertions may PASS even before docker-compose.yml is created
    because the files themselves come from prior chunks. This is acceptable —
    the suite as a whole still fails due to the missing compose file.
    """

    @pytest.mark.parametrize("rel_path", [str(p) for p in REQUIRED_SOURCE_FILES])
    def test_required_source_file_exists(self, rel_path: str) -> None:
        """Each compose source file (from prior chunks) must exist.

        WHY: If these files are absent, the stack breaks in silent or cryptic
        ways. For the three bind-mounted files, Docker Compose creates an empty
        directory at the mount point instead of mounting the file: postgres
        silently ignores init.sql; redis crashes with a config parse error;
        keycloak imports nothing. For openldap, bootstrap.ldif is a Dockerfile
        COPY source — if it is missing the image build fails outright (or, were
        the COPY guarded, the directory would start with no users). Asserting
        file existence catches this class of bug before the stack is ever built
        or started.

        Files validated:
          - infrastructure/postgres/init.sql                (Chunk 3, bind-mount)
          - infrastructure/redis/redis.conf                 (Chunk 3, bind-mount)
          - infrastructure/keycloak/naas-realm-export.json  (Chunk 4, bind-mount)
          - infrastructure/openldap/bootstrap.ldif          (Chunk 4, Dockerfile COPY)
        """
        abs_path = REPO_ROOT / rel_path
        assert abs_path.exists(), (
            f"Required compose source file not found: {abs_path}. "
            f"This file should have been created by a prior chunk."
        )
        assert abs_path.is_file(), (
            f"Path exists but is not a file: {abs_path}"
        )
        assert abs_path.stat().st_size > 0, (
            f"Required compose source file is empty: {abs_path}"
        )
