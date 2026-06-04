# Integration Validation Report — Spec 1: Event Ingestion Service

Append-only record of integration-validator invocations for this spec (CONTRACTS.md §9).

## Validation Run 1 — FAIL — 2026-06-04T14:58:42Z

**Scope:** Spec 1 Section 6 criteria, against live PostgreSQL + Redis (no mocks). Branch `feature/spec-1-event-ingestion`. Image built fresh with `docker compose ... --build`.

**Verdict: FAIL** — one blocking defect.

### Level 1 — Infrastructure Health (all PASS)
- Containers `naas-postgres`, `naas-redis`, `naas-event-ingestion` all healthy (deps gated via `service_healthy`).
- PostgreSQL: `events` table present; `timestamp` is `TIMESTAMP WITHOUT TIME ZONE`; `normalized_attributes`/`enriched_signals` nullable JSONB.
- Redis: `PING → PONG`.
- Shared import inside container resolves; `database_url` = `postgresql+asyncpg://naas:...@postgres:5432/naas`.
- `GET /health` → `{"status":"healthy","service":"event-ingestion","version":"2.0.0",...}` HTTP 200.

### Level 2 — Section 6 Criteria
- **Crit 1 — Single ingest (spec example body, `"timestamp":"2026-06-03T14:05:00Z"`): FAIL** → HTTP 500 `Internal Server Error`. No PG row, no stream message (fail-safe held). Same 500 with `+00:00`. With a **naive** timestamp (`...T14:05:00`) → 202 `{"id":...,"status":"accepted"}`.
- **Crit 2 — PostgreSQL row (naive-ts event): PASS** — exactly one row, `normalized_attributes`/`enriched_signals` NULL, metadata present.
- **Crit 3 — Redis stream correlatable: PASS** — `XLEN` rose; newest message single `data` field, JSON `id` == row `id`; payload carries `id`, null normalized/enriched, full metadata.
- **Crit 4 — Bulk (bare 3-array): PASS** — 202 `{"accepted":3,...}`, PG +3, `XLEN` +3; 5000-element boundary → 202.
- **Crit 5 — Health: PASS** — healthy when both up; `degraded` (HTTP 200) when Redis stopped while PG up; recovers to healthy.
- **Crit 6 — Validation rejection (writes nothing): PASS** — `client_ip:256.0.0.1` → 422; `protocol:kerberos` → 422; empty bulk `[]` → 422; bulk length 5001 → 422. Net PG/stream delta after rejections + one valid 5000-batch was exactly 5000.

### Blocking issue — HTTP 500 on timezone-aware timestamps
**Seam:** event-ingestion ↔ PostgreSQL (`naas_shared.models` ↔ `naas_shared.schemas.EventORM` ↔ `events` DDL).
**Evidence (service logs):** `asyncpg.exceptions.DataError: invalid input for query argument $6: datetime.datetime(2026, 6, 3, 14, 5, tzinfo=TzInfo(0)) ... can't subtract offset-naive and offset-aware datetimes`.
**Root cause:** `LoginEventIngest`/`LoginEventRecord` parse a `Z`/offset timestamp into a **tz-aware** `datetime`; `EventORM.timestamp` maps to `TIMESTAMP WITHOUT TIME ZONE`; asyncpg refuses to bind an aware datetime into a naive column.
**Impact:** Spec §2.1 example and §6.1 command both use `"...Z"` and §2.1 says "Submit UTC" — the canonical documented input is rejected. Upstream callers (gateway, simulator) sending ISO-8601 UTC with offset would all 500. Fail-safe (spec §5.5 #3) is correct: nothing persisted/published, 5xx returned.

### Recommendations
1. **feature-implementer (in-scope app-side fix):** normalize the timestamp to naive-UTC before the ORM insert — convert aware → UTC then drop tzinfo in the `LoginEventRecord`→`EventORM` mapping in `app/adapters.py`. DB schema is owned by the infra init script, so no DDL change. Re-run §6 Crit 1–3 with the literal spec example body afterward.
2. **technical-architect (optional follow-up):** decide whether `events.timestamp` should become `TIMESTAMPTZ` project-wide, since every downstream stage correlates on these records and will hit the same mismatch.

### Caveats
- `docker-compose` binary absent; used the `docker compose` plugin. Not a service defect.
- All non-Crit-1 behaviors verified via naive-timestamp inputs (the tz-aware path 500s before reaching them); dual-write/bulk/validation logic themselves are sound.

**Environment left running** (event-ingestion healthy); no volumes deleted.

## Validation Run 2 — PASS — 2026-06-04T19:51:00Z

**Re-validation after the developer's fix** (commits `18f4388` TIMESTAMPTZ, `056be17` end-to-end UTC normalization). Full Section 6 checklist on a freshly-initialized schema.

**Verdict: PASS** — all applicable criteria verified against live infra, including the previously-failing tz-aware path.

### Pre-run setup (mandatory wipe)
- `docker compose down -v` removed stale `naas_postgres-data` (old naive-`TIMESTAMP` schema) and `naas_redis-data`.
- `docker compose up -d --build event-ingestion` rebuilt the image and re-initialized Postgres from `infrastructure/postgres/init.sql` on an empty data dir.

### Level 1 — Infrastructure (all PASS)
- Containers healthy; `information_schema` confirms `events.timestamp` and `events.created_at` are both `timestamp with time zone` on the fresh volume.
- Redis `PING → PONG`, baseline `XLEN login_events = 0`. Shared import inside container clean. `/health` → healthy.

### Level 2 — Section 6 (all PASS)
- **Crit 1 — Single ingest (regression fixed):** literal spec body `"2026-06-03T14:05:00Z"` (the Run-1 500 case) → **202**, id `24c113a2-...`; `+00:00`, naive, and `+05:00` variants all → 202.
- **Crit 2 — PG rows:** all ids present, `normalized_attributes`/`enriched_signals` NULL. Literal-spec row stores `timestamp = 2026-06-03 14:05:00+00`; `Z`/`+00:00`/naive collapse to one instant; `+05:00` → `09:05:00+00` (correct conversion).
- **Crit 3 — Redis stream:** `XLEN = 4`; each message single `data` field, JSON `id` matches its PG row; stream timestamp text agrees with PG UTC instant (literal → `"2026-06-03T14:05:00Z"`; `+05:00` event → `"2026-06-03T09:05:00Z"`).
- **Crit 4 — Bulk:** bare 3-array → 202 `{"accepted":3,...}`; PG +3, `XLEN` +3.
- **Crit 5 — Health:** healthy (HTTP 200); degraded (HTTP 200) when Redis stopped while PG up; recovers.
- **Crit 6 — Validation rejection (writes nothing):** `256.0.0.1` → 422; `kerberos` → 422; empty bulk → 422; length 5001 → 422; 5000-boundary → 202. Net counter check confirms 422s wrote nothing.
- No `error`/`exception`/`DataError`/`500` log lines during the run.

### Non-blocking caveats
1. `HealthResponse.timestamp` is serialized without a `Z`/offset suffix, unlike event timestamps in the stream (which carry `Z`). Cosmetic — `/health` is a readiness probe, not pipeline data — but inconsistent with the otherwise UTC-explicit serialization.
2. Test data left in DB: `events` ~5007 rows, `login_events` `XLEN=5007`. Local dev data only; downstream specs starting fresh may want a clean volume.

**Environment left up and healthy** (naas-postgres, naas-redis, naas-event-ingestion). Volumes wiped only once pre-run, not after.
