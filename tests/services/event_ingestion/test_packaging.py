"""Dockerfile, requirements.txt, and .dockerignore contract for event-ingestion."""

from pathlib import Path
from typing import Any

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery (needed to locate committed files under test)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up until docs/architecture/ is found — repo root marker."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Could not locate repo root from {Path(__file__).resolve()}")


REPO_ROOT = _find_repo_root()
SERVICE_DIR = REPO_ROOT / "services" / "event-ingestion"
DOCKERFILE_PATH = SERVICE_DIR / "Dockerfile"
REQUIREMENTS_PATH = SERVICE_DIR / "requirements.txt"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_compose() -> dict[str, Any]:
    """Parse docker-compose.yml. Fails the calling test if absent or invalid YAML."""
    yaml = pytest.importorskip("yaml")
    if not COMPOSE_PATH.exists():
        pytest.fail(
            f"docker-compose.yml not found at {COMPOSE_PATH}. "
            "The implementer must create it or add the event-ingestion entry."
        )
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _dockerfile_text() -> str:
    """Return Dockerfile content. Fails the calling test if absent."""
    if not DOCKERFILE_PATH.exists():
        pytest.fail(
            f"Dockerfile not found at {DOCKERFILE_PATH}. "
            "The implementer must create services/event-ingestion/Dockerfile."
        )
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _requirements_text() -> str:
    """Return requirements.txt content. Fails the calling test if absent."""
    if not REQUIREMENTS_PATH.exists():
        pytest.fail(
            f"requirements.txt not found at {REQUIREMENTS_PATH}. "
            "The implementer must create services/event-ingestion/requirements.txt."
        )
    return REQUIREMENTS_PATH.read_text(encoding="utf-8")


def _compose_ei_service() -> dict[str, Any]:
    """Return the event-ingestion service config from docker-compose.yml.
    Fails if the service is absent."""
    compose = _load_compose()
    services = compose.get("services", {})
    if "event-ingestion" not in services:
        pytest.fail(
            "docker-compose.yml is missing the 'event-ingestion' service entry. "
            "The implementer must add it per spec §5.8."
        )
    return services["event-ingestion"]


# ===========================================================================
# CLASS 1 — requirements.txt
# ===========================================================================


class TestRequirementsTxt:
    """services/event-ingestion/requirements.txt: service-direct deps only.
    fastapi and uvicorn are the two direct deps. Data-layer deps come via
    naas_shared (installed as -e /app/shared/ in the Dockerfile)."""

    def test_requirements_txt_exists(self) -> None:
        """requirements.txt must exist at services/event-ingestion/requirements.txt.

        WHY: The Dockerfile copies this file and runs pip install -r on it. Without
        it the image build fails immediately at the COPY/RUN step.
        """
        assert REQUIREMENTS_PATH.exists(), (
            f"requirements.txt not found at {REQUIREMENTS_PATH}. "
            "The implementer must create services/event-ingestion/requirements.txt."
        )

    def test_requirements_txt_lists_fastapi(self) -> None:
        """requirements.txt must list fastapi (any version specifier or bare name).

        WHY: fastapi is the web framework for the event-ingestion service. Without
        it in requirements.txt, the image build installs it only if naas_shared
        happens to pull it in transitively — fragile and unspecified behavior.
        """
        content = _requirements_text()
        lines = [line.strip().lower() for line in content.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        fastapi_lines = [line for line in lines if line.startswith("fastapi")]
        assert fastapi_lines, (
            f"requirements.txt must list 'fastapi' (with or without version pin). "
            f"Found lines: {lines}"
        )

    def test_requirements_txt_lists_uvicorn(self) -> None:
        """requirements.txt must list uvicorn (with or without [standard] extra).

        WHY: uvicorn is the ASGI server that runs the service. The Dockerfile CMD
        is 'uvicorn app.main:app ...' — if uvicorn is absent from requirements.txt
        the CMD fails with 'command not found'.
        """
        content = _requirements_text()
        lines = [line.strip().lower() for line in content.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        uvicorn_lines = [line for line in lines if line.startswith("uvicorn")]
        assert uvicorn_lines, (
            f"requirements.txt must list 'uvicorn' (with or without [standard]). "
            f"Found lines: {lines}"
        )

    def test_requirements_txt_does_not_list_sqlalchemy(self) -> None:
        """requirements.txt must NOT list sqlalchemy.

        WHY: The spec §5.8 states 'data-layer dependencies (SQLAlchemy, asyncpg,
        redis, pydantic, ...) are pulled in transitively by installing naas_shared.'
        Duplicating them here creates version conflicts and makes the image heavier.
        The authoritative source is shared/pyproject.toml.
        """
        content = _requirements_text()
        lines = [line.strip().lower() for line in content.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        sqlalchemy_lines = [line for line in lines if line.startswith("sqlalchemy")]
        assert not sqlalchemy_lines, (
            f"requirements.txt must NOT list 'sqlalchemy' — it is a transitive dep "
            f"from naas_shared. Found: {sqlalchemy_lines}"
        )

    def test_requirements_txt_does_not_list_asyncpg(self) -> None:
        """requirements.txt must NOT list asyncpg.

        WHY: asyncpg is the async PostgreSQL driver pulled in by naas_shared's
        sqlalchemy[asyncio] dependency. Listing it separately risks version
        mismatch between what naas_shared expects and what the service overrides.
        """
        content = _requirements_text()
        lines = [line.strip().lower() for line in content.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        asyncpg_lines = [line for line in lines if line.startswith("asyncpg")]
        assert not asyncpg_lines, (
            f"requirements.txt must NOT list 'asyncpg' — it is a transitive dep "
            f"from naas_shared. Found: {asyncpg_lines}"
        )

    def test_requirements_txt_does_not_list_redis(self) -> None:
        """requirements.txt must NOT list redis (the Python client package).

        WHY: The redis Python client (redis-py) is a dependency of naas_shared.
        Listing it separately creates version conflicts with the shared client version.
        """
        content = _requirements_text()
        lines = [line.strip().lower() for line in content.splitlines()
                 if line.strip() and not line.strip().startswith("#")]
        # Match 'redis' but not something like 'fastapi-redis' (unlikely but safe)
        redis_lines = [line for line in lines if line == "redis" or line.startswith("redis==")
                       or line.startswith("redis>=") or line.startswith("redis~=")]
        assert not redis_lines, (
            f"requirements.txt must NOT list 'redis' — it is a transitive dep "
            f"from naas_shared. Found: {redis_lines}"
        )


# ===========================================================================
# CLASS 2 — Dockerfile
# ===========================================================================


class TestDockerfile:
    """services/event-ingestion/Dockerfile: repo-root build context, shared/ copied
    first, editable naas_shared install, EXPOSE 8001, uvicorn CMD on port 8001."""

    def test_dockerfile_exists(self) -> None:
        """Dockerfile must exist at services/event-ingestion/Dockerfile.

        WHY: Without it, docker compose build event-ingestion fails with 'Dockerfile
        not found'. This is also the path referenced in docker-compose.yml's
        build.dockerfile field.
        """
        assert DOCKERFILE_PATH.exists(), (
            f"Dockerfile not found at {DOCKERFILE_PATH}. "
            "The implementer must create services/event-ingestion/Dockerfile."
        )

    def test_dockerfile_exposes_port_8001(self) -> None:
        """Dockerfile must contain EXPOSE 8001.

        WHY: The spec §5.8 states the port is 8001 and the docker-compose.yml maps
        host:container traffic to container port 8001. EXPOSE is documentation that
        the image listens on 8001 — required so docker-compose port mapping is
        self-consistent and so `docker run -P` exposes the correct port.
        """
        content = _dockerfile_text()
        lines = [line.strip() for line in content.splitlines()]
        expose_lines = [line for line in lines if line.upper().startswith("EXPOSE")]
        assert any("8001" in line for line in expose_lines), (
            f"Dockerfile must contain 'EXPOSE 8001'. "
            f"Found EXPOSE lines: {expose_lines}"
        )

    def test_dockerfile_copies_shared_before_service_code(self) -> None:
        """COPY shared/ must appear before COPY services/event-ingestion/ in the Dockerfile.

        WHY: The spec §5.8 states 'Shared library first — changes least often, best
        layer caching.' Docker layer caching is invalidated by the first COPY that
        changes. Since shared/ changes less often than service code, placing it first
        means iterative builds only re-run from the service COPY onwards, not from
        the shared library install. Reversing the order wastes minutes on every build.
        """
        content = _dockerfile_text()
        lines = content.splitlines()

        shared_copy_idx = None
        service_copy_idx = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("COPY") and "shared/" in stripped and shared_copy_idx is None:
                shared_copy_idx = i
            if stripped.startswith("COPY") and "services/event-ingestion" in stripped:
                if service_copy_idx is None:
                    service_copy_idx = i

        assert shared_copy_idx is not None, (
            "Dockerfile must contain a COPY instruction for shared/ "
            "(e.g., 'COPY shared/ /app/shared/'). Not found."
        )
        assert service_copy_idx is not None, (
            "Dockerfile must contain a COPY instruction for services/event-ingestion "
            "(e.g., 'COPY services/event-ingestion/app/ ...'). Not found."
        )
        assert shared_copy_idx < service_copy_idx, (
            f"COPY shared/ (line {shared_copy_idx + 1}) must appear BEFORE "
            f"COPY services/event-ingestion/ (line {service_copy_idx + 1}). "
            "The shared library changes less often and should be an earlier layer "
            "for optimal Docker build cache utilization."
        )

    def test_dockerfile_installs_shared_as_editable(self) -> None:
        """Dockerfile must run `pip install -e /app/shared/` (editable install of naas_shared).

        WHY: The spec §5.8 states 'RUN pip install --no-cache-dir -e /app/shared/'.
        The -e (editable) flag installs the package from the COPYed source path,
        making `import naas_shared` resolve inside the container. Without it, the
        container has the shared source but naas_shared is not on the Python path.
        """
        content = _dockerfile_text()
        # Look for pip install ... -e ... shared or pip install -e /app/shared
        lines = content.splitlines()
        install_lines = [
            line.strip() for line in lines
            if "pip install" in line and "shared" in line
        ]
        # Accept both `pip install -e /app/shared/` and `pip install -e shared/`
        # and `pip install --no-cache-dir -e /app/shared/`
        has_editable_install = any(
            "-e" in line and "shared" in line for line in install_lines
        )
        assert has_editable_install, (
            f"Dockerfile must run 'pip install -e /app/shared/' (or equivalent). "
            f"Found install lines referencing shared: {install_lines}. "
            "The -e flag is required so that 'import naas_shared' resolves inside "
            "the container."
        )

    def test_dockerfile_cmd_launches_uvicorn_on_port_8001(self) -> None:
        """Dockerfile CMD must launch uvicorn on app.main:app port 8001.

        WHY: The spec §5.7 states CMD is 'uvicorn app.main:app --host 0.0.0.0
        --port 8001'. The docker-compose healthcheck probes http://localhost:8001/health.
        A CMD that uses a different port (e.g., 8000 or 8080) causes the container
        to report unhealthy because the healthcheck URL never responds.
        """
        content = _dockerfile_text()
        lines = content.splitlines()
        cmd_lines = [line.strip() for line in lines if line.strip().upper().startswith("CMD")]
        assert cmd_lines, (
            "Dockerfile must contain a CMD instruction. "
            f"No CMD found in {DOCKERFILE_PATH}."
        )
        last_cmd = cmd_lines[-1]  # The effective CMD is the last one
        assert "uvicorn" in last_cmd, (
            f"CMD must invoke uvicorn. Got: {last_cmd!r}"
        )
        assert "app.main:app" in last_cmd, (
            f"CMD must reference 'app.main:app' as the ASGI module. Got: {last_cmd!r}"
        )
        assert "8001" in last_cmd, (
            f"CMD must use port 8001. Got: {last_cmd!r}. "
            "The docker-compose healthcheck probes localhost:8001."
        )


# ===========================================================================
# CLASS 3 — .dockerignore
# ===========================================================================


class TestDockerignore:
    """.dockerignore at repo root keeps build contexts lean.
    Without it, every service build includes .git (~hundreds of MB), .venv,
    node_modules, and .claude, all of which are irrelevant to the container."""

    def test_dockerignore_exists_at_repo_root(self) -> None:
        """.dockerignore must exist at the repo root.

        WHY: The Dockerfile's build context is the repo root (build.context: .).
        Without .dockerignore, Docker sends the entire repo tree to the daemon on
        every build, including .git, node_modules (dashboard), and .venv — adding
        seconds to each build and potentially hundreds of MB to the build context.
        """
        assert DOCKERIGNORE_PATH.exists(), (
            f".dockerignore not found at {DOCKERIGNORE_PATH}. "
            "The implementer must create it per spec §5.8."
        )

    def test_dockerignore_contains_git_entry(self) -> None:
        """.dockerignore must contain an entry for .git.

        WHY: The .git directory contains the entire repository history and can be
        hundreds of MB. Including it in the build context is the single largest
        source of build slowness and unnecessarily exposes git history inside the
        container image.
        """
        if not DOCKERIGNORE_PATH.exists():
            pytest.fail(f".dockerignore not found at {DOCKERIGNORE_PATH}.")
        content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        entries = [line.strip() for line in content.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        assert ".git" in entries, (
            f".dockerignore must contain a '.git' entry. "
            f"Found entries: {entries}"
        )

    def test_dockerignore_contains_venv_entry(self) -> None:
        """.dockerignore must contain an entry for .venv.

        WHY: The .venv directory contains the local Python virtual environment
        (~1GB+ for this project). Including it in the build context means Docker
        copies thousands of files to the daemon for every build, all of which are
        replaced by the image's own pip install step.
        """
        if not DOCKERIGNORE_PATH.exists():
            pytest.fail(f".dockerignore not found at {DOCKERIGNORE_PATH}.")
        content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        entries = [line.strip() for line in content.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        assert ".venv" in entries, (
            f".dockerignore must contain a '.venv' entry. "
            f"Found entries: {entries}"
        )

    def test_dockerignore_contains_node_modules_entry(self) -> None:
        """.dockerignore must contain an entry for node_modules.

        WHY: The dashboard/ directory's node_modules is included in the repo-root
        build context. It can contain thousands of files and hundreds of MB.
        None of it is needed by any service image.
        """
        if not DOCKERIGNORE_PATH.exists():
            pytest.fail(f".dockerignore not found at {DOCKERIGNORE_PATH}.")
        content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        entries = [line.strip() for line in content.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        assert "node_modules" in entries, (
            f".dockerignore must contain a 'node_modules' entry. "
            f"Found entries: {entries}"
        )

    def test_dockerignore_contains_claude_entry(self) -> None:
        """.dockerignore must contain an entry for .claude.

        WHY: The .claude directory contains agent memory, pipeline state, and
        session artifacts from the agentic development workflow. None of this
        is relevant to the service image and it may contain sensitive pipeline
        configuration that should not be baked into container images.
        """
        if not DOCKERIGNORE_PATH.exists():
            pytest.fail(f".dockerignore not found at {DOCKERIGNORE_PATH}.")
        content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        entries = [line.strip() for line in content.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        assert ".claude" in entries, (
            f".dockerignore must contain a '.claude' entry. "
            f"Found entries: {entries}"
        )

    def test_dockerignore_contains_pycache_glob(self) -> None:
        """.dockerignore must contain an entry for **/__pycache__.

        WHY: Python generates __pycache__ directories and .pyc files throughout the
        source tree. Including them in the build context sends compiled bytecache
        files to the daemon — they are useless in the container (wrong Python version,
        absolute path baked in) and add noise to the build context.
        """
        if not DOCKERIGNORE_PATH.exists():
            pytest.fail(f".dockerignore not found at {DOCKERIGNORE_PATH}.")
        content = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        entries = [line.strip() for line in content.splitlines()
                   if line.strip() and not line.strip().startswith("#")]
        assert "**/__pycache__" in entries, (
            f".dockerignore must contain a '**/__pycache__' entry. "
            f"Found entries: {entries}"
        )


# ===========================================================================
# CLASS 4 — docker-compose.yml: event-ingestion service entry
# ===========================================================================


class TestDockerComposeEventIngestionService:
    """docker-compose.yml must have an event-ingestion service entry with the
    correct build config, env_file, port mapping, depends_on conditions, and
    healthcheck. Infrastructure services must remain unchanged."""

    def test_event_ingestion_service_present(self) -> None:
        """docker-compose.yml must include an 'event-ingestion' service key.

        WHY: Without this entry, `docker compose up event-ingestion` silently does
        nothing (or errors with 'no such service'). The entire automated pipeline
        depends on this service being compose-managed.
        """
        compose = _load_compose()
        services = compose.get("services", {})
        assert "event-ingestion" in services, (
            "docker-compose.yml is missing the 'event-ingestion' service entry. "
            "The implementer must add it per spec §5.8."
        )

    def test_event_ingestion_build_context_is_repo_root(self) -> None:
        """event-ingestion build.context must be '.' (the repo root).

        WHY: The Dockerfile uses COPY shared/ and COPY services/event-ingestion/ —
        both paths are relative to the repo root. If the build context is
        services/event-ingestion/, those COPY instructions fail because shared/ is
        not under that directory. The repo-root context is load-bearing for the
        multi-package image pattern.
        """
        svc = _compose_ei_service()
        build = svc.get("build")
        assert build is not None, (
            "event-ingestion must have a 'build' entry (not just an 'image' pull). "
            "The Dockerfile is a local build with repo-root context."
        )
        context = build if isinstance(build, str) else build.get("context", "")
        assert context == ".", (
            f"event-ingestion build.context must be '.' (repo root). "
            f"Got: {context!r}. "
            "The Dockerfile COPYs both shared/ and services/event-ingestion/, "
            "which requires the repo root as the build context."
        )

    def test_event_ingestion_build_dockerfile_path(self) -> None:
        """event-ingestion build.dockerfile must be 'services/event-ingestion/Dockerfile'.

        WHY: With a repo-root build context, Docker needs to be told where the
        Dockerfile is. Omitting this field causes Docker to look for 'Dockerfile'
        in the repo root, which does not exist (and should not — each service owns
        its own Dockerfile under its service directory).
        """
        svc = _compose_ei_service()
        build = svc.get("build", {})
        if isinstance(build, str):
            pytest.fail(
                "event-ingestion build must be a mapping with 'context' and 'dockerfile' "
                f"keys, not a bare string. Got: {build!r}"
            )
        dockerfile = build.get("dockerfile", "")
        assert dockerfile == "services/event-ingestion/Dockerfile", (
            f"event-ingestion build.dockerfile must be "
            f"'services/event-ingestion/Dockerfile', got {dockerfile!r}."
        )

    def test_event_ingestion_has_env_file_dot_env(self) -> None:
        """event-ingestion must declare env_file: .env (or a list containing '.env').

        WHY: The spec §5.8 states 'env_file: .env injects POSTGRES_*/REDIS_* into
        the container environment, which get_settings() reads.' Without env_file,
        the service starts with default Settings values (postgres host='postgres',
        redis port=6379, etc.) which may differ from whatever is in .env. If a
        developer customizes .env and the service ignores it, connection failures
        are hard to diagnose.
        """
        svc = _compose_ei_service()
        env_file = svc.get("env_file")
        assert env_file is not None, (
            "event-ingestion must declare 'env_file: .env'. "
            "Without it, POSTGRES_*/REDIS_* env vars from .env are not injected "
            "into the container."
        )
        # env_file may be a string '.env' or a list ['.env']
        if isinstance(env_file, list):
            assert ".env" in env_file, (
                f"event-ingestion env_file list must contain '.env'. Got: {env_file!r}"
            )
        else:
            assert env_file == ".env", (
                f"event-ingestion env_file must be '.env'. Got: {env_file!r}"
            )

    def test_event_ingestion_port_maps_to_container_8001(self) -> None:
        """event-ingestion must expose a port mapping to container port 8001.

        WHY: The service listens on port 8001 (uvicorn --port 8001). The port
        mapping makes it reachable from the host for development and integration
        testing. Without the mapping, `curl localhost:8001/health` fails from outside
        Docker.
        """
        svc = _compose_ei_service()
        ports = svc.get("ports", [])
        assert ports, (
            "event-ingestion must declare a 'ports' mapping. "
            "The service listens on 8001 and must be reachable from the host."
        )
        # Each port entry is a string like "8001:8001" or "${VAR:-8001}:8001"
        # We assert that at least one entry maps to container port 8001
        has_8001 = any(
            (isinstance(p, str) and p.endswith(":8001"))
            or (isinstance(p, dict) and str(p.get("target", "")) == "8001")
            for p in ports
        )
        assert has_8001, (
            f"event-ingestion ports must include a mapping to container port 8001. "
            f"Found ports: {ports}"
        )

    def test_event_ingestion_depends_on_postgres_service_healthy(self) -> None:
        """event-ingestion depends_on.postgres.condition must be 'service_healthy'.

        WHY: The spec §5.8 states 'depends_on: postgres: condition: service_healthy'.
        Without this condition, Docker starts event-ingestion immediately when the
        postgres container exists, even if PostgreSQL hasn't finished initializing.
        The service's startup sequence executes DB connection setup in its lifespan
        handler — if PostgreSQL isn't accepting connections yet, the service crashes
        and Docker Compose does not restart it.
        """
        svc = _compose_ei_service()
        depends_on = svc.get("depends_on", {})
        assert "postgres" in depends_on, (
            "event-ingestion depends_on must include 'postgres'. "
            "The service requires PostgreSQL to be healthy before it can start."
        )
        postgres_dep = depends_on["postgres"]
        condition = (
            postgres_dep.get("condition") if isinstance(postgres_dep, dict) else None
        )
        assert condition == "service_healthy", (
            f"event-ingestion depends_on.postgres.condition must be 'service_healthy', "
            f"got {condition!r}. "
            "Without this condition the service may start before PostgreSQL is ready."
        )

    def test_event_ingestion_depends_on_redis_service_healthy(self) -> None:
        """event-ingestion depends_on.redis.condition must be 'service_healthy'.

        WHY: The spec §5.8 states 'depends_on: redis: condition: service_healthy'.
        Without this condition, the service may start before Redis is ready to accept
        connections. The lifespan handler warms the Redis client; if Redis isn't up,
        the warmup fails and stream publishing is broken from service start.
        """
        svc = _compose_ei_service()
        depends_on = svc.get("depends_on", {})
        assert "redis" in depends_on, (
            "event-ingestion depends_on must include 'redis'. "
            "The service publishes to login_events stream and requires Redis."
        )
        redis_dep = depends_on["redis"]
        condition = (
            redis_dep.get("condition") if isinstance(redis_dep, dict) else None
        )
        assert condition == "service_healthy", (
            f"event-ingestion depends_on.redis.condition must be 'service_healthy', "
            f"got {condition!r}. "
            "Without this condition the service may start before Redis is accepting connections."
        )

    def test_event_ingestion_has_healthcheck(self) -> None:
        """event-ingestion must declare a healthcheck.

        WHY: The healthcheck is what docker-compose ps uses to report service health.
        Any service that depends_on event-ingestion (none yet, but expected in later
        specs) needs a healthcheck to use condition: service_healthy. The spec §5.8
        defines the exact healthcheck command.
        """
        svc = _compose_ei_service()
        healthcheck = svc.get("healthcheck")
        assert healthcheck is not None, (
            "event-ingestion must declare a 'healthcheck' entry. "
            "It is required for depends_on: condition: service_healthy in downstream services."
        )
        assert isinstance(healthcheck, dict), (
            f"event-ingestion healthcheck must be a mapping, got {type(healthcheck).__name__!r}"
        )
        # Must have at least a 'test' key
        assert "test" in healthcheck, (
            f"event-ingestion healthcheck must have a 'test' key. "
            f"Found healthcheck keys: {list(healthcheck.keys())}"
        )

    def test_event_ingestion_healthcheck_probes_port_8001(self) -> None:
        """The event-ingestion healthcheck test must reference port 8001.

        WHY: The spec §5.8 healthcheck uses urllib.request to probe
        http://localhost:8001/health. Any healthcheck that probes a different port
        (e.g., 8000 or 80) always fails since the service only listens on 8001,
        causing the container to permanently report 'unhealthy'.
        """
        svc = _compose_ei_service()
        healthcheck = svc.get("healthcheck", {})
        test = healthcheck.get("test", [])
        test_str = " ".join(str(t) for t in test) if isinstance(test, list) else str(test)
        assert "8001" in test_str, (
            f"event-ingestion healthcheck.test must reference port 8001. "
            f"Got: {test_str!r}"
        )


# ===========================================================================
# CLASS 5 — docker-compose.yml: infrastructure services unchanged
# ===========================================================================


INFRASTRUCTURE_SERVICES = {"postgres", "redis", "keycloak", "openldap"}


class TestDockerComposeInfrastructureIntact:
    """Adding the event-ingestion service must not remove or break the four
    infrastructure services. These are unchanged from the Spec 0 state."""

    @pytest.mark.parametrize("svc_name", sorted(INFRASTRUCTURE_SERVICES))
    def test_infrastructure_service_still_present(self, svc_name: str) -> None:
        """Each infrastructure service must remain present in docker-compose.yml.

        WHY: The spec §5.8 states 'do not touch the infrastructure services.'
        Accidentally removing postgres, redis, keycloak, or openldap while adding
        the event-ingestion entry would break the entire stack. This test detects
        that class of accidental deletion.
        """
        compose = _load_compose()
        services = compose.get("services", {})
        assert svc_name in services, (
            f"Infrastructure service '{svc_name}' was removed from docker-compose.yml. "
            f"The spec §5.8 prohibits touching infrastructure services. "
            f"Present services: {sorted(services.keys())}"
        )

    def test_all_five_services_present(self) -> None:
        """docker-compose.yml must contain at least all 5 expected services:
        the 4 infrastructure services plus event-ingestion.

        WHY: Consolidated assertion that catches a wholesale services section
        replacement in one test, in addition to the per-service parametrized tests.
        """
        compose = _load_compose()
        services = set(compose.get("services", {}).keys())
        required = INFRASTRUCTURE_SERVICES | {"event-ingestion"}
        missing = required - services
        assert not missing, (
            f"docker-compose.yml is missing required services: {missing}. "
            f"Present services: {sorted(services)}"
        )
