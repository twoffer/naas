# NAAS System Architecture
## Complete Architectural Reference

**Version:** 2.0
**Status:** Design Finalized, Ready for Implementation

---

## Architecture Overview

```
                    ┌─────────────────────┐
                    │   React Dashboard   │
                    │  (5 tabs + floating │
                    │   simulator panel)  │
                    └────────┬────────────┘
                             │ REST + WebSocket
                             ▼
                    ┌─────────────────────┐
                    │    API Gateway /    │
                    │   BFF (FastAPI)     │
                    │  JWT auth, routing, │
                    │  WS mgmt, rate limit│
                    └────────┬────────────┘
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
│   Event      │  │     Policy       │  │   Alert      │
│  Ingestion   │  │   Management     │  │   Service    │
│   Service    │  │    Service       │  │              │
└──────┬───────┘  └──────────────────┘  └──────▲───────┘
       │                                       │
       │ Redis Stream: login_events            │ Redis Pub/Sub: decisions
       ▼                                       │
┌──────────────────┐                           │
│    Identity      │                           │
│  Normalization   │                           │
│    Service       │                           │
│ (Protocol adapt.)│                           │
└──────┬───────────┘                           │
       │                                       │
       │ Redis Stream: normalized_events       │
       ▼                                       │
┌──────────────────┐                           │
│ Signal Enrichment│                           │
│    Service       │                           │
│ (IP, geo, device)│                           │
└──────┬───────────┘                           │
       │                                       │
       │ Redis Stream: enriched_events         │
       ▼                                       │
┌──────────────────┐                           │
│  Risk Evaluator  │───────────────────────────┘
│    Service       │──→ Redis Pub/Sub: decisions → Dashboard (WS)
│ (rules + ML)     │
└──────────────────┘

External Identity Sources:
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ Keycloak │  │ OpenLDAP │  │   SAML   │
  │  (OIDC)  │  │ (Legacy) │  │ Provider │
  └──────────┘  └──────────┘  └──────────┘

Simulation:
  ┌──────────────────┐
  │ Persona Simulator│ → Posts to Event Ingestion
  │ (floating panel) │
  └──────────────────┘
```

---

## Service Catalog

### 1. API Gateway / BFF
- **Port:** 8000
- **Role:** Single entry point for dashboard. JWT validation (Keycloak JWKS), request routing, WebSocket management, rate limiting, circuit breakers, CORS.
- **Subscribes to:** Redis Pub/Sub channels `decisions`, `alerts` → forwards via WebSocket to dashboard.
- **Auth:** Validates Bearer tokens against Keycloak public keys (cached, 5min TTL).

### 2. Event Ingestion Service
- **Port:** 8001
- **Role:** Accept login events via REST, validate schema (Pydantic), dual-write to PostgreSQL + Redis Stream.
- **Endpoints:** `POST /events/ingest`, `POST /events/bulk`
- **Writes to:** PostgreSQL `events` table + Redis Stream `login_events`
- **Metadata fields on every event:** `source` (user|simulator|api), `is_synthetic` (bool), `is_historical` (bool), `protocol` (oidc|saml|ldap)
- **Returns:** 202 Accepted (async processing downstream)

### 3. Identity Normalization Service
- **Port:** 8002
- **Role:** Protocol-specific attribute extraction and normalization to unified schema. This is the NAAS differentiator.
- **Consumes:** Redis Stream `login_events` (consumer group: `normalization_workers`)
- **Publishes to:** Redis Stream `normalized_events`
- **Contains protocol adapters:**
  - **OIDC Adapter:** Extracts JWT claims from Keycloak tokens (name, email, groups)
  - **LDAP Adapter:** Queries OpenLDAP for user attributes (cn, mail, departmentNumber, employeeType). Handles Active Directory vs OpenLDAP schema variations.
  - **SAML Adapter:** Parses SAML assertions, extracts attributes (displayName, email, dept)
- **Attribute mapping:** Protocol-specific attributes → unified schema:
  ```
  LDAP cn / SAML displayName / OIDC name  →  display_name
  LDAP mail / SAML email / OIDC email     →  primary_email
  LDAP departmentNumber / SAML dept / OIDC department → department
  LDAP employeeType / SAML employeeType / OIDC employee_type → employee_type (normalized to: FTE|contractor|vendor)
  ```
- **Conflict resolution:** When multiple sources disagree, applies configurable priority rules.
- **Updates:** PostgreSQL `events.normalized_attributes` (JSONB)

### 4. Signal Enrichment Service
- **Port:** 8003
- **Role:** Augment normalized events with risk signals. I/O-heavy (external APIs, DB queries).
- **Consumes:** Redis Stream `normalized_events` (consumer group: `enrichment_workers`)
- **Publishes to:** Redis Stream `enriched_events`
- **Enrichers (run in parallel):**
  - **IP Reputation:** Multi-provider with fallback (AbuseIPDB → IPQualityScore → mock). Cached 24h in Redis.
  - **Geolocation:** MaxMind GeoLite2 local DB. IP → city/country/lat/lon. Cached 7d in Redis.
  - **Device Fingerprinting:** User-Agent parsing → browser, OS, device type. Track known devices per user.
  - **Impossible Travel:** Haversine distance between consecutive logins. Flag if required speed > 1800 km/h.
  - **Failed Login Tracking:** Count failed attempts in past 24h from PostgreSQL.
  - **Time-of-Day Risk:** Evaluate login time against user's typical timezone patterns.
- **Updates:** PostgreSQL `events.enriched_signals` (JSONB)

### 5. Policy Management Service
- **Port:** 8004
- **Role:** CRUD for YAML-based declarative risk policies. Policy versioning. Only one active policy at a time.
- **Endpoints:** `GET/POST/PUT/DELETE /policies`, `POST /policies/{id}/activate`
- **Policy format:** YAML with conditions (expressions using AND/OR/NOT), signal weights, decision thresholds.
- **Caching:** Active policy cached in Redis (60s TTL).
- **Shadow mode support:** Policies can be flagged as shadow — evaluated but not enforced (results logged for comparison).

### 6. Risk Evaluator Service
- **Port:** 8005
- **Role:** Calculate risk scores and make access decisions. The "brain."
- **Consumes:** Redis Stream `enriched_events` (consumer group: `evaluator_workers`)
- **Publishes to:** Redis Pub/Sub channel `decisions`
- **Scoring approach:**
  - **Rule-based:** Weighted sum of normalized signals per active policy weights
  - **ML-based:** Random Forest classifier (scikit-learn, joblib serialized). Predicts probability of malicious.
  - **Ensemble:** `final_score = (rule_score × rule_weight) + (ml_score × ml_weight)`. Default: 60/40.
- **Decision thresholds (configurable per policy):**
  - `< 0.3` → ALLOW
  - `0.3 – 0.7` → STEP_UP_MFA
  - `≥ 0.7` → DENY
- **Shadow mode:** If shadow policy exists, evaluate with both active and shadow, log comparison.
- **Writes to:** PostgreSQL `risk_assessments` table
- **Fail-safe:** On error, returns score 1.0 (DENY).

### 7. Alert Service
- **Port:** 8006
- **Role:** Subscribe to risk decisions, generate alerts for high-risk events.
- **Subscribes to:** Redis Pub/Sub channel `decisions`
- **Alert criteria:**
  - Decision = DENY → CRITICAL
  - Risk score ≥ 0.75 → HIGH
  - Impossible travel detected → HIGH
  - Failed logins ≥ 5 in 24h → HIGH
- **CRITICAL RULE:** Never alert on events where `is_historical = true`.
- **Publishes to:** Redis Pub/Sub channel `alerts` → Dashboard via WebSocket
- **Writes to:** PostgreSQL `alerts` table

### 8. Persona Simulator
- **Role:** Generate realistic login events for testing/demo. Accessed via floating dashboard panel.
- **Generates events by POSTing to Event Ingestion Service.**
- **All events tagged:** `source=simulator, is_synthetic=true`
- **Personas:** Office Worker (regular patterns), Road Warrior (travel), Attacker (suspicious behavior)
- **Three generation modes:**
  - **Manual:** Select protocol, persona, count → generate on-demand
  - **Auto:** Background continuous generation at configurable rate (5-30 events/min), configurable protocol mix (% OIDC/SAML/LDAP)
  - **Historical Bulk:** Generate 100-5000 backdated events for analytics population. `is_historical=true` → no alerts.
- **Does NOT authenticate as users** (trusted internal tool, events carry metadata).

### 9. Dashboard (React SPA)
- **Port:** 3000
- **Auth:** OIDC flow with Keycloak (authorization code grant). Tokens stored in React state (NOT localStorage).
- **WebSocket:** Connects to API Gateway for real-time event stream and alerts.
- **5-Tab Structure:**
  - **Tab 1 — Identity Sources:** Keycloak/OpenLDAP/SAML connection status, health, event counts
  - **Tab 2 — Normalization:** Attribute mapping tables (raw → normalized), conflict resolution rules, success rates
  - **Tab 3 — Risk Engine:** Active policy config, decision distribution charts, risk score trends
  - **Tab 4 — Migration Tools:** Shadow mode controls, policy comparison (active vs shadow), rollout % slider, feature flags
  - **Tab 5 — Live Activity:** Real-time event stream (color-coded: green/yellow/red), Protocol Flow Visualization (React Flow), alert notifications
- **Floating Simulator Panel:** Accessible from any tab via button. Contains Manual/Auto/Historical Bulk modes.

### 10. Keycloak (External — OIDC Provider)
- **Port:** 8080
- **Config:** Realm `naas-demo`, Client `naas-dashboard` (public), test users (alice, bob, charlie).
- **Endpoints used:** `/.well-known/openid-configuration`, `/auth`, `/token`, `/certs` (JWKS)

### 11. OpenLDAP (External — Legacy Directory)
- **Port:** 389
- **Base DN:** `dc=corp,dc=com`
- **Test data:** Users with inetOrgPerson attributes (cn, sn, mail, uid, departmentNumber, employeeType)

---

## Optional / Future Components

### MCP Server (P2 — Not in MVP)
- Exposes NAAS data as tools for Claude Desktop via Model Context Protocol
- Tools: query_recent_events, query_users, query_risk_assessments
- Transport: Server-Sent Events (SSE)

### ML Training Service (P2 — Not in MVP)
- Offline training pipeline: extract data → feature engineering → train Random Forest → serialize model
- For MVP: ship a pre-trained model file (`random_forest.pkl`)

---

## Data Flow: End-to-End Pipeline

```
User/Simulator → Event Ingestion (validate, dual-write)
                     │
                     ├─→ PostgreSQL: events table (permanent record)
                     └─→ Redis Stream: login_events
                              │
                              ▼
                   Identity Normalization (protocol adapters, schema mapping)
                     │
                     ├─→ PostgreSQL: events.normalized_attributes (update)
                     └─→ Redis Stream: normalized_events
                              │
                              ▼
                   Signal Enrichment (IP, geo, device, travel, failed logins)
                     │
                     ├─→ PostgreSQL: events.enriched_signals (update)
                     └─→ Redis Stream: enriched_events
                              │
                              ▼
                   Risk Evaluator (rule-based + ML ensemble → decision)
                     │
                     ├─→ PostgreSQL: risk_assessments table (insert)
                     └─→ Redis Pub/Sub: decisions channel
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              Alert Service        API Gateway
              (filter, alert)      (WS broadcast)
                    │                   │
                    ▼                   ▼
              Redis Pub/Sub:       Dashboard
              alerts channel       (real-time UI)
                    │
                    ▼
              API Gateway → Dashboard
```

**Target Latency:** < 500ms end-to-end (ingestion → decision broadcast)
- Ingestion: < 10ms
- Normalization: < 50ms
- Enrichment: < 200ms
- Evaluation: < 50ms
- Alert + broadcast: < 50ms

---

## Database Schema (PostgreSQL)

### Core Tables

```sql
events (
  id UUID PK,
  event_id VARCHAR(255) UNIQUE,
  user_id VARCHAR(255),
  protocol VARCHAR(10),         -- oidc | saml | ldap
  client_ip INET,
  user_agent TEXT,
  timestamp TIMESTAMP,
  source VARCHAR(20),           -- user | simulator | api
  is_synthetic BOOLEAN,
  is_historical BOOLEAN,
  raw_attributes JSONB,         -- protocol-specific raw data
  normalized_attributes JSONB,  -- unified schema output
  enriched_signals JSONB,       -- IP rep, geo, device, etc.
  created_at TIMESTAMP
)

policies (
  id UUID PK,
  policy_id VARCHAR(255) UNIQUE,
  name VARCHAR(255),
  version VARCHAR(50),
  is_active BOOLEAN,
  is_shadow BOOLEAN,
  policy_yaml TEXT,             -- full YAML policy definition
  created_at TIMESTAMP
)

risk_assessments (
  id UUID PK,
  event_id UUID FK → events,
  policy_id UUID FK → policies,
  rule_based_score FLOAT,
  ml_based_score FLOAT,
  final_score FLOAT,
  decision VARCHAR(20),         -- allow | step_up_mfa | deny
  shadow_decision VARCHAR(20),  -- decision from shadow policy (if any)
  shadow_score FLOAT,
  contributing_factors JSONB,
  created_at TIMESTAMP
)

alerts (
  id UUID PK,
  event_id UUID FK → events,
  assessment_id UUID FK → risk_assessments,
  severity VARCHAR(20),         -- critical | high | medium | low
  title VARCHAR(500),
  status VARCHAR(20),           -- new | acknowledged | investigating | dismissed
  created_at TIMESTAMP
)

users (
  id UUID PK,
  user_id VARCHAR(255) UNIQUE,
  email VARCHAR(255),
  display_name VARCHAR(255),
  created_at TIMESTAMP
)
```

### Key Indexes
```sql
idx_events_user_id (user_id)
idx_events_timestamp (timestamp DESC)
idx_events_protocol (protocol)
idx_risk_assessments_event_id (event_id)
idx_risk_assessments_decision (decision)
idx_alerts_status (status)
```

---

## Redis Usage

| Purpose | Redis Feature | Key/Channel | TTL |
|---------|--------------|-------------|-----|
| Event pipeline stage 1 | Stream | `login_events` | maxlen 10000 |
| Event pipeline stage 2 | Stream | `normalized_events` | maxlen 10000 |
| Event pipeline stage 3 | Stream | `enriched_events` | maxlen 10000 |
| Decision broadcast | Pub/Sub | `decisions` | N/A |
| Alert broadcast | Pub/Sub | `alerts` | N/A |
| Policy cache | String | `policy:active` | 60s |
| IP reputation cache | Hash | `ip_rep:{ip}` | 24h |
| Geo cache | Hash | `geo:{ip}` | 7d |
| JWT public key cache | String | `jwks:keycloak` | 5min |
| Feature flags | Hash | `feature_flags` | 60s |

---

## Communication Patterns

| Pattern | When Used | Mechanism |
|---------|-----------|-----------|
| Synchronous REST | Dashboard ↔ API Gateway, Gateway → Policy Mgmt, Simulator → Ingestion | HTTP + JSON |
| Async Pipeline | Ingestion → Normalization → Enrichment → Evaluation | Redis Streams + Consumer Groups |
| Broadcast | Decisions → Alert Service + Dashboard | Redis Pub/Sub |
| Real-time Push | API Gateway → Dashboard | WebSocket |
| Auth | Dashboard → Keycloak → API Gateway | OIDC auth code flow + JWT Bearer |

---

## Key Design Patterns

- **Microservices:** Each service = single responsibility, independent deployment
- **Event-driven pipeline:** Redis Streams with consumer groups for async decoupled processing
- **Dual persistence:** PostgreSQL (permanent record) + Redis Stream (pipeline trigger) on ingestion
- **Fail-safe defaults:** Unknown risk → DENY; service down → CHALLENGE; parse error → log and drop
- **Circuit breakers:** API Gateway implements circuit breakers for downstream services
- **Stateless services:** All state in PostgreSQL/Redis; services can crash and restart cleanly
- **Cache-heavy:** Policy (60s), IP reputation (24h), geo (7d), JWKS (5min) — all in Redis
- **Metadata tracking:** Every event carries source/is_synthetic/is_historical for filtering
- **Shadow mode:** Dual policy evaluation for safe migration testing
- **Ensemble scoring:** Rule-based (interpretable) + ML (adaptive), configurable blend

---

## Implementation Priority

| Priority | Components |
|----------|-----------|
| **P0** | Infrastructure (Docker Compose, PG, Redis), Keycloak, Event Ingestion, Identity Normalization (OIDC/LDAP/SAML adapters), Signal Enrichment, Risk Evaluator, Policy Management (YAML), Dashboard (5 tabs + Protocol Flow Viz), Persona Simulator (3 modes) |
| **P1** | Shadow mode, Feature flags, Alert Service, Policy versioning, OpenTelemetry tracing, Prometheus metrics, Integration tests, ADRs |
| **P2** | ML model monitoring, MCP Server, Model explainability, Real-time risk heatmap, Policy diff viewer, Automated rollback |
