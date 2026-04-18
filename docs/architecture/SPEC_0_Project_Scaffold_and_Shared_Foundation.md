# Spec 0: Project Scaffold & Shared Foundation

**NAAS — Normalized Adaptive Access System**
**Spec Version:** 1.1 (Updated February 2026)
**Target Agent:** Claude Code
**Depends On:** Nothing (this is the foundation)
**Depended On By:** All subsequent specs (1–6)

---

## 1. Scope Boundary

This spec creates the project skeleton, infrastructure containers, database schema, identity provider configs, and the shared Python library that every downstream service imports. After this spec is complete, `docker-compose up` should bring up a working infrastructure stack with no application services yet.

### Files and Directories Created

```
naas/
├── docker-compose.yml
├── .env.example
├── .env                              # Copy of .env.example (gitignored)
├── .gitignore
├── CLAUDE.md                         # Agent reference (copy from project docs)
├── README.md                         # Minimal quick-start placeholder
├── infrastructure/
│   ├── postgres/
│   │   └── init.sql                  # Full DDL: all tables, indexes, extensions
│   ├── redis/
│   │   └── redis.conf                # Custom Redis config (maxmemory, streams)
│   ├── keycloak/
│   │   └── naas-realm-export.json    # Realm import file (realm, client, users)
│   └── openldap/
│       └── bootstrap.ldif            # OU structure + test users
├── shared/
│   ├── pyproject.toml                # Package metadata (installable via pip -e)
│   └── naas_shared/
│       ├── __init__.py
│       ├── database.py               # Async SQLAlchemy engine + session factory
│       ├── redis_client.py           # Redis connection, stream helpers, pub/sub helpers
│       ├── models.py                 # Base Pydantic models (LoginEvent, etc.)
│       ├── schemas.py                # SQLAlchemy ORM table definitions
│       ├── logging.py                # Structlog configuration
│       ├── config.py                 # Pydantic Settings (env-driven config)
│       └── constants.py              # Stream names, channel names, consumer groups
        └── simulation_tools.py       # Shared tool definitions + ToolExecutor (P0: definitions, P2: executor)
└── services/                         # Empty subdirs with placeholder READMEs
    ├── api-gateway/
    │   └── README.md
    ├── event-ingestion/
    │   └── README.md
    ├── identity-normalization/
    │   └── README.md
    ├── signal-enrichment/
    │   └── README.md
    ├── risk-evaluator/
    │   └── README.md
    ├── policy-management/
    │   └── README.md
    ├── alert-service/
    │   └── README.md
    └── persona-simulator/
        └── README.md
```

### Files NOT Created by This Spec

- No service `Dockerfile` files (each spec creates its own)
- No service `app/` directories or Python code inside `services/*/`
- No `dashboard/` directory (Spec 6)
- No `docs/` directory beyond README.md (Phase 6 polish)
- No monitoring stack (Prometheus/Grafana) — deferred to a polish pass

---

## 2. Input Contracts

Spec 0 has no upstream inputs. It IS the upstream. However, it defines contracts that all downstream specs consume.

### Environment Variables (`.env.example`)

```env
# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=naas
POSTGRES_PASSWORD=naas_dev_password
POSTGRES_DB=naas

# Keycloak (also uses PG — separate DB auto-created by Keycloak)
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
KEYCLOAK_DB=keycloak

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# OpenLDAP
LDAP_HOST=openldap
LDAP_PORT=389
LDAP_BASE_DN=dc=corp,dc=com
LDAP_ADMIN_DN=cn=admin,dc=corp,dc=com
LDAP_ADMIN_PASSWORD=admin
LDAP_ORGANISATION=Corp Inc
LDAP_DOMAIN=corp.com
LDAP_POOL_SIZE=3                               # LDAP connection pool size for enrichment (normalization service)

# Service Ports
API_GATEWAY_PORT=8000
EVENT_INGESTION_PORT=8001
IDENTITY_NORMALIZATION_PORT=8002
SIGNAL_ENRICHMENT_PORT=8003
POLICY_MANAGEMENT_PORT=8004
RISK_EVALUATOR_PORT=8005
ALERT_SERVICE_PORT=8006
PERSONA_SIMULATOR_PORT=8007

# Dashboard
DASHBOARD_PORT=3000

# LLM Provider Configuration (Persona Simulator)
LLM_PROVIDER=mock                              # claude | ollama | mock
LLM_MODEL=claude-sonnet-4-20250514             # Model for Claude API
ANTHROPIC_API_KEY=                              # Required only if LLM_PROVIDER=claude
OLLAMA_URL=http://host.docker.internal:11434   # Ollama API URL (external to Docker)
OLLAMA_MODEL=llama3.1                          # Model for Ollama
SIMULATION_BATCH_SIZE=10                       # Events per LLM call for auto/bulk modes
SIMULATION_MAX_RATE=30                         # Max events per minute for auto mode

# Keycloak OIDC
KEYCLOAK_URL=http://keycloak:8080
KEYCLOAK_REALM=naas-demo
KEYCLOAK_CLIENT_ID=naas-dashboard
```

---

## 3. Output Contracts

This spec produces the infrastructure and shared code that every other spec relies on. The contracts below are **canonical** — downstream specs MUST NOT redefine them.

### 3.1 PostgreSQL Schema

All tables live in the default `public` schema of the `naas` database.

```sql
-- infrastructure/postgres/init.sql

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- EVENTS TABLE (core pipeline record)
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id VARCHAR(255) UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    protocol VARCHAR(10) NOT NULL CHECK (protocol IN ('oidc', 'saml', 'ldap')),
    client_ip INET NOT NULL,
    user_agent TEXT,
    timestamp TIMESTAMP NOT NULL,
    source VARCHAR(20) DEFAULT 'user' CHECK (source IN ('user', 'simulator', 'api')),
    is_synthetic BOOLEAN DEFAULT FALSE,
    is_historical BOOLEAN DEFAULT FALSE,
    raw_attributes JSONB,
    normalized_attributes JSONB,
    enriched_signals JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_user_id ON events(user_id);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_events_protocol ON events(protocol);

-- ============================================================
-- POLICIES TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    policy_id VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    is_shadow BOOLEAN DEFAULT FALSE,
    policy_yaml TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- RISK ASSESSMENTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS risk_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    policy_id UUID REFERENCES policies(id),
    rule_based_score FLOAT,
    ml_based_score FLOAT,
    final_score FLOAT NOT NULL,
    decision VARCHAR(20) NOT NULL CHECK (decision IN ('allow', 'step_up_mfa', 'deny')),
    shadow_decision VARCHAR(20),
    shadow_score FLOAT,
    contributing_factors JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_risk_assessments_event_id ON risk_assessments(event_id);
CREATE INDEX idx_risk_assessments_decision ON risk_assessments(decision);

-- ============================================================
-- ALERTS TABLE
-- ============================================================
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID REFERENCES events(id),
    assessment_id UUID REFERENCES risk_assessments(id),
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    title VARCHAR(500) NOT NULL,
    status VARCHAR(20) DEFAULT 'new' CHECK (status IN ('new', 'acknowledged', 'investigating', 'dismissed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_alerts_status ON alerts(status);

-- ============================================================
-- SEED DATA: Default policy
-- ============================================================
INSERT INTO policies (policy_id, name, version, is_active, is_shadow, policy_yaml) VALUES (
    'default-v1',
    'Default Risk Policy',
    '1.0.0',
    TRUE,
    FALSE,
    '
name: Default Risk Policy
version: "1.0.0"
description: Baseline risk evaluation policy for NAAS demo
is_shadow: false

signal_weights:
  ip_reputation_risk: 0.20
  normalization_risk: 0.15
  failed_login_risk: 0.15
  login_recency_risk: 0.10

conditions:
  - name: "impossible-travel"
    expression: "signals.impossible_travel"
    weight: 0.25
  - name: "contractor-after-hours"
    expression: "user.employee_type == ''contractor'' AND time.hour > 18"
    weight: 0.15
  - name: "unknown-device-off-network"
    expression: "NOT device.known_device AND NOT device.on_corporate_network"
    weight: 0.20
  - name: "known-device-off-network"
    expression: "device.known_device AND NOT device.on_corporate_network"
    weight: 0.05
  - name: "weekend-login"
    expression: "time.day_of_week >= 5"
    weight: 0.05
  - name: "foreign-contractor"
    expression: "user.employee_type == ''contractor'' AND signals.country != ''US''"
    weight: 0.15
  - name: "legacy-protocol-usage"
    expression: "event.protocol == ''ldap''"
    weight: 0.05
  - name: "dormant-account-login"
    expression: "signals.days_since_last_login > 90"
    weight: 0.10

thresholds:
  step_up_mfa: 0.3
  deny: 0.7

ensemble:
  rule_weight: 0.6
  ml_weight: 0.4
'
) ON CONFLICT (policy_id) DO NOTHING;
```

**⚠️ SQL string escaping:** Single quotes inside the YAML string literals must be escaped as `''` (doubled) in the SQL INSERT statement. The expression `user.employee_type == 'contractor'` becomes `user.employee_type == ''contractor''` inside the SQL string. This is standard PostgreSQL string escaping.

**⚠️ CRITICAL:** Keycloak needs its own database. The `init.sql` must also create the Keycloak database:

```sql
-- This goes at the TOP of init.sql, before the naas tables.
-- PostgreSQL docker entrypoint runs init scripts against POSTGRES_DB.
-- Keycloak needs its own database on the same server.
-- Create it here so we don't need a second PG instance.

-- NOTE: CREATE DATABASE cannot run inside a transaction block.
-- The docker entrypoint handles this. Use a separate init script or
-- configure Keycloak to use its own internal H2 in dev mode.
```

**ARCHITECT'S NOTE — Keycloak DB Strategy:**

There are two clean approaches here, and I want to flag this because getting it wrong wastes hours:

**Option A (Recommended): Let Keycloak use its built-in H2 dev database.** Since we run `start-dev`, Keycloak will use an embedded H2 database automatically. Zero config. The data is ephemeral (lost on container restart), but that's fine for a demo project — we import the realm on every start anyway.

**Option B: Shared PostgreSQL with separate database.** Requires a custom init script that creates a `keycloak` database before Keycloak starts. This adds complexity for no demo benefit.

**Decision: Use Option A.** Remove `KC_DB*` environment variables from the Keycloak container. Let it default to H2 dev mode. This eliminates an entire class of startup-ordering bugs.

### 3.2 Redis Configuration

```conf
# infrastructure/redis/redis.conf
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
```

No custom stream configuration needed at startup. Streams are lazily created by producers (XADD auto-creates).

### 3.3 Redis Stream and Channel Names (Constants)

Defined in `shared/naas_shared/constants.py` — the single source of truth:

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

### 3.4 Shared Pydantic Models

These are the **canonical** pipeline message schemas. Every service MUST use these when publishing to or consuming from Redis Streams.

```python
# shared/naas_shared/models.py
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from typing import Literal, Dict, Any, Optional
from uuid import UUID, uuid4


class LoginEventBase(BaseModel):
    """Schema for events entering the pipeline via ingestion."""
    user_id: str = Field(..., min_length=1, max_length=255)
    client_ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    protocol: Literal["oidc", "saml", "ldap"]
    timestamp: datetime
    user_agent: Optional[str] = None
    source: Literal["user", "simulator", "api"] = "user"
    is_synthetic: bool = False
    is_historical: bool = False
    raw_attributes: Dict[str, Any] = Field(default_factory=dict)


class LoginEventIngest(LoginEventBase):
    """Request body for POST /events/ingest."""
    pass


class LoginEventRecord(LoginEventBase):
    """Full event record after ingestion (has IDs assigned)."""
    id: UUID = Field(default_factory=uuid4)
    event_id: str
    normalized_attributes: Optional[Dict[str, Any]] = None
    enriched_signals: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class NormalizedIdentity(BaseModel):
    """Unified identity schema output from normalization."""
    display_name: Optional[str] = None
    primary_email: Optional[str] = None
    department: Optional[str] = None
    employee_type: Optional[Literal["FTE", "contractor", "vendor"]] = None
    groups: list[str] = Field(default_factory=list)
    source_protocol: Literal["oidc", "saml", "ldap"]
    normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    raw_source_attributes: Dict[str, Any] = Field(default_factory=dict)


class RiskDecision(BaseModel):
    """Published to decisions Pub/Sub channel."""
    event_id: str
    user_id: str
    rule_based_score: float
    ml_based_score: Optional[float] = None
    final_score: float
    decision: Literal["allow", "step_up_mfa", "deny"]
    contributing_factors: Dict[str, Any] = Field(default_factory=dict)
    shadow_decision: Optional[str] = None
    shadow_score: Optional[float] = None
    is_historical: bool = False
    timestamp: datetime


class AlertMessage(BaseModel):
    """Published to alerts Pub/Sub channel."""
    alert_id: str
    event_id: str
    user_id: str
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    decision: str
    final_score: float
    timestamp: datetime


class HealthResponse(BaseModel):
    """Standard health check response for all services."""
    status: Literal["healthy", "degraded", "unhealthy"]
    service: str
    version: str = "2.0.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

### 3.5 Shared Database Module

```python
# shared/naas_shared/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from naas_shared.config import get_settings

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def get_db_session() -> AsyncSession:
    """FastAPI dependency for DB sessions."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 3.6 Shared Redis Module

```python
# shared/naas_shared/redis_client.py
import redis.asyncio as aioredis
from naas_shared.config import get_settings
from naas_shared.constants import STREAM_MAXLEN
import json

_redis = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}",
            decode_responses=True,
        )
    return _redis


async def publish_to_stream(stream: str, data: dict) -> str:
    """XADD to a Redis Stream. Returns the message ID."""
    r = await get_redis()
    msg_id = await r.xadd(stream, {"data": json.dumps(data)}, maxlen=STREAM_MAXLEN)
    return msg_id


async def publish_to_channel(channel: str, data: dict) -> int:
    """PUBLISH to a Redis Pub/Sub channel. Returns subscriber count."""
    r = await get_redis()
    return await r.publish(channel, json.dumps(data))


async def ensure_consumer_group(stream: str, group: str) -> None:
    """Create consumer group if it doesn't exist. Idempotent."""
    r = await get_redis()
    try:
        await r.xgroup_create(stream, group, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise
```

### 3.7 Shared Logging Module

```python
# shared/naas_shared/logging.py
import structlog
import logging
import sys


def setup_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure structlog for JSON output with correlation ID support."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get a structlog logger. Bind correlation_id in middleware."""
    return structlog.get_logger(name or __name__)
```

### 3.8 Shared Config Module

```python
# shared/naas_shared/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "naas"
    postgres_password: str = "naas_dev_password"
    postgres_db: str = "naas"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # LDAP
    ldap_host: str = "openldap"
    ldap_port: int = 389
    ldap_base_dn: str = "dc=corp,dc=com"
    ldap_admin_dn: str = "cn=admin,dc=corp,dc=com"
    ldap_admin_password: str = "admin"

    # Keycloak
    keycloak_url: str = "http://keycloak:8080"
    keycloak_realm: str = "naas-demo"
    keycloak_client_id: str = "naas-dashboard"

    # LLM Provider Configuration
    llm_provider: str = Field(default="mock", pattern="^(claude|ollama|mock)$")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    anthropic_api_key: Optional[str] = None
    ollama_url: str = Field(default="http://host.docker.internal:11434")
    ollama_model: str = Field(default="llama3.1")
    simulation_batch_size: int = Field(default=10, ge=1, le=50)
    simulation_max_rate: int = Field(default=30, ge=1, le=60)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """For Alembic or sync contexts."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

---

## 4. Shared Imports

This IS the shared imports spec. All subsequent specs import from `naas_shared`:

```python
# Every service's requirements.txt (or pyproject.toml) includes:
#   -e /app/shared   (mounted via Docker volume)

# Standard imports available to all services:
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
```

### Shared Library Installation Strategy

The `shared/` directory is a pip-installable package. In Docker, each service mounts it as a volume and installs it in editable mode:

```yaml
# docker-compose.yml pattern for each service:
volumes:
  - ./shared:/app/shared
```

```dockerfile
# Each service's Dockerfile:
COPY shared/ /app/shared/
RUN pip install -e /app/shared/
```

**⚠️ CRITICAL — Do not duplicate.** If you find yourself copy-pasting database connection code, Redis client code, Pydantic models, or structlog setup into a service, STOP. Import it from `naas_shared` instead. This is the entire point of this spec.

---

## 5. Implementation Requirements

### 5.1 Docker Compose Orchestration

```yaml
# docker-compose.yml
version: "3.8"

services:
  # ─── INFRASTRUCTURE ────────────────────────────────────
  postgres:
    image: postgres:17-alpine
    container_name: naas-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-naas}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-naas_dev_password}
      POSTGRES_DB: ${POSTGRES_DB:-naas}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./infrastructure/postgres/init.sql:/docker-entrypoint-initdb.d/01-init.sql
    networks:
      - naas-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-naas}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7.4-alpine
    container_name: naas-redis
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redis-data:/data
      - ./infrastructure/redis/redis.conf:/usr/local/etc/redis/redis.conf
    command: ["redis-server", "/usr/local/etc/redis/redis.conf"]
    networks:
      - naas-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    container_name: naas-keycloak
    environment:
      KEYCLOAK_ADMIN: ${KEYCLOAK_ADMIN:-admin}
      KEYCLOAK_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD:-admin}
    # No KC_DB* vars — use built-in H2 dev database (see Architect's Note §3.1)
    command: >
      start-dev --import-realm
    ports:
      - "8080:8080"
    volumes:
      - ./infrastructure/keycloak/naas-realm-export.json:/opt/keycloak/data/import/naas-realm-export.json
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - naas-network
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080 && echo -e 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && cat <&3 | grep -q '200\\|UP'"]
      interval: 30s
      timeout: 10s
      retries: 15
      start_period: 60s

  openldap:
    image: osixia/openldap:1.5.0
    container_name: naas-openldap
    environment:
      LDAP_ORGANISATION: ${LDAP_ORGANISATION:-Corp Inc}
      LDAP_DOMAIN: ${LDAP_DOMAIN:-corp.com}
      LDAP_ADMIN_PASSWORD: ${LDAP_ADMIN_PASSWORD:-admin}
    ports:
      - "389:389"
      - "636:636"
    volumes:
      - ldap-data:/var/lib/ldap
      - ldap-config:/etc/ldap/slapd.d
      - ./infrastructure/openldap/bootstrap.ldif:/container/service/slapd/assets/config/bootstrap/ldif/custom/bootstrap.ldif
    networks:
      - naas-network
    healthcheck:
      test: ["CMD", "ldapsearch", "-x", "-H", "ldap://localhost", "-b", "dc=corp,dc=com", "-D", "cn=admin,dc=corp,dc=com", "-w", "admin", "(objectClass=organization)"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 15s

  # ─── APPLICATION SERVICES ──────────────────────────────
  # Placeholder comments — each Spec (1-6) adds its own services here.
  # DO NOT add service containers in this spec.

networks:
  naas-network:
    driver: bridge

volumes:
  postgres-data:
  redis-data:
  ldap-data:
  ldap-config:
```

**⚠️ CRITICAL — Keycloak Healthcheck:**

The Keycloak healthcheck above uses a raw TCP approach. If this proves flaky, an acceptable alternative is:

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -sf http://localhost:8080/health/ready || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 15
  start_period: 60s
```

This requires `curl` to be available in the Keycloak image. The `quay.io/keycloak/keycloak:26.0` image is based on UBI (Red Hat Universal Base Image) and does NOT include curl by default. If the TCP-based healthcheck fails, use `start_period: 90s` with no `test` (rely on startup delay) or switch to `depends_on` without `condition: service_healthy` and add a retry loop in downstream services.

**Recommendation for Claude Code:** Start with the TCP healthcheck. If `docker-compose up` hangs waiting for Keycloak healthy, fall back to removing the healthcheck and using `start_period` only. Do NOT spend more than 20 minutes debugging Keycloak healthchecks.

### 5.2 Keycloak Realm Configuration

Create `infrastructure/keycloak/naas-realm-export.json` — a Keycloak realm import file.

The realm import should configure:

- **Realm:** `naas-demo`
- **Client:** `naas-dashboard`
  - Client Protocol: `openid-connect`
  - Access Type: `public` (no client secret)
  - Standard Flow Enabled: `true`
  - Direct Access Grants Enabled: `true`
  - Valid Redirect URIs: `http://localhost:3000/*`
  - Web Origins: `http://localhost:3000`
- **Test Users** (3 minimum):

| Username | Email | First Name | Last Name | Password | Groups |
|----------|-------|-----------|-----------|----------|--------|
| alice | alice@corp.com | Alice | Smith | password123 | engineering |
| bob | bob@corp.com | Bob | Jones | password123 | product |
| charlie | charlie@corp.com | Charlie | Brown | password123 | security |

**⚠️ CRITICAL — Realm Export Format:**

The JSON file must conform to Keycloak's realm representation format. The key structure:

```json
{
  "realm": "naas-demo",
  "enabled": true,
  "sslRequired": "none",
  "registrationAllowed": false,
  "clients": [
    {
      "clientId": "naas-dashboard",
      "enabled": true,
      "publicClient": true,
      "standardFlowEnabled": true,
      "directAccessGrantsEnabled": true,
      "redirectUris": ["http://localhost:3000/*"],
      "webOrigins": ["http://localhost:3000"],
      "protocol": "openid-connect"
    }
  ],
  "users": [
    {
      "username": "alice",
      "enabled": true,
      "email": "alice@corp.com",
      "firstName": "Alice",
      "lastName": "Smith",
      "credentials": [
        {
          "type": "password",
          "value": "password123",
          "temporary": false
        }
      ],
      "groups": ["engineering"]
    }
    // ... bob, charlie similarly
  ],
  "groups": [
    {"name": "engineering"},
    {"name": "product"},
    {"name": "security"}
  ]
}
```

**Generation approach:** Rather than hand-writing this large JSON (easy to get wrong), Claude Code should either:

1. Use the Keycloak Admin REST API after startup to create realm/client/users programmatically via a setup script, OR
2. Write the JSON realm export file directly (preferred — simpler, no startup dependency)

If using approach 2, verify the format against Keycloak's documentation. Key pitfall: Keycloak `--import-realm` expects the file in `/opt/keycloak/data/import/`. The `command: start-dev --import-realm` flag tells Keycloak to import on startup.

### 5.3 OpenLDAP Bootstrap Data

```ldif
# infrastructure/openldap/bootstrap.ldif
# NOTE: The osixia/openldap image auto-creates dc=corp,dc=com from LDAP_DOMAIN.
# This file adds the OU and users underneath.

dn: ou=users,dc=corp,dc=com
objectClass: organizationalUnit
ou: users

dn: ou=groups,dc=corp,dc=com
objectClass: organizationalUnit
ou: groups

dn: uid=alice,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Alice Smith
sn: Smith
mail: alice@corp.com
uid: alice
userPassword: password123
departmentNumber: Engineering
employeeType: FTE

dn: uid=bob,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Bob Jones
sn: Jones
mail: bob@corp.com
uid: bob
userPassword: password123
departmentNumber: Product
employeeType: FTE

dn: uid=charlie,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Charlie Brown
sn: Brown
mail: charlie@corp.com
uid: charlie
userPassword: password123
departmentNumber: Security
employeeType: contractor

dn: uid=diana,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Diana Prince
sn: Prince
mail: diana@corp.com
uid: diana
userPassword: password123
departmentNumber: Engineering
employeeType: vendor

dn: uid=eve,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Eve Torres
sn: Torres
mail: eve@partner.com
uid: eve
userPassword: password123
departmentNumber: External
employeeType: contractor
```

**Note:** 5 users instead of 3 in LDAP to demonstrate variety in `employeeType` (FTE, contractor, vendor) which feeds the normalization layer. The same alice/bob/charlie exist in both Keycloak and OpenLDAP — this is intentional to show cross-protocol identity correlation.

### 5.4 Shared Python Package Structure

```toml
# shared/pyproject.toml
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

### 5.5 .gitignore

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/

# Environment
.env

# IDE
.vscode/
.idea/
*.swp
*.swo

# Docker
postgres-data/
redis-data/

# OS
.DS_Store
Thumbs.db

# Node (dashboard)
node_modules/
dashboard/dist/

# ML models
*.pkl
*.joblib

# Logs
*.log
```

### 5.6 Service Directory Placeholders

Create empty service directories with a README.md placeholder in each:

```markdown
# {Service Name}

Part of the NAAS system. Implementation defined in Spec {N}.

See `docs/architecture/SYSTEM_ARCHITECTURE.md` for architectural context.
```

This ensures the directory structure exists for subsequent specs and makes `git` track the directories.

---

## 6. Validation Criteria

Run these checks after implementation to verify success.

### 6.1 Docker Compose Starts Clean

```bash
# From the naas/ root directory:
docker-compose up -d

# Wait for all services to be healthy (may take 60-90s for Keycloak):
docker-compose ps

# Expected: postgres (healthy), redis (healthy), keycloak (healthy or running), openldap (healthy)
```

### 6.2 PostgreSQL Schema Exists

```bash
docker exec -it naas-postgres psql -U naas -d naas -c "\dt"

# Expected output should list: users, events, policies, risk_assessments, alerts
```

```bash
# Verify default policy was seeded:
docker exec -it naas-postgres psql -U naas -d naas -c "SELECT policy_id, name, is_active FROM policies;"

# Expected: default-v1 | Default Risk Policy | t
```

### 6.3 Redis Responds

```bash
docker exec -it naas-redis redis-cli ping
# Expected: PONG

docker exec -it naas-redis redis-cli CONFIG GET maxmemory
# Expected: "256mb" (or equivalent bytes)
```

### 6.4 Keycloak OIDC Discovery Works

```bash
curl -s http://localhost:8080/realms/naas-demo/.well-known/openid-configuration | python3 -m json.tool

# Expected: JSON with authorization_endpoint, token_endpoint, jwks_uri, etc.
```

```bash
# Verify token endpoint works (direct access grant):
curl -s -X POST http://localhost:8080/realms/naas-demo/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=naas-dashboard" \
  -d "username=alice" \
  -d "password=password123" | python3 -m json.tool

# Expected: JSON with access_token, refresh_token, token_type, etc.
```

### 6.5 OpenLDAP Returns Test Users

```bash
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(uid=alice)"

# Expected: dn, cn, sn, mail, uid, departmentNumber, employeeType for alice
```

```bash
# Count all users:
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "ou=users,dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(objectClass=inetOrgPerson)" dn | grep "numEntries"

# Expected: 5 entries
```

### 6.6 Shared Library Importable

```bash
# Test that the shared library is valid Python:
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

### 6.7 Clean Shutdown

```bash
docker-compose down -v
# Expected: All containers stopped, volumes removed, no errors
```

---

## 7. What NOT to Build

This section exists because AI agents love to be helpful, which sometimes means building things nobody asked for.

- **Do NOT create any service application code.** No `app/main.py`, no `Dockerfile`, no `requirements.txt` inside any `services/*/` directory. Only the placeholder `README.md`.
- **Do NOT create the React dashboard.** No `dashboard/` directory beyond what's in the file tree above.
- **Do NOT set up Prometheus or Grafana.** Monitoring is deferred. Do not create `infrastructure/monitoring/`.
- **Do NOT create Alembic migrations.** The `init.sql` handles schema creation. Alembic is unnecessary for a demo project.
- **Do NOT create CI/CD pipelines.** No `.github/workflows/`.
- **Do NOT create test files.** No `tests/` directories, no `pytest.ini`, no `conftest.py`. Testing comes with each service spec.
- **Do NOT add Nginx or Traefik.** No reverse proxy. The API Gateway (Spec 5) handles routing.
- **Do NOT install the shared library globally.** It's installed in editable mode inside each service's container. Local development can use `pip install -e shared/` from the repo root.
- **Do NOT create a Makefile.** Docker Compose commands are sufficient.
- **Do NOT add docker-compose profiles or override files.** One `docker-compose.yml` is enough.
- **Do NOT pre-create Redis Streams or consumer groups.** Streams are created lazily by XADD. Consumer groups are created by each service on startup via `ensure_consumer_group()`.

---

## Architect's Review Notes

### Gaps Identified and Resolved

**Gap 1: Keycloak Database Coupling.**
The Implementation Guide shows Keycloak sharing the same PostgreSQL instance with `KC_DB` env vars. This creates a startup ordering problem and adds `init.sql` complexity. **Resolution:** Use Keycloak's built-in H2 dev database (see §3.1). Simpler, no cross-dependency, and the realm is imported fresh on every start anyway.

**Gap 2: Missing `user_agent` column in events table.**
The SYSTEM_ARCHITECTURE.md lists `user_agent TEXT` in the events schema, but the Implementation Guide's `init.sql` snippet omits it. **Resolution:** Included in this spec's DDL.

**Gap 3: Shadow mode columns in risk_assessments.**
SYSTEM_ARCHITECTURE.md defines `shadow_decision` and `shadow_score` columns, but the Implementation Guide's DDL omits them. **Resolution:** Included in this spec's DDL.

**Gap 4: Shared library packaging.**
The project documents mention a `shared/` library but never specify how it's packaged or installed. **Resolution:** This spec defines it as a pip-installable package with `pyproject.toml`, installed via `pip install -e /app/shared/` in each service's Dockerfile.

**Gap 5: No SQLAlchemy ORM models defined.**
The shared library needs ORM table definitions for services that do database writes/reads. **Resolution:** Added `schemas.py` to the file tree. However, implementation of the ORM models is deferred to Spec 1 (which first needs them), since defining ORM models without a consumer is premature. The `schemas.py` file should be created as an empty placeholder with a comment: `# ORM table definitions — populated by Spec 1 when first needed`.

**Gap 6: OpenLDAP LDIF format sensitivity.**
The `osixia/openldap` image has specific requirements for custom LDIF files. The file must NOT include the base DN entry (`dc=corp,dc=com`) — the image creates it automatically from `LDAP_DOMAIN`. Including it causes a "Already exists" error that silently skips the rest of the file. **Resolution:** LDIF in this spec starts at `ou=users` level.

### Areas Requiring Extra Care

1. **Keycloak realm JSON format.** The `--import-realm` flag is picky about JSON structure. If realm import fails silently, the OIDC discovery endpoint will 404. Always verify with the curl check in §6.4 after startup. If it fails, check `docker-compose logs keycloak` for import errors.

2. **OpenLDAP LDIF ordering.** Parent entries (OUs) must appear before child entries (users). LDIF is order-sensitive. The `bootstrap.ldif` in this spec is correctly ordered.

3. **async Redis client vs sync.** The shared library uses `redis.asyncio` (aliased as `aioredis`). Some services may need sync Redis calls during startup (e.g., creating consumer groups). Use `asyncio.run()` wrapper or call setup in the FastAPI `lifespan` event. Do NOT import `redis` (sync) separately — keep everything async.

4. **Docker network DNS.** Inside containers, services reference each other by service name (`postgres`, `redis`, `keycloak`, `openldap`), not `localhost`. The `.env.example` defaults reflect this. When running the shared library tests OUTSIDE Docker (bare metal), override these with `localhost` via environment variables.

5. **The `shared/` volume mount.** When adding services in later specs, every service container MUST mount `./shared:/app/shared` and install it. Forgetting this mount means imports fail with `ModuleNotFoundError: No module named 'naas_shared'`. This is the #1 predicted failure mode across specs.

---

*End of Spec 0.*
