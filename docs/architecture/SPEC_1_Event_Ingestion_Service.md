# Spec 1: Event Ingestion Service

**Service:** `event-ingestion` · **HTTP port:** `8001` · **Pipeline position:** first stage (entry point).

The Event Ingestion Service is the front door of the NAAS pipeline. It exposes a small REST API that accepts login events (from the API gateway, the persona simulator, or direct API callers), assigns each event a durable identity, and performs a **dual-write**: it persists the event to the PostgreSQL `events` table (the system of record) and then publishes it to the Redis Stream `login_events` (the transport that feeds Identity Normalization). It owns no business logic beyond validation, identity assignment, and the dual-write; it does not interpret event contents.

This spec is consumed by the technical-architect agent to produce the chunked implementation plan, and by the per-chunk implementation agents as the source of truth. Sections marked **⚠️ CRITICAL** are hard requirements: do not deviate. Code blocks are labelled either **[TRANSCRIBE EXACTLY]** (reproduce as written) or **[EXEMPLARY]** (conveys shape and intent; the implementer may adjust details while preserving the stated behaviour).

---

## 1. Scope Boundary

This spec **creates** the following:

```
services/event-ingestion/
├── Dockerfile                  # Option A build (repo-root context); establishes the service-image pattern
├── requirements.in             # service-direct dependency floors (fastapi, uvicorn); data-layer deps owned by naas_shared
├── requirements.txt            # pip-compiled lock (requirements.in + shared/pyproject.toml); full pinned closure (ADR-0012)
└── app/
    ├── __init__.py
    ├── main.py                 # composition root: app factory, lifespan, dependency wiring, router mount
    ├── ports.py                # Protocol definitions: EventRepository, EventPublisher
    ├── service.py              # IngestionService — domain orchestration of the dual-write
    ├── adapters.py             # PostgresEventRepository, RedisEventPublisher
    ├── routes.py               # APIRouter: POST /events/ingest, POST /events/bulk, GET /health
    └── schemas.py              # API response models (IngestAccepted, BulkIngestAccepted)
.dockerignore                   # repo root; created here, reused by all later service builds
```

This spec **modifies** the following (no other shared or cross-service files):

- `shared/naas_shared/schemas.py` — append the SQLAlchemy declarative `Base` and the `EventORM` mapping for the `events` table. **Add only these**; later specs add their own table mappings when first needed.
- `docker-compose.yml` — add the `event-ingestion` service entry. Modify only this new entry; do not touch the infrastructure services.

**Do NOT touch** any other `services/*/` directory, any other `shared/naas_shared/*` module, `infrastructure/`, or `docs/`. The existing `services/event-ingestion/README.md` may remain as-is.

> ⚠️ `services/event-ingestion/app/schemas.py` (API response models) and `shared/naas_shared/schemas.py` (ORM table definitions) are different files with the same basename. Keep them distinct.

---

## 2. Input Contracts

### 2.1 `POST /events/ingest` — single event

Request body is the canonical `LoginEventIngest` model from `naas_shared.models`. **Import it; do not redefine it.** Its fields (for reference — the shared model is authoritative):

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `user_id` | string (1–255) | yes | Identity subject. |
| `client_ip` | string | yes | **IPv4 only.** Validated against the shared model's octet-bounded regex (each octet 0–255). Non-IPv4 or malformed values are rejected with HTTP 422. |
| `protocol` | `"oidc" \| "saml" \| "ldap"` | yes | Drives downstream normalization routing. |
| `timestamp` | datetime (ISO 8601) | yes | Event time. Stored in `events.timestamp` (`TIMESTAMPTZ`, the UTC instant). Submit UTC (e.g. `"...Z"`); timezone-aware values are converted to UTC. Naive (zone-less) submissions are interpreted as UTC by the model validator. |
| `user_agent` | string | no | Pass-through; used downstream for device fingerprinting. |
| `source` | `"user" \| "simulator" \| "api"` | no | Defaults to `"user"`. |
| `is_synthetic` | bool | no | Defaults to `false`. |
| `is_historical` | bool | no | Defaults to `false`. Propagates through the pipeline; historical events must never raise alerts. |
| `raw_attributes` | object | no | Defaults to `{}`. Protocol-specific claims/attributes, **opaque to ingestion** (see 2.3). |

Example (OIDC):

```json
{
  "user_id": "alice",
  "client_ip": "203.0.113.42",
  "protocol": "oidc",
  "timestamp": "2026-06-03T14:05:00Z",
  "user_agent": "Mozilla/5.0 ...",
  "source": "user",
  "raw_attributes": {
    "name": "Alice Anderson",
    "email": "alice@corp.com",
    "groups": ["engineering"],
    "department": "Engineering",
    "employee_type": "FTE"
  }
}
```

### 2.2 `POST /events/bulk` — batch

Request body is a **bare JSON array** of `LoginEventIngest` objects (not wrapped in an envelope). This matches what upstream callers send (e.g. the simulator submits `[event.model_dump(...) , ...]`). The array MUST contain at least 1 and at most **5000** events (the historical-generation ceiling); a larger array is rejected with HTTP 422.

### 2.3 `raw_attributes` is opaque to ingestion

Ingestion validates only the `LoginEventIngest` envelope. It does **not** parse, validate, or reshape `raw_attributes`; that is the Identity Normalization service's job. The per-protocol shapes below are documented so callers know what to send and so the spec is self-contained — ingestion treats the object as an opaque pass-through regardless.

- **OIDC:** `name`, `email`, `groups`, `department`, `employee_type`
- **SAML:** `displayName`, `email`, `dept`, `employeeType`, `groups`
- **LDAP:** `cn`, `sn`, `mail`, `uid`, `departmentNumber`, `employeeType`, `memberOf`

### 2.4 Upstream

Ingestion has no upstream stream or database read. It is the pipeline entry point.

---

## 3. Output Contracts

### 3.1 PostgreSQL — one row per event in `events`

Each accepted event becomes exactly one row in the existing `events` table (DDL owned by the infrastructure init script; **do not redefine or migrate it**). Column mapping:

| `events` column | Source | Notes |
|-----------------|--------|-------|
| `id` (UUID PK) | **assigned by ingestion** | The single event identity. Generated app-side (UUID v4) and inserted explicitly. This is the value every downstream stage correlates on. |
| `user_id`, `protocol`, `client_ip`, `user_agent`, `timestamp`, `source`, `is_synthetic`, `is_historical`, `raw_attributes` | from the request | Direct mapping. `client_ip` (a string) is stored in the `INET` column. |
| `normalized_attributes`, `enriched_signals` | **NULL at ingestion** | Populated by Identity Normalization and Signal Enrichment respectively. Ingestion must leave them NULL. |
| `created_at` | DB default (`CURRENT_TIMESTAMP`) | Ingestion timestamp stored as `TIMESTAMPTZ` (the UTC instant). Do not set it from the app. |

### 3.2 Redis Stream — publish to `login_events`

After the PostgreSQL row is committed (see 5.5), publish the event to the `login_events` stream using the shared helper. **⚠️ CRITICAL — the published payload is the canonical `LoginEventRecord` serialized to JSON, and it MUST carry `id`** (the correlation key downstream uses to locate the row it just read). Use the shared constant `STREAM_LOGIN_EVENTS` and the shared `publish_to_stream` helper — do not hand-roll the XADD.

The helper wraps the payload as a single stream field `data` containing the JSON string. The resulting message therefore looks like:

```
XADD login_events * data '{"id": "f3c1...e9", "user_id": "alice", "protocol": "oidc",
  "client_ip": "203.0.113.42", "timestamp": "2026-06-03T14:05:00", "user_agent": "...",
  "source": "user", "is_synthetic": false, "is_historical": false,
  "raw_attributes": {...}, "normalized_attributes": null, "enriched_signals": null,
  "created_at": "2026-06-03T14:05:01Z"}'
```

`normalized_attributes` and `enriched_signals` are present-but-null at this stage; downstream stages ignore them on the `login_events` stream. Consumers parse the `data` field as JSON and validate it with `LoginEventRecord`.

### 3.3 HTTP responses

- `POST /events/ingest` → **202 Accepted**, body `IngestAccepted`:
  ```json
  { "id": "f3c1...e9", "status": "accepted" }
  ```
- `POST /events/bulk` → **202 Accepted**, body `BulkIngestAccepted`:
  ```json
  { "accepted": 3, "event_ids": ["...", "...", "..."], "status": "accepted" }
  ```
  (The `id`/`event_ids` are the assigned `events.id` values. Upstream callers that only check the status code are unaffected by the body shape; the body exists for direct API use and validation.)
- `GET /health` → **200**, body is the shared `HealthResponse` (see 5.6).
- Validation failures (bad IP, unknown protocol, oversized bulk) → **422** with FastAPI's standard validation error body.

---

## 4. Shared Imports

Import all common infrastructure from `naas_shared`. **Do not reimplement** the DB session, Redis client, models, logging, or config.

```python
# [TRANSCRIBE EXACTLY] — these symbols exist in naas_shared
from naas_shared.models import LoginEventIngest, LoginEventRecord, HealthResponse
from naas_shared.database import get_db_session
from naas_shared.redis_client import get_redis, publish_to_stream
from naas_shared.constants import STREAM_LOGIN_EVENTS
from naas_shared.logging import setup_logging, get_logger
from naas_shared.config import get_settings
# Added to naas_shared by THIS spec (see 5.2), then imported by the adapter:
from naas_shared.schemas import Base, EventORM
```

Notes:
- `get_db_session` is an async generator dependency that yields an `AsyncSession`, commits on clean exit, and rolls back on exception. The dual-write needs an **explicit** commit before publish (see 5.5); the dependency's end-of-request commit then becomes a harmless no-op.
- `publish_to_stream(stream, data)` performs the `XADD` with `maxlen` capping and JSON-encodes `data`. Pass `record.model_dump(mode="json")`.
- `get_redis()` returns the shared singleton async client (used by the health check).

---

## 5. Implementation Requirements

The service follows the project's hexagonal (ports/adapters) structure, applied pragmatically for a small service: domain logic and port Protocols in the core, concrete I/O in adapters, and a thin composition root. **⚠️ Keep the dual-write orchestration in the domain `IngestionService`, not inlined into the route handler** — the route handler only translates HTTP to/from the service.

### 5.1 ORM model — append to `shared/naas_shared/schemas.py`

`shared/naas_shared/schemas.py` is currently an empty placeholder. Replace its placeholder comment with a declarative `Base` and the `EventORM` mapping for the `events` table. **⚠️ The columns MUST mirror the existing `events` DDL exactly** (names, types, nullability). Use SQLAlchemy 2.0 declarative style (consistent with the async engine in `naas_shared.database`).

```python
# [EXEMPLARY — column set/types must match the events DDL exactly; idiom may vary]
from datetime import datetime
from uuid import UUID as PyUUID, uuid4

from sqlalchemy import String, DateTime, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, INET, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EventORM(Base):
    __tablename__ = "events"

    id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)
    client_ip: Mapped[str] = mapped_column(INET, nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_historical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    raw_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    normalized_attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    enriched_signals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

> ⚠️ **CRITICAL — the database schema is owned by the infrastructure init script.** Do NOT call `Base.metadata.create_all(...)`, do NOT add Alembic migrations, and do NOT alter the table. `EventORM` is a read/write mapping over a table that already exists.

### 5.2 Ports — `app/ports.py`

Define the two boundaries the domain depends on, as `typing.Protocol` classes:

```python
# [EXEMPLARY]
from typing import Protocol
from naas_shared.models import LoginEventRecord


class EventRepository(Protocol):
    async def persist(self, record: LoginEventRecord) -> None: ...
    async def persist_many(self, records: list[LoginEventRecord]) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, record: LoginEventRecord) -> None: ...
```

### 5.3 Adapters — `app/adapters.py`

- `PostgresEventRepository(session: AsyncSession)` implements `EventRepository`. `persist` builds an `EventORM` from the record (mapping the fields per 3.1; leave `normalized_attributes`/`enriched_signals`/`created_at` unset), `session.add(...)`, then **`await session.commit()`** (explicit — this is the durability point). `persist_many` `add_all(...)` then a single `commit()` (one transaction for the whole batch).
- `RedisEventPublisher` implements `EventPublisher`. `publish` calls `await publish_to_stream(STREAM_LOGIN_EVENTS, record.model_dump(mode="json"))`.

```python
# [EXEMPLARY — the explicit commit in persist() and persist_many() is required]
class PostgresEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def persist(self, record: LoginEventRecord) -> None:
        self._session.add(_to_orm(record))
        await self._session.commit()

    async def persist_many(self, records: list[LoginEventRecord]) -> None:
        self._session.add_all([_to_orm(r) for r in records])
        await self._session.commit()
```

### 5.4 Domain — `app/service.py`

`IngestionService(repo: EventRepository, publisher: EventPublisher, logger)` orchestrates the dual-write. It is the only place that knows the order and the failure policy.

```python
# [EXEMPLARY — the ORDER and the failure handling are the contract; see 5.5]
class IngestionService:
    def __init__(self, repo, publisher, logger):
        self._repo, self._publisher, self._log = repo, publisher, logger

    async def ingest_one(self, event: LoginEventIngest) -> UUID:
        record = LoginEventRecord(**event.model_dump())   # assigns id (uuid4) app-side
        await self._repo.persist(record)                  # PG commit = point of no return
        await self._safe_publish(record)
        return record.id

    async def ingest_many(self, events: list[LoginEventIngest]) -> list[UUID]:
        records = [LoginEventRecord(**e.model_dump()) for e in events]
        await self._repo.persist_many(records)            # single transaction, all-or-nothing
        for r in records:
            await self._safe_publish(r)                   # per-event best-effort
        return [r.id for r in records]

    async def _safe_publish(self, record):
        try:
            await self._publisher.publish(record)
        except Exception:
            self._log.error("login_events publish failed",
                            event_id=str(record.id), exc_info=True)
```

### 5.5 Dual-write order and failure semantics — ⚠️ CRITICAL

PostgreSQL is the system of record; the Redis Stream is transport. The order and failure policy are non-negotiable:

1. **Persist to PostgreSQL first and commit.** The commit is the point of no return.
2. **Then publish to `login_events`.** Publishing strictly follows a successful commit.
3. **If the commit fails** (DB unavailable, constraint violation, etc.): the event is *not* accepted. Let the exception propagate so the request returns a 5xx and nothing enters the pipeline. (`get_db_session` rolls back.)
4. **If the publish fails after a successful commit:** the durable record already exists and is replayable. **Catch the error, log it (structured, including the event `id`), and still return 202.** Do **NOT** roll back the PostgreSQL write, and do **NOT** return an error — a committed event is an accepted event.

For `/events/bulk`: the PostgreSQL write is one transaction (all-or-nothing — any insert failure rolls back the whole batch and returns 5xx); publishing is then per-event best-effort with the same catch-and-log policy.

### 5.6 Routes — `app/routes.py`

An `APIRouter` with exactly three endpoints:

- `POST /events/ingest` → `IngestAccepted`, status code **202**. Body: `LoginEventIngest`. Resolves an `IngestionService` (via dependency), calls `ingest_one`, returns the assigned `id`.
- `POST /events/bulk` → `BulkIngestAccepted`, status code **202**. Body: `list[LoginEventIngest]`. Reject length 0 or > 5000 with 422. Calls `ingest_many`, returns count + ids.
- `GET /health` → `HealthResponse`, status code **200**. Readiness probe:
  - PostgreSQL: execute `SELECT 1`.
  - Redis: `await (await get_redis()).ping()`.
  - Both OK → `status="healthy"`. Redis down but PG OK → `"degraded"` (events can still be persisted, but pipeline publish will fail). PG down → `"unhealthy"`. Set `service="event-ingestion"`.

Response models live in `app/schemas.py`:

```python
# [EXEMPLARY — field names are the contract]
class IngestAccepted(BaseModel):
    id: UUID
    status: Literal["accepted"] = "accepted"

class BulkIngestAccepted(BaseModel):
    accepted: int
    event_ids: list[UUID]
    status: Literal["accepted"] = "accepted"
```

### 5.7 Composition root — `app/main.py`

- `create_app() -> FastAPI` builds the app, calls `setup_logging("event-ingestion")`, includes the router, and exposes a module-level `app = create_app()` for uvicorn.
- Use a FastAPI dependency that, given a session from `get_db_session`, constructs `IngestionService(PostgresEventRepository(session), RedisEventPublisher(), get_logger("event-ingestion"))`.
- A lifespan handler may warm the Redis client. **Do not** create consumer groups (this service is a producer, not a consumer).
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8001`.

### 5.8 Docker — Option A (self-contained image, repo-root build context)

The shared library is **copied into the image at build time** and installed; the image is self-contained (no runtime source mounts). The build context is the repository root so the Dockerfile can see both `shared/` and the service. This is the **first service image in the project — it establishes the pattern all later services follow**, including the non-root user (`useradd` + `USER appuser`) which every subsequent service Dockerfile copies.

`services/event-ingestion/Dockerfile`:

```dockerfile
# [EXEMPLARY — but the repo-root context, COPY order, port, and non-root user are load-bearing]
FROM python:3.12-slim
WORKDIR /app

# Pinned dependency closure first — the compiled lockfile (service deps +
# shared's full transitive closure). This is the heavy, slowest-changing layer.
COPY services/event-ingestion/requirements.txt /app/svc/requirements.txt
RUN pip install --no-cache-dir -r /app/svc/requirements.txt

# Shared library installed editable WITHOUT deps — the lockfile above already
# pins shared's third-party closure, so --no-deps keeps the locked versions
# authoritative and prevents re-resolution (ADR-0012).
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/ --no-deps

# Service code last — changes most often.
COPY services/event-ingestion/app/ /app/svc/app/

# The service needs no root privileges at runtime; switch to a dedicated user.
# This non-root pattern is copied by all subsequent service Dockerfiles.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app/svc
USER appuser

WORKDIR /app/svc
EXPOSE 8001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

Dependencies follow the repo-wide lockfile posture (ADR-0012). `services/event-ingestion/requirements.in` declares the service-direct **floors** only — `fastapi` and `uvicorn[standard]`; the data-layer dependencies (SQLAlchemy, asyncpg, redis, pydantic, pydantic-settings, structlog) are owned by `naas_shared` and are not redeclared here. `services/event-ingestion/requirements.txt` is the pip-compiled **lock** (from that `.in` plus `shared/pyproject.toml`); it pins the full transitive closure, which is why the image installs it first and then adds `naas_shared` editable with `--no-deps`. See `DEPENDENCIES.md` for the regenerate workflow.

`.dockerignore` at the repo root (keeps the build context lean — all service builds share it):

```
# [EXEMPLARY]
.git
.venv
venv
node_modules
dashboard
tests
docs
.claude
**/__pycache__
**/*.pyc
.env
```

`docker-compose.yml` — add this service entry (and nothing else):

```yaml
# [EXEMPLARY — context/dockerfile, env_file, ports, depends_on conditions are load-bearing]
  event-ingestion:
    build:
      context: .
      dockerfile: services/event-ingestion/Dockerfile
    container_name: naas-event-ingestion
    env_file: .env
    ports:
      - "${EVENT_INGESTION_PORT:-8001}:8001"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - naas-network
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)\""]
      interval: 10s
      timeout: 5s
      retries: 5
```

`env_file: .env` injects `POSTGRES_*`/`REDIS_*` into the container environment, which `get_settings()` reads (its defaults already target the `postgres`/`redis` service hostnames on `naas-network`).

---

## 6. Validation Criteria

Bring up infrastructure and the service: `docker compose up -d --build event-ingestion` (with `postgres` and `redis` healthy). Then:

1. **Single ingest → 202 + dual-write.**
   ```bash
   curl -s -X POST http://localhost:8001/events/ingest \
     -H 'Content-Type: application/json' \
     -d '{"user_id":"alice","client_ip":"203.0.113.42","protocol":"oidc",
          "timestamp":"2026-06-03T14:05:00Z","raw_attributes":{"email":"alice@corp.com"}}'
   ```
   Expect HTTP 202 and `{"id":"<uuid>","status":"accepted"}`. Capture the `id`.
2. **PostgreSQL row present.**
   ```bash
   docker exec naas-postgres psql -U naas -d naas -c \
     "SELECT id, user_id, protocol, normalized_attributes, enriched_signals
      FROM events WHERE id = '<uuid>';"
   ```
   Expect one row; `normalized_attributes` and `enriched_signals` are NULL.
3. **Redis Stream message present and correlatable.**
   ```bash
   docker exec naas-redis redis-cli XLEN login_events          # >= 1
   docker exec naas-redis redis-cli XRANGE login_events - + COUNT 1
   ```
   The message has a single `data` field; its JSON `id` equals the row's `id`.
4. **Bulk → 202 + N rows + N stream messages.** POST a 3-element array to `/events/bulk`; expect `{"accepted":3,...}`, the `events` row count to rise by 3, and `XLEN login_events` to rise by 3.
5. **Health.** `curl -s http://localhost:8001/health` → `{"status":"healthy","service":"event-ingestion",...}`. (Optional: stop Redis → health reports `"degraded"`.)
6. **Validation rejection.** A request with `"client_ip":"256.0.0.1"` or `"protocol":"kerberos"` returns 422 and writes nothing. A `/events/bulk` array of length > 5000 returns 422.

---

## 7. What NOT to Build

- **Do NOT redefine** `LoginEventIngest`, `LoginEventRecord`, or `HealthResponse` — import them from `naas_shared.models`.
- **Do NOT interpret, validate, or reshape `raw_attributes`.** Ingestion is protocol-agnostic; Identity Normalization interprets it.
- **Do NOT write `normalized_attributes` or `enriched_signals`.** They are NULL at ingestion; downstream stages own them.
- **Do NOT consume from any stream or create consumer groups.** This service only *produces* to `login_events`.
- **Do NOT call `Base.metadata.create_all`, add migrations, or alter the `events` table.** The schema is owned by the infrastructure init script.
- **Do NOT roll back the PostgreSQL commit if the stream publish fails** (see 5.5).
- **Do NOT add endpoints** beyond `/events/ingest`, `/events/bulk`, and `/health`.
- **Do NOT add authentication, JWT verification, or rate limiting.** Auth is handled upstream by the gateway/Keycloak in a later spec.
- **Do NOT implement idempotency keys or duplicate detection.** Identity is a server-assigned UUID; collisions are not a concern at this scale.
- **Do NOT add IPv6 handling.** `client_ip` is IPv4-only by decision; the shared model's regex enforces it.
- **Do NOT touch other services or other `naas_shared` modules** beyond appending `Base`/`EventORM` to `shared/naas_shared/schemas.py` and adding the `event-ingestion` entry to `docker-compose.yml`.
