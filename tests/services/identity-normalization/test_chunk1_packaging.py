# Component: NAAS Spec 2 — Chunk 1: packaging artifacts
# Mode: TDD — all tests MUST fail until the implementer creates:
#   services/identity-normalization/Dockerfile
#   services/identity-normalization/requirements.txt
#
# What these tests validate:
#
#   requirements.txt:
#     - Lists fastapi (any version specifier)
#     - Lists uvicorn (with or without [standard])
#     - Lists python-ldap (required for LDAP enrichment; needs system build deps)
#     - Lists pyyaml (required for loading config/normalization.yaml)
#     - Does NOT list sqlalchemy, asyncpg, or redis (transitive via naas_shared)
#
#   Dockerfile:
#     - Exists at services/identity-normalization/Dockerfile
#     - Contains EXPOSE 8002 (port 8002, NOT 8001 which is event-ingestion)
#     - COPYs shared/ BEFORE service code (layer caching contract)
#     - Contains `pip install -e /app/shared/` (editable naas_shared install)
#     - CMD launches uvicorn on app.main:app port 8002
#     - Installs python-ldap system build dependencies BEFORE pip install:
#       gcc, libldap2-dev, libsasl2-dev — required to compile python-ldap C extension.
#       Without these, the image build fails at `pip install python-ldap`.
#
# Why python-ldap needs special handling:
#   python-ldap is a C extension that wraps the OpenLDAP client library.
#   The python:3.12-slim base image has no C compiler or LDAP headers.
#   Installing gcc + libldap2-dev + libsasl2-dev (via apt-get) before pip
#   is the documented installation pattern. Omitting any one of these causes
#   the build to fail with a cryptic gcc/ldap.h/sasl.h error.
#
# TDD state:
#   Dockerfile and requirements.txt do not exist yet.
#   All tests MUST fail with assertion errors until the files are created.

# stdlib
import sys
from pathlib import Path
from typing import Any

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
        "Could not locate repo root (expected a directory containing "
        f"docs/architecture/). Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"
DOCKERFILE_PATH = SERVICE_DIR / "Dockerfile"
REQUIREMENTS_PATH = SERVICE_DIR / "requirements.txt"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dockerfile_text() -> str:
    """Return Dockerfile content. Fails the calling test if absent."""
    if not DOCKERFILE_PATH.exists():
        pytest.fail(
            f"Dockerfile not found at {DOCKERFILE_PATH}. "
            "The implementer must create services/identity-normalization/Dockerfile."
        )
    return DOCKERFILE_PATH.read_text(encoding="utf-8")


def _requirements_text() -> str:
    """Return requirements.txt content. Fails the calling test if absent."""
    if not REQUIREMENTS_PATH.exists():
        pytest.fail(
            f"requirements.txt not found at {REQUIREMENTS_PATH}. "
            "The implementer must create services/identity-normalization/requirements.txt."
        )
    return REQUIREMENTS_PATH.read_text(encoding="utf-8")


def _requirements_lines() -> list[str]:
    """Return non-comment, non-empty lowercased lines from requirements.txt."""
    content = _requirements_text()
    return [
        line.strip().lower()
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# ===========================================================================
# CLASS 1 — requirements.txt
# ===========================================================================


class TestRequirementsTxt:
    """services/identity-normalization/requirements.txt: direct deps only.

    The four direct deps are: fastapi, uvicorn, python-ldap, pyyaml.
    Data-layer deps come transitively via naas_shared (installed via -e /app/shared/).
    """

    def test_requirements_txt_exists(self) -> None:
        """requirements.txt must exist at services/identity-normalization/requirements.txt.

        WHY: The Dockerfile copies this file and runs `pip install -r` on it.
        Without it, the image build fails at the COPY/RUN step.
        """
        assert REQUIREMENTS_PATH.exists(), (
            f"requirements.txt not found at {REQUIREMENTS_PATH}. "
            "The implementer must create services/identity-normalization/requirements.txt."
        )

    def test_requirements_txt_lists_fastapi(self) -> None:
        """requirements.txt must list fastapi (any version specifier or bare name).

        WHY: fastapi is the web framework for the /health endpoint. Without it,
        the image build installs it only if naas_shared pulls it transitively —
        fragile and unspecified behavior. Spec §5.8 names it explicitly.
        """
        lines = _requirements_lines()
        fastapi_lines = [l for l in lines if l.startswith("fastapi")]
        assert fastapi_lines, (
            f"requirements.txt must list 'fastapi' (with or without version pin). "
            f"Found lines: {lines}"
        )

    def test_requirements_txt_lists_uvicorn(self) -> None:
        """requirements.txt must list uvicorn (with or without [standard] extra).

        WHY: uvicorn is the ASGI server. The Dockerfile CMD is 'uvicorn app.main:app
        --port 8002'. If uvicorn is absent, the CMD fails with 'command not found'.
        """
        lines = _requirements_lines()
        uvicorn_lines = [l for l in lines if l.startswith("uvicorn")]
        assert uvicorn_lines, (
            f"requirements.txt must list 'uvicorn' (with or without [standard]). "
            f"Found lines: {lines}"
        )

    def test_requirements_txt_lists_python_ldap(self) -> None:
        """requirements.txt must list python-ldap (required for LDAP enrichment).

        WHY: Spec §5.8 — 'requirements.txt: python-ldap>=3.4'. python-ldap is the
        C-extension LDAP client used by the LdapEnricher adapter (app/adapters/ldap.py).
        Without it, any attempt to import ldap raises ModuleNotFoundError.
        Note: PyPI name is 'python-ldap'; pip normalizes hyphens to dashes/underscores.
        """
        lines = _requirements_lines()
        # Match 'python-ldap', 'python_ldap' — pip normalizes these
        ldap_lines = [
            l for l in lines
            if l.startswith("python-ldap") or l.startswith("python_ldap")
        ]
        assert ldap_lines, (
            f"requirements.txt must list 'python-ldap' (with or without version pin). "
            f"Spec §5.8. Found lines: {lines}"
        )

    def test_requirements_txt_lists_pyyaml(self) -> None:
        """requirements.txt must list pyyaml (required for loading normalization.yaml).

        WHY: Spec §5.8 — 'pyyaml>=6.0'. The composition root loads and validates
        config/normalization.yaml at startup. Without pyyaml, the yaml.safe_load
        call raises ModuleNotFoundError and startup fails with a confusing error.
        """
        lines = _requirements_lines()
        # Match 'pyyaml', 'pyyaml>=...', etc.
        yaml_lines = [l for l in lines if l.startswith("pyyaml")]
        assert yaml_lines, (
            f"requirements.txt must list 'pyyaml' (with or without version pin). "
            f"Spec §5.8. Found lines: {lines}"
        )

    def test_requirements_txt_does_not_list_sqlalchemy(self) -> None:
        """requirements.txt must NOT list sqlalchemy.

        WHY: SQLAlchemy is pulled in transitively by naas_shared. Duplicating it
        risks version conflicts between what the service pins and what naas_shared
        expects.
        """
        lines = _requirements_lines()
        sqlalchemy_lines = [l for l in lines if l.startswith("sqlalchemy")]
        assert not sqlalchemy_lines, (
            f"requirements.txt must NOT list 'sqlalchemy' — it is a transitive dep "
            f"from naas_shared. Found: {sqlalchemy_lines}"
        )

    def test_requirements_txt_does_not_list_asyncpg(self) -> None:
        """requirements.txt must NOT list asyncpg.

        WHY: asyncpg is the async PostgreSQL driver pulled in by naas_shared's
        sqlalchemy[asyncio] dependency. Listing it separately risks version mismatch.
        """
        lines = _requirements_lines()
        asyncpg_lines = [l for l in lines if l.startswith("asyncpg")]
        assert not asyncpg_lines, (
            f"requirements.txt must NOT list 'asyncpg' — it is a transitive dep "
            f"from naas_shared. Found: {asyncpg_lines}"
        )

    def test_requirements_txt_does_not_list_redis_client(self) -> None:
        """requirements.txt must NOT list the redis Python client package.

        WHY: redis-py is a dependency of naas_shared. Listing it separately
        creates version conflicts with the shared client version.
        """
        lines = _requirements_lines()
        redis_lines = [
            l for l in lines
            if l == "redis" or l.startswith("redis==") or l.startswith("redis>=") or l.startswith("redis~=")
        ]
        assert not redis_lines, (
            f"requirements.txt must NOT list 'redis' — it is a transitive dep "
            f"from naas_shared. Found: {redis_lines}"
        )


# ===========================================================================
# CLASS 2 — Dockerfile
# ===========================================================================


class TestDockerfile:
    """services/identity-normalization/Dockerfile: repo-root context, shared/ first,
    python-ldap system deps before pip, EXPOSE 8002, uvicorn CMD on port 8002.
    """

    def test_dockerfile_exists(self) -> None:
        """Dockerfile must exist at services/identity-normalization/Dockerfile.

        WHY: Without it, docker compose build identity-normalization fails with
        'Dockerfile not found'. This is the path referenced in docker-compose.yml's
        build.dockerfile field.
        """
        assert DOCKERFILE_PATH.exists(), (
            f"Dockerfile not found at {DOCKERFILE_PATH}. "
            "The implementer must create services/identity-normalization/Dockerfile."
        )

    def test_dockerfile_exposes_port_8002(self) -> None:
        """Dockerfile must contain EXPOSE 8002.

        WHY: The spec §5.8 states the port is 8002 (not 8001 — that is event-ingestion).
        The docker-compose.yml maps ${IDENTITY_NORMALIZATION_PORT:-8002}:8002.
        An EXPOSE for the wrong port creates a confusing mismatch and may cause
        the healthcheck to probe the wrong port.
        """
        content = _dockerfile_text()
        lines = [line.strip() for line in content.splitlines()]
        expose_lines = [l for l in lines if l.upper().startswith("EXPOSE")]
        assert any("8002" in l for l in expose_lines), (
            f"Dockerfile must contain 'EXPOSE 8002'. "
            f"Found EXPOSE lines: {expose_lines}. "
            "Port 8002 is the identity-normalization port (not 8001 / event-ingestion)."
        )

    def test_dockerfile_copies_shared_before_service_code(self) -> None:
        """COPY shared/ must appear before COPY services/identity-normalization/ in Dockerfile.

        WHY: Spec §5.8 Option A pattern. Docker layer caching is invalidated by the
        first COPY that changes. Shared/ changes less often than service code, so it
        must be copied first for efficient incremental rebuilds.
        """
        content = _dockerfile_text()
        lines = content.splitlines()

        shared_copy_idx = None
        service_copy_idx = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("COPY") and "shared/" in stripped and shared_copy_idx is None:
                shared_copy_idx = i
            if stripped.startswith("COPY") and "identity-normalization" in stripped:
                if service_copy_idx is None:
                    service_copy_idx = i

        assert shared_copy_idx is not None, (
            "Dockerfile must contain a COPY instruction for shared/ "
            "(e.g., 'COPY shared/ /app/shared/'). Not found."
        )
        assert service_copy_idx is not None, (
            "Dockerfile must contain a COPY instruction for services/identity-normalization "
            "(e.g., 'COPY services/identity-normalization/app/ ...'). Not found."
        )
        assert shared_copy_idx < service_copy_idx, (
            f"COPY shared/ (line {shared_copy_idx + 1}) must appear BEFORE "
            f"COPY services/identity-normalization/ (line {service_copy_idx + 1}). "
            "The shared library changes less often and should be an earlier layer."
        )

    def test_dockerfile_installs_shared_as_editable(self) -> None:
        """Dockerfile must run `pip install -e /app/shared/` (editable naas_shared install).

        WHY: Spec §5.8 Option A pattern — 'COPY shared/ /app/shared/ then RUN pip
        install -e /app/shared/'. The -e flag installs the package from the COPYed
        source path, making `import naas_shared` resolve inside the container.
        Without it, the shared source is present but not on the Python path.
        """
        content = _dockerfile_text()
        lines = content.splitlines()
        install_lines = [
            line.strip() for line in lines
            if "pip install" in line and "shared" in line
        ]
        has_editable_install = any(
            "-e" in l and "shared" in l for l in install_lines
        )
        assert has_editable_install, (
            f"Dockerfile must run 'pip install -e /app/shared/' (or equivalent). "
            f"Found install lines referencing shared: {install_lines}. "
            "The -e flag is required so 'import naas_shared' resolves in the container."
        )

    def test_dockerfile_cmd_launches_uvicorn_on_port_8002(self) -> None:
        """Dockerfile CMD must launch uvicorn on app.main:app port 8002.

        WHY: Spec §5.8 — CMD is 'uvicorn app.main:app --host 0.0.0.0 --port 8002'.
        The docker-compose healthcheck probes http://localhost:8002/health. A CMD
        that uses a different port causes the healthcheck to always fail and the
        container to be permanently 'unhealthy'.
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
        assert "8002" in last_cmd, (
            f"CMD must use port 8002. Got: {last_cmd!r}. "
            "The docker-compose healthcheck probes localhost:8002."
        )

    def test_dockerfile_installs_gcc_for_python_ldap(self) -> None:
        """Dockerfile must apt-get install gcc before pip install.

        WHY: Spec §5.8 — 'python-ldap needs system build dependencies: add an
        apt-get install for libldap2-dev, libsasl2-dev, and gcc BEFORE pip install,
        or the build fails compiling python-ldap.' python:3.12-slim has no C compiler.
        Without gcc the python-ldap build fails with 'gcc: command not found'.
        """
        content = _dockerfile_text()
        lower = content.lower()
        assert "gcc" in lower, (
            "Dockerfile must install 'gcc' via apt-get (needed to compile python-ldap). "
            "Spec §5.8: add 'gcc' to the apt-get install list before pip install."
        )

    def test_dockerfile_installs_libldap2_dev_for_python_ldap(self) -> None:
        """Dockerfile must apt-get install libldap2-dev before pip install.

        WHY: Spec §5.8 — libldap2-dev provides ldap.h, the C header for the OpenLDAP
        client library that python-ldap's C extension includes at build time.
        Without it the build fails with 'ldap.h: No such file or directory'.
        """
        content = _dockerfile_text()
        lower = content.lower()
        assert "libldap2-dev" in lower, (
            "Dockerfile must install 'libldap2-dev' via apt-get "
            "(needed to compile python-ldap). "
            "Spec §5.8: add 'libldap2-dev' to the apt-get install list."
        )

    def test_dockerfile_installs_libsasl2_dev_for_python_ldap(self) -> None:
        """Dockerfile must apt-get install libsasl2-dev before pip install.

        WHY: Spec §5.8 — libsasl2-dev provides sasl.h, the C header for SASL
        authentication used by python-ldap. Without it the build fails with
        'sasl.h: No such file or directory'.
        """
        content = _dockerfile_text()
        lower = content.lower()
        assert "libsasl2-dev" in lower, (
            "Dockerfile must install 'libsasl2-dev' via apt-get "
            "(needed to compile python-ldap). "
            "Spec §5.8: add 'libsasl2-dev' to the apt-get install list."
        )

    def test_dockerfile_apt_get_before_pip_install_python_ldap(self) -> None:
        """apt-get install for system deps must appear BEFORE pip install in the Dockerfile.

        WHY: If pip install runs before gcc/libldap2-dev are installed, python-ldap's
        C extension compilation fails immediately. The apt-get RUN must precede the
        pip RUN. This test validates line ordering, not just presence.
        """
        content = _dockerfile_text()
        lines = content.splitlines()

        apt_get_idx = None
        pip_install_idx = None

        for i, line in enumerate(lines):
            stripped = line.strip()
            if "apt-get" in stripped and "install" in stripped and apt_get_idx is None:
                apt_get_idx = i
            if "pip install" in stripped and pip_install_idx is None:
                pip_install_idx = i

        assert apt_get_idx is not None, (
            "Dockerfile must contain an apt-get install line for system build deps "
            "(gcc, libldap2-dev, libsasl2-dev). Not found."
        )
        assert pip_install_idx is not None, (
            "Dockerfile must contain a pip install line. Not found."
        )
        assert apt_get_idx < pip_install_idx, (
            f"apt-get install (line {apt_get_idx + 1}) must appear BEFORE "
            f"pip install (line {pip_install_idx + 1}). "
            "System build deps (gcc, libldap2-dev, libsasl2-dev) must be installed "
            "before python-ldap is compiled."
        )
