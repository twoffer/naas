# Code Security Review — Spec 2: Identity Normalization Service

Append-only audit trail of every code-security-reviewer invocation for this spec (CONTRACTS.md §8).

## Chunk 1 — Iteration 1 — PASS WITH NOTES — 2026-06-05T19:30:44Z

**Files reviewed:** 6 in scope (Dockerfile, requirements.txt, app/__init__.py, app/main.py, app/ports.py, docker-compose.yml entry) + 6 out-of-scope test-harness files assessed.

**Overall verdict:** PASS WITH NOTES (passing gate). Critical: 0, High: 0, Medium: 0, Low: 1. No blocking issues.

### Per-file results
- **Dockerfile — PASS.** Spec 1 Option A pattern (§5.8): `python:3.12-slim`, repo-root context, `python-ldap` system build deps (`gcc`, `build-essential`, `libldap2-dev`, `libsasl2-dev`) installed before pip with `rm -rf /var/lib/apt/lists/*`, `EXPOSE 8002`, correct uvicorn CMD, `--no-cache-dir`. No secrets baked in.
- **requirements.txt — PASS.** Exactly the four mandated deps (`fastapi>=0.115`, `uvicorn[standard]>=0.30`, `python-ldap>=3.4`, `pyyaml>=6.0`); data-layer deps left transitive via `naas_shared`.
- **app/__init__.py — PASS.** Empty package marker.
- **app/main.py — PASS (Low: 1).** `/health` is fail-safe: always HTTP 200, status in body, PG down → `unhealthy`, Redis down (PG OK) → `degraded`, both OK → `healthy`; per-probe `except Exception` (no 500/stack-trace leakage); body carries only status/service/version/timestamp (no secrets/PII). DB probe drives the async generator and closes it in `finally`. Call-time `naas_shared.*` attribute lookup so test patches take effect. Lifespan is a minimal `yield`-only stub deferring consumer loop/group/config to later chunks. Thin composition root, hexagonally clean.
- **app/ports.py — PASS.** Four `@runtime_checkable` `typing.Protocol` defs only; shared models imported under `TYPE_CHECKING`. Signatures align with §5.1–5.3 later-chunk call sites and the existing `EventORM` (`id` PK + `normalized_attributes` JSONB).
- **docker-compose.yml (identity-normalization entry) — PASS.** Repo-root build context, `env_file: .env`, `${IDENTITY_NORMALIZATION_PORT:-8002}:8002`, `/health` healthcheck on 8002, `depends_on` postgres/redis/openldap with `condition: service_healthy`, read-only `./config:/app/config:ro`. No hardcoded secrets. Infrastructure and event-ingestion entries byte-unchanged.

### Out-of-scope test-infrastructure changes (assessed — test-harness only, no production code; no existing assertions weakened/deleted)
- Root `conftest.py` (`pytest_collect_file` clearing `sys.modules`) — acceptable; narrowly scoped to two colliding basenames. Root cause: hyphenated sibling service test dirs aren't valid Python package names.
- Per-service `conftest.py` (`pytest_runtest_setup` re-anchoring `app.*`/`sys.path`) — acceptable, symmetric across both services.
- `tests/spec_0/test_chunk_1_root_scaffold.py` and `test_chunk_5_docker_compose.py` — surgical `IMPLEMENTED_APP_SERVICES` additions exactly as their inline comments invite; no assertion deleted/loosened.

### Recommended Improvements (non-blocking)
1. Replace the manual `sys.modules`/`sys.path` juggling (root + two per-service conftests) with pytest `--import-mode=importlib` (plus `consider_namespace_packages`) in `pyproject.toml`/`pytest.ini` — more robust as more services land. (conftest.py, tests/services/*/conftest.py)
2. Either drop `swagger_ui_oauth2_redirect_url=None` to match event-ingestion, or add a one-line comment explaining the divergence — `services/identity-normalization/app/main.py:91`.

### Test quality
Strong. Health tests drive a real `TestClient` and patch only the two external deps at the `naas_shared` namespace, asserting status-code/body/schema across all four PG/Redis combinations (would fail against an always-`healthy` stub). Ports tests verify Protocol structure, runtime-checkability, async-ness, and parameter names. No assertion-free/mock-only tests.

## Chunk 2 — Iteration 1 — PASS WITH NOTES — 2026-06-05T19:50:28Z

**Files reviewed:** 5 in scope (normalization_values.py, adapters/__init__.py, adapters/oidc.py, adapters/saml.py, adapters/ldap.py). No shared_files.

**Overall verdict:** PASS WITH NOTES (passing gate). Critical: 0, High: 0, Medium: 1, Low: 1. No blocking issues.

### Contract fidelity (high-value check) — all PASS
- `DEPARTMENT_CANONICAL` — all 18 entries byte-identical to §5.2. `EMPLOYEE_TYPE_CANONICAL` — all 16 entries byte-identical (6 FTE / 5 contractor / 5 vendor).
- `UNIFIED_TO_LDAP` exactly `{display_name:cn, primary_email:mail, department:departmentNumber, employee_type:employeeType, groups:memberOf}`.
- Mapping table correct per adapter (OIDC name/email/department/employee_type/groups; SAML displayName/email/dept/employeeType/groups; LDAP cn/mail/departmentNumber/employeeType/memberOf). Canonical TARGET strings identical across adapters (all delegate to single-source helpers — no duplicated maps).
- Unmapped handling: `normalize_department` miss → retained + title-cased + `was_mapped=False`; `normalize_employee_type` miss → `None`, never a non-Literal. Lookups stripped + lowercased.
- Import safety: no top-level `import ldap` in `ldap.py` (only `re`); `enrich` is a deferred `NotImplementedError` stub — correct for this chunk.
- Port conformance, side-effect-only warnings, do_not_touch — all verified clean (no chunk-1 file modified).

### Findings (non-blocking)
- **[MEDIUM] Type confusion on attacker-influenceable `raw_attributes`** — `oidc.py:49-66`, `saml.py:50-67`, `ldap.py:97-114`, `normalization_values.py:80,106`. Adapters guard only for absence, then call `value.strip().lower()`; a non-string scalar claim (`department: 123`, `employee_type: ["x"]`, `groups: [1,2]`) raises inside `extract`. Per §5.1 the future consumer catches the exception and leaves the message unACKed — so this is a poison-message (availability for that single event), NOT a worker crash or silent-allow. Non-blocking. Fix: `isinstance(..., str)` guards on scalar fields + filter `groups` to strings, ideally centralized in the normalize helpers (accept `object`, treat non-`str` as a miss). May instead warrant an upstream Pydantic-validated `raw_attributes` contract decision (does not currently exist; `raw_attributes` is `dict`).
- **[LOW] DN regex mishandles escaped/encoded commas in RDN values** — `ldap.py:30`. `cn=([^,]+)` stops at the first literal comma, so `cn=Smith\, John,...` captures `Smith\`. Spec §5.2 explicitly permits the "first cn= RDN" regex; the seeded directory has no `memberOf`, so this is a production-directory edge case. Regex otherwise verified correct and ReDoS-free (linear quantifiers, handles bare names + malformed DNs without raising). Fix deferred: switch to `ldap.dn.str2dn` once python-ldap is available in the enrich chunk.

### Recommended Improvements (non-blocking)
1. Centralize the non-string guard inside `normalize_department`/`normalize_employee_type` (accept `object`, non-`str` → miss) so all three adapters inherit protection without duplication.
2. Replace `_CN_RDN_RE` with `ldap.dn.str2dn` for RFC-4514-correct RDN extraction when the enrich chunk lands.

## Chunk 3 — Iteration 1 — PASS — 2026-06-05T20:12:27Z

**Files reviewed:** 2 in scope (app/normalization_config.py, config/normalization.yaml) + 1 out-of-scope test-maintenance edit (tests/spec_0/test_chunk_1_root_scaffold.py guard conversion).

**Overall verdict:** PASS. Critical: 0, High: 0, Medium: 0, Low: 3. No blocking issues.

### config/normalization.yaml — full transcription audit vs §5.6 [TRANSCRIBE EXACTLY] — exact
- `defaults.source_weights`: ldap 0.7 / saml 0.6 / oidc 0.8.
- display_name pri [ldap,saml,oidc] w {ldap 0.90, saml 0.70, oidc 0.60}; primary_email pri [oidc,saml,ldap] w {oidc 0.95, saml 0.75, ldap 0.65}; department pri [ldap,oidc,saml] w {ldap 0.90, oidc 0.70, saml 0.50}; employee_type pri [ldap,saml,oidc] w {ldap 0.95, saml 0.80, oidc 0.60}; groups merge_strategy union (no weights/priority).
- enrichment.sources.ldap: enabled true, correlation_key primary_email, timeout_ms 2000, on_failure continue, cache_ttl_seconds 60; enrich_attributes commented out. All five rationale strings verbatim. No weight altered.

### app/normalization_config.py — PASS
- Startup validation complete & correct (§5.6): correlation_key reverse-mappable; on_failure in {continue,fail}; enrich_attributes entries reverse-mappable; cache_ttl_seconds positive via `Field(gt=0)`.
- Single source of truth: `_VALID_UNIFIED_FIELDS` derived from `UNIFIED_TO_LDAP.keys()` (not a hardcoded copy).
- Errors PROPAGATE (ValueError/FileNotFoundError/yaml.YAMLError/ValidationError) — none swallowed; will abort startup when the lifespan calls it (§5.1).
- Security: `yaml.safe_load` (not load/unsafe_load); no eval/exec; no injection/path interpolation.
- Accessors correct (weight_for→defaults fallback; priority_for→[]; merge_strategy_for→"union"). Clean port-side concern; only imports `UNIFIED_TO_LDAP`. No do_not_touch violation.

### tests/spec_0/test_chunk_1_root_scaffold.py guard conversion — PASS
Faithful, minimal conversion of stale `test_normalization_yaml_does_not_exist` → `test_normalization_yaml_exists` (asserts existence + YAML mapping + top-level attributes/defaults/enrichment). No other spec_0 assertion weakened/deleted; sibling guard `test_train_bootstrap_model_does_not_exist` preserved. Converting (not deleting) mirrors this file's own `IMPLEMENTED_APP_SERVICES` pattern and preserves traceability.

### Recommended Improvements (non-blocking)
1. Harden `weight_for` fallback against an unknown source with `.get(source, <floor>)` to avoid a latent `KeyError` (not reachable today — callers only pass ldap/saml/oidc) — `app/normalization_config.py:90`.
2. Use `X | None` instead of `Optional[X]` for consistency with `normalization_values.py` — `app/normalization_config.py:11,29-31,49`.
3. Correct the "stdlib-free import" comment (PyYAML is third-party) — `tests/spec_0/test_chunk_1_root_scaffold.py:376`.

## Chunk 4 — Iteration 1 — NEEDS CHANGES — 2026-06-05T20:40:42Z

**Files reviewed:** 4 (app/adapters/ldap.py [enrich addition], shared/naas_shared/constants.py, shared/naas_shared/config.py, docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md).

**Overall verdict:** NEEDS CHANGES (gate FAIL). Critical: 0, High: 1, Medium: 1, Low: 2.

### Blocking issues (must fix)
1. **[HIGH] Connection pool not implemented; per-call connection leak; `ldap_pool_size` dead** — `ldap.py:205-225` (`_ldap_search`), docstrings `:5`, `:234`. Spec §5.3 mandates a pool of `settings.ldap_pool_size`. `_ldap_search` calls `ldap.initialize(uri)` every enrich and never `unbind_s()`/closes (FD/socket leak under load). `settings.ldap_pool_size` — the entire reason for this chunk's lockstep config/constants/SPEC_0 additions — is never referenced, so the lockstep ships dead. Module + class docstrings falsely claim an "async connection pool." Fix: implement the bounded pool (e.g. `asyncio.Semaphore(ldap_pool_size)` gating reused bound connections) OR at minimum close per call in `try/finally` and reconcile docstrings/spec deviation. Spec calls for the pool.
2. **[MEDIUM] `last_enrich_outcome` side-channel is a read-after-await concurrency hazard for chunk 6** — `ldap.py:242-244` + per-branch assignments (328/350/359/392/405/421). Error-kind passed via a mutable instance attribute read "immediately after await enrich()"; `enrich` has multiple await points. Concurrent enrich on a shared adapter singleton would cross-assign outcomes → wrong skip_reason for the wrong event. §5.1 one-at-a-time masks it today but locks chunk 6 into a fragile contract. Fix now: return `(result, outcome)` tuple or an `EnrichOutcome` dataclass; update the `LdapEnricher` port to match.

### Non-blocking (Recommended Improvements)
1. **[LOW] PII (email `lookup_value`) logged at INFO/WARNING** — `ldap.py:397,408,422` (+debug 351,360). Log `record.id`/`user_id` or demote to DEBUG; confirm project PII stance.
2. **[LOW] Pyright "object is not iterable" at `_decode_list`** — `ldap.py:120`. Confirmed benign (sole caller always passes a list); tighten signature to `list | bytes | None` to silence.

### Verified correct (positive findings)
- **LDAP injection sanitization correct:** both `build_search_filter` (:175) and `_build_search_filter_internal` (:201) route `lookup_value` through `ldap.filter.escape_filter_chars`; no raw-interpolation path. Attribute side comes only from fixed `UNIFIED_TO_LDAP` — not injectable.
- **Three-state negative cache correct:** miss→query; sentinel `"null"`→None no-query; positive JSON→return; both positive (:419) and negative (:406) use same `cache_ttl_seconds`; transient failures (:389-400) return None and are NOT cached (no poisoning on a blip).
- **Credentials:** bind via `settings.ldap_admin_dn`/`ldap_admin_password`; URI from settings; no hardcoded creds; no DN/password logged.
- **Event-loop safety:** blocking `_ldap_search` wrapped in `asyncio.to_thread` (:380); `import ldap`/`ldap.filter` lazy inside functions (:173,199,221,445) — no top-level import (dev-venv safe).
- **Graceful degradation:** `enrich` catches all exceptions (:389), returns None, never propagates.
- **Cache-key cardinality:** attacker-influenceable email in key bounded by 60s TTL — acceptable.
- **Lockstep parity / surgical edits:** constants.py (+1 line), config.py (+1 line with ge=1/le=10 bounds, extra="ignore" still absorbs LDAP_POOL_SIZE), SPEC_0 §3.3/§3.8 mirrors byte-for-byte. Nothing else changed in those files. No do_not_touch violation.

## Chunk 4 — Iteration 2 — PASS WITH NOTES — 2026-06-05T21:14:36Z

**Files reviewed:** 4 (app/adapters/ldap.py, app/ports.py [authorized enrich-annotation edit], test_chunk4_ldap_enrich.py, test_chunk4_ldap_cache.py).

**Overall verdict:** PASS WITH NOTES (passing gate). Critical: 0, High: 0, Medium: 0, Low: 5. No blocking issues. All four iteration-1 findings resolved with no regressions.

### Iteration-1 findings — all RESOLVED
1. **[HIGH] pool/leak/dead ldap_pool_size — RESOLVED.** Bounded `asyncio.Queue(maxsize=settings.ldap_pool_size)`; `_pool_search` is slot-balanced on every exit path (success→put(conn); create-fail/search-fail/unexpected→put(None) discarding the broken conn) — no slot leak, no deadlock, no double-put. Broken connections discarded (rebind next call). All blocking ldap calls (`_create_ldap_connection`, `_ldap_search_on_conn`) wrapped in `asyncio.to_thread`.
2. **[MEDIUM] last_enrich_outcome side channel — RESOLVED.** Removed entirely; `LdapAdapter` is stateless (concurrency-safe). `enrich` returns `tuple[dict|None,str]` on all 6 paths with valid outcome codes; corrupted-positive-cache path falls through to live query. `ports.py` `LdapEnricher.enrich` annotation updated to match (only that change).
3. **[LOW] PII email logging — RESOLVED.** No log emits `lookup_value`; uses `ldap_attr`/`outcome`/field name; cache hit/miss/no-match demoted to DEBUG.
4. **[LOW] `_decode_list` signature — RESOLVED.** Now `list | bytes | None`.

### No regression (re-verified)
Sanitization (`escape_filter_chars`; attribute from fixed `UNIFIED_TO_LDAP`); three-state cache (miss→query / `"null"`→None no-query / positive→return; both at `cache_ttl_seconds`; transient NOT cached); credentials from settings, never logged; lazy `import ldap`; graceful degradation (no exception propagates). Test behavioral coverage preserved (match→attrs dict, no-match→None, bytes decode, value normalization, 5-field reverse map, unmappable, all 4 error paths) with additive `outcome` assertions; cache tests preserve miss/negative/positive/key-format/TTL/transient-not-cached coverage.

### Recommended Improvements (non-blocking)
1. **[LOW]** Don't log full corrupted cache JSON (PII risk) — log a length/hash/prefix — `app/adapters/ldap.py:460`.
2. **[LOW]** Best-effort `unbind_s()` on discarded/orphaned connections before drop — `app/adapters/ldap.py:329-331`.
3. **[LOW]** Update stale "Returns None" enrich docstring to the tuple contract — `app/ports.py:74`.
4. **[LOW]** Use `monkeypatch.delitem(...)` for the second sys.modules injection to avoid cross-test leakage — `tests/services/identity-normalization/test_chunk4_ldap_cache.py:966-992`.

## Chunk 5 — Iteration 1 — PASS — 2026-06-05T21:44:01Z

**Files reviewed:** 1 in scope (app/resolution.py) + 1 out-of-scope test-infra edit (tests/services/identity-normalization/conftest.py).

**Overall verdict:** PASS. Critical: 0, High: 0, Medium: 0, Low: 0. No blocking issues.

### resolution.py — algorithm verified against §5.5 / §5.5.1 / §5.5.2
- Only the four discriminators emitted (`single_source`/`unanimous`/`priority`/`list_merge`); zero-source attrs omitted from resolution_details + contribute 0.0.
- Scalar: 1→single_source @ weight_for; ≥2 agree→unanimous @ max agreeing weight; ≥2 disagree→priority (winner via priority_for, fallback highest weight; conf=winner_weight×0.8; conflicting_values=losing non-null; penalty_applied True).
- 0.2 penalty: department-only via was_mapped, clamped [0,1], stacks with ×0.8 on priority win, never on employee_type; discarded source doesn't penalize survivor.
- groups: union/intersection/priority merge, de-dup+sort, total_unique_groups correct; conf single→weight, multi→0.7+0.3×fraction; ⚠️ division-by-zero guarded (empty merged → fraction 0.0); 0 sources → omitted.
- Overall confidence: importance-weighted avg with ATTRIBUTE_IMPORTANCE exactly {0.15,0.25,0.20,0.25,0.15}, absent→0.0, clamped [0,1].
- source_protocol = passed primary even when ldap contributed; enrichment passed through unchanged.
- Pure/deterministic, no I/O, no eval/exec, no shared/global mutation (safe for singleton repeated/concurrent calls); imports only normalization_config + naas_shared.models (hexagonal-clean). Tests treat §3.3 payload (0.87) as illustrative and assert the §5.5 formula (~0.889) — deliberate, documented.

### conftest.py (out-of-scope test-infra) — PASS WITH NOTES (non-blocking)
Autouse global monkeypatch of `tempfile.NamedTemporaryFile` (flush-on-write) works around a real bug in `_load_config_with_strategy` (`test_chunk5_groups_merge.py:99-101` reads the temp file before flush). Verified it does NOT affect chunk-3 validation tests (they use pytest `tmp_path` + `write_text`, not NamedTemporaryFile) and weakens no assertion. Acceptable given the implementer couldn't edit test files.

### Recommended Improvements (non-blocking)
1. Prefer a one-line `f.flush()` in the chunk-5 groups-merge helper over the global tempfile monkeypatch (scopes the fix) — requires a test-file edit blocked by pipeline rules, so conftest approach acceptable — `test_chunk5_groups_merge.py:100`.
2. `resolution.py:38` redefines `EnrichmentMetadata = Union[...]` locally, duplicating the shared alias; consider importing the shared alias to avoid drift (type-hint only) — `app/resolution.py:38`.

### Scope
Only `resolution.py` (new) + test conftest changed. No do_not_touch violation.

## Chunk 6 — Iteration 1 — PASS WITH NOTES — 2026-06-06T01:08:16Z

**Files reviewed:** 4 (app/service.py, app/repository.py, app/consumer.py scope_boundary; app/main.py shared_files lifespan).

**Overall verdict:** PASS WITH NOTES (passing gate). Critical: 0, High: 0, Medium: 0, Low: 4. No blocking issues.

### Highest-value checks — verified correct
- **Dual-write ordering (§5.1, ADR-0002):** consumer does parse → normalize → write+commit → publish → XACK (consumer.py:133-145); XACK is last and only after BOTH commit and publish succeed; on ANY exception no XACK (msg stays pending for redelivery). Exact.
- **CPU-peg hardening:** empty-batch path now `await asyncio.sleep(_EMPTY_BATCH_SLEEP_S=0.5)` (consumer.py:87-93) — real non-zero yield, ONLY on the empty path, does not touch the processing path or ordering; both xreadgroup and sleep are cancellation points → clean shutdown.
- **§5.4 outcome→skip_reason mapping EXACT** for every code (ldap_match/cache_hit_positive→Applied; ldap_no_match/cache_hit_negative→no_ldap_match; ldap_timeout; ldap_connection_error; ldap_search_error/ldap_unexpected_error/unmappable_field→ldap_search_error; disabled→ldap_disabled; protocol==ldap→ldap_event; empty correlation→invalid_correlation_key). All seven skip_reasons are valid `EnrichmentSkipReason` members.
- **Graceful degradation:** normalize() never raises on enrichment failure (try/except → ldap_search_error); enrichment skip distinct from processing failure.
- **Source-agnostic:** `is_synthetic` only in a docstring, never branched on.
- **Persistence (§3.1):** `update(EventORM).where(id==event_id).values(...)` — no INSERT/SELECT/add/DDL/migration; bound params (no SQLi); one session per event via `get_session_factory()` (not request-scoped); idempotent.
- **Publish (§3.2, ADR-0011):** full LoginEventRecord via shared `publish_to_stream` to STREAM_NORMALIZED_EVENTS, normalized_attributes populated, id correlation key; no hand-rolled XADD.
- **Lifespan (§5.1):** invalid config aborts startup (propagates before task creation); `ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION)` called once; consumer launched via create_task, cancelled+awaited on shutdown; /health + create_app + module-level app intact.

### Recommended Improvements (non-blocking)
1. **[LOW]** Remove or wire up the dead `_MATCH_OUTCOMES`/`_OUTCOME_TO_SKIP_REASON` constants (defined but unreferenced; inline mapping in `_map_outcome_to_enrichment` is the live one) to eliminate a §5.4 dual-table drift hazard — `service.py:34,37-45`.
2. **[LOW]** Wrap the outer `xreadgroup` read in try/except (log, sleep, continue; let CancelledError propagate) so a transient Redis failure doesn't permanently kill the consumer task — `consumer.py:79-85`.
3. **[LOW]** Redact/bound the logged `str(exc)` on parse failure to avoid echoing a malformed field value — `consumer.py:154-159`.
4. **[LOW]** Add a real assertion to `test_consumer_loop_launched_on_startup` and replace the `assert True` placeholder in `test_lifespan_imports_run_consumer_loop` (substantive lifespan behavior is covered by sibling tests) — `tests/services/identity-normalization/test_chunk6_lifespan.py:279-347`.

### Context note
The consumer CPU-peg hang (chunk-1 `TestClient` lifespan firing the real consumer against a non-blocking AsyncMock Redis) was root-caused and fixed in a prior session: chunk-1 test fixtures (`test_chunk1_app_skeleton.py`, `test_chunk1_health.py`) now mock `app.main.run_consumer_loop` + `ensure_consumer_group`; the chunk-6 `test_chunk6_lifespan.py` health-regression test (malformed `async for` over a list) was repaired; and `consumer.py` gained the empty-batch sleep (defense-in-depth). Confirmed no non-test source outside scope changed.

### Scope
Only the four chunk-6 source files (+ expected test edits) changed. No do_not_touch violation.
