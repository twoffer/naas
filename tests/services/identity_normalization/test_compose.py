"""Docker Compose service definition for identity-normalization."""

from pathlib import Path
from typing import Any

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery (needed to locate docker-compose.yml under test)
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
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"

# Services that must remain present after adding identity-normalization
REQUIRED_EXISTING_SERVICES = {
    "postgres", "redis", "keycloak", "openldap", "event-ingestion"
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_compose() -> dict[str, Any]:
    """Parse docker-compose.yml. Fails the calling test if absent or invalid YAML."""
    yaml = pytest.importorskip("yaml")
    if not COMPOSE_PATH.exists():
        pytest.fail(
            f"docker-compose.yml not found at {COMPOSE_PATH}. "
            "The implementer must add the identity-normalization service entry."
        )
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def _compose_in_service() -> dict[str, Any]:
    """Return the identity-normalization service config from docker-compose.yml.
    Fails if the service is absent."""
    compose = _load_compose()
    services = compose.get("services", {})
    if "identity-normalization" not in services:
        pytest.fail(
            "docker-compose.yml is missing the 'identity-normalization' service entry. "
            "The implementer must add it per spec §5.8."
        )
    return services["identity-normalization"]


# ===========================================================================
# CLASS 1 — identity-normalization service entry
# ===========================================================================


class TestIdentityNormalizationServiceEntry:
    """docker-compose.yml must have an identity-normalization service entry with the
    correct build config, env_file, port mapping, depends_on conditions, config mount,
    and healthcheck.
    """

    def test_identity_normalization_service_present(self) -> None:
        """docker-compose.yml must include an 'identity-normalization' service key.

        WHY: Without this entry, `docker compose up identity-normalization` silently
        does nothing (or errors with 'no such service'). The entire normalization
        pipeline stage depends on this service being compose-managed.
        """
        compose = _load_compose()
        services = compose.get("services", {})
        assert "identity-normalization" in services, (
            "docker-compose.yml is missing the 'identity-normalization' service entry. "
            "The implementer must add it per spec §5.8."
        )

    def test_identity_normalization_build_context_is_repo_root(self) -> None:
        """identity-normalization build.context must be '.' (the repo root).

        WHY: The Dockerfile uses COPY shared/ and COPY services/identity-normalization/
        — both paths are relative to the repo root. If the build context is the service
        directory, those COPY instructions fail because shared/ is not under it.
        """
        svc = _compose_in_service()
        build = svc.get("build")
        assert build is not None, (
            "identity-normalization must have a 'build' entry (not just an 'image' pull). "
            "The Dockerfile is a local build with repo-root context."
        )
        context = build if isinstance(build, str) else build.get("context", "")
        assert context == ".", (
            f"identity-normalization build.context must be '.' (repo root). "
            f"Got: {context!r}. "
            "The Dockerfile COPYs both shared/ and services/identity-normalization/, "
            "which requires the repo root as the build context."
        )

    def test_identity_normalization_build_dockerfile_path(self) -> None:
        """build.dockerfile must be 'services/identity-normalization/Dockerfile'.

        WHY: With a repo-root build context, Docker needs to be told where the
        Dockerfile is. Omitting this field causes Docker to look for 'Dockerfile'
        in the repo root, which does not exist.
        """
        svc = _compose_in_service()
        build = svc.get("build", {})
        if isinstance(build, str):
            pytest.fail(
                "identity-normalization build must be a mapping with 'context' and "
                f"'dockerfile' keys, not a bare string. Got: {build!r}"
            )
        dockerfile = build.get("dockerfile", "")
        assert dockerfile == "services/identity-normalization/Dockerfile", (
            f"identity-normalization build.dockerfile must be "
            f"'services/identity-normalization/Dockerfile', got {dockerfile!r}."
        )

    def test_identity_normalization_has_env_file_dot_env(self) -> None:
        """identity-normalization must declare env_file: .env (or a list with '.env').

        WHY: Spec §5.8 — 'env_file: .env'. The shared Settings reads LDAP_HOST,
        LDAP_PORT, LDAP_ADMIN_DN etc. from environment variables. Without env_file,
        the service starts with default values that may not match the running OpenLDAP
        container's configuration.
        """
        svc = _compose_in_service()
        env_file = svc.get("env_file")
        assert env_file is not None, (
            "identity-normalization must declare 'env_file: .env'. "
            "Without it, LDAP_*/POSTGRES_*/REDIS_* vars from .env are not injected."
        )
        if isinstance(env_file, list):
            assert ".env" in env_file, (
                f"identity-normalization env_file list must contain '.env'. Got: {env_file!r}"
            )
        else:
            assert env_file == ".env", (
                f"identity-normalization env_file must be '.env'. Got: {env_file!r}"
            )

    def test_identity_normalization_port_maps_to_container_8002(self) -> None:
        """identity-normalization must expose a port mapping to container port 8002.

        WHY: The service listens on port 8002 (uvicorn --port 8002). The port
        mapping uses ${IDENTITY_NORMALIZATION_PORT:-8002}:8002. Without the
        mapping, curl localhost:8002/health fails from outside Docker.
        """
        svc = _compose_in_service()
        ports = svc.get("ports", [])
        assert ports, (
            "identity-normalization must declare a 'ports' mapping. "
            "The service listens on 8002 and must be reachable from the host."
        )
        has_8002 = any(
            (isinstance(p, str) and p.endswith(":8002"))
            or (isinstance(p, dict) and str(p.get("target", "")) == "8002")
            for p in ports
        )
        assert has_8002, (
            f"identity-normalization ports must include a mapping to container port 8002. "
            f"Found ports: {ports}"
        )

    def test_identity_normalization_depends_on_postgres_service_healthy(self) -> None:
        """identity-normalization depends_on.postgres.condition must be 'service_healthy'.

        WHY: Spec §5.8 — depends_on postgres, redis, and openldap each with
        condition: service_healthy. The service UPDATEs events.normalized_attributes
        in PostgreSQL; if PG isn't healthy at startup, the first message processed
        fails immediately.
        """
        svc = _compose_in_service()
        depends_on = svc.get("depends_on", {})
        assert "postgres" in depends_on, (
            "identity-normalization depends_on must include 'postgres'."
        )
        postgres_dep = depends_on["postgres"]
        condition = (
            postgres_dep.get("condition") if isinstance(postgres_dep, dict) else None
        )
        assert condition == "service_healthy", (
            f"identity-normalization depends_on.postgres.condition must be 'service_healthy', "
            f"got {condition!r}."
        )

    def test_identity_normalization_depends_on_redis_service_healthy(self) -> None:
        """identity-normalization depends_on.redis.condition must be 'service_healthy'.

        WHY: Spec §5.8 — the consumer loop uses XREADGROUP on login_events (Redis)
        and publishes to normalized_events (Redis). Redis must be healthy before
        the consumer loop starts.
        """
        svc = _compose_in_service()
        depends_on = svc.get("depends_on", {})
        assert "redis" in depends_on, (
            "identity-normalization depends_on must include 'redis'. "
            "The consumer loop reads from login_events and writes to normalized_events streams."
        )
        redis_dep = depends_on["redis"]
        condition = (
            redis_dep.get("condition") if isinstance(redis_dep, dict) else None
        )
        assert condition == "service_healthy", (
            f"identity-normalization depends_on.redis.condition must be 'service_healthy', "
            f"got {condition!r}."
        )

    def test_identity_normalization_depends_on_openldap_service_healthy(self) -> None:
        """identity-normalization depends_on.openldap.condition must be 'service_healthy'.

        WHY: Spec §5.8 — 'depends_on the postgres, redis, and openldap services with
        condition: service_healthy.' This is the key difference from event-ingestion
        (which does NOT depend on openldap). The normalization service queries OpenLDAP
        for OIDC/SAML enrichment; if OpenLDAP is not healthy at startup, the first
        enrichment attempt fails with a connection error.
        """
        svc = _compose_in_service()
        depends_on = svc.get("depends_on", {})
        assert "openldap" in depends_on, (
            "identity-normalization depends_on must include 'openldap'. "
            "Spec §5.8: 'depends_on postgres, redis, and openldap with condition: service_healthy'. "
            "This is CRITICAL: the normalization service performs live LDAP enrichment."
        )
        openldap_dep = depends_on["openldap"]
        condition = (
            openldap_dep.get("condition") if isinstance(openldap_dep, dict) else None
        )
        assert condition == "service_healthy", (
            f"identity-normalization depends_on.openldap.condition must be 'service_healthy', "
            f"got {condition!r}. "
            "Without this, the service may start before the OpenLDAP directory is ready, "
            "causing all LDAP enrichment to fail with connection errors on startup."
        )

    def test_identity_normalization_has_healthcheck(self) -> None:
        """identity-normalization must declare a healthcheck.

        WHY: Spec §5.8 — 'a /health healthcheck on port 8002'. The healthcheck is
        required for any future service that depends_on identity-normalization with
        condition: service_healthy. Without it, depends_on can never resolve.
        """
        svc = _compose_in_service()
        healthcheck = svc.get("healthcheck")
        assert healthcheck is not None, (
            "identity-normalization must declare a 'healthcheck' entry. "
            "Required for depends_on: condition: service_healthy in downstream services."
        )
        assert isinstance(healthcheck, dict), (
            f"identity-normalization healthcheck must be a mapping, got {type(healthcheck).__name__!r}"
        )
        assert "test" in healthcheck, (
            f"identity-normalization healthcheck must have a 'test' key. "
            f"Found healthcheck keys: {list(healthcheck.keys())}"
        )

    def test_identity_normalization_healthcheck_probes_port_8002(self) -> None:
        """The identity-normalization healthcheck test must reference port 8002.

        WHY: The service only listens on port 8002. A healthcheck probing a different
        port (e.g., 8001) always fails, causing the container to permanently report
        'unhealthy' and blocking any depends_on services from starting.
        """
        svc = _compose_in_service()
        healthcheck = svc.get("healthcheck", {})
        test = healthcheck.get("test", [])
        test_str = " ".join(str(t) for t in test) if isinstance(test, list) else str(test)
        assert "8002" in test_str, (
            f"identity-normalization healthcheck.test must reference port 8002. "
            f"Got: {test_str!r}"
        )


# ===========================================================================
# CLASS 2 — config bind-mount ./config:/app/config
# ===========================================================================


class TestConfigBindMount:
    """identity-normalization must mount ./config:/app/config (read-only).

    WHY: Spec §5.8 — 'Mount ./config:/app/config (read-only) so the service can
    read config/normalization.yaml.' The composition root loads this file at startup
    (spec §5.1). Without the mount, the container starts but crashes immediately
    with FileNotFoundError when it tries to read /app/config/normalization.yaml.
    The mount must be read-only to prevent the service from accidentally modifying
    the config source on the host.
    """

    def _get_volumes(self) -> list:
        """Return the volumes list for the identity-normalization service."""
        svc = _compose_in_service()
        return svc.get("volumes", [])

    def test_config_mount_is_present(self) -> None:
        """identity-normalization volumes must include a mount for ./config.

        WHY: config/normalization.yaml is loaded at service startup. Without the
        mount, the file is not visible inside the container and startup fails.
        """
        volumes = self._get_volumes()
        assert volumes, (
            "identity-normalization must declare a 'volumes' section. "
            "The ./config:/app/config mount is required for normalization.yaml."
        )
        # Accept both short string syntax and long object syntax
        has_config_mount = False
        for v in volumes:
            if isinstance(v, str):
                # Short syntax: "./config:/app/config" or "./config:/app/config:ro"
                if "./config" in v and "/app/config" in v:
                    has_config_mount = True
                    break
            elif isinstance(v, dict):
                # Long syntax: {source: ./config, target: /app/config, ...}
                source = v.get("source", "")
                target = v.get("target", "")
                if ("config" in source or "./config" in source) and "/app/config" in target:
                    has_config_mount = True
                    break
        assert has_config_mount, (
            f"identity-normalization volumes must include a mount for './config:/app/config'. "
            f"Found volumes: {volumes}. "
            "The normalization.yaml config is loaded at startup via this mount."
        )

    def test_config_mount_is_read_only(self) -> None:
        """The ./config:/app/config mount must be read-only (ro).

        WHY: Spec §5.8 — 'read-only'. The service should only READ the config, not
        write to it. A read-write mount would allow a bug in the service to overwrite
        the config file on the host, losing the normalization.yaml configuration.
        """
        volumes = self._get_volumes()
        config_vol = None
        for v in volumes:
            if isinstance(v, str):
                if "./config" in v and "/app/config" in v:
                    config_vol = v
                    break
            elif isinstance(v, dict):
                source = v.get("source", "")
                target = v.get("target", "")
                if ("config" in source or "./config" in source) and "/app/config" in target:
                    config_vol = v
                    break

        if config_vol is None:
            pytest.fail(
                "Cannot check read-only flag: config mount not found in volumes. "
                "Ensure ./config:/app/config is present first."
            )

        # Check for read-only flag
        if isinstance(config_vol, str):
            # Short syntax: ./config:/app/config:ro
            assert ":ro" in config_vol, (
                f"Config mount must be read-only (add ':ro' suffix). "
                f"Got: {config_vol!r}. "
                "Spec §5.8: mount ./config:/app/config read-only."
            )
        elif isinstance(config_vol, dict):
            # Long syntax: read_only: true
            read_only = config_vol.get("read_only", False)
            assert read_only is True, (
                f"Config mount must have read_only: true. "
                f"Got: {config_vol!r}."
            )


# ===========================================================================
# CLASS 3 — Existing services remain unchanged
# ===========================================================================


class TestExistingServicesUnchanged:
    """Adding identity-normalization must not remove any existing service.

    WHY: Spec §5.8 — 'Modify only the new entry; do not touch the infrastructure
    or event-ingestion services.' Accidentally removing or modifying postgres,
    redis, keycloak, openldap, or event-ingestion would break the entire stack.
    """

    @pytest.mark.parametrize("svc_name", sorted(REQUIRED_EXISTING_SERVICES))
    def test_existing_service_still_present(self, svc_name: str) -> None:
        """Each previously-existing service must remain in docker-compose.yml.

        WHY: The spec explicitly prohibits touching infrastructure services or
        event-ingestion when adding the identity-normalization entry. This test
        detects accidental deletions.
        """
        compose = _load_compose()
        services = compose.get("services", {})
        assert svc_name in services, (
            f"Service '{svc_name}' was removed from docker-compose.yml while adding "
            f"the identity-normalization entry. "
            f"Spec §5.8: do not touch existing services. "
            f"Present services: {sorted(services.keys())}"
        )

    def test_all_six_services_present(self) -> None:
        """docker-compose.yml must contain all 6 expected services.

        WHY: Consolidated assertion that catches a wholesale services section
        replacement in one test. The 6 services are: 4 infrastructure + event-ingestion
        + identity-normalization.
        """
        compose = _load_compose()
        services = set(compose.get("services", {}).keys())
        required = REQUIRED_EXISTING_SERVICES | {"identity-normalization"}
        missing = required - services
        assert not missing, (
            f"docker-compose.yml is missing required services: {missing}. "
            f"Present services: {sorted(services)}"
        )
