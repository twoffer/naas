# NAAS v2.0: Tech Stack Specification
## Complete Technology Choices with Rationale

**Document Date:** February 10, 2026 (Updated)  
**Budget Constraint:** ≤ $25/month deployment cost  
**Status:** Finalized

---

## Table of Contents

1. [Stack Overview](#stack-overview)
2. [Backend Services](#backend-services)
3. [Frontend](#frontend)
4. [Data Layer](#data-layer)
5. [Infrastructure & DevOps](#infrastructure--devops)
6. [External Services](#external-services)
7. [AI/ML Components](#aiml-components)
8. [Development Tools](#development-tools)
9. [Cost Breakdown](#cost-breakdown)
10. [Architectural Decision Records](#architectural-decision-records)

---

## Stack Overview

### Technology Philosophy

**Guiding Principles:**
1. **Python-First**: Leverage IAM ecosystem, ML integration, async performance
2. **Enterprise Patterns**: Demonstrate production-grade thinking
3. **Modern but Proven**: Avoid bleeding-edge (risk) or ancient (irrelevant)
4. **Cost-Conscious**: Free/open-source where possible, minimal cloud costs
5. **Developer Experience**: Tools that enhance productivity at 8-10 hours/week

### Stack Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend Layer                           │
│  React 19 + TypeScript + Vite + Tailwind CSS               │
│  TanStack Query + React Flow + Recharts                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓ (REST + WebSocket)
┌─────────────────────────────────────────────────────────────┐
│                   Backend Layer                             │
│  Python 3.12+ with FastAPI 0.115+                          │
│  Pydantic 2.10+ + SQLAlchemy 2.0 (async)                   │
│  Structlog 23.2+ + Prometheus Client                       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Data Layer                               │
│  PostgreSQL 17+ (primary database)                         │
│  Redis 7.4+ (streams, pub/sub, caching)                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                 Infrastructure                              │
│  Docker + Docker Compose                                   │
│  Keycloak 26+ (OIDC provider)                              │
│  OpenLDAP 2.6+ (legacy directory)                          │
│  Prometheus 2.54+ + Grafana 11+ (monitoring)               │
└─────────────────────────────────────────────────────────────┘
```

---

## Backend Services

### Language: Python 3.12+

**Why Python (Not Java/Go/Rust):**

**Advantages:**
- ✅ **IAM Ecosystem**: Best libraries for OIDC (Authlib), SAML (python3-saml), LDAP (ldap3)
- ✅ **ML Integration**: Native scikit-learn, pandas for data manipulation
- ✅ **Async Performance**: FastAPI + async/await rivals Go for I/O-bound workloads
- ✅ **Development Speed**: 2-3x faster than Java for same functionality
- ✅ **Type Safety**: Pydantic + mypy provide runtime + static type checking

**Enterprise Credibility:**
- Dropbox: Identity services (Python)
- Instagram: Auth at 1B+ users (Python)
- Netflix: Security services (Python)
- Okta/Auth0: Parts of platform (Python)

**Mitigation for "Not Enterprise Enough" Perception:**
1. Strict typing (Pydantic everywhere, mypy in CI)
2. Hexagonal architecture (ports & adapters)
3. Comprehensive docs (ADR explaining choice)
4. Production patterns (observability, error handling)

**Version:** 3.12+ (improved performance over 3.11, better error messages, stable ecosystem support)

---

### Web Framework: FastAPI 0.115+

**Why FastAPI (Not Flask/Django):**

| Feature | FastAPI | Flask | Django |
|---------|---------|-------|--------|
| Async-first | ✅ Native | ⚠️ Extensions | ⚠️ Immature |
| OpenAPI docs | ✅ Automatic | ❌ Manual | ❌ Manual |
| Type safety | ✅ Pydantic | ❌ No | ❌ No |
| WebSocket | ✅ Built-in | ⚠️ flask-socketio | ⚠️ Channels |
| Performance | ✅ High | ⚠️ Medium | ⚠️ Medium |
| Microservices | ✅ Perfect | ✅ Good | ❌ Monolithic |

**Why It Matters for NAAS:**
- **Async I/O**: NAAS services are I/O-bound (database, Redis, external APIs)
- **OpenAPI**: Automatic Swagger UI for each microservice (professional)
- **WebSocket**: API Gateway needs real-time updates (built-in)
- **Type Safety**: Pydantic integration prevents bugs

**Version:** 0.115+ (includes security patches, Starlette upgrades, Python 3.9+ syntax)

**Alternatives Considered:**
- **Flask**: Too manual for microservices (no auto-docs, weaker async)
- **Django**: Too heavy for microservices, monolithic philosophy
- **Go (Gin/Echo)**: Requires learning new language, smaller IAM ecosystem
- **Node.js (Express)**: Callback hell, weaker typing, not Python ML ecosystem

---

### ORM: SQLAlchemy 2.0 (Async Mode)

**Why SQLAlchemy:**
- ✅ Mature, battle-tested (15+ years)
- ✅ Async support in 2.0 (non-blocking database I/O)
- ✅ Powerful query API
- ✅ Alembic for migrations
- ✅ Industry standard for Python

**Async Pattern:**
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

engine = create_async_engine("postgresql+asyncpg://...")

async with AsyncSession(engine) as session:
    result = await session.execute(select(User).where(...))
    users = result.scalars().all()
```

**Why Async Matters:**
- NAAS services handle 10+ concurrent requests
- Blocking I/O would limit throughput
- Async enables efficient resource usage

**Version:** 2.0+ (async-first API)

---

### Validation: Pydantic 2.10+

**Why Pydantic:**
- ✅ Runtime validation (catches bad data at API boundary)
- ✅ Type hints (IDE autocomplete, mypy static checking)
- ✅ JSON schema generation (automatic OpenAPI docs)
- ✅ FastAPI native integration

**Example Usage:**
```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal

class LoginEvent(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=255)
    client_ip: str = Field(..., pattern=r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
    protocol: Literal["oidc", "saml", "ldap"]
    timestamp: datetime
    
    @field_validator("client_ip")
    def validate_ip(cls, v):
        # Custom validation logic
        return v
```

**Benefits:**
- API requests auto-validated (400 error if invalid)
- Type safety end-to-end (database → API → frontend)
- Self-documenting (schema in code)

**Version:** 2.10+ (significant performance improvements: up to 2x faster schema builds, 2-5x memory reduction)

---

### Logging: Structlog 23.2+

**Why Structured Logging:**

**Bad Logging (String Concatenation):**
```python
logger.info(f"User {user_id} logged in from {ip} at {timestamp}")
```
**Problem:** Can't query, can't alert on specific fields

**Good Logging (Structured):**
```python
logger.info(
    "user_login",
    user_id=user_id,
    client_ip=ip,
    timestamp=timestamp,
    protocol="oidc"
)
```
**Output (JSON):**
```json
{
  "event": "user_login",
  "user_id": "alice@corp.com",
  "client_ip": "203.0.113.42",
  "timestamp": "2025-11-24T10:30:00Z",
  "protocol": "oidc",
  "correlation_id": "abc-123-def",
  "service": "event-ingestion"
}
```

**Benefits:**
- Queryable in log aggregators (Elasticsearch, Loki)
- Correlation IDs for distributed tracing
- Machine-parseable (not human string parsing)

**Version:** 23.2+

---

### Monitoring: Prometheus Client

**Why Prometheus:**
- ✅ Industry standard for metrics
- ✅ Pull-based model (services expose `/metrics` endpoint)
- ✅ Powerful query language (PromQL)
- ✅ Grafana integration (dashboards)

**Key Metrics for NAAS:**
```python
from prometheus_client import Counter, Histogram, Gauge

# Event throughput
events_ingested = Counter(
    'naas_events_ingested_total',
    'Total number of login events ingested',
    ['protocol', 'source']
)

# Latency
policy_evaluation_duration = Histogram(
    'naas_policy_evaluation_duration_seconds',
    'Time spent evaluating policy',
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
)

# Queue depth
enrichment_backlog = Gauge(
    'naas_enrichment_backlog',
    'Number of events waiting for enrichment'
)
```

**Grafana Dashboards:**
- RED metrics (Rate, Errors, Duration)
- Policy performance comparison
- Enrichment pipeline health

**Version:** Latest stable

---

### HTTP Client: httpx (Async)

**Why httpx (Not requests):**
- ✅ Async/await support (non-blocking)
- ✅ HTTP/2 support
- ✅ requests-compatible API (easy migration)
- ✅ Better timeout handling

**Usage:**
```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.get(
        "https://api.abuseipdb.com/v2/check",
        params={"ipAddress": ip},
        headers={"Key": api_key},
        timeout=5.0
    )
```

**Version:** Latest stable

---

## Frontend

### Framework: React 19

**Why React (Not Vue/Svelte):**
- ✅ Largest ecosystem (best libraries for NAAS needs)
- ✅ Excellent WebSocket support (custom hooks)
- ✅ TanStack Query (perfect for real-time data)
- ✅ Industry standard (most recognizable to evaluators)
- ✅ Best charting libraries (Recharts, Victory)

**Drawbacks:**
- ⚠️ More boilerplate than Vue/Svelte
- ⚠️ Requires more setup

**Why It's Worth It:**
- Protocol Flow Visualization: React Flow library (best-in-class)
- Real-time updates: useWebSocket hooks (mature)
- State management: TanStack Query (reduces boilerplate vs Redux)

**React 19 New Features (relevant to NAAS):**
- Actions API for form handling (policy management forms)
- useActionState hook for async state management
- useOptimistic for instant UI feedback
- Improved Server Components (future enhancement path)

**Version:** 19+ (stable since December 2024, with Actions API and new hooks)

---

### Language: TypeScript 5.x

**Why TypeScript (Not JavaScript):**
- ✅ Type safety (catch bugs at compile time)
- ✅ IDE autocomplete (faster development)
- ✅ Self-documenting (types = docs)
- ✅ Easier refactoring

**Given Your Comfort Level (Frontend: 1/5):**
TypeScript actually HELPS beginners:
- IDE tells you what's wrong immediately
- Autocomplete shows available properties
- Less runtime debugging

**Version:** 5.x

---

### Build Tool: Vite 6.0+

**Why Vite (Not Create React App/Webpack):**
- ✅ Lightning-fast HMR (hot module reload)
- ✅ Modern ESM-based architecture
- ✅ Smaller bundle sizes
- ✅ Better developer experience

**Speed Comparison:**
- CRA (Webpack): 30-60 seconds for cold start
- Vite: 2-5 seconds for cold start

**When You're Working 8-10 Hours/Week:**
Fast feedback loops matter. Vite saves 5-10 minutes per session.

**Version:** 6.0+ (or 5.x if 6.0 has ecosystem compatibility issues)

---

### State Management: TanStack Query 5.x

**Why TanStack Query (Not Redux/Zustand):**

**For NAAS, Most State is "Server State":**
- Current events (from API)
- Policy list (from API)
- Alert notifications (from API)

**TanStack Query Excels at Server State:**
- ✅ Auto-caching (don't re-fetch unnecessarily)
- ✅ Auto-refetching (keep data fresh)
- ✅ Loading/error states (built-in)
- ✅ Optimistic updates (UX responsiveness)
- ✅ Less boilerplate than Redux

**Example:**
```typescript
import { useQuery } from '@tanstack/react-query';

function PolicyList() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['policies'],
    queryFn: fetchPolicies,
    refetchInterval: 60000  // Auto-refresh every minute
  });
  
  if (isLoading) return <Spinner />;
  if (error) return <Error message={error.message} />;
  
  return <PolicyTable policies={data} />;
}
```

**Version:** 5.x

---

### UI Components: shadcn/ui or Ant Design

**Why Component Library (Not Custom CSS):**

**Your Constraint:** Frontend comfort: 1/5, 10-14 hours for entire dashboard

**Strategy:** Use pre-built components, customize minimally

**Option A: shadcn/ui**
- Modern, Tailwind-based
- Copy-paste components (no npm install bloat)
- Very customizable
- Trendy (impresses modern companies)

**Option B: Ant Design**
- Comprehensive component set
- Enterprise-proven
- Less customization needed
- More "corporate" look

**Recommendation: shadcn/ui**
- More modern aesthetic
- Better with Tailwind (less CSS conflicts)
- Impressive to show you know current tools

**Version:** Latest

---

### Styling: Tailwind CSS 3.4

**Why Tailwind (Not CSS Modules/Styled Components):**
- ✅ Utility-first (rapid development)
- ✅ No CSS file sprawl
- ✅ Consistent design system (spacing, colors)
- ✅ Works well with shadcn/ui

**Example:**
```tsx
<div className="flex items-center gap-4 p-4 bg-slate-100 rounded-lg">
  <span className="text-lg font-semibold text-slate-900">
    User: {user.name}
  </span>
</div>
```

**Version:** 3.4 (Tailwind 4.x is still in beta; stick with 3.4 for stability)

---

### Charts: Recharts 2.12+

**Why Recharts:**
- ✅ React-native (not wrapper around D3)
- ✅ Composable components
- ✅ Good documentation
- ✅ Active maintenance

**Example:**
```tsx
<LineChart data={riskScoreTrend}>
  <XAxis dataKey="timestamp" />
  <YAxis />
  <Line type="monotone" dataKey="score" stroke="#8884d8" />
</LineChart>
```

**Version:** 2.12+

---

### Visualization: React Flow

**For Protocol Flow Visualization:**
- ✅ Pre-built node/edge components
- ✅ Auto-layout algorithms
- ✅ Custom styling support
- ✅ Real-time updates

**Estimated Effort:** 5-6 hours (vs 15+ building from scratch)

**Version:** Latest

---

## Data Layer

### Primary Database: PostgreSQL 17+

**Why PostgreSQL (Not MySQL/MongoDB/Cassandra):**

| Feature | PostgreSQL | MongoDB | Cassandra |
|---------|-----------|---------|-----------|
| ACID transactions | ✅ Strong | ⚠️ Eventual | ⚠️ Eventual |
| JSON support | ✅ JSONB | ✅ Native | ❌ Limited |
| Relational queries | ✅ Excellent | ⚠️ Limited | ⚠️ Limited |
| Consistency | ✅ Strong | ⚠️ Eventual | ⚠️ Tunable |
| IAM use case fit | ✅ Perfect | ⚠️ Risky | ⚠️ Overkill |

**Why Strong Consistency Matters for IAM:**
- User credentials revoked → MUST reflect immediately
- Policy changes → MUST apply immediately
- Eventual consistency = security vulnerabilities

**JSONB for Flexibility:**
```sql
-- Store enriched signals as JSONB
CREATE TABLE events (
  id UUID PRIMARY KEY,
  user_id VARCHAR(255),
  protocol VARCHAR(10),
  raw_attributes JSONB,        -- Protocol-specific attributes
  normalized_attributes JSONB,  -- Unified schema
  enriched_signals JSONB        -- IP reputation, geo, etc.
);

-- Query JSONB fields
SELECT * FROM events 
WHERE normalized_attributes->>'department' = 'Engineering'
  AND enriched_signals->>'ip_reputation_score' > 0.7;
```

**Scaling:**
- 10 events/sec: Single instance (plenty)
- 100 events/sec: Single instance (still fine)
- 1000+ events/sec: Read replicas + partitioning

**Version:** 17+ (significant performance gains: overhauled memory management for vacuum, storage access optimizations, high concurrency improvements)

---

### Cache & Messaging: Redis 7.4+

**Why Redis (Not Kafka/RabbitMQ for messaging):**

**NAAS Uses Redis for Three Purposes:**

**1. Messaging (Redis Streams)**
- Event pipeline (ingestion → enrichment → evaluation)
- Consumer groups (parallel processing)
- Persistence (messages survive crashes)

**2. Pub/Sub (Redis Pub/Sub)**
- Real-time broadcasts (decisions → dashboard)
- Alert notifications
- No persistence needed (ephemeral)

**3. Caching (Redis Strings/Hashes)**
- IP reputation results (24h TTL)
- Policy cache (60s TTL)
- JWT public keys (5min TTL)

**Why Not Kafka?**
- Kafka: 100k+ events/sec, multi-datacenter replication
- NAAS: 10 events/sec, single datacenter
- Kafka: Complex (Zookeeper, 3+ brokers)
- Redis: Simple (single container)

**Scaling Path:**
- 0-1000 events/sec: Single Redis instance
- 1000-10000 events/sec: Redis Cluster (6 nodes)
- 10000+ events/sec: Migrate to Kafka

**Version:** 7.4+ (last version under BSD-style license before Redis 8's AGPLv3 option; stable and well-tested)

---

## Infrastructure & DevOps

### Containerization: Docker + Docker Compose

**Why Docker Compose (Not Kubernetes):**

**NAAS Requirements:**
- Local development (primary use case)
- 11 services to orchestrate
- Simple deployment (evaluators can run it)

**Docker Compose:**
- ✅ Single file configuration
- ✅ Easy local development (docker-compose up)
- ✅ No operational complexity
- ✅ Production-ready concepts (services, networks, volumes)

**Kubernetes:**
- ⚠️ Overkill for portfolio project
- ⚠️ Complex (control plane, YAML sprawl)
- ⚠️ Hard for evaluators to run locally
- ✅ Better for production (100+ services)

**Production Migration Path:**
Document in `docs/production-deployment-guide.md`:
> "NAAS uses Docker Compose for local development and demonstration. For production deployment at scale (1000+ events/sec), consider:
> - Kubernetes for orchestration
> - Redis Cluster for HA
> - PostgreSQL replicas for read scaling
> - AWS ECS/Fargate as simpler alternative to K8s"

**Version:** Latest stable

---

### OIDC Provider: Keycloak 26+

**Why Keycloak (Not Mock IDP):**
- ✅ Production-grade (Red Hat, widely used)
- ✅ Real OIDC implementation (not toy)
- ✅ Shows integration skills (vs building from scratch)
- ✅ Potential SAML support (future enhancement)
- ✅ MCP (Model Context Protocol) documentation (relevant for P2 features)

**Setup:**
```yaml
# docker-compose.yml
keycloak:
  image: quay.io/keycloak/keycloak:26.0
  environment:
    - KEYCLOAK_ADMIN=admin
    - KEYCLOAK_ADMIN_PASSWORD=admin
  command: start-dev
  ports:
    - "8080:8080"
```

**Configuration:**
- Realm: `naas-demo`
- Client: `naas-dashboard`
- Users: alice, bob, charlie (test accounts)
- Redirect URI: `http://localhost:3000/callback`

**Version:** 26+ (latest stable major version with backwards compatibility guarantees)

---

### Legacy Directory: OpenLDAP 2.6+

**Why OpenLDAP:**
- ✅ Most common open-source LDAP implementation
- ✅ Demonstrates legacy integration
- ✅ Easy to set up (Docker image available)

**Test Data:**
```ldif
dn: uid=alice,ou=users,dc=corp,dc=com
objectClass: inetOrgPerson
cn: Alice Smith
sn: Smith
mail: alice@corp.com
uid: alice
userPassword: password123
department: Engineering
employeeType: E
```

**Purpose:** Shows you can work with legacy systems

**Version:** 2.6+ (using osixia/openldap:1.5.0 Docker image)

---

### Monitoring: Prometheus 2.54+ + Grafana 11+

**Prometheus:**
- Pull-based metrics collection
- Scrapes `/metrics` endpoints from each service
- PromQL for queries
- Alerting rules

**Grafana:**
- Visualization (dashboards)
- Connects to Prometheus
- Pre-built dashboard templates

**Setup:**
```yaml
# docker-compose.yml
prometheus:
  image: prom/prometheus:v2.54.0
  volumes:
    - ./prometheus.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"

grafana:
  image: grafana/grafana:11.0.0
  ports:
    - "3001:3000"
  environment:
    - GF_SECURITY_ADMIN_PASSWORD=admin
```

**Dashboards to Create:**
- RED metrics (Rate, Errors, Duration)
- Policy performance comparison
- Enrichment pipeline health

**Version:** Prometheus 2.54+, Grafana 11+

---

## External Services

### IP Reputation: Multi-Provider with Fallback

**Strategy:** Free tiers + graceful degradation

**Primary:** AbuseIPDB
- Free tier: 1000 requests/day
- Sufficient for development/demo
- Cost: $0

**Secondary:** IPQualityScore
- Free tier: 5000 requests/month
- Fallback if AbuseIPDB quota exceeded
- Cost: $0

**Tertiary:** Mock Provider
- Returns random scores
- Used when APIs unavailable or quota exceeded
- Cost: $0

**Implementation:**
```python
class IPReputationService:
    def __init__(self):
        self.providers = [
            AbuseIPDBProvider(),
            IPQualityScoreProvider(),
            MockProvider()  # Always works
        ]
    
    async def get_reputation(self, ip: str) -> float:
        for provider in self.providers:
            try:
                result = await provider.check(ip)
                return result.score
            except Exception as e:
                logger.warning(f"{provider.name} failed", error=str(e))
                continue
        
        # All providers failed - should never reach here
        return 0.5  # Neutral score
```

**Cost: $0/month** (free tiers)

---

### Geolocation: MaxMind GeoLite2

**Free Tier:** GeoLite2 database
- Download database file (updates weekly)
- Local queries (no API costs)
- Accuracy: City-level (sufficient for NAAS)

**Setup:**
```python
import geoip2.database

reader = geoip2.database.Reader('/path/to/GeoLite2-City.mmdb')

response = reader.city('203.0.113.42')
print(response.city.name)        # "Mountain View"
print(response.country.name)     # "United States"
print(response.location.latitude)  # 37.386
```

**Cost: $0/month** (free tier)

---

## AI/ML Components

### LLM Integration: Claude API + Ollama + Mock Fallback

**Purpose:** Power the Persona Simulator's intelligent event generation with a transparent LLM provider chain.

**Architecture:** All providers implement the `SimulationProvider` interface. Events enter the pipeline via `EventSink` as a side effect of generation — providers never return raw event data. This design pre-primes for MCP tool-use integration (P2) where the LLM submits events via tools that wrap the same EventSink.

**Primary LLM: Claude API (Anthropic SDK)**
- Model: claude-sonnet-4-20250514 (configurable via `LLM_MODEL`)
- SDK: `anthropic` Python package (latest)
- P0: Structured JSON output, construct-then-submit via EventSink
- P2: Tool-use with shared `TOOL_DEFINITIONS` for context-aware generation
- Cost: ~$3 input / $15 output per 1M tokens
- Rate limits handled with exponential backoff (3 retries)

**Fallback LLM: Ollama (Local, P1)**
- Models: llama3.1 (default), mistral (alternative)
- HTTP API: `POST /api/generate` on local Ollama instance
- Free, offline development — no API costs
- Same construct-then-submit pattern via EventSink
- Runs outside Docker Compose (user installs separately)

**Default Fallback: Mock Provider (Rule-Based)**
- No external calls — pure Python persona logic
- Deterministic generation with configurable random seed
- Always available — zero dependencies, zero cost
- Ships as default (`LLM_PROVIDER=mock`) so system works out of the box

**Shared Tool Library:** `shared/naas_shared/simulation_tools.py`
- `TOOL_DEFINITIONS`: Tool schemas for query_recent_events, query_users, query_risk_assessments, submit_login_event
- `ToolExecutor`: Executes tool calls against DB and EventSink (P2)
- Used internally by ClaudeMCPProvider and externally by MCP Server — one implementation, two transports
- Tool schemas encode protocol-specific data format constraints, replacing verbose prompt engineering

**Cost:** $0/month (mock or Ollama), variable (Claude API, typically < $1/demo session)

### ML Framework: Scikit-learn

- Random Forest classifier for risk scoring (see Risk Evaluator)
- 16-feature vector: 4 continuous signals + 4 booleans + 2 time derivatives + 6 one-hot categorical columns
- Feature column ordering contract: `shared/naas_shared/ml_features.py` (shared between training script and Risk Evaluator)
- Model serialized via joblib (`random_forest.pkl`)
- Fast inference (< 10ms per prediction)
- Pre-trained model shipped with repository (generated by `scripts/train_bootstrap_model.py`)
- Training data: synthetic, generated from 12 IAM domain-knowledge distribution profiles (independent of rule-based scoring — avoids entanglement)

### Model Context Protocol (P2)

- Shared tool implementations exposed via two transport layers:
  - Internal: Anthropic API tool-use (ClaudeMCPProvider in persona-simulator)
  - External: MCP Server service with SSE transport (Claude Desktop integration)
- From the LLM's perspective, both layers are identical — same tool definitions, same behavior
- Demonstrates understanding of both tool use (API capability) and MCP (transport protocol)

---

## Development Tools

### Version Control: Git + GitHub

**Repository Structure:**
```
naas/
├── .github/
│   └── workflows/
│       └── ci.yml          # GitHub Actions (optional)
├── services/
│   ├── event-ingestion/
│   ├── signal-enrichment/
│   └── ...
├── dashboard/
├── infrastructure/
├── docs/
├── docker-compose.yml
├── README.md
└── .env.example
```

**GitHub Features:**
- Issues for task tracking
- Projects for kanban board (optional)
- Wiki for extended docs (optional)

---

### IDE: VS Code (Recommended)

**Recommended Extensions:**
- Python (Microsoft)
- Pylance (type checking)
- Black Formatter
- mypy (static type checking)
- Docker
- PostgreSQL (database viewer)

---

### Code Quality: Black + mypy + pytest

**Black (Formatting):**
```bash
black services/event-ingestion/
```
Auto-formats code (consistent style, no debates)

**mypy (Type Checking):**
```bash
mypy services/event-ingestion/ --strict
```
Catches type errors before runtime

**pytest (Testing):**
```bash
pytest services/event-ingestion/tests/ -v --cov
```
Unit + integration tests

---

## Cost Breakdown

### Development Costs: $0/month

| Service | Tier | Cost |
|---------|------|------|
| Keycloak | Self-hosted (Docker) | $0 |
| PostgreSQL | Self-hosted (Docker) | $0 |
| Redis | Self-hosted (Docker) | $0 |
| OpenLDAP | Self-hosted (Docker) | $0 |
| Prometheus | Self-hosted (Docker) | $0 |
| Grafana | Self-hosted (Docker) | $0 |
| AbuseIPDB | Free tier (1000/day) | $0 |
| IPQualityScore | Free tier (5000/mo) | $0 |
| MaxMind GeoLite2 | Free tier | $0 |
| GitHub | Free tier | $0 |
| **TOTAL** | | **$0/month** |

---

### Deployment Costs: ≤ $25/month

**Option A: Local Demo Only (Recommended for Portfolio)**
- Run on laptop/desktop for demos
- No cloud costs
- **Cost: $0/month** ✅

**Option B: Cloud Deployment (If Needed)**

**Cheap Hosting ($5-12/month):**
- DigitalOcean Droplet: $6/month (1GB RAM, 25GB SSD)
- Linode Nanode: $5/month (1GB RAM, 25GB SSD)
- Vultr: $6/month (1GB RAM, 25GB SSD)

**What Fits:**
- Keycloak + PostgreSQL + Redis + NAAS services
- Tight, but doable for demo purposes
- Not production-grade (no HA, limited performance)

**Better Hosting ($20-25/month):**
- DigitalOcean: $12/month (2GB RAM, 50GB SSD)
- Fly.io: $0 (free tier) + $10-15 for addons
- Railway: $5 base + $15 for resources

**Cost: $5-25/month** ✅

**Recommendation:** Start with local demos ($0), deploy to cloud only if needed for remote interviews.

---

### Total Cost Summary

**Development:** $0/month  
**Demo (Local):** $0/month  
**Demo (Cloud, Optional):** $5-25/month

**Budget Constraint:** ≤ $25/month ✅ **SATISFIED**

---

## Architectural Decision Records

### ADR-001: Why Python (Not Java)

**Context:** Need to choose primary backend language

**Decision:** Python 3.12+

**Rationale:**
- Best IAM ecosystem (OIDC, SAML, LDAP libraries)
- ML integration (scikit-learn)
- Async performance (FastAPI rivals Go for I/O-bound)
- Development speed (2-3x faster than Java)
- Modern IAM companies use Python (Okta, Auth0, Dropbox, Instagram)

**Consequences:**
- ✅ Faster development
- ✅ Better ML integration
- ⚠️ "Not enterprise enough" perception (mitigated by patterns)

**Mitigation:**
- Strict typing (Pydantic + mypy)
- Hexagonal architecture
- Production patterns (observability, error handling)
- Document decision in ADR (shows senior thinking)

---

### ADR-002: Why Redis Streams (Not Kafka)

**Context:** Need message broker for event pipeline

**Decision:** Redis Streams

**Rationale:**
- NAAS throughput: 10 events/sec (Redis handles 10,000+)
- Operational simplicity (single container vs Zookeeper + 3 brokers)
- Consumer groups (parallel processing)
- Already using Redis (caching, pub/sub)
- Unified infrastructure

**Consequences:**
- ✅ Simple to operate
- ✅ Fast (sub-millisecond latency)
- ✅ Sufficient for scale
- ⚠️ Less durable than Kafka (mitigated: PostgreSQL persistence)

**Scaling Path:**
- 0-1000 events/sec: Redis Streams (current design)
- 1000-10000 events/sec: Redis Cluster
- 10000+ events/sec: Migrate to Kafka

---

### ADR-003: Why Keycloak (Not Mock IDP)

**Context:** Need OIDC provider for authentication

**Decision:** Keycloak 26+

**Rationale:**
- Production-grade (Red Hat, widely used)
- Shows integration skills (not toy implementation)
- Real OIDC flows (not simplified)
- Stronger "modern vs legacy" contrast for narrative
- MCP documentation available for potential Claude integrations

**Consequences:**
- ✅ Higher credibility
- ✅ Realistic integration
- ⚠️ Slightly more complex setup (+2-4 hours)

**Fallback Plan:**
- If Keycloak setup exceeds 6 hours (Week 1): Fall back to Mock IDP

### ADR-004: Why Transparent LLM Integration (Not Separate "AI Mode")

**Context:** The previous design had separate "Simple", "AI", and "MCP" simulator modes exposed to the user.

**Decision:** NAAS uses a single generation interface with a transparent, configurable LLM backend. The user interacts with persona/scenario controls, not LLM selection menus.

**Rationale:**
- Users care about *what* events to generate, not *how* the generation works
- Graceful degradation: system works identically at all LLM tiers
- No broken UI when API keys are missing
- Demonstrates production-grade AI integration (AI as infrastructure, not feature)
- Fallback chain ensures demos never fail due to LLM availability
- EventSink architecture pre-primes for MCP tool-use without refactoring

**Consequences:**
- ✅ Seamless user experience regardless of LLM configuration
- ✅ Zero-config demo mode (mock provider, no API keys)
- ✅ Cost control (mock for development, Claude for demos)
- ✅ P2 MCP integration requires no interface changes — just a new provider
- ⚠️ Less visible "AI" branding in the UI (mitigated: AI Suggest toggle, provider indicator in status bar)

---

## Technology Selection Principles

### How We Chose Each Technology

**Framework:**
1. Identify requirement (e.g., "need web framework")
2. List candidates (FastAPI, Flask, Django)
3. Evaluate against criteria:
   - Performance (async? I/O-bound?)
   - Developer experience (docs? learning curve?)
   - Ecosystem (libraries? community?)
   - Project fit (microservices? monolith?)
4. Document trade-offs
5. Choose winner
6. Capture in ADR

**Result:** Every technology choice is defensible, not arbitrary.

---

## Final Tech Stack Summary

**Backend:**
- Python 3.12+ with FastAPI 0.115+
- SQLAlchemy 2.0 (async), Pydantic 2.10+
- Structlog, Prometheus Client

**Frontend:**
- React 19 + TypeScript 5.x
- Vite 6.0+, TanStack Query 5.x
- shadcn/ui + Tailwind CSS 3.4
- React Flow, Recharts

**Data:**
- PostgreSQL 17+
- Redis 7.4+

**Infrastructure:**
- Docker + Docker Compose
- Keycloak 26+
- OpenLDAP 2.6+
- Prometheus 2.54+ + Grafana 11+

**External Services:**
- AbuseIPDB (free tier)
- MaxMind GeoLite2 (free tier)

**Cost:** $0/month (local), $5-25/month (cloud, optional)

---

*"Technology choices reflect architectural thinking. Choose intentionally. Document trade-offs."*

**— NAAS: Built with purpose, not by accident**
