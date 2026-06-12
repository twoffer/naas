"""conftest.py for event-ingestion service tests.

Ensures that `app.*` modules resolve to the event-ingestion service when tests
in this directory run, regardless of which other service test directories were
collected or run first.

WHY this is needed: Both event-ingestion and identity-normalization services
ship a top-level package literally named `app`. In a full-suite run with
importlib mode, pytest assigns unique module names to test files, but the
test's own `from app.main import app` still resolves via sys.path. Python's
module cache retains the first-imported `app.main` for the remainder of the
session. This conftest clears and re-anchors the `app.*` namespace before
each test in this directory so the correct service module is always loaded.

The root collection shim (previously in conftest.py at repo root) is no longer
needed now that test directories use underscored names — importlib mode
handles same-basename files in sibling directories without collision.
"""

from __future__ import annotations

import sys


from tests.helpers import REPO_ROOT

# Production service dir stays hyphenated — only test dirs use underscores.
SERVICE_DIR = str(REPO_ROOT / "services" / "event-ingestion")
SHARED_DIR = str(REPO_ROOT / "shared")

# Insert at collection time so `from app.main import app` in test files
# resolves during module-level import (before any test runs).
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)


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
