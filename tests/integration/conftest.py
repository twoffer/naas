"""tests/integration/conftest.py — live-docker integration test harness.

Provides:
- Skip gate: integration tests are skipped unless NAAS_RUN_INTEGRATION=1 env
  var or --integration CLI flag is present. Works for both plain `pytest` from
  repo root (collect-then-skip with zero errors) and `pytest tests/integration
  --integration` (opt-in execution).
- Session-scoped compose_stack fixture: brings up the subset of services needed
  for integration tests, waits for app-level readiness beyond healthchecks,
  tears down with volume wipe on completion (or captures logs on failure).

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


# ---------------------------------------------------------------------------
# Repo-root discovery
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()

# Ensure naas_shared is importable (mirrors root conftest, safe to repeat).
_shared_dir = str(REPO_ROOT / "shared")
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

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

# App services whose HTTP health endpoints must return status="healthy"
# before tests run (infrastructure services are gated by --wait healthchecks).
_APP_HEALTH_URLS = {
    "event-ingestion": "http://localhost:8001/health",
    "identity-normalization": "http://localhost:8002/health",
}

# Log directory for failure captures (gitignore is feature-implementer's concern)
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
# Helper: poll app health endpoints
# ---------------------------------------------------------------------------


def _wait_for_app_health(
    services: list[str],
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

    # Only poll services that are in the requested service list
    # (if services is empty we poll all app health URLs).
    urls_to_check = {
        name: url
        for name, url in _APP_HEALTH_URLS.items()
        if not services or name in services
    }

    deadline = time.monotonic() + timeout_s
    pending = dict(urls_to_check)  # name → url

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


def _capture_compose_logs(services: list[str]) -> None:
    """Write docker compose logs for app services to .logs/ directory."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_services = [s for s in services if s in _APP_HEALTH_URLS] or list(
        _APP_HEALTH_URLS
    )
    for svc in log_services:
        log_path = _LOGS_DIR / f"{svc}.log"
        try:
            result = subprocess.run(
                ["docker", "compose", "logs", "--no-color", svc],
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
def compose_stack() -> Generator[dict, None, None]:
    """Bring up the docker compose service subset, yield, then tear down.

    Lifecycle:
      1. Ensure .env exists.
      2. docker compose up -d --build --wait <services>
      3. Poll HTTP health endpoints until status=="healthy".
      4. Yield a dict with connection parameters.
      5. Capture logs if the session had failures.
      6. docker compose down -v (unless NAAS_IT_KEEP_STACK=1).

    The --wait flag makes docker compose block until all container
    healthchecks pass, then we do a second application-level health check
    to confirm the FastAPI services report status="healthy" (not degraded).

    NAAS_IT_KEEP_STACK=1 suppresses teardown — useful for local debugging
    without losing container state between test runs.
    """
    _ensure_dot_env()

    services = _resolve_services()
    cmd = ["docker", "compose", "up", "-d", "--build", "--wait"] + services

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
            f"stdout: {up_result.stdout}\nstderr: {up_result.stderr}"
        )

    # Application-level health poll (beyond container healthchecks)
    try:
        _wait_for_app_health(services)
    except RuntimeError as exc:
        _capture_compose_logs(services)
        pytest.fail(str(exc))

    # Connection parameters available to tests
    connection_info = {
        "pg_dsn": (
            "host=localhost port=5432 dbname=naas user=naas password=naas_dev_password"
        ),
        "pg_conninfo": {
            "host": "localhost",
            "port": 5432,
            "dbname": "naas",
            "user": "naas",
            "password": "naas_dev_password",
        },
        "event_ingestion_url": "http://localhost:8001",
        "identity_normalization_url": "http://localhost:8002",
        "services": services,
    }

    session_failed = False
    try:
        yield connection_info
    except Exception:
        session_failed = True
        raise
    finally:
        if session_failed:
            _capture_compose_logs(services)

        keep_stack = bool(os.environ.get("NAAS_IT_KEEP_STACK"))
        if not keep_stack:
            subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    "docker-compose.yml",
                    "-f",
                    "docker-compose.test.yml",
                    "down",
                    "-v",
                    "--remove-orphans",
                ],
                cwd=str(REPO_ROOT),
                timeout=60,
                capture_output=True,
                text=True,
            )
