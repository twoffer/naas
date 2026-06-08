"""shared/pyproject.toml structure and dependency declarations.

Verifies that shared/pyproject.toml is present, correctly structured, and
declares all required runtime dependencies so that `pip install -e shared/`
succeeds in service containers.
"""

from __future__ import annotations

from pathlib import Path

import pytest


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
SHARED_DIR = REPO_ROOT / "shared"


class TestPyprojectToml:
    """shared/pyproject.toml must be present and correctly structured so that
    `pip install -e shared/` works.
    """

    @pytest.fixture(scope="class")
    def pyproject_path(self) -> Path:
        return SHARED_DIR / "pyproject.toml"

    @pytest.fixture(scope="class")
    def pyproject_content(self, pyproject_path) -> str:
        if not pyproject_path.exists():
            pytest.fail(
                f"shared/pyproject.toml not found at {pyproject_path} — "
                "the package cannot be installed without it"
            )
        return pyproject_path.read_text(encoding="utf-8")

    def test_pyproject_toml_exists(self, pyproject_path):
        """shared/pyproject.toml must exist for pip install -e to work."""
        assert pyproject_path.exists(), (
            f"shared/pyproject.toml not found at {pyproject_path}"
        )

    def test_pyproject_toml_declares_package_name(self, pyproject_content):
        """pyproject.toml must declare the package name 'naas-shared'."""
        assert 'name = "naas-shared"' in pyproject_content

    def test_pyproject_toml_requires_python_312(self, pyproject_content):
        """requires-python must specify >=3.12 per the project tech stack."""
        assert ">=3.12" in pyproject_content

    def test_pyproject_toml_declares_pydantic_dependency(self, pyproject_content):
        """pydantic is a hard runtime dependency — must be in [project].dependencies."""
        assert "pydantic>=" in pyproject_content

    def test_pyproject_toml_declares_pydantic_settings_dependency(
        self, pyproject_content
    ):
        """pydantic-settings is required for Settings class — must be declared."""
        assert "pydantic-settings>=" in pyproject_content

    def test_pyproject_toml_declares_structlog_dependency(self, pyproject_content):
        """structlog is required for setup_logging — must be declared."""
        assert "structlog>=" in pyproject_content

    def test_pyproject_toml_declares_sqlalchemy_dependency(self, pyproject_content):
        """sqlalchemy[asyncio] is required for database.py — must be declared."""
        assert "sqlalchemy" in pyproject_content.lower()

    def test_pyproject_toml_has_build_system(self, pyproject_content):
        """[build-system] section must be present for pip install -e to work."""
        assert "[build-system]" in pyproject_content
