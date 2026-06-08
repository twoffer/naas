---
name: naas-shared-structure
description: Canonical naas_shared module layout, pipeline models, and Spec-0 placeholder discipline (verified against SPEC_0 §3.3-3.8, 5.4)
metadata:
  type: reference
---

`shared/naas_shared/` is the keystone library every NAAS service imports. Canonical contract is `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` §§3.3–3.8, 5.4. Downstream specs MUST NOT redefine these.

## Modules
- `constants.py` — stream/channel/group names + cache TTLs (§3.3). Streams: `login_events`, `normalized_events`, `enriched_events`; STREAM_MAXLEN=10000. Channels: `decisions`, `alerts`. Groups: `normalization_workers`, `enrichment_workers`, `evaluator_workers`.
- `config.py` — pydantic-settings `Settings`; `get_settings()` is `@lru_cache`d. `database_url` (postgresql+asyncpg), `database_url_sync` (postgresql) are properties. NOTE: `Settings.Config` must include `extra = "ignore"` because the committed `.env` carries many vars (KEYCLOAK_ADMIN, LDAP_*, *_PORT, DASHBOARD_*, OLLAMA_*) not declared as fields — pydantic-settings v2 rejects undeclared env-file keys otherwise. `ignore` (not `allow`) is correct: undeclared secrets are dropped, not absorbed.
- `models.py` — canonical pipeline schemas (§3.4): LoginEventBase/Ingest/Record, NormalizedAttributes, RiskDecision, AlertMessage, HealthResponse. Two discriminated unions: `ResolutionDetail` (discriminator `resolution`: unanimous|priority|single_source|list_merge), `EnrichmentMetadata` (discriminator `applied`: True→EnrichmentApplied, False→EnrichmentSkipped). `client_ip` regex `^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$`. `NormalizedAttributes.enrichment` is REQUIRED (even LDAP events carry EnrichmentSkipped skip_reason="ldap_event"). Timestamp defaults are aware-UTC: `default_factory=lambda: datetime.now(timezone.utc)` plus `@field_validator(..., mode="after")` on `timestamp`/`created_at` (LoginEventBase/Record) — the post–Spec 1 UTC-pin followup (commit 1410a50) replaced the original `datetime.utcnow`; no `utcnow` remains. Not a security issue.
- `database.py` — async SQLAlchemy engine/session singletons; `get_db_session` commits on clean exit, rolls back on exception. No string-interpolated SQL.
- `redis_client.py` — `redis.asyncio` (aliased aioredis), `decode_responses=True`. `publish_to_stream`/`publish_to_channel` use `json.dumps` (safe). `ensure_consumer_group` swallows only BUSYGROUP, re-raises others (correct fail-closed).
- `logging.py` — structlog JSON config. `get_logger(name: str = None)` — `= None` default on a `str`-typed param is a minor type-hint imprecision (should be `Optional[str]`), transcribed from spec.
- `schemas.py` — was a Gap-5 placeholder pre-Spec-1; Spec 1 (commit 0938bf8) populated `EventORM` (events table mapping). Imported by services as the contract; downstream specs must NOT redefine/migrate it.
- `ml_features.py` / `simulation_tools.py` — deferral-comment-only placeholders (Spec 3 / later spec own real content). Must NOT fabricate FEATURE_COLUMNS / TOOL_DEFINITIONS.

## Packaging (§5.4)
- `shared/pyproject.toml`: name `naas-shared`, version `2.0.0`, requires-python `>=3.12`, deps fastapi/pydantic/pydantic-settings/sqlalchemy[asyncio]/asyncpg/redis/structlog. `[tool.setuptools.packages.find]` include `naas_shared*`.
- `*.egg-info/` from `pip install -e` is a gitignored build artifact, not a source change.

## Spec-0 scope
- "What NOT to Build" (§7): no service app code, no ORM models yet, no Alembic/CI/monitoring, no pre-created Redis streams/groups.
