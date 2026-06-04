PLAN: Spec 0 — Project Scaffold & Shared Foundation
SPEC REFERENCE: docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md
PREREQUISITES:
- Docker + Docker Compose installed (validation §6.1–6.5, §6.7 require a live stack).
- Python 3.12+ available locally for the shared-library import check (§6.6) and for tests the test-suite-generator writes against the static artifacts.
- No upstream specs. Spec 0 IS the foundation; it is depended on by Specs 1–6.
- Repo already contains a root `README.md` (one-line description) and a root `.gitignore` that is a superset of the spec's §5.5 content (it additionally ignores `.obsidian/`, `.trash/`, `.claude/*` exceptions, `state.json`, `chunks.json`, and simulation runs). A root `CLAUDE.md` (project instructions) already exists. These three pre-existing files are AUGMENTED / VERIFIED, not blindly overwritten — see Step 1 and KNOWN RISKS.

OVERVIEW

Spec 0 produces a working infrastructure stack (`docker-compose up` brings up PostgreSQL, Redis, Keycloak, OpenLDAP) and the pip-installable `naas_shared` Python package that every downstream service imports. NO application code, NO service Dockerfiles, NO dashboard, NO monitoring, NO Alembic, NO tests, NO CI/CD, NO Makefile (spec §7). The deliverables are: root scaffolding + empty service dirs, the shared Python library, the static infrastructure config artifacts (Postgres DDL, Redis conf, Keycloak realm JSON, OpenLDAP LDIF), and the `docker-compose.yml` glue that wires them together.

The work decomposes into 5 chunks along clean seams. The shared library (Chunk 2) is the keystone: it is pure Python with no Docker dependency and is the single source of truth (§3.3–§3.8, §4) for constants, Pydantic models, config, DB/Redis helpers, and logging. The infrastructure artifacts (Chunks 3–4) are static, structurally validatable files. The `docker-compose.yml` (Chunk 5) is the orchestration glue and the integration-facing surface where the §6 end-to-end validation runs.

CANONICAL CONTRACTS — DO NOT REDEFINE OR PARAPHRASE
The spec §3 gives canonical, near-verbatim source for `constants.py`, `models.py`, `database.py`, `redis_client.py`, `logging.py`, `config.py`, the Postgres `init.sql`, and `redis.conf`. The feature-implementer MUST transcribe these from the spec exactly (transcription, not redesign). The default policy YAML seed (§3.1, lines 247–299) with `''`-doubled single quotes inside the SQL string is load-bearing — copy it precisely.

STEPS

Step 1: Root scaffolding and empty service/directory tree
  Files:
    - .env.example  (CREATE — verbatim from spec §2)
    - .env  (CREATE — exact copy of .env.example; gitignored)
    - .gitignore  (VERIFY/AUGMENT existing — ensure every entry from spec §5.5 is present; do NOT remove the repo's existing extra entries)
    - README.md  (AUGMENT existing — append a minimal quick-start section per spec §1; preserve the existing one-line description)
    - CLAUDE.md  (VERIFY existing — spec §1 wants an agent-reference copy at root; the root CLAUDE.md already exists and serves this purpose. Do NOT overwrite it.)
    - config/.gitkeep  (CREATE — scaffold the empty config/ directory; do NOT create normalization.yaml content — Spec 2 owns it)
    - scripts/.gitkeep  (CREATE — scaffold the empty scripts/ directory; do NOT create train_bootstrap_model.py content — Spec 3 owns it)
    - services/api-gateway/README.md
    - services/event-ingestion/README.md
    - services/identity-normalization/README.md
    - services/signal-enrichment/README.md
    - services/risk-evaluator/README.md
    - services/policy-management/README.md
    - services/alert-service/README.md
    - services/persona-simulator/README.md
  Details:
    - `.env.example`: transcribe the full env block from spec §2 exactly (PostgreSQL, Keycloak admin, Redis, OpenLDAP incl. LDAP_POOL_SIZE=3, all service ports 8000–8007, DASHBOARD_PORT=3000, LLM provider block, Keycloak OIDC block). `.env` is a byte-for-byte copy.
    - `.gitignore`: the repo's existing file already contains the spec §5.5 entries (Python, .env, IDE, postgres-data/, redis-data/, OS, Node, *.pkl/*.joblib, *.log) plus extras. Confirm presence of all §5.5 lines; if any are missing add them. Do not delete the Obsidian/Claude Code/simulation-run entries.
    - `README.md`: keep the existing tagline line; append a short "Quick start" (`docker-compose up -d`, `docker-compose ps`, link to docs/architecture/SYSTEM_ARCHITECTURE.md).
    - Each `services/*/README.md`: use the template from spec §5.6 — `# {Service Name}` / "Part of the NAAS system. Implementation defined in Spec {N}." / "See `docs/architecture/SYSTEM_ARCHITECTURE.md` for architectural context." Use the correct service name and the spec number that owns each service (Event Ingestion → Spec 1, Identity Normalization → Spec 2, Signal Enrichment + Risk Evaluator → Spec 3, Policy Management → Spec 4, API Gateway → Spec 5, Persona Simulator → Spec 6 or per the implementation-priority mapping; if unsure, reference "a later Spec" rather than guess a wrong number).
    - `config/` and `scripts/` use `.gitkeep` (or equivalent placeholder) so git tracks the otherwise-empty directories. Do NOT create their real content files.
  Shared imports: none (this chunk creates no Python that imports naas_shared).
  Verify:
    - `test -f .env.example && test -f .env && diff .env.example .env` (env files identical).
    - `grep -q 'POSTGRES_HOST=postgres' .env.example && grep -q 'LDAP_POOL_SIZE=3' .env.example && grep -q 'LLM_PROVIDER=mock' .env.example`.
    - All 8 `services/*/README.md` exist; `config/` and `scripts/` directories exist.
    - `.gitignore` contains `.env`, `__pycache__/`, `postgres-data/`, `redis-data/`, `*.pkl`.

Step 2: Shared Python library (naas_shared) — the keystone
  Files:
    - shared/pyproject.toml
    - shared/naas_shared/__init__.py
    - shared/naas_shared/constants.py
    - shared/naas_shared/config.py
    - shared/naas_shared/models.py
    - shared/naas_shared/database.py
    - shared/naas_shared/redis_client.py
    - shared/naas_shared/logging.py
    - shared/naas_shared/schemas.py  (EMPTY placeholder — see below)
    - shared/naas_shared/ml_features.py  (PLACEHOLDER — see KNOWN RISKS)
    - shared/naas_shared/simulation_tools.py  (PLACEHOLDER — see KNOWN RISKS)
  Details:
    - `pyproject.toml`: transcribe verbatim from spec §5.4 — name `naas-shared`, version `2.0.0`, requires-python `>=3.12`, dependencies (fastapi, pydantic, pydantic-settings, sqlalchemy[asyncio], asyncpg, redis, structlog with the spec's version pins), `[tool.setuptools.packages.find]` where=["."], include=["naas_shared*"].
    - `constants.py`: transcribe verbatim from spec §3.3 — stream names (login_events, normalized_events, enriched_events), STREAM_MAXLEN=10000, channels (decisions, alerts), consumer groups (normalization_workers, enrichment_workers, evaluator_workers), and all cache key/TTL constants.
    - `config.py`: transcribe verbatim from spec §3.8. NOTE the spec snippet uses `Field` and `Optional` (lines 738–743) but its import block only imports `BaseSettings` and `lru_cache`. The implementer MUST add `from pydantic import Field` and `from typing import Optional` so the module imports cleanly. The `database_url` / `database_url_sync` properties and `@lru_cache get_settings()` are exactly as specified. `class Config` keeps `env_file=".env"`.
    - `models.py`: transcribe verbatim from spec §3.4 — LoginEventBase, LoginEventIngest, LoginEventRecord, SourceProtocol alias, the ResolutionDetail discriminated union (UnanimousResolution/PriorityResolution/SingleSourceResolution/ListMergeResolution discriminated by `resolution`), the EnrichmentMetadata discriminated union (EnrichmentApplied/EnrichmentSkipped discriminated by `applied`, with the EnrichmentSkipReason Literal), NormalizedAttributes, RiskDecision, AlertMessage, HealthResponse. Keep all Field constraints (regex on client_ip, ge/le bounds, Literals) exactly.
    - `database.py`: transcribe verbatim from spec §3.5 — module-level `_engine`/`_session_factory` singletons, `get_engine()`, `get_session_factory()`, async `get_db_session()` FastAPI dependency with commit/rollback. Imports `from naas_shared.config import get_settings`.
    - `redis_client.py`: transcribe verbatim from spec §3.6 — `redis.asyncio as aioredis`, `get_redis()` singleton, `publish_to_stream()` (XADD with `{"data": json.dumps(data)}` and maxlen=STREAM_MAXLEN), `publish_to_channel()`, `ensure_consumer_group()` (idempotent, swallows BUSYGROUP). Imports STREAM_MAXLEN from constants.
    - `logging.py`: transcribe verbatim from spec §3.7 — `setup_logging(service_name, log_level)` configuring structlog JSON output with contextvars merge for correlation_id, and `get_logger()`.
    - `__init__.py`: minimal. A bare package marker is sufficient for §6.6 (the import test imports submodules directly, e.g. `from naas_shared.config import get_settings`). Optional convenience re-exports of the §4 import surface are acceptable but keep them simple and only export names that exist; do not re-export ml_features/simulation_tools placeholder symbols that aren't defined.
    - `schemas.py`: EMPTY placeholder containing exactly the comment `# ORM table definitions — populated by Spec 1 when first needed` (spec Gap 5).
    - `ml_features.py` and `simulation_tools.py`: PLACEHOLDERS only. Spec 0 §3 defines NO content for them and the §6.6 import test does not import them; their real content is owned by later specs (ml_features → Spec 3; simulation_tools P0 definitions → the persona-simulator track). Create each as an importable module with a single deferral comment, e.g. `# Feature-column ordering contract — populated by Spec 3 (ML bootstrap).` and `# Shared tool definitions + ToolExecutor — populated by later spec (P0 definitions, P2 executor).` This keeps the package structure complete and every module importable without inventing contracts the spec hasn't defined. See KNOWN RISKS.
  Shared imports: this chunk DEFINES the shared imports surface listed in spec §4. Internal cross-module imports: config→(nothing), database→config, redis_client→config+constants, models→(stdlib+pydantic only).
  Verify (spec §6.6, runnable without Docker):
    - `cd shared && pip install -e .` succeeds.
    - `cd shared && python3 -c "from naas_shared.config import get_settings; from naas_shared.models import LoginEventIngest, RiskDecision, AlertMessage; from naas_shared.constants import STREAM_LOGIN_EVENTS, CHANNEL_DECISIONS; from naas_shared.logging import setup_logging; setup_logging('test'); s=get_settings(); print(s.database_url); print(STREAM_LOGIN_EVENTS); print('All imports OK')"` prints a `postgresql+asyncpg://...` URL, `login_events`, and `All imports OK`.
    - Additional unit-testable assertions: `LoginEventIngest` rejects a non-dotted-quad `client_ip` (ValidationError); `NormalizedAttributes` requires an `enrichment` field; `RiskDecision.decision` only accepts allow/step_up_mfa/deny; constants module exposes GROUP_NORMALIZATION/GROUP_ENRICHMENT/GROUP_EVALUATOR and STREAM_MAXLEN==10000.

Step 3: PostgreSQL DDL and Redis configuration artifacts
  Files:
    - infrastructure/postgres/init.sql
    - infrastructure/redis/redis.conf
  Details:
    - `init.sql`: transcribe verbatim from spec §3.1. Order: `CREATE EXTENSION IF NOT EXISTS "pgcrypto";` then tables `users`, `events`, `policies`, `risk_assessments`, `alerts` (all with `IF NOT EXISTS`, the exact column types, CHECK constraints, and FKs from the spec), then the three event indexes (idx_events_user_id, idx_events_timestamp DESC, idx_events_protocol), the two risk_assessments indexes, the alerts status index, then the seed `INSERT INTO policies (...) VALUES ('default-v1', 'Default Risk Policy', '1.0.0', TRUE, FALSE, '<policy yaml>') ON CONFLICT (policy_id) DO NOTHING;`. CRITICAL: the embedded policy YAML uses doubled single quotes `''` for every literal single quote (e.g. `''contractor''`, `''US''`, `''ldap''`) — this is PostgreSQL string escaping and must be copied exactly (spec §3.1 warning). Do NOT add a `CREATE DATABASE keycloak` statement — per the Architect's Note (§3.1, Gap 1) Keycloak uses its built-in H2 dev DB; the commented guidance block in the spec is explanatory only and must NOT become an executable statement.
    - `redis.conf`: transcribe verbatim from spec §3.2 — `maxmemory 256mb`, `maxmemory-policy allkeys-lru`, `appendonly yes`, `appendfsync everysec`. No stream pre-creation.
  Shared imports: none.
  Verify (structural / static — no Docker required to test syntax):
    - `init.sql` parses as valid SQL (e.g. via `sqlparse` or `sqlfluff parse`); contains exactly the five `CREATE TABLE` statements for users/events/policies/risk_assessments/alerts; contains the `pgcrypto` extension; the policy CHECK constraints list the correct enum values; the seed INSERT targets `policies` with `policy_id='default-v1'`, `is_active TRUE`; the embedded YAML contains `signal_weights`, `conditions`, `thresholds` (step_up_mfa 0.3, deny 0.7), `ensemble` (rule_weight 0.6, ml_weight 0.4); no `CREATE DATABASE` statement is present.
    - `redis.conf` contains the four directives with the spec's exact values.
    - LIVE-STACK checks deferred to Chunk 5 / §6.2–§6.3 (psql `\dt`, policy SELECT, redis-cli PING, CONFIG GET maxmemory).

Step 4: Keycloak realm export and OpenLDAP bootstrap LDIF
  Files:
    - infrastructure/keycloak/naas-realm-export.json
    - infrastructure/openldap/bootstrap.ldif
  Details:
    - `naas-realm-export.json`: write a valid Keycloak realm-representation JSON per spec §5.2. Realm `naas-demo`, `enabled: true`, `sslRequired: "none"`, `registrationAllowed: false`. One client `naas-dashboard`: `enabled`, `publicClient: true`, `standardFlowEnabled: true`, `directAccessGrantsEnabled: true`, `redirectUris: ["http://localhost:3000/*"]`, `webOrigins: ["http://localhost:3000"]`, `protocol: "openid-connect"`. Three groups: engineering, product, security. Three users alice/bob/charlie with the emails, names, password `password123` (credential `type:password`, `temporary:false`), and group membership from the spec §5.2 table. Prefer writing the JSON file directly (spec §5.2 approach 2). Keycloak `--import-realm` reads it from `/opt/keycloak/data/import/` (mounted by docker-compose in Chunk 5).
    - `bootstrap.ldif`: transcribe verbatim from spec §5.3. CRITICAL ORDERING/FORMAT (spec Gap 6, Areas-of-Care #2): do NOT include the base DN entry `dc=corp,dc=com` (the osixia/openldap image auto-creates it from LDAP_DOMAIN; including it causes an "Already exists" error that silently skips the rest of the file). Start at `ou=users` and `ou=groups`, THEN the five users (alice, bob, charlie, diana, eve) as `inetOrgPerson` with cn/sn/mail/uid/userPassword/departmentNumber/employeeType. Parent OUs must appear before child user entries. Use the exact employeeType values (alice/bob FTE, charlie/eve contractor, diana vendor) and the exact mails (eve@partner.com, others @corp.com).
  Shared imports: none.
  Verify (structural / static — no Docker required to test syntax):
    - `naas-realm-export.json` is valid JSON (`python3 -m json.tool`); top-level `realm == "naas-demo"`; `clients[0].clientId == "naas-dashboard"` with `publicClient true`, `directAccessGrantsEnabled true`, redirectUris/webOrigins as specified; exactly 3 users with usernames alice/bob/charlie each carrying a password credential; groups include engineering/product/security.
    - `bootstrap.ldif` parses as valid LDIF (e.g. via `ldif3`/`python-ldap` parser, or structural line checks); does NOT contain a `dn: dc=corp,dc=com` entry; contains `dn: ou=users,dc=corp,dc=com` and `dn: ou=groups,dc=corp,dc=com` BEFORE any `uid=...,ou=users` entry; contains exactly 5 `inetOrgPerson` user entries; employeeType values across users cover FTE, contractor, vendor.
    - LIVE-STACK checks deferred to Chunk 5 / §6.4–§6.5 (OIDC discovery curl, token grant, ldapsearch).

Step 5: docker-compose orchestration + end-to-end validation surface (integration-facing)
  Files:
    - docker-compose.yml
  Details:
    - Transcribe the compose file from spec §5.1. Four services on a `naas-network` bridge:
      * `postgres` (postgres:17-alpine, container naas-postgres): env from ${POSTGRES_*} with defaults; ports ${POSTGRES_PORT:-5432}:5432; volumes postgres-data + `./infrastructure/postgres/init.sql:/docker-entrypoint-initdb.d/01-init.sql`; pg_isready healthcheck.
      * `redis` (redis:7.4-alpine, container naas-redis): ports ${REDIS_PORT:-6379}:6379; volumes redis-data + `./infrastructure/redis/redis.conf:/usr/local/etc/redis/redis.conf`; command runs redis-server with that conf; redis-cli ping healthcheck.
      * `keycloak` (quay.io/keycloak/keycloak:26.0, container naas-keycloak): env KEYCLOAK_ADMIN/KEYCLOAK_ADMIN_PASSWORD; NO KC_DB* vars (built-in H2 per Gap 1); `command: start-dev --import-realm`; ports 8080:8080; volume `./infrastructure/keycloak/naas-realm-export.json:/opt/keycloak/data/import/naas-realm-export.json`; depends_on postgres healthy; TCP healthcheck per §5.1 with start_period 60s.
      * `openldap` (osixia/openldap:1.5.0, container naas-openldap): env LDAP_ORGANISATION/LDAP_DOMAIN/LDAP_ADMIN_PASSWORD; ports 389:389 and 636:636; volumes ldap-data + ldap-config + `./infrastructure/openldap/bootstrap.ldif:/container/service/slapd/assets/config/bootstrap/ldif/custom/bootstrap.ldif`; ldapsearch healthcheck.
    - Include the "APPLICATION SERVICES" placeholder comment block (later specs add their containers here). Networks: `naas-network` (bridge). Volumes: postgres-data, redis-data, ldap-data, ldap-config.
    - KEYCLOAK HEALTHCHECK FALLBACK (spec §5.1 critical note): start with the TCP healthcheck. If `docker-compose up` hangs on Keycloak health, fall back to `start_period: 90s` with no `test`, OR drop `condition: service_healthy` for downstream deps. Do NOT spend >20 min debugging Keycloak healthchecks.
    - This is the only chunk that touches `docker-compose.yml`. It references the artifacts owned by Chunks 3 and 4 via bind mounts but does NOT modify them (they are in this chunk's do_not_touch).
  Shared imports: none.
  Verify:
    - Static: `docker-compose.yml` is valid YAML and `docker-compose config` (or `docker compose config`) validates without error; the four expected services, the naas-network, and the four named volumes are present; keycloak has NO KC_DB* env vars; the init.sql / redis.conf / realm-json / ldif bind-mount paths match the files created in Chunks 1/3/4.
    - LIVE STACK (spec §6.1–§6.5, §6.7) — end-to-end:
      * §6.1 `docker-compose up -d` then `docker-compose ps` → postgres/redis/openldap healthy, keycloak healthy or running.
      * §6.2 `docker exec naas-postgres psql -U naas -d naas -c "\dt"` lists users/events/policies/risk_assessments/alerts; `SELECT policy_id,name,is_active FROM policies;` → `default-v1 | Default Risk Policy | t`.
      * §6.3 `docker exec naas-redis redis-cli ping` → PONG; `CONFIG GET maxmemory` → 256mb.
      * §6.4 `curl http://localhost:8080/realms/naas-demo/.well-known/openid-configuration` → JSON with authorization/token/jwks endpoints; password grant for alice/naas-dashboard returns an access_token.
      * §6.5 ldapsearch `(uid=alice)` returns alice's attributes; user count under ou=users → 5 entries.
      * §6.7 `docker-compose down -v` exits cleanly, volumes removed.

INTEGRATION NOTES
- Upstream: none. Spec 0 is the root of the dependency graph; it defines contracts consumed by Specs 1–6.
- Downstream consumers of this spec's artifacts:
  * Every future service imports `naas_shared` (Chunk 2) and, per spec §4 / Areas-of-Care #5, MUST `COPY shared/ /app/shared/` and `RUN pip install -e /app/shared/` in its Dockerfile, with the compose `build.context` set to the repo root (`.`) so `shared/` is in the build context — a self-contained image, not a `./shared:/app/shared` runtime volume mount. Forgetting the copy is the spec's #1 predicted failure mode (ModuleNotFoundError: naas_shared).
  * The canonical Redis stream/channel/consumer-group names (Chunk 2 `constants.py`) are the single source of truth — downstream specs import them, never re-string-literal them. Stream messages are wrapped as `{"data": json.dumps(payload)}` by `publish_to_stream` (Chunk 2 `redis_client.py`); consumers must `json.loads(msg["data"])`. Consumer groups are created lazily by services via `ensure_consumer_group()` on startup — Spec 0 does NOT pre-create streams or groups (§7).
  * The Postgres schema (Chunk 3 `init.sql`) is created once on first container boot via the docker-entrypoint-initdb.d mount; it is the canonical DB schema (no Alembic per §7). Services read/write these tables.
  * Keycloak (Chunk 4 realm) is the OIDC IdP for the API Gateway (JWKS validation) and the dashboard auth-code flow. OpenLDAP (Chunk 4 LDIF) is queried by Identity Normalization for cross-protocol enrichment (LDAP tcp/389 on the internal Docker network).
- Shared state / caching: Redis is the pipeline transport (Streams) and the cache (policy 60s, IP rep 24h, geo 7d, JWKS 5min — TTL constants in Chunk 2). No caching logic is built in Spec 0; only the constants and the conf.
- Real-time / WebSocket: none in Spec 0 (the API Gateway WebSocket layer is Spec 5). The `decisions`/`alerts` Pub/Sub channel names are defined here for downstream use.
- docker-compose.yml is the shared orchestration file. In Spec 0 it is created wholesale (Chunk 5). Later specs APPEND their service containers under the "APPLICATION SERVICES" placeholder block — so it is a `shared_files` candidate across specs, though within Spec 0 only Chunk 5 owns it.

KNOWN RISKS
- ml_features.py / simulation_tools.py content is undefined in Spec 0 (AMBIGUITY, resolved by decision). They appear in the §1 file tree (lines 49–50) with descriptive comments, but §3 defines NO source for them, §4's import surface omits them, and the §6.6 import test does not import them. Their real content is owned by later specs (ml_features → Spec 3 per SYSTEM_ARCHITECTURE.md; simulation_tools P0 tool definitions → the persona-simulator track). DECISION: create both as importable PLACEHOLDER modules with a single deferral comment each (mirroring the explicit `schemas.py` placeholder precedent in Gap 5), so the package structure is complete and importable without inventing contracts the spec has not defined. This is surfaced rather than silently guessed — if the developer wants the full 16-feature ordering or the P0 TOOL_DEFINITIONS written now, that is a scope expansion to confirm.
- Pre-existing root files (`.gitignore`, `README.md`, `CLAUDE.md`). The spec §1 lists all three as "created," but they already exist in the repo. DECISION: `.gitignore` is verified/augmented (its current content is already a superset of §5.5); `README.md` is augmented with a quick-start section preserving the existing tagline; the root `CLAUDE.md` (project instructions) already satisfies the "agent reference copy" intent and is NOT overwritten. Overwriting any of these wholesale would destroy live project content. Flag for reviewer: confirm augment-not-overwrite is acceptable.
- config.py import gap in the spec snippet (spec §3.8 lines 738–743 use `Field` and `Optional` but the snippet's imports omit them). The implementer must add `from pydantic import Field` and `from typing import Optional`, or the module will NameError on import — which would fail §6.6. This is a transcription fix, not a redesign.
- Keycloak healthcheck flakiness (spec §5.1 critical note + Areas-of-Care #1). The TCP-based healthcheck may be unreliable; the keycloak image lacks curl. Mitigation per spec: try TCP first, fall back to `start_period`-only (90s) or drop `condition: service_healthy`; cap debugging at 20 min. The realm import failing silently manifests as a 404 on the OIDC discovery endpoint (§6.4) — verify with the curl check, and inspect `docker-compose logs keycloak` on failure.
- OpenLDAP LDIF sensitivity (spec Gap 6 + Areas-of-Care #2). Including the base DN entry, or ordering user entries before their parent OUs, silently breaks the bootstrap. The §6.5 "5 entries" count is the canonical live check that the full LDIF loaded.
- SQL string escaping in the seed policy (spec §3.1 warning). The doubled single quotes inside the embedded YAML are easy to mangle; a single broken quote breaks the entire init.sql and the §6.2 policy SELECT fails. Transcribe the seed INSERT exactly.
- Validation split: most §6 checks require a live Docker stack (Chunk 5). The test-suite-generator can still write meaningful pre-implementation tests against the STATIC artifacts: shared-library imports + Pydantic model behavior (§6.6, Chunk 2), SQL parse + structural assertions on init.sql, conf-directive assertions on redis.conf (Chunk 3), JSON-validity + structural assertions on the realm export, LDIF-validity + ordering assertions on bootstrap.ldif (Chunk 4), and YAML-validity + service/volume/network presence on docker-compose.yml (Chunk 5). The curl/psql/redis-cli/ldapsearch checks are integration-time and run when the stack is up.
- Scope discipline (spec §7): NO service app code or Dockerfiles inside services/, NO dashboard/, NO monitoring, NO Alembic, NO tests/ dirs, NO CI/CD, NO Makefile, NO docker-compose profiles/overrides, NO pre-created Redis streams/consumer groups. Do not create `config/normalization.yaml` content (Spec 2) or `scripts/train_bootstrap_model.py` content (Spec 3) or the random_forest.pkl artifact (Spec 3).
