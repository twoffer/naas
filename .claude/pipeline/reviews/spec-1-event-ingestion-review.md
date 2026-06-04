# Code Security Review — Spec 1: Event Ingestion Service

Append-only audit trail of code-security-reviewer invocations for this spec (CONTRACTS.md §8).

## Chunk 1 — Iteration 1 — PASS — 2026-06-04T14:20:24Z

**Files reviewed (7):** `services/event-ingestion/Dockerfile`, `requirements.txt`, `app/__init__.py`, `app/main.py`, `shared/naas_shared/schemas.py`, `.dockerignore`, `docker-compose.yml` (event-ingestion entry only).

**Overall verdict:** PASS — Critical: 0, High: 0, Medium: 0, Low: 0.

**Scope/boundary compliance:** PASS. Only the seven in-scope files changed. No `do_not_touch` path modified — other service dirs, `services/event-ingestion/README.md`, other `shared/naas_shared/*` modules, `infrastructure/` (events DDL untouched), and `docs/` all unchanged. `shared/naas_shared/schemas.py` received only `Base` + `EventORM`; `docker-compose.yml` received only the new service entry.

**ORM mapping correctness:** `EventORM` mirrors the `events` DDL in `infrastructure/postgres/init.sql` exactly — all 13 columns match on name, type, nullability (`user_agent` unbounded `String` ≈ `TEXT`; `created_at` uses `server_default=func.now()` so the DB owns the value per spec §3.1; `id` app-side `uuid4` per spec §3.1). No `Base.metadata.create_all`, no migrations, no DDL alteration. CHECK constraints on `protocol`/`source` intentionally omitted from the read/write mapping (DB- and Pydantic-enforced; table must not be altered).

**Dockerfile / build pattern:** Option A repo-root context, `shared/` copied + `pip install -e` before service deps/code (best layer caching), `EXPOSE 8001`, correct uvicorn CMD, `python:3.12-slim` base, no secrets baked in. Correctly establishes the pattern for later services.

**requirements.txt:** service-direct deps only (`fastapi>=0.115`, `uvicorn[standard]>=0.30`); data-layer deps come transitively via `naas_shared`.

**app/main.py skeleton:** `create_app()` calls `setup_logging("event-ingestion")`, exposes module-level `app`; `/health` stub returns valid `HealthResponse`. No `/events/*` endpoints, no Redis consumer groups (producer-only), no auth — all appropriate to scaffold scope per spec §7.

**.dockerignore:** matches spec §5.8 exactly; excludes `.env` so no secrets enter the build context.

**docker-compose.yml:** only the new `event-ingestion` entry added; postgres/redis/keycloak/openldap unchanged. Matches spec §5.8 — repo-root build context, `env_file: .env`, `${EVENT_INGESTION_PORT:-8001}:8001`, `depends_on` health conditions, `/health` healthcheck, no runtime `shared/` volume mount (consistent with commit bc843d4).

**Blocking issues:** None.

**Recommended improvements (non-blocking):**
1. `services/event-ingestion/app/main.py:8` — docstring references "Chunk 3" for the real readiness probe; align the chunk number when the real `/health` lands. Doc-only, harmless.

## Chunk 2 — Iteration 1 — PASS WITH NOTES — 2026-06-04T14:35:29Z

**Files reviewed (4):** `services/event-ingestion/app/{ports.py, schemas.py, adapters.py, service.py}`.

**Overall verdict:** PASS WITH NOTES — Critical: 0, High: 0, Medium: 0, Low: 2 (both [Quality], non-blocking). No blocking issues — gate passes.

**Scope/boundary compliance:** PASS. Only the four in-scope files changed. `main.py` remains the chunk-1 skeleton (do_not_touch respected); Dockerfile/requirements.txt/.dockerignore/docker-compose.yml unchanged; no `shared/naas_shared/*` or other-service modifications.

**Dual-write order & failure semantics (spec §5.5 — security-critical), verified exactly:**
- Order: `persist` (explicit `await session.commit()` = point of no return) precedes `_safe_publish` in both `ingest_one` and `ingest_many`.
- Persist-failure propagation: neither `ingest_one`/`ingest_many` nor `persist`/`persist_many` catch exceptions, so a commit failure propagates → 5xx, nothing published (§5.5 step 3).
- `_safe_publish` wraps ONLY `publisher.publish(record)` — it cannot swallow a persist failure. On publish failure it logs structured with `event_id=str(record.id)` and `exc_info=True`, does NOT re-raise, does NOT roll back → 202 still returned (§5.5 step 4).
- Bulk: `persist_many` = single `add_all` + single `commit` (all-or-nothing), then per-record best-effort `_safe_publish` loop so one record's publish failure does not block the rest.
- `LoginEventRecord(**event.model_dump())` assigns `id` app-side (uuid4 default), so the same `id` reaches PG and the stream.

**ORM mapping (`_to_orm`):** maps only request-derived fields + `id`; leaves `normalized_attributes`, `enriched_signals`, `created_at` UNSET → NULL / DB `server_default` (spec §3.1, §7). Correct.

**Injection surface:** `RedisEventPublisher.publish` uses the shared `publish_to_stream(STREAM_LOGIN_EVENTS, record.model_dump(mode="json"))` (json.dumps + parameterized xadd) — no hand-rolled XADD, no string interpolation; `raw_attributes` passes through opaquely (spec §2.3, §7).

**Module isolation:** `app/schemas.py` imports only `typing.Literal`, `uuid.UUID`, `pydantic.BaseModel` — no ORM symbols, no import from `naas_shared.schemas` (spec §1 callout). Correct.

**Logging hygiene:** only `event_id` (UUID, non-sensitive) + static message + traceback logged; no payloads/IPs/tokens/`raw_attributes`.

**LOW / non-blocking quality notes (not counted as security issues):**
1. `service.py:29` — `logger: object` is an imprecise type hint (`object` has no `.error()`); prefer a structlog logger type or `typing.Any`. Spec's exemplary code is untyped here, so this is a quality nit.
2. `adapters.py` (informational) — adapters rely on structural Protocol conformance rather than declared inheritance; fine with `typing.Protocol`, no change needed.

## Chunk 3 — Iteration 1 — NEEDS CHANGES — 2026-06-04T14:50:55Z

**Files reviewed (2):** `services/event-ingestion/app/routes.py` (new), `services/event-ingestion/app/main.py` (modified).

**Overall verdict:** NEEDS CHANGES — Critical: 0, High: 0, Medium: 1, Low: 0. One blocking issue → gate FAIL.

**Scope/boundary compliance:** PASS. Only `routes.py` (new) and `main.py` (modified) changed; chunk-2 files (`ports.py`, `service.py`, `adapters.py`, `schemas.py`) unmodified; no `do_not_touch` path touched.

**Verified correct:**
- Endpoint surface (spec §7): exactly three routes (`/events/ingest`, `/events/bulk`, `/health`); no auth/JWT, no rate limiting, no extra endpoints, no consumer groups (producer-only).
- Thin handlers (spec §5): `ingest_one`/`ingest_many` delegate entirely to `IngestionService`; no dual-write logic inlined.
- Input validation/fail-safe: validation rides the shared `LoginEventIngest` model (octet-bounded IPv4 regex, `protocol` Literal) → 422; bulk bounds via `Annotated[list[...], Body(min_length=1, max_length=5000)]` reject empty/oversized before the handler — no invalid event reaches the dual-write.
- `/health` status logic (spec §5.6): both OK → healthy; Redis down + PG OK → degraded; PG down → unhealthy; HTTP always 200. Correct. Redis uses the shared singleton (`get_redis`) + `ping()` — no per-poll resource.
- `main.py`: chunk-1 `/health` stub removed (no duplicate route); `setup_logging` and module-level `app = create_app()` preserved; lifespan warms Redis only, creates no consumer groups; `get_ingestion_service` re-export benign.
- Injection/hygiene: `text("SELECT 1")` static literal, no interpolation; no secrets logged.
- Module-attribute references (`_db_mod`/`_redis_mod`) are intentional (so `naas_shared.*` patches take effect) and not themselves the cause of the leak.

**BLOCKING issue (Medium) — `routes.py:86-90`, `/health` async-generator session leak on PG-down path:**
`get_db_session` is an async-generator dependency holding the session inside `async with factory() as session:`, releasing it only when driven to completion or explicitly closed. In the happy path `async for` drives the generator to `StopAsyncIteration`, so cleanup runs — no leak. But when `session.execute(text("SELECT 1"))` raises (PG down), the exception propagates out of the `async for` body and is swallowed by `except Exception: pg_ok = False`. Python does NOT auto-close an async iterator when its loop body raises; the generator is left suspended at the `yield`, still inside `async with`, holding a checked-out pooled connection until non-deterministic async-gen GC finalization. With the healthcheck polling every 10s during a PG outage, each poll orphans a connection (pool_size=5, max_overflow=10) → plausible pool exhaustion exactly when the probe must keep answering. Tests pass because the health fakes patch `get_db_session` with a connection-less generator — the leak only manifests against a live session on the failure path.
**Fix (reviewer-supplied):** bind the generator and guarantee close on all paths:
```python
pg_ok = True
agen = _db_mod.get_db_session()
try:
    session = await agen.__anext__()
    await session.execute(text("SELECT 1"))
except Exception:
    pg_ok = False
finally:
    await agen.aclose()
```

**Recommended improvement (non-blocking):**
1. `main.py:24-27` — add a debug-level log line in the lifespan Redis-warm `except` instead of a bare `pass`, for operability.

## Chunk 3 — Iteration 2 — PASS — 2026-06-04T14:54:34Z

**Re-review after the iteration-1 fix.** Files: `services/event-ingestion/app/routes.py` (health PG-check block), `services/event-ingestion/app/main.py` (lifespan debug log).

**Overall verdict:** PASS — Critical: 0, High: 0, Medium: 0, Low: 0. The iteration-1 blocking leak is fully resolved.

**Leak fix verified — `routes.py:85-93`:** the PG `SELECT 1` check binds the async generator to `agen`, drives it with `await agen.__anext__()`, and closes it via `await agen.aclose()` in a `finally`. Deterministic teardown on all three paths:
- Success: `aclose()` throws `GeneratorExit` (a `BaseException`, not caught by the dependency's `except Exception`), so `async with factory()` exits cleanly and returns the connection to the pool. (`session.commit()` is skipped — fine, `SELECT 1` is read-only.)
- `__anext__()` raises (PG down at session entry): generator already finished; `aclose()` is a no-op.
- `execute()` raises (PG down mid-query): `aclose()` unwinds the `async with`, releasing the session/connection.
No suspended generator or checked-out connection survives a poll.

**No behavior change:** decision table unchanged (PG-down → unhealthy; Redis-down+PG-OK → degraded; both-OK → healthy; HTTP 200; `service="event-ingestion"`). `_db_mod`/`_redis_mod` module-attribute access preserved (test patches remain effective). Redis check uses the shared singleton and correctly does not close it.

**`main.py:24-30`:** lifespan Redis-warm `except` now logs at debug level (via `get_logger`); failure stays non-fatal; no consumer groups created (spec §5.7, §7). Benign.

**Scope:** changes confined to `routes.py` (health block) and `main.py` (lifespan log). No chunk-1/2 files, no `shared/naas_shared/*`, no other service, no `infrastructure/`/`docs/`, no Dockerfile/compose/requirements, no test files modified.

**Blocking issues:** None. **Recommended improvements:** None.
