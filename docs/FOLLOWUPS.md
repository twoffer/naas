# NAAS Follow-ups & TODOs

Tracking document for deferred, non-blocking work surfaced during development. Items here were triaged as **not worth doing immediately** but should not be lost. Each entry cites its source and (where applicable) the file:line it concerns.

When an item is completed, move it to the **Done** section at the bottom (or delete it) with a one-line note.

---

## Pre-deployment security hardening

Demo-scope postures that are intentional for local development and explicitly out of scope until a non-local (shared/staging/production) deployment is on the table. Harden all of these before exposing the stack beyond localhost.

- **Keycloak demo client posture** — `infrastructure/keycloak/naas-realm-export.json`: `publicClient: true` + ROPC (`directAccessGrants: true`) + `sslRequired: "none"`. Before non-local deploy: switch to a confidential client with PKCE, disable ROPC, set `sslRequired` to `external`/`all`. _(Source: security review, chunk 4)_
- **LDAP plaintext passwords** — `infrastructure/openldap/bootstrap.ldif`: `userPassword: password123` is plaintext. Real directories must store hashed passwords (e.g. `{SSHA}`). _(Source: security review, chunk 4)_
- **Host port exposure** — `docker-compose.yml`: postgres `5432`, redis `6379`, keycloak `8080`, openldap `389`/`636` are bound to the host with dev credentials. For non-local hosts, bind to `127.0.0.1` or drop the host port mappings and rely on `naas-network`. _(Source: security review, chunk 5)_
- **Redis authentication** — `infrastructure/redis/redis.conf`: no `requirepass`/ACL. Add when promoted beyond local dev. _(Source: security review, chunk 3)_

## Spec-faithful cosmetics

Minor code-quality items in the shared library. These files were **faithfully transcribed from the canonical SPEC_0 contract**, and no lint gate currently enforces them. They are deliberately deferred rather than hand-patched: editing the code directly would create code↔spec drift that a future pipeline run could flag. **Address by revising the spec, then letting the pipeline regenerate** — ideally bundled into the next spec revision that touches these files.

- **`Optional` type annotation** — `shared/naas_shared/logging.py:31`: `get_logger(name: str = None)` should be `get_logger(name: Optional[str] = None)` (and add `from typing import Optional`). Faithful to SPEC_0 §3.7; cosmetic. _(Source: security review, chunk 2)_
- **Unused import** — `shared/naas_shared/models.py:5`: `field_validator` is imported but unused, carried with `# noqa: F401` to match the spec's import block. Drop it when a future model actually needs it, or when the spec import block is revised. _(Source: security review, chunk 2)_
- **README placeholder wording** — `services/*/README.md:3`: uses "a later Spec" where the SPEC_0 §5.6 template says "Spec {N}". Benign and arguably better (avoids hardcoding a possibly-wrong number); traceability only. _(Source: security review, chunk 1)_

## Service code-quality nits

Minor non-blocking quality items in service code. No lint gate enforces them; low value, deferred.

- **Stale chunk reference in health docstring** — `services/event-ingestion/app/main.py:8`: the module docstring still cites "Chunk 3" for the real readiness probe, which has since landed. Pipeline-artifact wording; doc-only, harmless. _(Source: security review, chunk 1)_
- **`logger: object` type hint** — `services/event-ingestion/app/service.py:29`: `logger: object` is imprecise (`object` exposes no `.error()`); prefer a structlog logger type or `typing.Any`. The spec's exemplary code is untyped here, so this is a quality nit. _(Source: security review, chunk 2)_
- **Cross-service `swagger_ui_oauth2_redirect_url` alignment** — `services/identity-normalization/app/main.py` sets `swagger_ui_oauth2_redirect_url=None` (now with an explanatory comment) while `services/event-ingestion/app/main.py` omits it. Neither service has OAuth2-protected endpoints, so both are correct; aligning them for uniformity would touch event-ingestion and is deferred. _(Source: Spec 2 remediation triage; security review chunk 1)_
- **Raw attribute value logged at WARNING** — `services/identity-normalization/app/normalization_values.py` (`normalize_department`/`normalize_employee_type` unmapped-value path): logs `raw_value=<value>` (the raw department/employee_type string) at WARNING. Low sensitivity (not email/name/token) and pre-existing, but worth redacting/bounding in a future cleanup. _(Source: Spec 2 remediation security review, LOW)_

## Test coverage polish

Low-value test improvements; current coverage is adequate.

- **Negative quote guards for `'US'` / `'ldap'`** — `tests/infrastructure/test_postgres_init_sql.py` (`TestInitSqlStringEscaping`): the unescaped-quote negative guard only checks `'contractor'`. Add equivalent negative-lookbehind guards for `'US'` and `'ldap'`. (Positive doubled-quote coverage already exists for both.) _(Source: security review, chunk 3)_
- **LDIF parser robustness** — `tests/infrastructure/test_openldap_ldif.py` (`TestLdifUserEntries`, the structural parser helper): lacks base64/continuation-line handling. Fine for the current LDIF; revisit only if the LDIF grows to use those features. _(Source: security review, chunk 4)_

## Test infrastructure

Repo-resident test-harness improvements deferred as too broad/risky for an incremental remediation batch.

- **Per-service `app`-isolation conftest removal** — the test suite now runs under `--import-mode=importlib` (+ `consider_namespace_packages`) and the root `conftest.py` collection shim has been removed (see Done). What remains is the per-service `conftest.py` `pytest_runtest_setup` that clears `app.*` from `sys.modules` and re-anchors `sys.path` before each test. **Still blocked by the same prerequisite:** both services ship a real top-level package literally named `app`, imported by bare name from ~20+ test files; importlib does NOT fix that collision (it governs test-file import, not the test's own `import app.main`). Fully removing this conftest requires renaming the services' production `app` packages (touching Dockerfiles, `docker-compose.yml`, `uvicorn app.main:app` commands, and in-app imports) — high blast radius into production runtime. Address as its own dedicated change. _(Source: security review chunk 1; Spec 2 quality report; remediation triage)_
- **Convert the manual `_run()` async-test helper to pytest-asyncio markers** — the suite drives coroutines via a hand-rolled `_run(coro)` helper rather than `@pytest.mark.asyncio` (zero markers, no `asyncio_mode` configured). Modernizing interacts with the root `pyproject.toml [tool.pytest.ini_options]` (added for `pytest-timeout`), so it was kept out of that change. _(Source: Spec 2 remediation triage)_

## Forward-looking design items

Decisions deferred to the spec that first needs them.

- **Keycloak group-name binding (plain vs slash)** — `infrastructure/keycloak/naas-realm-export.json` uses plain group names (`engineering`/`product`/`security`); SPEC_0 §6.4 acceptance does not assert group-membership binding via the OIDC `groups` claim. Resolve the plain-vs-slash question in the **first downstream spec that consumes the OIDC `groups` claim** (identity-normalization / risk-evaluator). Note: this is **not** Spec 1 (event ingestion → Postgres/Redis), so it does not block the immediate next spec. _(Source: security review, chunk 4)_
- **Broader RFC-4514 DN conformance + real-directory group test** — `services/identity-normalization/app/adapters/ldap.py` `_reduce_dn_to_group_name` now uses `ldap.dn.str2dn` (handles escaped commas) with a regex fallback. Remaining RFC-4514 edge cases (hex `\NN` escapes, multi-valued/`+`-joined RDNs) are untriggered today because the seeded directory has no `memberOf`. Add a real-directory integration test exercising group enrichment once a directory with group memberships exists. _(Source: Spec 2 remediation triage; security review chunk 2/4)_
- **Dead-letter handling for unparseable stream messages** — `services/identity-normalization/app/consumer.py`: a structurally-invalid `login_events` message is logged (PII-redacted) but never XACKed, so it remains in the consumer group's pending-entries list and is redelivered on every consumer restart. Decide a deliberate policy (dead-letter stream vs. ACK-and-drop vs. keep-pending) — applies to all stream consumers. _(Source: Spec 2 remediation integration validation, LOW)_

---

## Done

- **Keycloak healthcheck never reports `healthy`** — fixed before Spec 1. The probe targeted port 8080 and health was not enabled; corrected to set `KC_HEALTH_ENABLED: "true"` and probe the management port 9000. Updated `docker-compose.yml`, SPEC_0 §5.1, and the integration-validator memory note. _(Source: integration & quality reports, Spec 0)_
- **`--build` requirement documentation** — already surfaced in both `README.md` (Quick start) and `CLAUDE.md` before this triage; no further action. _(Source: integration & quality reports, Spec 0)_
- **`datetime.utcnow` deprecation / `HealthResponse` timestamp missing UTC offset** — resolved. The last remaining `datetime.utcnow` in `shared/` (`HealthResponse.timestamp` in `shared/naas_shared/models.py`) was switched to `default_factory=lambda: datetime.now(timezone.utc)`, making the timestamp timezone-aware so it serializes with an explicit UTC `Z`/offset consistent with event timestamps. SPEC_0 §3 updated in lockstep (incl. the `from datetime import datetime, timezone` import) to avoid code↔spec drift. `grep -rn datetime.utcnow shared/` now returns nothing. _(Source: security review chunk 2; integration report Run 2 caveat 1)_
- **`events.timestamp` TIMESTAMPTZ extended to all tables** — the four remaining naive `created_at TIMESTAMP` columns (`users`, `policies`, `risk_assessments`, `alerts`) were changed to `TIMESTAMPTZ` in `infrastructure/postgres/init.sql`, matching the `events` table and pre-empting the tz-aware-vs-naive bind error that downstream specs (Risk Evaluator, Alert Service) would otherwise hit. DDL-only (no ORM/write-paths exist yet; the async engine's UTC session pin already covers all connections). SPEC_0 DDL updated in lockstep. Takes effect on a fresh volume (`docker compose down -v`). _(Source: integration report Run 1 architect follow-up #2)_
- **Test suite reorganization + importlib adoption** — the `tests/` tree was reorganized from build-provenance naming (`test_chunk6_*`, `tests/spec_0/`) to subject/component-based layout (`tests/services/<svc>/`, `tests/shared/`, `tests/infrastructure/`, `tests/repo/`), with stale TDD-authoring headers and pipeline vocabulary stripped. The suite now runs under `--import-mode=importlib` (+ `consider_namespace_packages` in `pyproject.toml`) and the root `conftest.py` collection shim (`pytest_collect_file`/`_SHARED_BASENAMES`) was deleted — its duplicate-basename problem is now handled by importlib + underscored test-dir names. Per-file `sys.path`-for-imports boilerplate was centralized into `tests/conftest.py` (shared/) and the per-service conftests. Conventions were encoded normatively in the `test-suite-generator` agent definition. Parity held at 1308 passed / 2 skipped. The per-service `app`-isolation conftest remains (see Test infrastructure above). _(Source: post-Spec-2 test-organization review)_
