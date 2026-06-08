---
name: patterns-test-suite-reorg
description: Mechanical test-suite reorganization patterns: importlib mode, dir rename, split strategies, boilerplate stripping, and pitfalls from the June 2026 reorg
metadata:
  type: feedback
---

# Test Suite Reorganization (June 2026) — Patterns and Pitfalls

## Final Structure

```
tests/
  conftest.py                       # Central sys.path for naas_shared
  services/
    event_ingestion/                # underscored (was event-ingestion/)
      conftest.py                   # app.* isolation + SERVICE_DIR injection
      test_*.py
    identity_normalization/         # underscored (was identity-normalization/)
      conftest.py                   # app.* isolation + SERVICE_DIR injection
      test_*.py
  shared/                           # 7 files: constants, ldap_constants, models, orm_mapping,
                                    #           package_surface, pyproject, settings
  infrastructure/                   # 5 files: docker_compose, keycloak_realm, openldap_ldif,
                                    #           postgres_init_sql, redis_conf
  repo/                             # 2 files: root_scaffold, spec0_doc_mirror
```

## importlib Mode

Add to `pyproject.toml` under `[tool.pytest.ini_options]`:
```toml
addopts = "--import-mode=importlib"
consider_namespace_packages = true
```

**Why**: Eliminates `import file mismatch` errors from same-basename files in sibling dirs.
The old `conftest.py` root-level `pytest_collect_file` shim is no longer needed.
Delete root `conftest.py`; replace with `tests/conftest.py` that only inserts `shared/` onto sys.path.

**How to apply**: Always use importlib mode for any project with multiple test subdirectories
that may share filenames.

## Boilerplate Stripping Rule

When removing `_find_repo_root()` + `sys.path.insert()` boilerplate from test files:

**REMOVE from files that only use paths for import resolution** (naas_shared, app.*):
- The per-service `conftest.py` now handles this via `pytest_runtest_setup`

**KEEP in files that use `REPO_ROOT` for fixture path discovery** (reading committed files):
- `test_packaging.py` — needs `SERVICE_DIR` for Dockerfile/requirements.txt paths
- `test_schemas.py` — needs `SERVICE_DIR` to locate `app/schemas.py`
- `test_compose.py` — needs `REPO_ROOT` for `docker-compose.yml` path
- `test_confidence.py`, `test_config_model.py`, `test_config_yaml.py`,
  `test_groups_merge.py`, `test_penalty.py`, `test_scalar_resolution.py`
  — all need `REPO_ROOT` for `config/normalization.yaml` path
- All `tests/infrastructure/` files — need paths to init.sql, redis.conf, keycloak JSON, ldif, compose
- All `tests/repo/` files — need paths to .env.example, README, docs

**Pitfall**: A naive "remove all `_find_repo_root` calls" script will break module-level
`REPO_ROOT = _find_repo_root()` usages that are needed for fixture paths.
Set `keep_repo_root=True` in the stripping function, but also verify the FUNCTION BODY is preserved
— not just the assignment. The header replacement script can accidentally remove the function
body if it's located in the comment header zone.

## Split Strategies

### test_remediation.py → 3 files
Split 2006-line file by concern:
- `test_input_coercion.py` — TestNormalizeHelperNonString, TestAdapterExtractNonStringInputs, TestAdapterExtractNonStringNameEmail
- `test_log_redaction.py` — TestCorruptedCacheLogRedaction, TestMalformedMessageLogRedaction, TestValidationErrorLogRedaction
- `test_consumer_resilience.py` — TestConsumerLoopXreadgroupResilience, TestWeightForUnknownSource, TestPoolSearchUnbindOnBrokenConnection, TestReduceDnToGroupNameWithStr2dn, TestClassifyLdapError

Each split file duplicates needed helpers (`_make_fake_ldap_module`, `_inject_fake_ldap`, `_FakeRedis`, `_run`).
Key: `del fake.TIMEOUT_EXCEEDED` simulates real python-ldap exception hierarchy (no such attribute by default).

### test_chunk_2_shared_library.py → 5 files
Split 1576-line file:
- `test_models.py` — LoginEventIngest, RiskDecision, NormalizedAttributes, AlertMessage, HealthResponse validation
- `test_constants.py` — Exact constant values (stream names, group names, TTLs)
- `test_settings.py` — Settings defaults, database_url properties
- `test_pyproject.py` — pyproject.toml structure (KEEPS `_find_repo_root` for `SHARED_DIR` path)
- `test_package_surface.py` — Import surface, placeholder module guards

### test_chunk_4_keycloak_ldap.py → 2 files
When splitting, ALWAYS check which helper functions are used by which classes:
- `_find_client` and `_find_user` → `test_keycloak_realm.py`
- `_load_ldif_lines`, `_parse_ldif_blocks`, `_extract_user_dns`, `_extract_uid_from_dn` → `test_openldap_ldif.py`

**Pitfall**: If you create the split file structure without copying the shared helpers, the tests
fail at runtime with `NameError: name '_find_client' is not defined` even though the function
was "in the original file" (which is now deleted).

## Header Cleanup

Replace multi-line TDD headers with a single docstring:
```python
"""What this file verifies, in one concise sentence."""
```

Remove: "Mode: TDD", "ALL tests MUST fail", "NOT YET CREATED", "Chunk N", "TDD state",
        "MUST fail until...", pipeline vocabulary in class names.

**Pitfall**: The header replacement script walks forward from line 0 to skip comment lines,
then replaces up to the first non-blank non-comment line. If `_find_repo_root()` is defined
in a docstring-comment zone before the imports, the function gets eaten. Insert the header
replacement BEFORE the boilerplate stripping step, or check that the function survives.

## Per-Service Conftest Pattern

```python
# tests/services/<service_name>/conftest.py
SERVICE_DIR = str(REPO_ROOT / "services" / "<service-name>")  # HYPHENATED production path
SHARED_DIR = str(REPO_ROOT / "shared")

if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)

def pytest_runtest_setup(item) -> None:
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if SERVICE_DIR in sys.path:
        sys.path.remove(SERVICE_DIR)
    sys.path.insert(0, SERVICE_DIR)
    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)
```

Note: Production service directories stay hyphenated (`services/event-ingestion/`).
Only TEST directories become underscored (`tests/services/event_ingestion/`).

## Why: Correct
Why: The `--import-mode=importlib` + underscored test dirs + centralized conftest
pattern eliminates all `import file mismatch` errors while keeping production paths intact.
How to apply: Any new service should follow this exact pattern — add an underscored
`tests/services/<service_name>/` directory with a conftest.py following the pattern above.
