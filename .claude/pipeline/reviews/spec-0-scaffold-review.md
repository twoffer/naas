# Code Security Review — Spec 0: Project Scaffold & Shared Foundation

Append-only audit trail of every code-security-reviewer invocation for this spec (CONTRACTS.md §8).

## Chunk 1 — Iteration 1 — PASS — 2026-06-03T14:56:30Z

Config/documentation-only chunk. Reviewed for calibrated risks: secret hygiene, scope-boundary discipline, `.gitignore` augmentation safety, README augmentation, content correctness against SPEC_0 §2 / §5.5 / §5.6.

**1. Secrets hygiene — PASS**
- `.env.example` contains only documented dev-default placeholders from spec §2 (`POSTGRES_PASSWORD=naas_dev_password`, `KEYCLOAK_ADMIN_PASSWORD=admin`, `LDAP_ADMIN_PASSWORD=admin`, `ANTHROPIC_API_KEY=` empty). No real/leaked credentials.
- `.env` is byte-for-byte identical to `.env.example`.
- `.gitignore` contains `.env` — the local copy will not be committed (key secret-handling control in place).

**2. Scope discipline — PASS**
- `services/*/` contains exactly one file each (README.md). No Dockerfiles, no `app/` code, no `requirements.txt`.
- `config/normalization.yaml` absent (Spec 2); `scripts/train_bootstrap_model.py` absent (Spec 3). Both dirs scaffolded via `.gitkeep` only.
- No `do_not_touch` boundary modified (`CLAUDE.md`, `shared/`, `infrastructure/`, `docker-compose.yml`, `docs/`, `.claude/` untouched).

**3. `.gitignore` augmentation safety — PASS**
- All required §5.5 lines present; pre-existing entries (Claude Code, Obsidian) preserved — implementer added, did not delete.

**4. `README.md` augmentation — PASS**
- Tagline "Normalized Adaptive Access System" preserved; "Quick start" section appended; existing content intact.

**5. Content correctness — PASS**
- `.env.example` has every required key with spec-correct values (all eight service ports 8000–8007, `LLM_PROVIDER=mock`, `LDAP_POOL_SIZE=3`, `KEYCLOAK_REALM=naas-demo`, `KEYCLOAK_DB=keycloak`). All eight service READMEs contain "Part of the NAAS system."

**Test quality — PASS** — meaningful behavioral assertions (byte-for-byte `.env` identity, exact-key presence, only-README directory check, absence of later-spec files).

### Verdict: PASS
Critical: 0, High: 0, Medium: 0, Low: 1

**Blocking issues:** none

**Recommended improvements (non-blocking):**
1. `services/*/README.md:3` — README placeholder wording differs from spec §5.6 template ("a later Spec" vs "Spec {N}"). Benign and arguably better (avoids hardcoding a possibly-wrong spec number); no change required. Flagged for traceability only.

## Chunk 2 — Iteration 1 — PASS WITH NOTES — 2026-06-03T15:23:23Z

Keystone shared library `naas_shared`. Reviewed all 11 source files + the 102-test suite for correctness against the canonical SPEC_0 §§3.3–3.8 / 5.4 contract and for security/quality. Critical: 0, High: 0, Medium: 0, Low: 3.

**Per-file verdicts:** `pyproject.toml` PASS (matches §5.4); `__init__.py` PASS; `constants.py` PASS (exact §3.3 values); `config.py` PASS WITH NOTES; `models.py` PASS WITH NOTES; `database.py` PASS; `redis_client.py` PASS; `logging.py` PASS; `schemas.py`/`ml_features.py`/`simulation_tools.py` PASS (correct placeholder discipline); test suite PASS (asserts real behavior, no mocking of the package under test).

**Two documented deviations assessed correct & safe:**
1. `config.py` added `from pydantic import Field` + `from typing import Optional` — required transcription fix; the §3.8 snippet uses both but omitted them from imports (without it the module raises `NameError`).
2. `config.py` added `extra = "ignore"` to `Settings.Config` — correct, not a masked misconfiguration. The committed `.env`/`.env.example` carry many keys not declared as `Settings` fields (`KEYCLOAK_ADMIN`, `LDAP_*`, `*_PORT`, `OLLAMA_*`); pydantic-settings v2 rejects undeclared env-file keys by default, breaking every `Settings()` construction. `ignore` is strictly safer than `allow` (undeclared secrets like `KEYCLOAK_ADMIN_PASSWORD` are dropped, not absorbed as attributes). Correct security posture.

**Security checks:** no SQL string interpolation (URLs assembled from settings); `redis_client` serializes payloads with `json.dumps` (no injection / unsafe deserialization); `ensure_consumer_group` fails closed (swallows only `BUSYGROUP`, re-raises all other `ResponseError`); `get_db_session` commits on clean exit, rolls back + re-raises on exception; credentials sourced from settings/env, not hardcoded. Both discriminated unions (`ResolutionDetail` by `resolution`, `EnrichmentMetadata` by `applied`) preserved; `RiskDecision.decision` Literal fails closed (`challenge`/`block` rejected). `NormalizedAttributes.enrichment` required.

**Scope discipline:** no `do_not_touch` paths modified; no extra source files beyond scope_boundary (`*.egg-info/`, `__pycache__/` are gitignored build artifacts).

### Verdict: PASS WITH NOTES (no blocking issues)

**Blocking issues:** none

**Recommended improvements (non-blocking, all spec-faithful):**
1. `shared/naas_shared/models.py:35,213` — `datetime.utcnow` default_factory deprecated in Python 3.12+ (naive UTC). Faithful to §3.4; address only if the spec is revised (`lambda: datetime.now(timezone.utc)` is the modern equivalent).
2. `shared/naas_shared/logging.py:31` — `get_logger(name: str = None)` should be `Optional[str]`. Faithful to §3.7; cosmetic.
3. `shared/naas_shared/models.py:5` — unused `field_validator` import carried via `# noqa: F401`. Matches the §3.4 import block; leave as-is for spec fidelity.

## Chunk 3 — Iteration 1 — PASS — 2026-06-03T15:48:33Z

Static infrastructure config: PostgreSQL DDL + Redis config. Reviewed against canonical SPEC_0 §3.1/§3.2 and for SQL correctness/escaping/injection-surface and Redis posture. Critical: 0, High: 0, Medium: 0, Low: 1 (test-only).

**`infrastructure/postgres/init.sql` — PASS**
- DDL matches §3.1 exactly: pgcrypto extension; five tables (users, events, policies, risk_assessments, alerts) with correct columns/defaults/CHECKs/FKs. `events.user_agent` present; `events.protocol` CHECK = oidc/saml/ldap; `events.source` CHECK = user/simulator/api; `risk_assessments.shadow_decision`/`shadow_score` present with decision CHECK = allow/step_up_mfa/deny; `alerts` severity/status CHECKs. All six indexes present.
- **SQL string-escaping (the #1 transcription hazard) — correct & balanced.** The `policy_yaml` literal opens (line 102) and closes (line 147) cleanly; all 16 interior single quotes are doubled pairs (`''contractor''` x2 contexts, `''US''`, `''ldap''`) — even count, no premature termination.
- Embedded YAML carries signal_weights (4), the 8 conditions, thresholds (step_up_mfa 0.3 < deny 0.7), ensemble (rule_weight 0.6 + ml_weight 0.4 = 1.0). Seed INSERT uses `ON CONFLICT (policy_id) DO NOTHING`.
- NO `CREATE DATABASE` statement anywhere (Gap 1 honored — Keycloak DB guidance stayed explanatory). No injection surface (static seed data, no dynamic SQL).

**`infrastructure/redis/redis.conf` — PASS**
- Exactly the four required directives (maxmemory 256mb, maxmemory-policy allkeys-lru, appendonly yes, appendfsync everysec); no stream/consumer-group pre-creation. No `requirepass`/ACL — correct for Spec 0 dev config, out of scope.

**Test quality — PASS WITH NOTES** — 54 tests assert real structure/content (constraint-shape regexes, doubled-quote presence, weight-sum arithmetic, exact-set Redis directive equality, no-CREATE-DATABASE guard); `sqlparse` importorskip appropriate.

**Scope discipline:** clean — only the two scope files under `infrastructure/postgres/` and `infrastructure/redis/`; no `do_not_touch` paths modified.

### Verdict: PASS (no blocking issues)

**Blocking issues:** none

**Recommended improvements (non-blocking):**
1. `tests/spec_0/test_chunk_3_postgres_redis.py:643-660` — the unescaped-quote negative guard only checks `'contractor'`; add equivalent negative-lookbehind guards for `'US'` and `'ldap'` (positive coverage already exists for both).
2. `infrastructure/redis/redis.conf` — when promoted beyond local dev, add `requirepass`/ACL hardening (out of scope for Spec 0).

## Chunk 4 — Iteration 1 — PASS WITH NOTES — 2026-06-03T16:13:23Z

Static identity-provider config: Keycloak realm import JSON + OpenLDAP bootstrap LDIF. Reviewed against canonical SPEC_0 §5.2/§5.3 + Gap 6 + Areas-of-Care #1/#2 and for identity-config correctness, LDIF hazards, demo-credential hygiene, and cross-protocol correlation. Critical: 0, High: 0, Medium: 0, Low: 4.

**`infrastructure/keycloak/naas-realm-export.json` — PASS WITH NOTES**
- Valid JSON; `realm == "naas-demo"`, `enabled` true, `sslRequired` "none", `registrationAllowed` false. Exactly one client `naas-dashboard` (publicClient/standardFlow/directAccessGrants true, protocol openid-connect, correct redirectUris/webOrigins). Exactly 3 users alice/bob/charlie, each enabled with one `password123`/temporary-false credential and correct group (engineering/product/security). Top-level `groups` includes all three. No service-account secrets, no clientSecret, no admin creds embedded.

**`infrastructure/openldap/bootstrap.ldif` — PASS WITH NOTES**
- NO `dn: dc=corp,dc=com` base-DN entry (osixia auto-creates it — silent-skip hazard avoided). OU entries (`ou=users`, `ou=groups`) precede all user entries. Exactly 5 inetOrgPerson users (alice, bob, charlie, diana, eve) with mail/uid/userPassword/departmentNumber/employeeType. employeeType coverage: FTE (alice, bob), contractor (charlie, eve), vendor (diana).
- Cross-protocol correlation intact: alice@corp.com/bob@corp.com/charlie@corp.com identical in realm and LDIF; diana@corp.com + eve@partner.com LDAP-only.

**Test quality — PASS** — 91 tests use exact-set identity checks (not bare counts), a precise case-insensitive base-DN-hazard regex, line-index ordering checks, and two-sided cross-protocol correlation assertions. No mocking of artifacts under test.

**Plain-vs-slash group names:** NOT blocking for Spec 0. Spec §5.2 example uses plain names; §6.4 acceptance only checks OIDC discovery + alice's password grant (neither asserts group-membership binding). Carried forward as a known item for the first downstream spec that consumes the OIDC `groups` claim.

**Scope discipline:** clean — each infra dir holds only its scope file; no `do_not_touch` paths modified.

### Verdict: PASS WITH NOTES (no blocking issues)

**Blocking issues:** none

**Recommended improvements (non-blocking, demo-scope / forward-looking):**
1. `infrastructure/keycloak/naas-realm-export.json:4,11,12` — demo-only postures (`publicClient`+ROPC+`sslRequired:none`) require hardening (confidential client/PKCE, ROPC off, `sslRequired` external/all) before non-local deployment.
2. `infrastructure/openldap/bootstrap.ldif` — plaintext `userPassword: password123` is demo-only; real directories must hash (`{SSHA}`).
3. `infrastructure/keycloak/naas-realm-export.json` — carry the plain-vs-slash group-name binding question forward to the first downstream spec consuming the OIDC `groups` claim.
4. `tests/spec_0/test_chunk_4_keycloak_ldap.py:676` — structural LDIF parser lacks base64/continuation-line handling; fine for current LDIF, note if it grows.

## Chunk 5 — Iteration 1 — PASS — 2026-06-03T16:37:25Z

Integration-facing chunk: single `docker-compose.yml` orchestrating the four infra services, wiring Chunk 1/3/4 artifacts via bind mounts. Reviewed against canonical SPEC_0 §5.1 + Architect's Note §3.1 (Gap 1). Critical: 0, High: 0, Medium: 0, Low: 1 (forward note).

**`docker-compose.yml` — PASS**
1. Exactly four services (postgres, redis, keycloak, openldap); no application/service containers (scope-boundary placeholder comment present). Images match spec exactly (`postgres:17-alpine`, `redis:7.4-alpine`, `quay.io/keycloak/keycloak:26.0`, `osixia/openldap:1.5.0`). `naas-network` bridge; four named volumes (postgres-data, redis-data, ldap-data, ldap-config). `docker compose config` validates.
2. Obsolete `version` key correctly omitted (right call for Compose v2; no validity impact).
3. **Keycloak H2 (Gap 1):** NO `KC_DB*` env vars — only `KEYCLOAK_ADMIN`/`KEYCLOAK_ADMIN_PASSWORD`; `command: start-dev --import-realm`; realm bind-mounted to `/opt/keycloak/data/import/`. (`.env.example`'s `KEYCLOAK_DB` is never interpolated and doesn't match the `KC_DB*` prefix — inert.)
4. **Bind-mount path integrity:** all four source paths exist on disk (Chunk 1/3/4 files) and targets are correct (init.sql → `/docker-entrypoint-initdb.d/01-init.sql`; redis.conf → `/usr/local/etc/redis/redis.conf` and passed to `command`; realm → `/opt/keycloak/data/import/`; ldif → osixia custom bootstrap path). No typos. init.sql confirmed to NOT create a keycloak DB, consistent with H2 decision.
5. **Credentials:** all via `${VAR:-default}` with documented dev defaults; no hardcoded secrets beyond those. openldap healthcheck's literal `admin` arg matches the §5.1 block verbatim (demo-scope, not a service-to-service path).
6. **Scope discipline:** only `docker-compose.yml` created; no `do_not_touch` paths modified (infra files referenced by bind mount, content untouched).

**Test quality — PASS** — 46 static tests with concrete structural assertions and documented WHYs, including critical negatives (exact four-service set, no `KC_DB*` keys, no forbidden app services) and on-disk bind-mount-source existence checks; `docker compose config -q` subprocess cross-check skips cleanly without the CLI. Volume/env/command/network helpers handle both short and long syntaxes.

### Verdict: PASS (no blocking issues)

**Blocking issues:** none

**Recommended improvements (non-blocking):**
1. `docker-compose.yml:11,27,50,73-74` — host port bindings (postgres 5432, redis 6379, keycloak 8080, openldap 389/636) are acceptable for a local demo but would expose dev-credentialed datastores/LDAP on a shared/public host; for non-local deployment bind to `127.0.0.1` or drop host port mappings and rely on `naas-network`.
