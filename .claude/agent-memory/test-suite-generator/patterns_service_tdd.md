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
docker-compose.yml before application services are implemented. Tests asserting their
presence correctly pass before the first application service is implemented — this is
documented and acceptable as long as the suite overall has the bulk of its tests failing.
Note in the test docstring:
"Tests that assert pre-existing state may pass before implementation — intentional."

## event-ingestion service test files

- `tests/shared/test_orm_mapping.py` — Base/EventORM import, tablename,
  column set (exact 13 columns), INET/JSONB types, nullability, no create_all
- `tests/services/event_ingestion/test_app_skeleton.py` — app.main import,
  FastAPI instance, /health 200, service/status fields, HealthResponse validation
- `tests/services/event_ingestion/test_packaging.py` — requirements.txt
  (fastapi+uvicorn present; sqlalchemy/asyncpg/redis absent), Dockerfile (EXPOSE 8001,
  COPY order, -e install, uvicorn CMD), .dockerignore (5 required entries),
  docker-compose.yml (event-ingestion entry with build/env_file/ports/depends_on/healthcheck)
- `tests/services/event_ingestion/test_ports.py` — Protocol import, typing.Protocol
  MRO check, async method presence on EventRepository (persist/persist_many) and EventPublisher
  (publish)
- `tests/services/event_ingestion/test_schemas.py` — IngestAccepted/BulkIngestAccepted
  import, Literal["accepted"] default, Pydantic BaseModel check, model_dump key presence,
  ORM isolation assertions (no EventORM/Base in app.schemas)
- `tests/services/event_ingestion/test_service.py` — IngestionService with FakeRepo /
  FakePublisher sharing a call_log list for ordering assertions; persist-before-publish order;
  publisher exception swallowing; logger.error called with event_id= kwarg; ingest_many
  best-effort publish (all 3 attempted even if all raise)
- `tests/services/event_ingestion/test_adapters.py` — _to_orm mapping (direct via
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

## identity-normalization service test files

- `tests/services/identity_normalization/test_app_skeleton.py` — app.main import,
  FastAPI instance, /health route registered, ONLY /health route initially (no extras)
- `tests/services/identity_normalization/test_ports.py` — ports.py Protocol imports,
  @runtime_checkable typing.Protocol check, method signatures: ProtocolAdapter.extract,
  LdapEnricher.extract + async enrich (correlation_field + lookup_value params),
  NormalizationRepository.async write (event_id + normalized params),
  EventPublisher.async publish_normalized (record + normalized params)
- `tests/services/identity_normalization/test_health.py` — /health handler with
  real PG+Redis probing; all three states (healthy/degraded/unhealthy); service field
  must be "identity-normalization" (not "event-ingestion"); same patch pattern as
  event-ingestion test_health.py
- `tests/services/identity_normalization/test_packaging.py` — requirements.txt
  (fastapi+uvicorn+python-ldap+pyyaml present; sqlalchemy/asyncpg/redis absent),
  Dockerfile (EXPOSE 8002, COPY order, -e install, uvicorn CMD port 8002,
  gcc+libldap2-dev+libsasl2-dev via apt-get BEFORE pip install)
- `tests/services/identity_normalization/test_compose.py` — identity-normalization
  compose entry (build/env_file/port 8002/depends_on postgres+redis+openldap+condition,
  config bind-mount read-only, healthcheck port 8002); existing services preservation

## python-ldap system deps pattern (Spec 2)

python-ldap is a C extension requiring gcc, libldap2-dev, and libsasl2-dev.
Test that all three are present in the Dockerfile AND that the apt-get install
line precedes the pip install line (line number ordering). Without the ordering
check, a Dockerfile that has the deps listed but after pip install would still fail the build.

## openldap depends_on (identity-normalization specific)

Unlike event-ingestion (postgres + redis only), identity-normalization must also
depend on openldap with condition: service_healthy. Test this as a separate test case
with a clear WHY — it's easy for implementers to copy event-ingestion's depends_on
and omit the openldap dependency.

## config bind-mount read-only (identity-normalization specific)

The ./config:/app/config mount must be read-only. Accept both short syntax
("./config:/app/config:ro") and long object syntax (read_only: true). The read-only
check requires finding the specific config mount first, then inspecting its flags.

## Pre-existing scope-preservation tests passing in TDD state

The `test_existing_service_still_present` parametrized tests (postgres, redis, keycloak,
openldap, event-ingestion) CORRECTLY PASS before the identity-normalization entry is added —
they assert pre-existing state. This is intentional and follows the same pattern as
event-ingestion's TestDockerComposeInfrastructureIntact. Document this explicitly so
the TDD verification step does not flag these as invalid.
Total expected passes before implementation: 5 (the 5 service-presence checks).
Total expected failures: 76.

## _to_orm fallback pattern

When testing _to_orm mapping, try class attribute first (PostgresEventRepository._to_orm),
then module-level function (app.adapters._to_orm). If neither is accessible directly,
fall back to calling persist() with a fake AsyncMock session and observing what
session.add() received. Tests use a helper method `_get_to_orm_callable()` that returns
None on failure; callers then conditionally use the fallback path.
