---
name: naas-shared-structure
description: Canonical naas_shared module layout, pipeline models, and Spec-0 placeholder discipline (verified against SPEC_0 §3.3-3.8, 5.4)
metadata:
  type: reference
---

`shared/naas_shared/` is the keystone library every NAAS service imports. Canonical contract is `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` §§3.3–3.8, 5.4. Downstream specs MUST NOT redefine these.

## Modules
- `constants.py` — stream/channel/group names + cache TTLs (§3.3). Streams: `login_events`, `normalized_events`, `enriched_events`; STREAM_MAXLEN=10000. Channels: `decisions`, `alerts`. Groups: `normalization_workers`, `enrichment_workers`, `evaluator_workers`.
- `config.py` — pydantic-settings `Settings`; `get_settings()` is `@lru_cache`d. `database_url` (postgresql+asyncpg), `database_url_sync` (postgresql) are properties. Uses `model_config = SettingsConfigDict(extra="ignore")` (v2 idiom; older memory said `Settings.Config`) because the committed `.env` carries many vars (KEYCLOAK_ADMIN, LDAP_*, *_PORT, DASHBOARD_*, OLLAMA_*) not declared as fields — pydantic-settings v2 rejects undeclared env-file keys otherwise. `ignore` (not `allow`) is correct: undeclared secrets are dropped, not absorbed. Dev-default secrets (postgres_password, ldap_admin_password) carry `# noqa: S105` with a "local-dev/compose default" rationale — documented in SECURITY.md, intentional, NOT a finding. `llm_model` default is `claude-sonnet-5` (pre-public model-id refresh).
- `models.py` — canonical pipeline schemas (§3.4): LoginEventBase/Ingest/Record, NormalizedAttributes, RiskDecision, AlertMessage, HealthResponse. Two discriminated unions: `ResolutionDetail` (discriminator `resolution`: unanimous|priority|single_source|list_merge), `EnrichmentMetadata` (discriminator `applied`: True→EnrichmentApplied, False→EnrichmentSkipped). `client_ip` is a STRICT 0-255-octet IPv4 regex (not `\d{1,3}`); Pydantic v2 `pattern` runs on the Rust regex engine → linear-time, no ReDoS. INPUT CAPS (pre-public DoS hardening): `user_id` max_length=255, `user_agent` max_length=2048, `raw_attributes: dict[str,Any]` `max_length=200` (bounds KEY COUNT only — value byte-size + nesting remain unbounded, and Pydantic validates AFTER full body parse; no ASGI/proxy body-size limit exists → residual pre-parse DoS on the unauthenticated ingestion port). `NormalizedAttributes.enrichment` is REQUIRED (even LDAP events carry EnrichmentSkipped skip_reason="ldap_event"). Timestamp defaults are aware-UTC via `_to_utc` helper + `@field_validator(..., mode="after")` on `timestamp`/`created_at`; no `utcnow` remains. Not a security issue.
- `middleware.py` (added pre-public) — `CorrelationIdMiddleware`, a PURE ASGI middleware (not Starlette BaseHTTPMiddleware, so bound contextvars reach the handler). Reads inbound `x-request-id`, else mints `uuid4().hex`; binds `correlation_id` via structlog contextvars; echoes on response; clears context in `finally`. SECURITY: inbound id vetted by `_SAFE_ID = [A-Za-z0-9._-]{1,128}` + `fullmatch` → CRLF/response-splitting-proof, length-bounded, log-forgery-proof; anything failing → fresh UUID. correlation_id is a debug aid only (pipeline correlation uses server-assigned `event_id`), so client-controlled echo has no security impact. Thoroughly tested in `tests/shared/test_correlation_middleware.py` (CRLF, 128/129 boundary, control chars, context-clear-on-raise). Clean.
- `database.py` — async SQLAlchemy engine/session singletons; `get_db_session` commits on clean exit, rolls back on exception. No string-interpolated SQL.
- `redis_client.py` — `redis.asyncio` (aliased aioredis), `decode_responses=True`. `publish_to_stream`/`publish_to_channel` use `json.dumps` (safe). `ensure_consumer_group` swallows only BUSYGROUP, re-raises others (correct fail-closed).
- `logging.py` — structlog JSON config with `merge_contextvars` (so the middleware's `correlation_id` reaches every log line). `get_logger(name: str | None = None)` — type hint now correct (older memory flagged `str = None`; fixed).
- `schemas.py` — was a Gap-5 placeholder pre-Spec-1; Spec 1 (commit 0938bf8) populated `EventORM` (events table mapping). Imported by services as the contract; downstream specs must NOT redefine/migrate it.
- `ml_features.py` / `simulation_tools.py` — deferral-comment-only placeholders (Spec 3 / later spec own real content). Must NOT fabricate FEATURE_COLUMNS / TOOL_DEFINITIONS.

## Packaging (§5.4)
- `shared/pyproject.toml`: name `naas-shared`, version `2.0.0`, requires-python `>=3.12`, deps fastapi/pydantic/pydantic-settings/sqlalchemy[asyncio]/asyncpg/redis/structlog. `[tool.setuptools.packages.find]` include `naas_shared*`.
- `*.egg-info/` from `pip install -e` is a gitignored build artifact, not a source change.

## Spec-0 scope
- "What NOT to Build" (§7): no service app code, no ORM models yet, no Alembic/CI/monitoring, no pre-created Redis streams/groups.
