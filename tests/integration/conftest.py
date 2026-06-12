"""tests/integration/conftest.py — live-docker integration test harness.

Provides:
- Skip gate: integration tests are skipped unless NAAS_RUN_INTEGRATION=1 env
  var or --integration CLI flag is present. Works for both plain `pytest` from
  repo root (collect-then-skip with zero errors) and `pytest tests/integration
  --integration` (opt-in execution).
- Session-scoped compose_stack fixture: brings up the subset of services needed
  for integration tests, waits for app-level readiness beyond healthchecks,
  tears down with volume wipe on completion (or captures logs on failure).

Compose project isolation: every compose command runs under the dedicated
project name "naas-it" (see _COMPOSE_PROJECT), so the `down -v` teardown can
only ever remove the harness's own containers/volumes — never the default
project's dev stack or its data. Because docker-compose.yml pins container
names and host ports, the suite cannot run *concurrently* with a dev stack:
`up` fails loudly on a name/port conflict instead of silently taking the dev
stack over.

Connection parameters (PG credentials, host ports) are resolved the same way
docker compose resolves them: process environment first, then the .env file,
then the compose-file defaults — so a customized .env keeps tests and stack
in agreement instead of failing with auth errors.

NOTE: pytest_addoption for --integration is registered in tests/conftest.py,
not here. pytest_addoption must live in the conftest that is active regardless
of invocation root — placing it here would silence it whenever pytest is
invoked from the repo root.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator

import pytest

from tests.helpers import REPO_ROOT

# Ensure naas_shared is importable (mirrors root conftest, safe to repeat).
_shared_dir = str(REPO_ROOT / "shared")
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

# ---------------------------------------------------------------------------
# Compose project isolation
# ---------------------------------------------------------------------------

# Dedicated compose project name: teardown's `down -v` is scoped to this
# project and cannot touch the default project's containers or volumes.
_COMPOSE_PROJECT = "naas-it"

# Base command for every compose invocation. Both -f files are always passed
# so the profile-gated test-runner service is part of the same project (and a
# lingering test-runner container is removed by `down --remove-orphans`).
_COMPOSE_CMD = [
    "docker",
    "compose",
    "-p",
    _COMPOSE_PROJECT,
    "-f",
    str(REPO_ROOT / "docker-compose.yml"),
    "-f",
    str(REPO_ROOT / "docker-compose.test.yml"),
]

# ---------------------------------------------------------------------------
# Default service subset (excludes keycloak: 60s start_period dominates)
# ---------------------------------------------------------------------------

_DEFAULT_SERVICES = [
    "postgres",
    "redis",
    "openldap",
    "event-ingestion",
    "identity-normalization",
]

# Log directory for failure captures
_LOGS_DIR = Path(__file__).parent / ".logs"


# ---------------------------------------------------------------------------
# Skip gate — collection hook
# ---------------------------------------------------------------------------


def pytest_collection_modifyitems(config, items):
    """Skip integration-marked tests unless the flag or env var is set.

    Runs after collection so plain `pytest` from any root collects cleanly
    and then skips — no collection errors, no import failures.
    """
    run_integration = config.getoption("--integration", default=False) or bool(
        os.environ.get("NAAS_RUN_INTEGRATION")
    )
    if run_integration:
        return  # Let all items run; integration tests are not deselected.

    skip_marker = pytest.mark.skip(
        reason=(
            "Integration test skipped by default. "
            "Pass --integration or set NAAS_RUN_INTEGRATION=1 to run."
        )
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_marker)


# ---------------------------------------------------------------------------
# Helper: resolve service list
# ---------------------------------------------------------------------------


def _resolve_services() -> list[str]:
    """Return the list of docker compose services to start.

    Override via NAAS_IT_SERVICES env var (space-separated). Literal "all"
    means the full compose stack (no explicit service list).
    """
    override = os.environ.get("NAAS_IT_SERVICES", "").strip()
    if not override:
        return _DEFAULT_SERVICES
    if override == "all":
        return []  # Empty list → docker compose up starts everything
    return override.split()


# ---------------------------------------------------------------------------
# Helper: ensure .env exists
# ---------------------------------------------------------------------------


def _ensure_dot_env() -> None:
    """Copy .env.example → .env if .env is absent.

    Integration tests require .env for service env_file references in
    docker-compose.yml. A missing .env causes compose to warn/fail.
    """
    env_file = REPO_ROOT / ".env"
    env_example = REPO_ROOT / ".env.example"
    if not env_file.exists():
        if env_example.exists():
            shutil.copy(env_example, env_file)
        else:
            pytest.fail(
                f"Neither .env nor .env.example found at {REPO_ROOT}. "
                "Cannot start integration stack."
            )


# ---------------------------------------------------------------------------
# Helper: resolve connection settings like docker compose does
# ---------------------------------------------------------------------------


def _read_dot_env() -> dict[str, str]:
    """Parse REPO_ROOT/.env into a dict (simple KEY=VALUE lines only).

    Mirrors compose's dotenv handling for the subset this repo uses:
    inline ` #` comments are stripped from unquoted values, and matching
    surrounding single/double quotes are removed.
    """
    values: dict[str, str] = {}
    env_file = REPO_ROOT / ".env"
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'") and len(value) > 1 and value.endswith(value[0]):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key.strip()] = value
    return values


def _resolve_settings() -> dict[str, str]:
    """Resolve connection settings with compose's precedence.

    docker compose resolves ${VAR:-default} from the process environment
    first, then the project .env file, then the compose-file default. Mirror
    that here so the harness always agrees with the stack it started.
    """
    dot_env = _read_dot_env()
    defaults = {
        "POSTGRES_USER": "naas",
        "POSTGRES_PASSWORD": "naas_dev_password",
        "POSTGRES_DB": "naas",
        "POSTGRES_PORT": "5432",
        "EVENT_INGESTION_PORT": "8001",
        "IDENTITY_NORMALIZATION_PORT": "8002",
    }
    return {
        key: os.environ.get(key) or dot_env.get(key) or default
        for key, default in defaults.items()
    }


# ---------------------------------------------------------------------------
# Helper: poll app health endpoints
# ---------------------------------------------------------------------------


def _wait_for_app_health(
    health_urls: dict[str, str],
    timeout_s: float = 90.0,
    poll_interval_s: float = 2.0,
) -> None:
    """Poll each app service health URL until status=="healthy" or timeout.

    The docker compose --wait flag gates on container healthchecks, but those
    check TCP reachability / a simple HTTP 200.  The event-ingestion health
    endpoint returns HTTP 200 even when reporting status="degraded" (PG/Redis
    down in body).  This poller checks the body status field.

    Raises RuntimeError if any service does not reach "healthy" within timeout.
    """
    # httpx may not be installed yet on some dev setups; use urllib from stdlib.
    import json
    import urllib.error
    import urllib.request

    deadline = time.monotonic() + timeout_s
    pending = dict(health_urls)  # name → url

    while pending:
        if time.monotonic() > deadline:
            still_pending = ", ".join(pending)
            raise RuntimeError(
                f"Timed out ({timeout_s}s) waiting for app health: {still_pending}"
            )
        for name in list(pending):
            url = pending[name]
            try:
                with urllib.request.urlopen(url, timeout=5) as resp:
                    body = json.loads(resp.read())
                    if body.get("status") == "healthy":
                        del pending[name]
            except (urllib.error.URLError, OSError, ValueError):
                pass  # service not ready yet; retry on next iteration
        if pending:
            time.sleep(poll_interval_s)


# ---------------------------------------------------------------------------
# Helper: capture docker compose logs to .logs/ on failure
# ---------------------------------------------------------------------------


def _capture_compose_logs(services: list[str], app_services: list[str]) -> None:
    """Write docker compose logs for app services to .logs/ directory."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_services = [s for s in services if s in app_services] or app_services
    for svc in log_services:
        log_path = _LOGS_DIR / f"{svc}.log"
        try:
            result = subprocess.run(
                _COMPOSE_CMD + ["logs", "--no-color", svc],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                timeout=30,
            )
            log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            log_path.write_text(f"Failed to capture logs: {exc}", encoding="utf-8")


# ---------------------------------------------------------------------------
# Session-scoped stack fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def compose_stack(request: pytest.FixtureRequest) -> Generator[dict, None, None]:
    """Bring up the docker compose service subset, yield, then tear down.

    Lifecycle:
      1. Ensure .env exists; resolve connection settings from it.
      2. docker compose -p naas-it up -d --build --wait <services>
      3. Poll HTTP health endpoints until status=="healthy".
      4. Yield a dict with connection parameters.
      5. Capture logs if any test in the session failed.
      6. docker compose -p naas-it down -v (unless NAAS_IT_KEEP_STACK=1).

    The --wait flag makes docker compose block until all container
    healthchecks pass, then we do a second application-level health check
    to confirm the FastAPI services report status="healthy" (not degraded).

    NAAS_IT_KEEP_STACK=1 suppresses teardown — useful for local debugging
    without losing container state between test runs.

    Yields (all derived from the resolved .env — tests must consume these
    rather than hardcoding credentials/ports):
      pg_dsn / pg_conninfo  — PostgreSQL connection parameters
      event_ingestion_url / identity_normalization_url — service base URLs
      services              — the compose services started
      repo_root             — repo root as a Path
      compose_cmd           — base compose command (project + -f flags) for
                              tests that need their own compose invocations
    """
    _ensure_dot_env()
    settings = _resolve_settings()

    ingestion_url = f"http://localhost:{settings['EVENT_INGESTION_PORT']}"
    normalization_url = f"http://localhost:{settings['IDENTITY_NORMALIZATION_PORT']}"

    # App services whose HTTP health endpoints must return status="healthy"
    # before tests run (infrastructure services are gated by --wait healthchecks).
    app_health_urls = {
        "event-ingestion": f"{ingestion_url}/health",
        "identity-normalization": f"{normalization_url}/health",
    }

    services = _resolve_services()
    # Only poll services that are in the requested service list
    # (if services is empty we poll all app health URLs).
    urls_to_check = {
        name: url
        for name, url in app_health_urls.items()
        if not services or name in services
    }
    app_services = list(app_health_urls)

    cmd = _COMPOSE_CMD + ["up", "-d", "--build", "--wait"] + services

    up_result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        timeout=300,  # 5 min max for image build + container start
        capture_output=True,
        text=True,
    )
    if up_result.returncode != 0:
        pytest.fail(
            f"docker compose up failed (exit {up_result.returncode}).\n"
            f"stdout: {up_result.stdout}\nstderr: {up_result.stderr}\n"
            "Hint: a name/port conflict here usually means a dev stack is "
            "already running in the default compose project — stop it first "
            "(the harness deliberately refuses to share or replace it)."
        )

    # Application-level health poll (beyond container healthchecks)
    try:
        _wait_for_app_health(urls_to_check)
    except RuntimeError as exc:
        _capture_compose_logs(services, app_services)
        pytest.fail(str(exc))

    # Connection parameters available to tests
    connection_info = {
        "pg_dsn": (
            f"host=localhost port={settings['POSTGRES_PORT']} "
            f"dbname={settings['POSTGRES_DB']} user={settings['POSTGRES_USER']} "
            f"password={settings['POSTGRES_PASSWORD']}"
        ),
        "pg_conninfo": {
            "host": "localhost",
            "port": int(settings["POSTGRES_PORT"]),
            "dbname": settings["POSTGRES_DB"],
            "user": settings["POSTGRES_USER"],
            "password": settings["POSTGRES_PASSWORD"],
        },
        "event_ingestion_url": ingestion_url,
        "identity_normalization_url": normalization_url,
        "services": services,
        "repo_root": REPO_ROOT,
        "compose_cmd": list(_COMPOSE_CMD),
    }

    failed_before = request.session.testsfailed
    try:
        yield connection_info
    finally:
        # Test failures do NOT propagate through a fixture's yield — compare
        # the session failure counter instead to decide on log capture.
        if request.session.testsfailed > failed_before:
            _capture_compose_logs(services, app_services)

        keep_stack = bool(os.environ.get("NAAS_IT_KEEP_STACK"))
        if not keep_stack:
            subprocess.run(
                _COMPOSE_CMD + ["down", "-v", "--remove-orphans"],
                cwd=str(REPO_ROOT),
                timeout=60,
                capture_output=True,
                text=True,
            )
