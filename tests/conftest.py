"""tests/conftest.py — project-wide test configuration.

Inserts shared/naas_shared onto sys.path at collection time so that every
test subtree can import naas_shared without per-file path boilerplate.

WHY here and not in the repo root: with importlib mode active the root
conftest's pytest_collect_file shim is no longer needed (importlib gives
each test file a unique module name, eliminating same-basename collisions).
The only shared setup remaining is the sys.path insertion for naas_shared.
"""

from __future__ import annotations

import sys

from tests.helpers import REPO_ROOT

SHARED_DIR = str(REPO_ROOT / "shared")

# Insert shared/ so naas_shared imports resolve for all subtrees.
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)


def pytest_addoption(parser):
    """Register the --integration flag.

    Must live here (tests/conftest.py) so it is visible regardless of the
    pytest invocation root. pytest_addoption in a subdirectory conftest is
    ignored when pytest is invoked from the repo root — only the *initial*
    conftest (determined by rootdir / testpaths) processes addoption hooks.

    Integration tests are skipped by default; opt in via:
      --integration CLI flag
      NAAS_RUN_INTEGRATION=1 environment variable
    """
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run live-docker integration tests (requires docker compose stack).",
    )
