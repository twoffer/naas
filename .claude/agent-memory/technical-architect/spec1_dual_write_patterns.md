---
name: spec1-dual-write-patterns
description: Event Ingestion (Spec 1) dual-write order, failure semantics, and the created_at ORM trap
metadata:
  type: project
---

Event Ingestion Service (Spec 1) dual-write contract and a recurring ORM trap.

**Dual-write order (spec §5.5, ⚠️ CRITICAL):** PG persist + explicit `await session.commit()` FIRST (point of no return), THEN publish to `login_events` stream. Commit fail → propagate (5xx, nothing in pipeline). Publish fail AFTER commit → catch-and-log with `event_id`, STILL return 202, NEVER roll back. Bulk = one all-or-nothing PG transaction (`add_all` + single commit), then per-event best-effort publish.

**created_at trap:** `LoginEventRecord` carries a Python-side `created_at` (default_factory), but the `events` table owns `created_at` via DB `CURRENT_TIMESTAMP` / `server_default=func.now()`. The PG adapter's `_to_orm` MUST leave the ORM `created_at` UNSET (do not copy `record.created_at`) so the server_default fires. Same for `normalized_attributes`/`enriched_signals` — left NULL for downstream stages. The record's created_at is only used in the published wire payload (slight skew from DB value is acceptable; DB is authoritative).

**Why:** Setting created_at app-side would override the DB default and break the "ingestion timestamp from DB" contract (§3.1). This trap applies to any service that builds an ORM row from a Pydantic record where the DB owns a default column.

**How to apply:** When planning any PG-writing service, map only request/identity fields into the ORM; leave DB-default and downstream-owned columns unset. Cross-ref [[event-ingestion-orm-matches-init-sql]].

**Wire payload:** publish `record.model_dump(mode="json")` (NOT the ORM) via shared `publish_to_stream(STREAM_LOGIN_EVENTS, ...)`. Includes id + present-but-null normalized/enriched/created_at. The `id` is the downstream correlation key and MUST be present (§3.2).
