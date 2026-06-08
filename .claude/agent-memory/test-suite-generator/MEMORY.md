# Test Suite Generator — Agent Memory

Naming & placement conventions are NORMATIVE in the agent definition's TEST STANDARDS — follow it; do not re-derive file names from older example memories.

## Patterns

- [patterns_filesystem_tests.md](patterns_filesystem_tests.md) — Conventions for writing scaffold/filesystem assertion tests in this repo. ⚠ Includes the IMPLEMENTED_APP_SERVICES maintenance step: append a service to that set when its spec lands, or the "only README" scaffold guard false-fails
- [patterns_naas_shared_tdd.md](patterns_naas_shared_tdd.md) — Import strategy, lru_cache fixture, placeholder module assertions, discriminated union testing for naas_shared. ⚠ schemas.py is now populated — do not regenerate the retired placeholder-comment / no-public-names guards

## Docker / Compose Tests

- [patterns_docker_compose_tests.md](patterns_docker_compose_tests.md) — PyYAML importorskip, docker compose config subprocess skip guard, bind-mount short/long syntax helper, KC_DB* absence pattern, module-scoped fixture behaviour on missing file. ⚠ Includes the IMPLEMENTED_APP_SERVICES maintenance step: append a service when its spec adds it to compose, or the exact service-set guard false-fails

## Fixtures

- [fixtures_repo_root.md](fixtures_repo_root.md) — Robust repo-root discovery pattern used in tests/infrastructure and tests/repo

## Reorganization

- [patterns_test_suite_reorg.md](patterns_test_suite_reorg.md) — importlib mode setup, dir rename strategy, boilerplate strip pitfalls, split patterns for remediation/shared-library/keycloak files, per-service conftest pattern

## Service Tests

- [patterns_service_tdd.md](patterns_service_tdd.md) — event-ingestion service patterns: sys.path injection for app.main, mock patching for FastAPI health endpoint tests, ORM column-type assertions (INET/JSONB), negative requirements.txt assertions
- [patterns_spec2_identity_normalization_tests.md](patterns_spec2_identity_normalization_tests.md) — identity-normalization durable test patterns: fake-ldap sys.modules injection, three-state Redis cache contract, sanitization assertions, resolve() shape, outcome→skip_reason mapping, consumer ordering invariants. ⚠ conftest auto-flush REMOVED — use explicit f.flush() in each test helper. Input-coercion / log-redaction / consumer-resilience hardening patterns appended.
- [patterns_adapter_refactor_tests.md](patterns_adapter_refactor_tests.md) — _mapping.py engine tests, normalize_department_value tuple-return invariant, bare-string groups behavior change pattern, FieldRule multi-key test, append-vs-new-file placement strategy
