---
name: patterns_utc_timestamp_defense
description: Defense-in-depth pattern for pinning events-table timestamps to UTC — Pydantic validator + ORM DateTime(timezone=True) + engine connect_args
metadata:
  type: project
---

Three-layer UTC timestamp pinning pattern used for the `events` table (applied in the UTC-pin fix task):

1. **Pydantic validator on `LoginEventBase`** — `@field_validator("timestamp", mode="after")` normalizes
   naive datetimes to UTC (`replace(tzinfo=timezone.utc)`) and converts aware datetimes to UTC
   (`astimezone(timezone.utc)`). This is the app-boundary guard.

2. **ORM `DateTime(timezone=True)`** — both `timestamp` and `created_at` on `EventORM` use
   `mapped_column(DateTime(timezone=True), ...)`. asyncpg returns aware datetimes for TIMESTAMPTZ
   columns; naive `DateTime` would drop zone info on read.

3. **Engine `connect_args`** — `create_async_engine(..., connect_args={"server_settings": {"timezone": "UTC"}})`
   pins the Postgres session timezone at the connection level. Prevents a non-UTC session TZ from
   silently shifting naive timestamps that slip past the validator.

**Scope note:** Only the `events` table uses this pattern. The other four tables (`users`, `policies`,
`risk_assessments`, `alerts`) retain `TIMESTAMP` / naive `DateTime` for their `created_at` columns —
do not change them unless explicitly in scope.

**Related models scope:** `RiskDecision.timestamp`, `AlertMessage.timestamp`, and
`HealthResponse.timestamp` in `naas_shared/models.py` were explicitly out of scope for this fix.
`HealthResponse.timestamp` still uses `datetime.utcnow` and will emit a DeprecationWarning — a
pre-existing issue outside the events-table scope.

**Pre-existing test failures:** Five Spec 0 tests fail because the event-ingestion service has been
fully implemented (Spec 1), making those scaffold-phase assertions stale. These are not regressions.
