---
name: patterns-service-tdd
description: Patterns for TDD tests against NAAS FastAPI services — sys.path injection, ASGI health endpoint mocking, ORM column type assertions, packaging file checks
metadata:
  type: feedback
---

## sys.path injection for service tests

Services are not installed packages — their `app/` directory lives under
`services/<name>/`. To allow `from app.main import app` to resolve in tests,
inject `services/<name>/` onto `sys.path` at module level:

```python
SERVICE_DIR = REPO_ROOT / "services" / "event-ingestion"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))
```

Also inject `shared/` for `naas_shared` resolution. Do both before any imports.
Both go under the same `_find_repo_root()` pattern used across all spec test files.

## Mocking FastAPI lifespan dependencies for health endpoint tests

The /health endpoint calls `get_db_session` (async generator) and `get_redis`.
Use `unittest.mock.patch` at the naas_shared module path (where the symbols are
defined), not at the app.main path (where they are imported). Use `AsyncMock`
for async calls and `patch.object` patterns:

```python
with (
    patch("naas_shared.database.get_db_session", return_value=mock_session),
    patch("naas_shared.redis_client.get_redis", return_value=mock_redis),
):
    yield
```

Use `starlette.testclient.TestClient` (sync) with `raise_server_exceptions=False`
so connection errors become test failures rather than exceptions that skip assertions.

## ORM column-type assertions

To assert a column is INET or JSONB (PostgreSQL-specific), import the type class
from `sqlalchemy.dialects.postgresql` and use `isinstance`:

```python
from sqlalchemy.dialects.postgresql import INET, JSONB
col = EventORM.__table__.columns["client_ip"]
assert isinstance(col.type, INET)
```

Check nullability with `col.nullable` and primary key with `col.primary_key`.
Access the column set via `set(EventORM.__table__.columns.keys())`.

## No create_all at import time — two-part test

Use two tests:
1. Static: read `schemas.py` source and assert `"create_all("` not in content.
2. Dynamic: `importlib.reload(module)` with `patch.object(Base.metadata, "create_all")`
   and assert `call_count == 0`.

The static test catches the pattern before `Base` is importable. The dynamic
test catches `create_all` called via a function invoked at module level.

## Negative requirements.txt assertions

Strip comment lines (startswith '#') and blank lines before checking.
Normalize to lowercase for comparison. Use `startswith` for negative checks
to catch all specifier variants (e.g., `sqlalchemy==`, `sqlalchemy>=`, `sqlalchemy[asyncio]`).

## Pre-existing files that legitimately pass in TDD state

Infrastructure services (postgres, redis, keycloak, openldap) already exist in
docker-compose.yml at Spec 0. Tests asserting their presence correctly pass before
Chunk 1 implementation — this is documented and acceptable as long as the suite
overall has the bulk of its tests failing. Note in the test docstring: 
"Tests that assert pre-existing state may pass before implementation — intentional."

## Spec 1 Chunk 1 test file layout

- `tests/shared/test_chunk1_orm_mapping.py` — Base/EventORM import, tablename,
  column set (exact 13 columns), INET/JSONB types, nullability, no create_all
- `tests/services/event-ingestion/test_chunk1_app_skeleton.py` — app.main import,
  FastAPI instance, /health 200, service/status fields, HealthResponse validation
- `tests/services/event-ingestion/test_chunk1_packaging.py` — requirements.txt
  (fastapi+uvicorn present; sqlalchemy/asyncpg/redis absent), Dockerfile (EXPOSE 8001,
  COPY order, -e install, uvicorn CMD), .dockerignore (5 required entries),
  docker-compose.yml (event-ingestion entry with build/env_file/ports/depends_on/healthcheck)

## Spec 1 Chunk 2 test file layout

- `tests/services/event-ingestion/test_chunk2_ports.py` — Protocol import, typing.Protocol
  MRO check, async method presence on EventRepository (persist/persist_many) and EventPublisher
  (publish)
- `tests/services/event-ingestion/test_chunk2_schemas.py` — IngestAccepted/BulkIngestAccepted
  import, Literal["accepted"] default, Pydantic BaseModel check, model_dump key presence,
  ORM isolation assertions (no EventORM/Base in app.schemas)
- `tests/services/event-ingestion/test_chunk2_service.py` — IngestionService with FakeRepo /
  FakePublisher sharing a call_log list for ordering assertions; persist-before-publish order;
  publisher exception swallowing; logger.error called with event_id= kwarg; ingest_many
  best-effort publish (all 3 attempted even if all raise)
- `tests/services/event-ingestion/test_chunk2_adapters.py` — _to_orm mapping (direct via
  class/module attribute or fallback via session.add() observation); session.add+commit for
  persist; session.add_all+single commit for persist_many; publish_to_stream patched at
  app.adapters.publish_to_stream; id is a string in the published payload

## Dual-write ordering test pattern

Use a shared call_log list (plain Python list) appended to by both FakeRepo and FakePublisher.
Check `call_names.index("persist") < call_names.index("publish")` for ordering assertion.
This is more reliable than mock.call_order inspection.

## asyncio in sync tests pattern

Use `asyncio.get_event_loop().run_until_complete(coroutine)` for calling async service
methods from sync test classes. Avoid pytest-asyncio for chunk 2 service tests — sync
test classes are simpler and avoid loop scope configuration warnings.

## _to_orm fallback pattern

When testing _to_orm mapping, try class attribute first (PostgresEventRepository._to_orm),
then module-level function (app.adapters._to_orm). If neither is accessible directly,
fall back to calling persist() with a fake AsyncMock session and observing what
session.add() received. Tests use a helper method `_get_to_orm_callable()` that returns
None on failure; callers then conditionally use the fallback path.
