PLAN: Event Ingestion Service — pipeline entry point (REST → dual-write PG + Redis Stream)
SPEC REFERENCE: docs/architecture/SPEC_1_Event_Ingestion_Service.md
PREREQUISITES:
- Spec 0 scaffold is merged and present: `shared/naas_shared/` exposes config, constants, database, redis_client, logging, models (verified: all referenced symbols exist).
- Infrastructure init script `infrastructure/postgres/init.sql` already creates the `events` table (verified: DDL at lines 23-37 matches the EventORM column set/types/nullability the spec mandates). This service does NOT create or migrate that table.
- `docker-compose.yml` defines healthy `postgres` and `redis` services on `naas-network` with `.env`-driven config. Bringing the service up requires those two healthy first.
- `services/event-ingestion/README.md` already exists; leave it untouched.
- No root `.dockerignore` exists yet — this spec creates it (first service image establishes the build pattern).

OVERVIEW

The Event Ingestion Service is the front door of the NAAS pipeline. It exposes three REST
endpoints on port 8001 — `POST /events/ingest`, `POST /events/bulk`, `GET /health` — validates
the `LoginEventIngest` envelope (IPv4-only client_ip, protocol enum, bulk size 1..5000), assigns
each event a server-side UUID v4, and performs a CRITICAL dual-write:

  1. Persist to PostgreSQL `events` (system of record) and COMMIT explicitly — point of no return.
  2. Publish the canonical `LoginEventRecord` JSON to the Redis Stream `login_events` AFTER commit.

Failure policy (spec §5.5, ⚠️ CRITICAL):
- Commit fails  → propagate → 5xx, nothing enters the pipeline (get_db_session rolls back).
- Publish fails AFTER commit → catch, log structured with event id, STILL return 202. Never roll back.
- Bulk: one all-or-nothing PG transaction, then per-event best-effort publish with the same catch-and-log.

Architecture is pragmatic hexagonal: Protocol-typed ports (EventRepository, EventPublisher),
concrete adapters (PostgresEventRepository, RedisEventPublisher), a domain orchestrator
(IngestionService) that owns the dual-write order and failure policy, and a thin composition
root + routes that only translate HTTP. This is the FIRST service image in the project — its
Dockerfile (Option A: repo-root build context, shared lib copied in at build time) and
docker-compose entry establish the pattern all later services follow.

The implementation is decomposed into 3 chunks: (1) scaffold + ORM mapping + bootable health
skeleton, (2) domain core (ports, adapters, service, response schemas) verifiable with fakes,
(3) routes + composition-root wiring that connects the dual-write end-to-end.

STEPS:

Step 1: Append the SQLAlchemy ORM mapping to the shared schemas module
  Files: shared/naas_shared/schemas.py (currently a one-line placeholder comment)
  Details:
    - Replace the placeholder comment with a declarative `Base(DeclarativeBase)` and an
      `EventORM(Base)` mapping for `__tablename__ = "events"`, SQLAlchemy 2.0 declarative style
      (Mapped / mapped_column), consistent with the async engine in naas_shared.database.
    - Columns MUST mirror the existing events DDL EXACTLY (verified against init.sql §EVENTS TABLE):
        id            UUID(as_uuid=True) PK, default=uuid4
        user_id       String(255) NOT NULL
        protocol      String(10)  NOT NULL
        client_ip     INET        NOT NULL          (string value stored in the INET column)
        user_agent    String      nullable
        timestamp     DateTime    NOT NULL
        source        String(20)  NOT NULL default="user"
        is_synthetic  Boolean     NOT NULL default=False
        is_historical Boolean     NOT NULL default=False
        raw_attributes        JSONB nullable
        normalized_attributes JSONB nullable
        enriched_signals      JSONB nullable
        created_at    DateTime    server_default=func.now()   (DB owns this — never set app-side)
    - Use the exemplary mapping in spec §5.1 as the template (column set/types are the contract).
    - ⚠️ Do NOT call Base.metadata.create_all, add Alembic, or alter the table (spec §5.1, §7).
      EventORM is a read/write mapping over a table the infra init script already owns.
  Shared imports: none new (this file IS a shared module; it imports from sqlalchemy only).
  Verify: `python -c "from naas_shared.schemas import Base, EventORM; print(EventORM.__tablename__)"`
          prints `events`; `EventORM.__table__.columns.keys()` lists all 13 columns above.

Step 2: Create the service scaffold (Dockerfile, requirements.txt, package, bootable app)
  Files:
    services/event-ingestion/Dockerfile
    services/event-ingestion/requirements.txt
    services/event-ingestion/app/__init__.py
    services/event-ingestion/app/main.py    (skeleton: app factory + minimal /health)
    .dockerignore                            (repo root)
  Details:
    - Dockerfile (Option A, spec §5.8 — repo-root context, COPY order and port are load-bearing):
        FROM python:3.12-slim; WORKDIR /app
        COPY shared/ /app/shared/  ; RUN pip install --no-cache-dir -e /app/shared/
        COPY services/event-ingestion/requirements.txt /app/svc/requirements.txt
        RUN pip install --no-cache-dir -r /app/svc/requirements.txt
        COPY services/event-ingestion/app/ /app/svc/app/
        WORKDIR /app/svc ; EXPOSE 8001
        CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8001"]
    - requirements.txt: service-direct deps ONLY — `fastapi` and `uvicorn[standard]`, pinned per
      tech stack (fastapi>=0.115, uvicorn[standard]). Data-layer deps (sqlalchemy, asyncpg, redis,
      pydantic, pydantic-settings, structlog) come transitively via `pip install -e naas_shared`.
      Do NOT duplicate them here unless the shared install does not provide one.
    - .dockerignore (repo root): .git, .venv, venv, node_modules, dashboard, tests, docs, .claude,
      **/__pycache__, **/*.pyc, .env  (per spec §5.8; keeps build context lean; reused by all later builds).
    - app/__init__.py: empty package marker.
    - app/main.py (SKELETON for this chunk): `create_app() -> FastAPI` that calls
      `setup_logging("event-ingestion")` and exposes module-level `app = create_app()`. Include a
      minimal `GET /health` returning a `HealthResponse(status="healthy", service="event-ingestion")`
      good enough to boot and satisfy the docker healthcheck. The REAL readiness-probing /health
      (PG SELECT 1, Redis ping, degraded/unhealthy logic) moves into routes.py in Step 6, at which
      point this skeleton route is replaced by the mounted router.
  Shared imports: `from naas_shared.logging import setup_logging`;
                  `from naas_shared.models import HealthResponse`.
  Verify: image builds (`docker compose build event-ingestion` after Step 3 entry exists) OR locally
          `python -c "from app.main import app"` resolves; container boots and `GET /health` → 200.

Step 3: Add the docker-compose service entry
  Files: docker-compose.yml (modify ONLY — add the new `event-ingestion` entry under
         "─── APPLICATION SERVICES ───", lines ~96-98; do NOT touch infra services)
  Details (spec §5.8 — context/dockerfile, env_file, ports, depends_on conditions, healthcheck
           are load-bearing):
        event-ingestion:
          build: { context: ., dockerfile: services/event-ingestion/Dockerfile }
          container_name: naas-event-ingestion
          env_file: .env
          ports: ["${EVENT_INGESTION_PORT:-8001}:8001"]
          depends_on:
            postgres: { condition: service_healthy }
            redis:    { condition: service_healthy }
          networks: [naas-network]
          healthcheck:
            test: python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8001/health').status==200 else 1)"
            interval: 10s, timeout: 5s, retries: 5
    - env_file: .env injects POSTGRES_*/REDIS_* which get_settings() reads (defaults already target
      the postgres/redis service hostnames on naas-network).
  Shared imports: n/a.
  Verify: `docker compose config` parses without error and shows the event-ingestion service with
          the depends_on conditions and the healthcheck. `docker compose up -d --build event-ingestion`
          (with postgres+redis healthy) reaches healthy state.

Step 4: Define ports (Protocol boundaries) and API response schemas
  Files:
    services/event-ingestion/app/ports.py
    services/event-ingestion/app/schemas.py    (API response models — distinct from naas_shared.schemas)
  Details:
    - ports.py (spec §5.2): two `typing.Protocol` classes —
        EventRepository: `async persist(record: LoginEventRecord) -> None`,
                         `async persist_many(records: list[LoginEventRecord]) -> None`
        EventPublisher:  `async publish(record: LoginEventRecord) -> None`
    - app/schemas.py (spec §5.6 — field names are the contract):
        class IngestAccepted(BaseModel): id: UUID; status: Literal["accepted"] = "accepted"
        class BulkIngestAccepted(BaseModel): accepted: int; event_ids: list[UUID];
                                             status: Literal["accepted"] = "accepted"
    - ⚠️ Keep app/schemas.py (response models) distinct from shared/naas_shared/schemas.py (ORM).
      Same basename, different files (spec §1 callout).
  Shared imports: `from naas_shared.models import LoginEventRecord` (ports.py).
  Verify: `python -c "from app.ports import EventRepository, EventPublisher"` and
          `from app.schemas import IngestAccepted, BulkIngestAccepted` import clean;
          `IngestAccepted(id=uuid4())` defaults status to "accepted".

Step 5: Implement adapters and the domain dual-write orchestrator
  Files:
    services/event-ingestion/app/adapters.py
    services/event-ingestion/app/service.py
  Details:
    - adapters.py (spec §5.3):
        PostgresEventRepository(session: AsyncSession):
          A private `_to_orm(record: LoginEventRecord) -> EventORM` maps record fields per §3.1:
          id, user_id, protocol, client_ip, user_agent, timestamp, source, is_synthetic,
          is_historical, raw_attributes. ⚠️ Do NOT set normalized_attributes, enriched_signals,
          or created_at — leave them unset so they default NULL / DB CURRENT_TIMESTAMP (§3.1, §7).
          persist():      session.add(_to_orm(record)); `await session.commit()`  (explicit — durability point)
          persist_many(): session.add_all([_to_orm(r) for r in records]); single `await session.commit()`
                          (one transaction; any insert failure rolls back the whole batch).
        RedisEventPublisher (no DB dependency):
          publish(): `await publish_to_stream(STREAM_LOGIN_EVENTS, record.model_dump(mode="json"))`.
          The shared helper wraps payload as a single stream field `data` (JSON string) and caps maxlen.
          model_dump(mode="json") serializes UUID/datetime to strings and INCLUDES id, created_at,
          normalized_attributes (null), enriched_signals (null) — matching the §3.2 wire shape.
    - service.py (spec §5.4, §5.5 — ORDER and failure handling are the contract):
        IngestionService(repo: EventRepository, publisher: EventPublisher, logger):
          ingest_one(event: LoginEventIngest) -> UUID:
            record = LoginEventRecord(**event.model_dump())   # assigns id app-side (uuid4)
            await repo.persist(record)                        # PG commit = point of no return
            await self._safe_publish(record)
            return record.id
          ingest_many(events: list[LoginEventIngest]) -> list[UUID]:
            records = [LoginEventRecord(**e.model_dump()) for e in events]
            await repo.persist_many(records)                  # single all-or-nothing transaction
            for r in records: await self._safe_publish(r)     # per-event best-effort
            return [r.id for r in records]
          _safe_publish(record): try publisher.publish(record); except Exception:
            logger.error("login_events publish failed", event_id=str(record.id), exc_info=True)
            (catch-and-log; do NOT re-raise; do NOT roll back the PG write — §5.5 step 4).
        ⚠️ The dual-write orchestration lives HERE, not in the route handler (spec §5).
  Shared imports:
    adapters.py: `from naas_shared.redis_client import publish_to_stream`;
                 `from naas_shared.constants import STREAM_LOGIN_EVENTS`;
                 `from naas_shared.schemas import EventORM`;
                 `from naas_shared.models import LoginEventRecord`;
                 `from sqlalchemy.ext.asyncio import AsyncSession`.
    service.py:  `from naas_shared.models import LoginEventIngest, LoginEventRecord`.
  Verify (unit, with fakes — no live PG/Redis): a fake repo records persist/persist_many calls; a
    fake publisher can be set to raise. Then:
    - ingest_one returns a UUID equal to the persisted record's id and calls persist exactly once.
    - When the fake publisher raises, ingest_one STILL returns the id (no exception escapes) and
      logs an error containing the event id.
    - ingest_many persists once (single batch call) and returns ids in input order; one publisher
      failure does not abort publishing of the remaining records.
    - PostgresEventRepository._to_orm leaves normalized_attributes/enriched_signals/created_at unset.

Step 6: Routes + composition-root wiring (integration-facing dual-write end-to-end)
  Files:
    services/event-ingestion/app/routes.py
    services/event-ingestion/app/main.py    (wire DI + mount router; replace the Step-2 health stub)
  Details:
    - routes.py (spec §5.6): an APIRouter with EXACTLY three endpoints (no others — §7):
        POST /events/ingest  → response_model IngestAccepted, status_code 202. Body LoginEventIngest.
          Resolve IngestionService via dependency, call ingest_one, return IngestAccepted(id=...).
        POST /events/bulk    → response_model BulkIngestAccepted, status_code 202.
          Body `list[LoginEventIngest]` (a BARE JSON array, not an envelope — §2.2). Reject length 0
          or > 5000 with HTTP 422. Recommended: enforce via a typed parameter
          `events: Annotated[list[LoginEventIngest], Body(min_length=1, max_length=5000)]` so FastAPI
          emits the standard 422 body. Call ingest_many; return BulkIngestAccepted(accepted=len(ids),
          event_ids=ids).
        GET /health → response_model HealthResponse, status_code 200. Readiness probe:
          PG: `await session.execute(text("SELECT 1"))`. Redis: `await (await get_redis()).ping()`.
          Both OK → "healthy". Redis down but PG OK → "degraded". PG down → "unhealthy".
          service="event-ingestion". (Health should not 500 on dependency failure — it reports
          status in the body; the docker healthcheck only requires HTTP 200, so keep returning 200
          with the degraded/unhealthy status string.)
    - DI dependency (in routes.py or main.py): given a session from get_db_session, construct
        IngestionService(PostgresEventRepository(session), RedisEventPublisher(),
                         get_logger("event-ingestion")).
    - main.py composition root (spec §5.7): create_app() calls setup_logging("event-ingestion"),
      includes the router, exposes module-level `app = create_app()`. A lifespan handler MAY warm the
      Redis client (`await get_redis()`). ⚠️ Do NOT create consumer groups — this service is a
      PRODUCER only (§5.7, §7). Replace the Step-2 inline /health stub: /health now lives in the
      mounted router.
  Shared imports:
    routes.py: `from naas_shared.models import LoginEventIngest, HealthResponse`;
               `from naas_shared.database import get_db_session`;
               `from naas_shared.redis_client import get_redis`;
               `from naas_shared.logging import get_logger`;
               `from sqlalchemy import text`.
    main.py:   `from naas_shared.logging import setup_logging`;
               `from naas_shared.redis_client import get_redis` (lifespan, optional).
  Verify (end-to-end, spec §6, with postgres+redis healthy):
    1. POST /events/ingest valid OIDC body → 202 + {"id":"<uuid>","status":"accepted"}.
    2. `SELECT id,user_id,protocol,normalized_attributes,enriched_signals FROM events WHERE id='<uuid>'`
       → one row; normalized_attributes and enriched_signals are NULL.
    3. `XLEN login_events` >= 1; `XRANGE login_events - + COUNT 1` → single `data` field whose JSON
       `id` equals the row id.
    4. POST a 3-element array to /events/bulk → {"accepted":3,...}; events count +3; XLEN +3.
    5. GET /health → {"status":"healthy","service":"event-ingestion",...}. (Optional: stop Redis →
       "degraded".)
    6. client_ip "256.0.0.1" or protocol "kerberos" → 422, writes nothing. Bulk array length > 5000 → 422.

INTEGRATION NOTES:
- Upstream: no stream/DB read. Entry point. Synchronous REST callers are the API Gateway, the
  Persona Simulator (via its EventSink → POST /events/bulk with a bare array), and direct API users.
  No authentication in this service — auth is handled upstream by the gateway/Keycloak (later spec); §7.
- Downstream: publishes the canonical LoginEventRecord JSON to Redis Stream `login_events`
  (constant STREAM_LOGIN_EVENTS, maxlen 10000 via the shared helper). The Identity Normalization
  Service consumes this stream (consumer group `normalization_workers`) and correlates on the
  payload `id` — which MUST be present in the published JSON (§3.2 ⚠️ CRITICAL). This service does
  NOT create that consumer group (it is a producer); Normalization owns its own group creation.
- Shared state: PostgreSQL `events` table (system of record, INSERT only here; normalized_attributes
  and enriched_signals left NULL for downstream stages to populate). Redis used only for stream
  publish + health ping. No caching introduced by this service.
- Wire payload contract (§3.2): record.model_dump(mode="json") is published as the single stream
  field `data` (a JSON string). Includes id, user_id, protocol, client_ip, timestamp, user_agent,
  source, is_synthetic, is_historical, raw_attributes, plus present-but-null normalized_attributes /
  enriched_signals / created_at. Downstream consumers parse `data` as JSON and validate with
  LoginEventRecord.
- No WebSocket / real-time concerns in this service (those live in the API Gateway, later spec).
- This is the FIRST service image: its Dockerfile (Option A, repo-root context) and the root
  `.dockerignore` are reused verbatim as the template by every later service spec.

KNOWN RISKS:
- [Resolved — no ambiguity] The exemplary EventORM in spec §5.1 matches the existing events DDL in
  infrastructure/postgres/init.sql EXACTLY (verified column-by-column). No conflict between the spec
  and the infrastructure init script.
- [Implementation nuance] `created_at` divergence: LoginEventRecord assigns a Python-side created_at
  (default_factory=datetime.utcnow), but per §3.1 the DB owns created_at via CURRENT_TIMESTAMP. The
  adapter's `_to_orm` MUST leave the ORM `created_at` unset so the server_default fires; do NOT copy
  record.created_at into the ORM. The record's created_at is only used in the published wire payload
  (a harmless slight skew from the DB value — acceptable, the DB value is authoritative). Surfaced so
  the implementer does not "helpfully" set it.
- [Implementation nuance] `LoginEventRecord(**event.model_dump())` works because LoginEventIngest
  dumps only base fields and LoginEventRecord supplies id/created_at/normalized/enriched via defaults
  (verified against shared models). If a future LoginEventIngest field is removed/renamed this breaks
  — but that is out of scope here.
- [Decision, not a guess] /events/bulk size validation (1..5000): the spec says "rejected with 422".
  The recommended approach is FastAPI Body(min_length=1, max_length=5000) on a typed
  `list[LoginEventIngest]` parameter, which yields FastAPI's standard 422 body (§3.3) without a
  hand-rolled check. An explicit length check raising HTTPException(422) is an acceptable alternative;
  either satisfies the validation criterion. Flagged because the spec states the constraint but not
  the mechanism.
- [Decision] /health returning 200 even when degraded/unhealthy: the spec's readiness logic reports
  status in the BODY ("healthy"/"degraded"/"unhealthy"), and the docker healthcheck only checks for
  HTTP 200. Health therefore returns 200 with the status string rather than a 503, so that PG-down /
  Redis-down states are observable via the body and the container does not flap purely on a transient
  Redis blip when PG is fine. If a future operator wants the container marked unhealthy on PG-down,
  that is a follow-up decision, not in this spec.
- [Failure mode, by design] Publish-after-commit failure leaves a durable PG row that never reached
  the stream (replayable, but not auto-replayed in this spec). This is the intended §5.5 semantics: a
  committed event is an accepted event; the service logs the orphan with event_id for later manual
  replay. No idempotency keys or duplicate detection (§7) — out of scope.
- [Scope boundary] main.py is owned (primary) by the scaffold chunk and modified again (as a
  shared_file) by the routes/wiring chunk to mount the router and replace the health stub. This is
  the single intentional intra-spec shared-file overlap; the wiring chunk's instructions scope its
  edit to the DI/router-mount/lifespan section only. shared/naas_shared/schemas.py and
  docker-compose.yml are each touched by exactly one chunk, so they are not shared across chunks here.
