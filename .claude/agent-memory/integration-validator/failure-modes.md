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

## What works correctly in Spec 1 event-ingestion (verified)
- Dual-write mechanics with naive ts: PG row (normalized_attributes/enriched_signals
  NULL), stream `login_events` single `data` field, JSON `id` == row `id`.
- Bulk bare-array: 202, accepted:N, +N rows, +N stream msgs. 5000 boundary = 202.
- Validation 422s: bad IP (256.0.0.1), bad protocol (kerberos), empty bulk,
  bulk>5000 — all 422 and write nothing.
- Health: PG+Redis ok -> healthy; redis down -> degraded (HTTP 200); recovers.
