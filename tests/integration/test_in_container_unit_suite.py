"""tests/integration/test_in_container_unit_suite.py

Verifies that the full host unit test suite passes when run INSIDE the
identity-normalization container image.

Motivation: the identity-normalization image is the only environment where
python-ldap is fully importable (it is compiled during image build). Unit
tests that import the LDAP adapter are skipped on the host dev machine
because python-ldap cannot be installed there. Running the suite inside the
image gives those tests real coverage.

Contract for the test-runner service (implemented by feature-implementer):
  - Service name: test-runner
  - Profile: test (started only via --profile test)
  - Base image: services/identity-normalization/Dockerfile
  - Repo mounted read-only at /workspace
  - Default command:
      pip install -r requirements-dev.txt &&
      pytest tests/
        --ignore=tests/integration
        --ignore=tests/infrastructure/test_docker_compose.py

The test-runner service is started via docker-compose.test.yml which overlays
onto docker-compose.yml via -f flags. The suite uses docker compose v2 plugin
syntax throughout (never docker-compose hyphenated binary).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repo-root discovery (self-contained — cannot import from conftest)
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(f"Cannot locate repo root from {Path(__file__).resolve()}")


REPO_ROOT = _find_repo_root()

# ---------------------------------------------------------------------------
# Module-level markers
# ---------------------------------------------------------------------------

pytestmark = [
    pytest.mark.integration,
    # 600s: image build + pip install inside container + full test suite run
    pytest.mark.timeout(600),
]

# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestInContainerUnitSuite:
    """Run the full host unit suite inside the identity-normalization image.

    The test-runner docker compose service (profile: test) executes:
      pytest tests/ --ignore=tests/integration
                    --ignore=tests/infrastructure/test_docker_compose.py

    That second ignore is required because test_docker_compose.py shells out
    to the docker CLI, which is not present inside the container.
    """

    def test_unit_suite_passes_in_container(self, compose_stack: dict) -> None:
        """All unit tests must pass when run inside the identity-normalization image.

        Shells out to:
          docker compose
            -f docker-compose.yml
            -f docker-compose.test.yml
            --profile test
            run --rm test-runner

        The compose_stack fixture ensures infrastructure (postgres, redis,
        openldap) is already up, so the test-runner can connect to them.

        Asserts:
          - exit code 0 (pytest passed all tests)
          - stdout/stderr contains a pytest summary line indicating tests ran
            (e.g. "passed" appearing in the summary — proves the suite was not
            vacuously empty and did execute).
        """
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "-f",
                "docker-compose.test.yml",
                "--profile",
                "test",
                "run",
                "--rm",
                "test-runner",
            ],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=590,  # inner timeout < outer pytest timeout (600s)
        )

        combined = result.stdout + result.stderr

        assert result.returncode == 0, (
            f"In-container unit suite failed (exit {result.returncode}).\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )

        # Verify the suite actually ran (not vacuously empty).
        # pytest summary lines contain "passed" when at least one test passes.
        assert "passed" in combined, (
            "In-container test run did not report any 'passed' tests. "
            "The suite may have been empty or failed before collecting.\n"
            f"Combined output:\n{combined}"
        )
