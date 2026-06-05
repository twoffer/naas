"""conftest.py for identity-normalization service tests.

Ensures that `app.*` modules resolve to the identity-normalization service
when tests in this directory run, regardless of which other service test
directories were collected first.

WHY this is needed: Both event-ingestion and identity-normalization test files
insert their respective service directory into sys.path at module level. In a
full-suite run (`pytest tests/`), Python's module cache retains the first-imported
`app.main` for the remainder of the session. This conftest clears and re-anchors
the `app.*` namespace before each test in this directory so the correct service
module is always loaded.

The auto_flush_tempfile fixture below works around a buffering issue in test
helper functions that call load_config() on a NamedTemporaryFile whose write
buffer has not yet been flushed to the OS.  Python's text-mode file objects
buffer writes; reading the same path from a second file descriptor before the
first is flushed or closed yields an empty file.  The fixture monkeypatches
tempfile.NamedTemporaryFile so its write() method flushes immediately, making
the data visible to any concurrent reader of the same path.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
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
SERVICE_DIR = str(REPO_ROOT / "services" / "identity-normalization")
SHARED_DIR = str(REPO_ROOT / "shared")


_REAL_NAMED_TEMP_FILE = tempfile.NamedTemporaryFile


class _AutoFlushWrapper:
    """Thin wrapper around a NamedTemporaryFile that flushes on every write().

    WHY: test helper functions (e.g. _load_config_with_strategy) call
    load_config() on the same path while still inside the NamedTemporaryFile
    ``with`` block, before Python's write buffer is flushed to the OS.
    Wrapping the file object to flush-on-write makes the data immediately
    visible to a second open() of the same path.
    """

    def __init__(self, ntf: io.IOBase) -> None:
        self._ntf = ntf

    def write(self, data: str) -> int:
        """Write data and flush immediately so concurrent readers see it."""
        n = self._ntf.write(data)  # type: ignore[arg-type]
        self._ntf.flush()  # type: ignore[attr-defined]
        return n

    def __getattr__(self, name: str) -> object:
        return getattr(self._ntf, name)

    def __enter__(self) -> "_AutoFlushWrapper":
        self._ntf.__enter__()
        return self

    def __exit__(self, *args: object) -> object:
        return self._ntf.__exit__(*args)


@contextlib.contextmanager  # type: ignore[misc]
def _auto_flush_named_temp_file(**kwargs: object):
    """Context manager that yields a flush-on-write wrapper around NamedTemporaryFile."""
    with _REAL_NAMED_TEMP_FILE(**kwargs) as ntf:  # type: ignore[call-overload]
        yield _AutoFlushWrapper(ntf)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _patch_named_temp_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch tempfile.NamedTemporaryFile for all tests in this directory.

    Ensures write() flushes immediately so load_config() calls made from
    inside a ``with NamedTemporaryFile`` block can read the written data.
    """
    monkeypatch.setattr(
        tempfile,
        "NamedTemporaryFile",
        lambda **kw: _auto_flush_named_temp_file(**kw),
    )


def pytest_runtest_setup(item) -> None:
    """Before each test, ensure app.* resolves to identity-normalization.

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
