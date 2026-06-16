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

    # flatten a FastAPI app's route tree for introspection:
    from tests.helpers import iter_routes
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
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


def iter_routes(routes: Iterable) -> Iterator:
    """Yield leaf routes from a FastAPI app's route list, flattening include wrappers.

    WHY: FastAPI (pinned to 0.137.x via the lockfiles — see
    DEPENDENCIES.md) has ``app.include_router()`` insert a
    single ``_IncludedRouter`` wrapper into ``app.routes`` whose child routes
    live on ``.original_router.routes``, rather than flattening the child
    ``APIRoute`` instances directly into ``app.routes``. Route introspection
    that iterates ``app.routes`` would otherwise see the opaque wrapper (which
    has no ``.path``) instead of the real endpoints.

    Wrappers are detected via the ``original_router`` attribute and recursed
    into (handling nested includes); every other route type (plain
    ``APIRoute``, ``Mount``, etc.) is yielded as-is.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None and hasattr(included, "routes"):
            yield from iter_routes(included.routes)
        else:
            yield route
