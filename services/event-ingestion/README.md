# Event Ingestion Service

Accepts login events over REST, validates them, and **dual-writes** each event to PostgreSQL (the durable system of record) and the Redis `login_events` stream (the pipeline trigger) — returning immediately so ingestion never blocks on downstream work.

**Status:** implemented and integration-validated end-to-end. Implements [`SPEC_1_Event_Ingestion_Service`](../../docs/architecture/SPEC_1_Event_Ingestion_Service.md); see [`docs/architecture/SYSTEM_ARCHITECTURE.md`](../../docs/architecture/SYSTEM_ARCHITECTURE.md) for the surrounding system.

## Responsibilities

- **Validate** every incoming event against the Pydantic `LoginEventIngest` schema before it touches a datastore.
- **Dual-write** per event: a durable row in the PostgreSQL `events` table, then a message onto the Redis `login_events` stream. The HTTP response returns as soon as the durable write completes, decoupling ingestion from the async normalization → enrichment → risk pipeline. The stream publish is best-effort — a publish failure is logged, not surfaced to the caller, since the committed row is the source of truth.
- **Tag** every event with its pipeline metadata: `source` (`user`/`simulator`/`api`), `is_synthetic`, `is_historical`, and `protocol` (`oidc`/`saml`/`ldap`).
- **Report real readiness** — the health probe distinguishes `healthy` / `degraded` / `unhealthy` by live dependency state rather than always returning `200 OK`.

## API

Exactly three endpoints (no others are mounted). **Port `8001`.**

| Method & path | Purpose | Success response |
|---|---|---|
| `POST /events/ingest` | Ingest a single login event | `202 Accepted` → `{"id": "<uuid>", "status": "accepted"}` |
| `POST /events/bulk` | Ingest a bare JSON array of **1–5000** events in one all-or-nothing transaction | `202 Accepted` → `{"accepted": <n>, "event_ids": [...], "status": "accepted"}` |
| `GET /health` | Readiness probe (table below) | `200` always; operational status in the body |

A bulk array outside the 1–5000 range is rejected by FastAPI with `422` before the handler runs.

**Health decision table** (HTTP status is always `200`; the operational status is in the body):

| PostgreSQL | Redis | Reported status |
|---|---|---|
| reachable | reachable | `healthy` |
| reachable | unreachable | `degraded` — events still persist; the stream publish will fail |
| unreachable | — | `unhealthy` — no new events can be accepted |

## Internals (hexagonal — ports & adapters)

Route handlers translate HTTP only; the dual-write logic lives in a domain service that depends on typed `Protocol` ports, never on concrete infrastructure (see [ADR-0009](../../docs/adr/0009-hexagonal-service-architecture.md)).

- `app/routes.py` — the three endpoints; wires the adapters to the service via FastAPI `Depends`.
- `app/service.py` — `IngestionService`: the dual-write domain logic.
- `app/ports.py` — `EventRepository` (persist / persist_many) and `EventPublisher` (publish) ports.
- `app/adapters.py` — `PostgresEventRepository` + `RedisEventPublisher` (the concrete adapters).
- `app/schemas.py` — the `202` response models.
- `app/main.py` — composition root (`uvicorn app.main:app`); warms Redis on startup, disposes connections on shutdown.

**Tests:** [`tests/services/event_ingestion/`](../../tests/services/event_ingestion/) (unit) and [`tests/integration/test_event_ingestion_live.py`](../../tests/integration/test_event_ingestion_live.py) (live, against the running stack).

## Run

The service starts with the rest of the stack via `docker compose up -d --build` from the repo root. See the root [`README.md`](../../README.md) for the full quick start and a worked `curl` example.
