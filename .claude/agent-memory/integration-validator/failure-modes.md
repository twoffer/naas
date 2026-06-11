---
name: failure-modes
description: Recurring integration failure modes observed in NAAS validation runs, with the seam each one breaks
metadata:
  type: project
---

# NAAS Integration Failure Modes

## event-ingestion ↔ PostgreSQL: tz-aware timestamp rejected by naive TIMESTAMP column (Spec 1) — FIXED + RE-VERIFIED (Run 2, 2026-06-04)
- STATUS: RESOLVED, confirmed PASS on Validation Run 2 against fresh pg volume
  (commits 18f4388 + 056be17). Literal-spec `...Z` body → 202; `Z`/`+00:00`/naive
  collapse to one 14:05:00Z instant; `+05:00`→09:05:00Z; stream text agrees w/ PG;
  zero error logs. Fix = `events.timestamp` + `events.created_at` → `TIMESTAMPTZ`
  (init.sql), `EventORM` cols → `DateTime(timezone=True)`, Pydantic `@field_validator`
  normalizes to aware-UTC (naive treated as UTC) via shared `_to_utc()`, and
  `create_async_engine(connect_args={"server_settings":{"timezone":"UTC"}})`.
  Verified end-to-end on fresh-volume init: `Z`/`+00:00`/`+05:00`/naive all → 202,
  all store byte-identical `...14:05:00+00` (count(distinct)=1), stream serializes UTC
  as `...Z`. NOTE: fix only lands on FRESH pg volume — `init.sql` runs once on empty
  data dir, so re-validation REQUIRES `docker compose down -v` + `up --build`.
- Symptom (historical): `POST /events/ingest` (and `/bulk`) returned 500 for any tz-aware
  `timestamp` (`...Z` or `+00:00`). Naive timestamps (no offset) succeeded (202).
- Error in event-ingestion logs:
  `asyncpg.exceptions.DataError: invalid input for query argument $6 ...
  can't subtract offset-naive and offset-aware datetimes`.
- Root cause (schema provenance): `naas_shared.models.LoginEventIngest/LoginEventRecord`
  parse a `Z`/offset timestamp into a **timezone-aware** datetime (tzinfo=UTC).
  `naas_shared.schemas.EventORM.timestamp` maps to `events.timestamp` which is
  `TIMESTAMP WITHOUT TIME ZONE`. asyncpg cannot bind aware -> naive column.
- Why it matters: the spec's OWN canonical example (Section 2.1 / Section 6.1)
  uses `"2026-06-03T14:05:00Z"` and says "Submit UTC", so the documented happy
  path is broken out of the box. Fail-safe held (no PG row, no stream msg, 5xx).
- Fix belongs to feature-implementer: either normalize aware->naive (strip tz to
  UTC) before ORM insert, or make the column `TIMESTAMPTZ`. Schema is owned by
  the infra init script per spec, so the app-side normalization is the in-scope fix.

## identity-normalization ↔ config volume mount: config path resolves to /config not /app/config (Spec 2) — FIXED + RE-VERIFIED (Run 2, 2026-06-06)
- STATUS: RESOLVED. Fix in main.py three-tier resolution: (1) env NORMALIZATION_CONFIG_PATH,
  (2) /app/config/normalization.yaml if exists (compose mount target), (3) repo-relative
  4-parent fallback. Docker selects tier 2. Run 2 PASS: plain `docker compose up -d --build
  identity-normalization` reaches healthy (no exit 3, no FileNotFoundError); /health 200; full
  §6 verified on the REAL committed container (not a probe): mapping, value-norm, enrich+conflict
  →ldap wins (alice dept Sales→Engineering), ldap_event skip, no_ldap_match, cache_hit_negative
  on 2nd absent lookup (one LDAP query for two ghost logins), ADR-0011 full-record publish to
  normalized_events, ACK pending→0, §6.10 graceful degradation (openldap stopped → skip_reason
  ldap_search_error, event NOT dropped), §6.9 bad correlation_key aborts startup (ValueError,
  exit 3, tested via tmp config + NORMALIZATION_CONFIG_PATH env — confirms tier-1 too). main.py:104-115.
- SEAM (historical): composition root (main.py) ↔ docker-compose bind mount (spec §5.8).
- Symptom (historical): container exited code 3 on startup, never healthy:
  `FileNotFoundError: '/config/normalization.yaml'` from main.py lifespan.
- Root cause: main.py computes config_path as
  `Path(__file__).parent.parent.parent.parent / "config" / "normalization.yaml"`.
  That 4-parent walk assumes the HOST repo layout
  (naas/services/identity-normalization/app/main.py → 4 up → naas/). Inside the
  image the app lives at /app/svc/app/main.py, so 4 parents reach `/`, yielding
  `/config/normalization.yaml`. The compose mount delivers it to `/app/config`.
  They never agree. No env-var override (no CONFIG_PATH/NORMALIZATION_CONFIG support).
- Fix (feature-implementer): point the loader at the mounted path. Either hard-set
  `/app/config/normalization.yaml`, or (better) read an env override defaulting to
  the compose mount target. File: services/identity-normalization/app/main.py:100-102.
- Verification done: a throwaway probe container (same image/env/network) with the
  config additionally bind-mounted at /config started healthy and the FULL pipeline
  passed (mapping, value-norm, enrich+conflict, no_ldap_match, ldap_event skip,
  negative cache, ACK semantics, ADR-0011 full-record publish, §6.9 bad-config abort).
  So the defect is ISOLATED to the config-path/mount seam; service logic is sound.
- NOTE: probe trick = `docker run --env-file <compose-resolved env list> -v ./config:/config:ro`.
  Do NOT use raw .env with --env-file: inline comments leak into values and Settings
  fails int_parsing on ldap_pool_size/simulation_* and pattern on llm_provider.

## identity-normalization ↔ python-ldap: _classify_ldap_error referenced nonexistent ldap.TIMEOUT_EXCEEDED — RESOLVED (post-spec-2 remediation, same session it was found)
- SEAM: LDAP adapter error-classification (app/adapters/ldap.py) ↔ python-ldap 3.4.7 API.
- Was: `_classify_ldap_error` checked `isinstance(exc, ldap_module.TIMEOUT_EXCEEDED)`, an attribute
  that does NOT exist on python-ldap 3.4.7. The `AttributeError` escaped the `except ImportError`,
  so the `ldap_timeout`/`ldap_connection_error` branches were dead code and every transient LDAP
  failure was mislabeled skip_reason `ldap_search_error`. Fail-safe always held (events still
  published+ACKed, service healthy) — observability/classification defect, not availability.
- Fixed: now classifies `ldap.TIMEOUT` + `ldap.TIMELIMIT_EXCEEDED` → `ldap_timeout`, `SERVER_DOWN`
  → `ldap_connection_error`, `LDAPError` → `ldap_search_error`, via `getattr` + `isinstance(t, type)`
  probing (tolerates stub modules), except broadened to `(ImportError, AttributeError)`. Covered by
  `TestClassifyLdapError` in `tests/services/identity-normalization/test_remediation.py`.
- Durable lesson: this only surfaced under a REAL broken python-ldap connection (openldap
  stop/restart) — fakes did not exercise it. When validating LDAP error paths, drive a real
  transient failure (stop openldap mid-run) and grep logs for `ldap_enrichment_unexpected_exception`
  / `module 'ldap' has no attribute`. Enrichment self-heals once broken pooled connections drain
  (the E unbind-on-discard path works).

## identity-normalization consumer: unparseable stream message left PENDING, not ACKed (design)
- Injecting structurally-invalid JSON into login_events → consumer logs `message_processing_failed`
  (ValidationError, redacted to error_locations only — F fix works) but does NOT ACK; message stays
  in PEL forever, redelivered on restart. Distinct from the A poison-message case (valid record w/
  non-str scalars) which IS normalized+ACKed (pending stays 0). Pre-existing, informational.

## live E2E suite (tests/integration) ↔ docker-compose.test.yml: test-runner `command` YAML-folded wrong + rich missing in image (first live run, 2026-06-11) — RESOLVED same day
- SEAM: tests/integration/test_in_container_unit_suite.py ↔ docker-compose.test.yml test-runner service.
- Suite result: 25 passed / 1 failed in ~217s. The other 3 scenarios (demo-script-live 4, event-ingestion-live 11, identity-normalization-live 10) all PASS. Only the in-container scenario failed.
- BUG 1 (harness, blocking the scenario): test-runner `command` uses a YAML `>` folded block but lines 2+ are MORE indented than line 1, so YAML preserves the newlines (resolves to a `|-`-style multiline string, confirmed via `docker compose ... config`). `sh -c` runs only line 1 (`pip install ... && python -m pytest tests/`), then tries to exec each subsequent line as its own command → `sh: 3: --ignore=tests/integration: not found`, etc. Net effect: pytest runs with NONE of the 4 intended flags (`--ignore=tests/integration`, `--ignore=.../test_docker_compose.py`, `-p no:cacheprovider`, `--rootdir`, `-o cache_dir`). Container exits 127 (last `sh` not-found), not pytest's own code. Fix: make `command` a single logical line (or `command: ["sh","-c","pip install ... && python -m pytest tests/ --ignore=... -p no:cacheprovider ..."]`), OR de-indent so the `>` fold joins lines with spaces.
- BUG 2 (genuine, dependency): `rich` is only in demo/requirements.txt, NOT requirements-dev.txt; test-runner installs only requirements-dev.txt → image lacks rich. 8 tests in tests/demo/test_demo_flow.py fail `ModuleNotFoundError: No module named 'rich'` (demo_normalization.py:235 get_console lazy import). These pass on host because run_integration_tests.sh installs demo/requirements.txt. Fix: add `rich==13.9.4` to requirements-dev.txt (or have test-runner also `pip install -r demo/requirements.txt`).
- Image dep inventory (probed `naas-identity-normalization:local`): ldap OK, ldif OK, sqlparse MISSING, rich MISSING. Host venv: ldap/ldif/sqlparse MISSING, rich present.
- In-container scenario PURPOSE (un-skip python-ldap deep-parse) — the genuine coverage gain is exactly ONE test: tests/infrastructure/test_openldap_ldif.py:566 ("python-ldap/ldif not installed — skip deep parse") RUNS in-container (ldap+ldif present in image) but is SKIPPED on host. test_adapters_ldap.py (63) passes on BOTH host and container (host has no real `ldap` but those tests don't need the C-ext / use lazy import). So python-ldap delivers ~1 net un-skip, not a large delta.
- Counts: HOST `pytest tests/` = 1518 passed / 28 skipped (26 integration-skip + 1 openldap_ldif + 1 postgres_init_sql sqlparse). IN-CONTAINER (flags dropped, so it wrongly collected integration+infra) = 1503 passed / 8 failed / 35 skipped (1546 collected = 26 integration-skip + 7 demo skips + 1 docker_compose skip + 1 postgres_init_sql skip). Once BUG 1 is fixed the integration tests won't be collected in-container (the `--ignore` returns) and the 26 integration skips disappear from the container run.
- Teardown VERIFIED clean: post-run `docker compose ps` empty, no naas volumes, no `test-runner-run` orphans. Caveat: suite tears down ANY pre-existing stack via `down -v` (took over a 26h-running stack here, by design).
- Gating VERIFIED: host `python -m pytest tests/` still 1518/28 with integration collect-then-skip (zero errors). The `--integration` opt-in and NAAS_RUN_INTEGRATION env both honored.
- RESOLUTION (same session): BUG 1 — `command` converted to JSON exec-array `["sh","-c","pip install ... && python -m pytest tests/ --ignore=... -p no:cacheprovider --rootdir /workspace -o cache_dir=/tmp/.pytest_cache"]`. BUG 2 — `rich==13.9.4` added to requirements-dev.txt. Standalone test-runner re-run: 1475 passed / 1 skipped / 0 failed (lone skip = sqlparse-gated postgres_init_sql, same as host; openldap_ldif deep-parse now RUNS in-container as intended). Full-suite re-run via `bash scripts/run_integration_tests.sh`: 26/26 passed in ~76s, exit 0, teardown clean (no containers, no naas volumes).

## What works correctly in Spec 1 event-ingestion (verified)
- Dual-write mechanics with naive ts: PG row (normalized_attributes/enriched_signals
  NULL), stream `login_events` single `data` field, JSON `id` == row `id`.
- Bulk bare-array: 202, accepted:N, +N rows, +N stream msgs. 5000 boundary = 202.
- Validation 422s: bad IP (256.0.0.1), bad protocol (kerberos), empty bulk,
  bulk>5000 — all 422 and write nothing.
- Health: PG+Redis ok -> healthy; redis down -> degraded (HTTP 200); recovers.
