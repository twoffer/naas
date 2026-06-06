"""Root conftest.py — pytest project-wide configuration.

Manages sys.modules isolation for same-named test modules in sibling service
test directories whose names contain hyphens (not valid Python identifiers).

Without this, pytest's default import mode stores same-named files (e.g.,
test_chunk1_app_skeleton.py) under the same module key in sys.modules,
causing 'import file mismatch' collection errors when both event-ingestion
and identity-normalization test directories contain identically-named files.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# Test module basenames that appear in multiple service test directories.
# Clearing these from sys.modules before each collection pass lets pytest
# import the correct file for each service directory.
_SHARED_BASENAMES: frozenset[str] = frozenset(
    [
        "test_chunk1_app_skeleton",
        "test_chunk1_packaging",
    ]
)


def pytest_collect_file(parent: pytest.Collector, file_path: Path):
    """Clear same-named test modules from sys.modules before each file collection.

    WHY: Service test directories have hyphenated names (e.g., event-ingestion,
    identity-normalization) which are not valid Python identifiers.  pytest
    cannot form a unique package-qualified module name for them, so it uses the
    bare filename as the module key.  When two service directories contain files
    with the same basename, the second file's collection fails with 'import file
    mismatch' because the first file's module is already in sys.modules.

    Clearing the relevant module entries before each file collection pass lets
    pytest re-import the correct version for each service directory.
    """
    import sys

    if file_path.stem in _SHARED_BASENAMES:
        # Remove stale module entries so pytest re-imports from the correct path.
        for key in list(sys.modules.keys()):
            if key == file_path.stem or key.endswith(f".{file_path.stem}"):
                del sys.modules[key]
