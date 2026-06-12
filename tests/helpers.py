"""tests/helpers.py — single source of truth for repo-root discovery.

WHY self-contained: this module may be imported before tests/conftest.py has
run (e.g., when a single test file is collected directly via
``python -m pytest tests/infrastructure/test_openldap_ldif.py``). Under
importlib mode, Python resolves the ``tests`` package from the filesystem; the
walk-up logic uses ``__file__`` so it does not rely on sys.path being
pre-populated.

Usage::

    from tests.helpers import REPO_ROOT

    # or when a callable is needed (e.g., in module-level conditional logic):
    from tests.helpers import find_repo_root
"""

from __future__ import annotations

from pathlib import Path


def find_repo_root() -> Path:
    """Walk up from this file until we find docs/architecture/ — repo root marker.

    Uses ``__file__`` (this module's own path) so the result is correct even
    when conftest.py has not yet run and sys.path does not yet include the repo
    root.
    """
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT: Path = find_repo_root()
