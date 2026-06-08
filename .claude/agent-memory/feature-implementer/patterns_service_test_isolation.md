---
name: patterns_service_test_isolation
description: Isolating the same-named `app` package across sibling service test dirs
metadata:
  type: feedback
---

Both application services ship a top-level package literally named `app` (`app/main.py`, etc.),
imported by bare name from test files (`from app.main import app`). When tests from both services
run in one session, the first-collected service's `app.main` stays in `sys.modules` for the rest
of the session, so a test in the other service imports the wrong service's `app`.

**Import-mode / collection (solved structurally — no per-collision hack needed):** the suite runs
under `--import-mode=importlib` (+ `consider_namespace_packages`) in `pyproject.toml`, and the
TEST directories use valid Python identifiers — underscores, not hyphens
(`tests/services/event_ingestion/`, `tests/services/identity_normalization/`), even though the
PRODUCTION service dirs stay hyphenated (`services/event-ingestion/`). With underscored dirs +
importlib, same-basename test files (`test_health.py` in both services) get unique module names
automatically. The old root-`conftest.py` `pytest_collect_file`/`_SHARED_BASENAMES` shim has been
DELETED — do not reintroduce it.

**Per-service `app`-isolation conftest (still required):** importlib governs how test *files* are
imported, NOT how a test's own `import app.main` resolves. So each service test directory keeps a
`conftest.py` that re-anchors `app.*` before each test:
```python
def pytest_runtest_setup(item):
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if SERVICE_DIR in sys.path:
        sys.path.remove(SERVICE_DIR)
    sys.path.insert(0, SERVICE_DIR)   # SERVICE_DIR = the hyphenated production path
```
The conftest also inserts SERVICE_DIR onto `sys.path` at module level (collection time) so
module-level `from app.main import app` resolves. `naas_shared` is put on `sys.path` once by
`tests/conftest.py` (no per-file boilerplate).

**How to apply:** When a new application service gains a test suite, create
`tests/services/<service_name>/` (UNDERSCORED) with a `conftest.py` carrying `pytest_runtest_setup`
plus the module-level SERVICE_DIR/`sys.path` insert, pointing SERVICE_DIR at the hyphenated
`services/<service-name>/` production path.

**Also:** `tests/repo/test_root_scaffold.py` and `tests/infrastructure/test_docker_compose.py`
have `IMPLEMENTED_APP_SERVICES` sets that must be updated when a new service's implementation lands.
These are living registries — updating them is required and expected when implementing each new spec.

**Related:** per-service conftest at `tests/services/identity_normalization/conftest.py`; the
`shared/`-path conftest at `tests/conftest.py`. (There is no longer a repo-root `conftest.py`.)
