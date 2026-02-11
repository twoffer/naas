# Chunk 2: Shared Python Library (naas_shared)

**Spec Reference:** `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md`
**Prerequisites:** Chunk 0 and Chunk 1 completed (all 4 infrastructure containers running)
**Estimated Effort:** ~35 minutes, ~300 lines of new code

---

## Scope

This chunk creates the `shared/` Python package containing all foundation modules that every NAAS service will import. After this chunk, the library is pip-installable and all imports specified in Spec 0, Section 4 work correctly.

### Files Created

```
naas/
└── shared/
    ├── pyproject.toml                # Package metadata, dependencies
    └── naas_shared/
        ├── __init__.py               # Package init with version
        ├── config.py                 # Pydantic Settings (env-driven config)
        ├── constants.py              # Stream names, channel names, consumer groups, cache keys
        ├── models.py                 # Pydantic models: LoginEvent*, NormalizedIdentity, RiskDecision, AlertMessage, HealthResponse
        ├── database.py               # Async SQLAlchemy engine + session factory
        ├── redis_client.py           # Redis connection, stream helpers, pub/sub helpers
        ├── logging.py                # Structlog configuration
        └── schemas.py                # Placeholder for ORM table definitions
```

### Files NOT Touched

- No modifications to `docker-compose.yml`
- No modifications to infrastructure configs
- No `services/` directories (chunk 3)

---

## Steps

### Step 1: Create `shared/pyproject.toml`

**File:** `naas/shared/pyproject.toml`

Create the directory `shared/` and then the `pyproject.toml`. Copy the content exactly from Spec 0, Section 5.4:

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "naas-shared"
version = "2.0.0"
description = "Shared library for NAAS microservices"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "pydantic>=2.10.0",
    "pydantic-settings>=2.1.0",
    "sqlalchemy[asyncio]>=2.0.0",
    "asyncpg>=0.29.0",
    "redis>=5.0.0",
    "structlog>=23.2.0",
]

[tool.setuptools.packages.find]
where = ["."]
include = ["naas_shared*"]
```

**Verify:** `python3 -c "import tomllib; tomllib.load(open('shared/pyproject.toml','rb'))"` exits without error.

---

### Step 2: Create `shared/naas_shared/__init__.py`

**File:** `naas/shared/naas_shared/__init__.py`

Create the `naas_shared/` directory and the init file:

```python
"""NAAS Shared Library - Common models, config, and utilities for all NAAS services."""

__version__ = "2.0.0"
```

Keep it minimal. The version must match `pyproject.toml`.

**Verify:** Directory structure exists: `ls shared/naas_shared/__init__.py`

---

### Step 3: Create `shared/naas_shared/config.py`

**File:** `naas/shared/naas_shared/config.py`

Implement the `Settings` class and `get_settings()` factory exactly as specified in Spec 0, Section 3.8:

- Class `Settings(BaseSettings)` with fields for:
  - PostgreSQL: `postgres_host`, `postgres_port`, `postgres_user`, `postgres_password`, `postgres_db` (all with defaults matching `.env.example`)
  - Redis: `redis_host`, `redis_port`
  - LDAP: `ldap_host`, `ldap_port`, `ldap_base_dn`, `ldap_admin_dn`, `ldap_admin_password`
  - Keycloak: `keycloak_url`, `keycloak_realm`, `keycloak_client_id`
- Property `database_url` returning async connection string: `postgresql+asyncpg://...`
- Property `database_url_sync` returning sync connection string: `postgresql://...`
- Inner `class Config` with `env_file = ".env"` and `env_file_encoding = "utf-8"`
- Function `get_settings()` decorated with `@lru_cache()` returning `Settings()`

**Imports needed:**
- `from pydantic_settings import BaseSettings`
- `from functools import lru_cache`

**Verify:** `cd shared && python3 -c "from naas_shared.config import get_settings; s = get_settings(); print(s.database_url)"` prints a connection string (will use defaults since we are outside Docker).

---

### Step 4: Create `shared/naas_shared/constants.py`

**File:** `naas/shared/naas_shared/constants.py`

Copy all constants exactly from Spec 0, Section 3.3. This is the single source of truth for Redis stream names, channel names, consumer groups, and cache settings:

```python
# Redis Streams (pipeline stages)
STREAM_LOGIN_EVENTS = "login_events"
STREAM_NORMALIZED_EVENTS = "normalized_events"
STREAM_ENRICHED_EVENTS = "enriched_events"

# Redis Streams - maxlen cap
STREAM_MAXLEN = 10000

# Redis Pub/Sub channels (broadcast)
CHANNEL_DECISIONS = "decisions"
CHANNEL_ALERTS = "alerts"

# Consumer groups
GROUP_NORMALIZATION = "normalization_workers"
GROUP_ENRICHMENT = "enrichment_workers"
GROUP_EVALUATOR = "evaluator_workers"

# Cache key prefixes and TTLs (seconds)
CACHE_POLICY_ACTIVE = "policy:active"
CACHE_POLICY_TTL = 60
CACHE_IP_REP_PREFIX = "ip_rep:"
CACHE_IP_REP_TTL = 86400       # 24h
CACHE_GEO_PREFIX = "geo:"
CACHE_GEO_TTL = 604800         # 7d
CACHE_JWKS = "jwks:keycloak"
CACHE_JWKS_TTL = 300           # 5min
CACHE_FEATURE_FLAGS = "feature_flags"
CACHE_FEATURE_FLAGS_TTL = 60
```

No imports needed. All values are plain strings and integers.

**Verify:** `cd shared && python3 -c "from naas_shared.constants import STREAM_LOGIN_EVENTS, CHANNEL_DECISIONS; print(STREAM_LOGIN_EVENTS, CHANNEL_DECISIONS)"` prints `login_events decisions`.

---

### Step 5: Create `shared/naas_shared/models.py`

**File:** `naas/shared/naas_shared/models.py`

Implement all Pydantic models from Spec 0, Section 3.4. These are the canonical pipeline message schemas. There are 7 models:

1. **`LoginEventBase(BaseModel)`** -- Schema for events entering the pipeline. Fields:
   - `user_id: str` (min_length=1, max_length=255)
   - `client_ip: str` (pattern for IPv4: `r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$"`)
   - `protocol: Literal["oidc", "saml", "ldap"]`
   - `timestamp: datetime`
   - `user_agent: Optional[str] = None`
   - `source: Literal["user", "simulator", "api"] = "user"`
   - `is_synthetic: bool = False`
   - `is_historical: bool = False`
   - `raw_attributes: Dict[str, Any] = Field(default_factory=dict)`

2. **`LoginEventIngest(LoginEventBase)`** -- Request body for POST /events/ingest. Empty body (inherits everything).

3. **`LoginEventRecord(LoginEventBase)`** -- Full event record after ingestion. Additional fields:
   - `id: UUID = Field(default_factory=uuid4)`
   - `event_id: str`
   - `normalized_attributes: Optional[Dict[str, Any]] = None`
   - `enriched_signals: Optional[Dict[str, Any]] = None`
   - `created_at: datetime = Field(default_factory=datetime.utcnow)`

4. **`NormalizedIdentity(BaseModel)`** -- Unified identity schema output. Fields:
   - `display_name: Optional[str] = None`
   - `primary_email: Optional[str] = None`
   - `department: Optional[str] = None`
   - `employee_type: Optional[Literal["FTE", "contractor", "vendor"]] = None`
   - `groups: list[str] = Field(default_factory=list)`
   - `source_protocol: Literal["oidc", "saml", "ldap"]`
   - `normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)`
   - `raw_source_attributes: Dict[str, Any] = Field(default_factory=dict)`

5. **`RiskDecision(BaseModel)`** -- Published to decisions Pub/Sub channel. Fields:
   - `event_id: str`
   - `user_id: str`
   - `rule_based_score: float`
   - `ml_based_score: Optional[float] = None`
   - `final_score: float`
   - `decision: Literal["allow", "step_up_mfa", "deny"]`
   - `contributing_factors: Dict[str, Any] = Field(default_factory=dict)`
   - `shadow_decision: Optional[str] = None`
   - `shadow_score: Optional[float] = None`
   - `is_historical: bool = False`
   - `timestamp: datetime`

6. **`AlertMessage(BaseModel)`** -- Published to alerts Pub/Sub channel. Fields:
   - `alert_id: str`
   - `event_id: str`
   - `user_id: str`
   - `severity: Literal["critical", "high", "medium", "low"]`
   - `title: str`
   - `decision: str`
   - `final_score: float`
   - `timestamp: datetime`

7. **`HealthResponse(BaseModel)`** -- Standard health check response. Fields:
   - `status: Literal["healthy", "degraded", "unhealthy"]`
   - `service: str`
   - `version: str = "2.0.0"`
   - `timestamp: datetime = Field(default_factory=datetime.utcnow)`

**Imports needed:**
- `from pydantic import BaseModel, Field, field_validator`
- `from datetime import datetime`
- `from typing import Literal, Dict, Any, Optional`
- `from uuid import UUID, uuid4`

Note: `field_validator` is imported per the spec but not used in any model currently. Include it anyway for downstream use.

**Verify:** `cd shared && python3 -c "from naas_shared.models import LoginEventIngest, NormalizedIdentity, RiskDecision, AlertMessage, HealthResponse; print('All models importable')"` prints `All models importable`.

---

### Step 6: Create `shared/naas_shared/logging.py`

**File:** `naas/shared/naas_shared/logging.py`

Implement the structlog configuration exactly from Spec 0, Section 3.7:

- Function `setup_logging(service_name: str, log_level: str = "INFO") -> None` that configures structlog with:
  - Processors: `merge_contextvars`, `add_log_level`, `TimeStamper(fmt="iso")`, `StackInfoRenderer()`, `format_exc_info`, `JSONRenderer()`
  - `wrapper_class`: `make_filtering_bound_logger` using the log_level
  - `context_class`: `dict`
  - `logger_factory`: `PrintLoggerFactory(file=sys.stdout)`
  - `cache_logger_on_first_use`: `True`

- Function `get_logger(name: str = None) -> structlog.BoundLogger` that returns `structlog.get_logger(name or __name__)`

**Imports needed:**
- `import structlog`
- `import logging`
- `import sys`

**Verify:** `cd shared && python3 -c "from naas_shared.logging import setup_logging, get_logger; setup_logging('test'); log = get_logger('test'); log.info('hello', correlation_id='abc')"` prints a JSON log line to stdout.

---

### Step 7: Create `shared/naas_shared/database.py`

**File:** `naas/shared/naas_shared/database.py`

Implement the async SQLAlchemy engine and session factory exactly from Spec 0, Section 3.5:

- Module-level globals: `_engine = None`, `_session_factory = None`

- Function `get_engine()`:
  - Creates `AsyncEngine` via `create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)` on first call
  - Returns cached engine on subsequent calls

- Function `get_session_factory() -> async_sessionmaker[AsyncSession]`:
  - Creates `async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)` on first call
  - Returns cached factory on subsequent calls

- Async generator `get_db_session() -> AsyncSession`:
  - FastAPI dependency that yields a session
  - Commits on success, rolls back on exception

**Imports needed:**
- `from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker`
- `from naas_shared.config import get_settings`

**Verify:** `cd shared && python3 -c "from naas_shared.database import get_engine, get_session_factory, get_db_session; print('Database module importable')"` prints `Database module importable`. (Will not connect to a real DB since we are outside Docker; import verification is sufficient.)

---

### Step 8: Create `shared/naas_shared/redis_client.py`

**File:** `naas/shared/naas_shared/redis_client.py`

Implement the Redis connection and helpers exactly from Spec 0, Section 3.6:

- Module-level global: `_redis = None`

- Async function `get_redis() -> aioredis.Redis`:
  - Creates Redis connection via `aioredis.from_url(f"redis://{settings.redis_host}:{settings.redis_port}", decode_responses=True)` on first call
  - Returns cached connection on subsequent calls

- Async function `publish_to_stream(stream: str, data: dict) -> str`:
  - Calls `r.xadd(stream, {"data": json.dumps(data)}, maxlen=STREAM_MAXLEN)`
  - Returns the message ID

- Async function `publish_to_channel(channel: str, data: dict) -> int`:
  - Calls `r.publish(channel, json.dumps(data))`
  - Returns subscriber count

- Async function `ensure_consumer_group(stream: str, group: str) -> None`:
  - Calls `r.xgroup_create(stream, group, id="0", mkstream=True)`
  - Catches `ResponseError` and suppresses if `"BUSYGROUP"` is in the message (group already exists)
  - Re-raises any other `ResponseError`

**Imports needed:**
- `import redis.asyncio as aioredis`
- `from naas_shared.config import get_settings`
- `from naas_shared.constants import STREAM_MAXLEN`
- `import json`

**Verify:** `cd shared && python3 -c "from naas_shared.redis_client import get_redis, publish_to_stream, publish_to_channel, ensure_consumer_group; print('Redis module importable')"` prints `Redis module importable`.

---

### Step 9: Create `shared/naas_shared/schemas.py` (placeholder)

**File:** `naas/shared/naas_shared/schemas.py`

Create a placeholder file as specified in Spec 0, Architect's Review Notes, Gap 5:

```python
# ORM table definitions - populated by Spec 1 when first needed.
# SQLAlchemy ORM models for the NAAS database tables.
# See infrastructure/postgres/init.sql for the canonical DDL.
```

This is intentionally empty of class definitions. ORM models are deferred to Spec 1.

**Verify:** `cd shared && python3 -c "import naas_shared.schemas; print('Schemas placeholder importable')"` exits without error.

---

### Step 10: Install and run full import verification

**Commands:**

First, install the shared library in editable mode (outside Docker, for local verification):

```bash
cd /path/to/naas
pip install -e shared/
```

Then run the comprehensive import test from Spec 0, Section 6.6:

```bash
cd shared && python3 -c "
from naas_shared.config import get_settings
from naas_shared.models import LoginEventIngest, RiskDecision, AlertMessage
from naas_shared.constants import STREAM_LOGIN_EVENTS, CHANNEL_DECISIONS
from naas_shared.logging import setup_logging

setup_logging('test')
s = get_settings()
print(f'DB URL: {s.database_url}')
print(f'Stream: {STREAM_LOGIN_EVENTS}')
print('All imports OK')
"
```

**Expected output:**
```
DB URL: postgresql+asyncpg://naas:naas_dev_password@postgres:5432/naas
Stream: login_events
All imports OK
```

Also verify every individual module can import without circular dependency issues:

```bash
cd shared && python3 -c "
from naas_shared.database import get_db_session, get_engine
from naas_shared.redis_client import get_redis, publish_to_stream, publish_to_channel, ensure_consumer_group
from naas_shared.models import LoginEventBase, LoginEventIngest, LoginEventRecord, NormalizedIdentity, RiskDecision, AlertMessage, HealthResponse
from naas_shared.logging import setup_logging, get_logger
from naas_shared.config import get_settings
from naas_shared.constants import (
    STREAM_LOGIN_EVENTS, STREAM_NORMALIZED_EVENTS, STREAM_ENRICHED_EVENTS,
    CHANNEL_DECISIONS, CHANNEL_ALERTS,
    GROUP_NORMALIZATION, GROUP_ENRICHMENT, GROUP_EVALUATOR,
)
print('All shared imports verified successfully')
"
```

This is the exact import list from Spec 0, Section 4. Every line must work.

---

## naas_shared Imports Needed

This chunk IS the naas_shared library. No external naas_shared imports needed.

---

## Done When

All of the following pass:

1. `ls shared/naas_shared/` shows 8 files: `__init__.py`, `config.py`, `constants.py`, `models.py`, `database.py`, `redis_client.py`, `logging.py`, `schemas.py`
2. `pip install -e shared/` succeeds without errors
3. The full import test from Spec 0, Section 6.6 prints `All imports OK` with no errors
4. The comprehensive import test (all imports from Section 4) prints `All shared imports verified successfully`
5. No circular import errors when importing any module individually
6. Infrastructure containers from chunks 0 and 1 are unaffected (still running if up)

---

## Next Chunk Preview

Chunk 3 creates the service directory placeholders (8 services with README.md each) and runs the full integration smoke test covering all Spec 0 validation criteria end-to-end. **Do NOT proceed to chunk 3 until all "Done When" criteria above are verified.**
