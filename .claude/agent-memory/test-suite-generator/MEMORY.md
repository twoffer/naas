# Test Suite Generator — Agent Memory

## Patterns

- [patterns_filesystem_tests.md](patterns_filesystem_tests.md) — Conventions for writing scaffold/filesystem assertion tests in this repo. ⚠ Includes the IMPLEMENTED_APP_SERVICES maintenance step: append a service to that set when its spec lands, or the "only README" scaffold guard false-fails
- [patterns_naas_shared_tdd.md](patterns_naas_shared_tdd.md) — Import strategy, lru_cache fixture, placeholder module assertions, discriminated union testing for naas_shared. ⚠ schemas.py is now populated by Spec 1 — do not regenerate the retired placeholder-comment / no-public-names guards

## Docker / Compose Tests

- [patterns_docker_compose_tests.md](patterns_docker_compose_tests.md) — PyYAML importorskip, docker compose config subprocess skip guard, bind-mount short/long syntax helper, KC_DB* absence pattern, module-scoped fixture behaviour on missing file. ⚠ Includes the IMPLEMENTED_APP_SERVICES maintenance step: append a service when its spec adds it to compose, or the exact service-set guard false-fails

## Fixtures

- [fixtures_repo_root.md](fixtures_repo_root.md) — Robust repo-root discovery pattern used in spec_0 tests

## Service Tests

- [patterns_service_tdd.md](patterns_service_tdd.md) — Spec 1 Chunk 1 patterns: sys.path injection for app.main, mock patching for FastAPI health endpoint tests, ORM column-type assertions (INET/JSONB), negative requirements.txt assertions
- [patterns_spec2_identity_normalization_tests.md](patterns_spec2_identity_normalization_tests.md) — Spec 2 identity-normalization durable test patterns: fake-ldap sys.modules injection, three-state Redis cache contract, sanitization assertions, resolve() shape, outcome→skip_reason mapping, consumer ordering invariants. ⚠ conftest auto-flush REMOVED (N hygiene fix) — use explicit f.flush() in each test helper. Remediation patterns for A/B/C/E/J/D/F appended.
- [patterns_adapter_refactor_tests.md](patterns_adapter_refactor_tests.md) — _mapping.py engine tests, normalize_department_value tuple-return invariant, bare-string groups behavior change pattern, FieldRule multi-key test, append-vs-new-file placement strategy
