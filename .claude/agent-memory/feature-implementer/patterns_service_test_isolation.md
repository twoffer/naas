---
name: patterns_service_test_isolation
description: Isolating same-named test modules across sibling service test dirs with hyphenated names
metadata:
  type: feedback
---

When multiple service test directories exist under `tests/services/` with hyphenated names (e.g., `event-ingestion`, `identity-normalization`), pytest cannot form valid Python package-qualified module names for them (hyphens are invalid in identifiers). If two such directories contain files with the same basename (e.g., `test_chunk1_app_skeleton.py`), pytest collects them as the same module, causing "import file mismatch" errors.

Additionally, test files insert their SERVICE_DIR into sys.path[0] at module level. This contaminates `app.*` in sys.modules, causing event-ingestion tests to import the identity-normalization `app.main` (or vice versa) when run together.

**The fix is two-part:**

1. Root `conftest.py` — clears `sys.modules` for same-named test module basenames before each file is collected:
```python
def pytest_collect_file(parent, file_path):
    import sys
    if file_path.stem in _SHARED_BASENAMES:
        for key in list(sys.modules.keys()):
            if key == file_path.stem or key.endswith(f".{file_path.stem}"):
                del sys.modules[key]
```

2. Per-service `conftest.py` in each service test directory — clears and re-anchors `app.*` before each test:
```python
def pytest_runtest_setup(item):
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if SERVICE_DIR in sys.path:
        sys.path.remove(SERVICE_DIR)
    sys.path.insert(0, SERVICE_DIR)
```

**Why:** Without this, the first-collected service's `app.main` stays in sys.modules for the entire session. Any test in a different service that imports `app.main` gets the wrong service.

**How to apply:** Every time a new application service is added to NAAS with its own test suite under `tests/services/<service-name>/`, create a `conftest.py` in that directory with `pytest_runtest_setup`. Also add the service to the existing `conftest.py` in the root if it has test files with the same basename as any other service's test files.

**Also:** The spec_0 test files (`test_chunk_1_root_scaffold.py`, `test_chunk_5_docker_compose.py`) have `IMPLEMENTED_APP_SERVICES` sets that must be updated when a new service's implementation lands. These are designed as living registries — updating them is required and expected when implementing each new spec.

**Related:** `services/identity-normalization` conftest at `/home/toffer/naas-workspace/naas/tests/services/identity-normalization/conftest.py`; root conftest at `/home/toffer/naas-workspace/naas/conftest.py`.
