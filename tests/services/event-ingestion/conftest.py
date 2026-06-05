"""conftest.py for event-ingestion service tests.

Ensures that `app.*` modules resolve to the event-ingestion service when tests
in this directory run, regardless of which other service test directories were
collected or run first.

WHY this is needed: Both event-ingestion and identity-normalization test files
insert their respective service directory into sys.path at module level. In a
full-suite run (`pytest tests/`), Python's module cache retains the first-imported
`app.main` for the remainder of the session. This conftest clears and re-anchors
the `app.*` namespace before each test in this directory so the correct service
module is always loaded.
"""

from __future__ import annotations

import sys
from pathlib import Path


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
SERVICE_DIR = str(REPO_ROOT / "services" / "event-ingestion")
SHARED_DIR = str(REPO_ROOT / "shared")


def pytest_runtest_setup(item) -> None:
    """Before each test, ensure app.* resolves to event-ingestion.

    Clears any cached `app` modules from a prior service's collection pass
    and ensures this service's directory is at the front of sys.path.
    """
    # Clear all cached `app.*` modules so Python re-imports from the correct path.
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]

    # Ensure this service dir is at the front of sys.path.
    if SERVICE_DIR in sys.path:
        sys.path.remove(SERVICE_DIR)
    sys.path.insert(0, SERVICE_DIR)

    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)
