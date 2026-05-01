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
  - **LDAP Adapter:** Dual-role adapter. (1) **Extract:** Maps LDAP-convention attribute names from `raw_attributes` to the unified schema — used as the primary adapter for `protocol: "ldap"` events. (2) **Enrich:** Queries the live OpenLDAP server to fetch directory attributes for cross-protocol enrichment — used for OIDC and SAML events to merge directory data with token/assertion claims. The correlation lookup uses a configurable unified schema field (default: `primary_email`); the adapter internally reverse-maps this to the corresponding LDAP attribute (`mail`). Handles Active Directory vs OpenLDAP schema variations. Enrichment results cached in Redis (60s TTL). Graceful degradation: if LDAP lookup fails or no match is found, normalization proceeds with single-source data only.
  - **SAML Adapter:** Maps SAML-convention attribute names to the unified schema (displayName, email, dept)

    > **Scope Note — SAML in the Demo Environment:**
    > There is no live SAML Identity Provider in the Docker Compose stack. SAML events are simulator-generated: the Persona Simulator constructs events with `protocol: "saml"` and SAML-convention attribute names (e.g., `displayName`, `dept`) in `raw_attributes`. The SAML Adapter maps these to the unified schema through the same normalization pipeline used for OIDC and LDAP. In a production deployment, the adapter would additionally parse raw SAML assertion XML to extract these attributes before normalization — Keycloak (already present for OIDC) could serve as the SAML IdP, or any standards-compliant SAML 2.0 provider would work. This is a deliberate scope decision: the architectural value is in the multi-protocol normalization layer, not in XML parsing or running three separate IdP containers.

- **Attribute mapping:** Protocol-specific attributes → unified schema:
  ```
  LDAP cn / SAML displayName / OIDC name  →  display_name
  LDAP mail / SAML email / OIDC email     →  primary_email
  LDAP departmentNumber / SAML dept / OIDC department → department
  LDAP employeeType / SAML employeeType / OIDC employee_type → employee_type (normalized to: FTE|contractor|vendor)
  ```
- **Conflict resolution:** When multiple sources disagree, applies configurable priority rules.
- **Cross-protocol enrichment:** For OIDC and SAML events, the service queries OpenLDAP to find the same user (by configurable unified schema field, default: `primary_email` — the adapter internally reverse-maps this to the corresponding LDAP attribute). If found, both the primary protocol's attributes and the LDAP directory attributes are fed into the conflict resolution algorithm, producing a multi-source normalized identity with per-attribute confidence scores. Enrichment is source-agnostic (applies equally to live and simulated events). LDAP events skip enrichment (directory data is already in the payload). Configuration lives in `config/normalization.yaml` under `enrichment.sources.ldap`.
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
  - **Login Recency:** Days since user's last successful login. `NULL` for first-ever logins. Simple PostgreSQL `MAX(timestamp)` query.
- **Updates:** PostgreSQL `events.enriched_signals` (JSONB)

### 5. Policy Management Service
- **Port:** 8004
- **Role:** CRUD for YAML-based declarative risk policies. Policy validation (including expression parsing). Policy versioning. Only one active policy at a time.
- **Endpoints:** `GET/POST/PUT/DELETE /policies`, `POST /policies/{id}/activate`
- **Policy format:** YAML with hybrid scoring model — `signal_weights` (continuous pre-normalized signals) + `conditions` (boolean expressions using AND/OR/NOT/IN, comparisons). Decision thresholds and ensemble configuration.
- **Expression validation:** All condition expressions are parsed and validated at policy creation time using the safe `ast`-based evaluator. Invalid expressions are rejected with descriptive error messages.
- **Signal weight validation:** `signal_weights` keys must be from the closed `VALID_SIGNAL_WEIGHTS` enum: `ip_reputation_risk`, `normalization_risk`, `failed_login_risk`, `login_recency_risk`.
- **Caching:** Active policy cached in Redis (60s TTL).
- **Shadow mode support:** Policies can be flagged as shadow — evaluated but not enforced (results logged for comparison).

### 6. Risk Evaluator Service
- **Port:** 8005
- **Role:** Calculate risk scores and make access decisions. The "brain."
- **Consumes:** Redis Stream `enriched_events` (consumer group: `evaluator_workers`)
- **Publishes to:** Redis Pub/Sub channel `decisions`
- **Hybrid scoring model:**
  - **Signal weights:** Pre-normalizes continuous enrichment signals to [0.0, 1.0] risk values using hardcoded formulas (`ip_reputation_risk`, `normalization_risk`, `failed_login_risk`, `login_recency_risk`). Multiplies each by its policy-defined weight.
  - **Conditions:** Evaluates boolean expressions against the event context (5 namespaces: `user`, `device`, `signals`, `time`, `event`). Each triggered condition contributes its weight.
  - **Rule-based score:** `clamp(signal_score + condition_score, 0.0, 1.0)`
  - **ML-based:** Random Forest classifier (scikit-learn, joblib serialized). 16-feature vector extracted from full evaluation context (not limited to the 4 signal_weights signals). Predicts probability of malicious. Falls back to `0.0` (ML path disabled) if model file missing.
  - **Ensemble:** `final_score = (rule_score × rule_weight) + (ml_score × ml_weight)`. Default: 60/40.
- **Decision thresholds (configurable per policy, escalating severity):**
  - `< 0.3` → ALLOW (implicit — below all thresholds)
  - `≥ 0.3` → STEP_UP_MFA
  - `≥ 0.7` → DENY
- **Expression evaluator:** Python `ast`-based safe evaluator. Whitelist of allowed AST node types. Expressions preprocessed from uppercase (AND/OR/NOT/IN) to lowercase Python syntax.
- **Contributing factors:** Every scoring decision records which signals and conditions contributed, stored in `risk_assessments.contributing_factors` JSONB for dashboard explainability.
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

### 8. Persona Simulator Service
- **Port:** 8007
- **Role:** Generate realistic login events for testing/demo using configurable LLM intelligence. Dedicated backend service accessed via floating dashboard panel.
- **Submits events via EventSink** (abstraction over Event Ingestion Service REST API). Events enter the pipeline as a side effect of the generation call — the provider never returns raw event data.
- **All events tagged:** `source=simulator, is_synthetic=true`
- **Personas:** Office Worker (regular patterns), Road Warrior (travel), Attacker (suspicious behavior)
- **Four generation options:**
  - **Manual:** Select protocol, persona, set parameter overrides → generate one event. No LLM call.
  - **AI Suggest:** Toggle on manual form. LLM pre-populates parameter fields with realistic values for selected persona/protocol. User can review and override before generating. Falls back to rule-based defaults if LLM unavailable.
  - **Auto:** Background continuous generation at configurable rate (5–30 events/min), configurable protocol mix (% OIDC/SAML/LDAP). Events generated in LLM batches of 10, submitted via EventSink, dispatched at configured rate.
  - **Historical Bulk:** Generate 100–5000 backdated events for analytics population. `is_historical=true` → no alerts. Events generated in LLM batches of 20, submitted via EventSink.
- **LLM Provider Abstraction:** All generation modes (except Manual without AI Suggest) use the configured LLM provider via the `SimulationProvider` interface. Provider selected via `LLM_PROVIDER` env var:
  - **Claude API** (primary): Anthropic SDK, structured JSON output, protocol-aware prompts. P0: construct-then-submit pattern. P2: tool-use pattern with shared tools (context-aware generation).
  - **Ollama** (fallback, P1): Local LLM, same prompt templates, lower quality but free
  - **Mock** (default): Rule-based generation, no external calls, always available
- **Fallback chain:** Claude → Ollama → Mock. Automatic fallback on failure. System works out of the box with `LLM_PROVIDER=mock` (no API keys needed).
- **Protocol-aware prompts:** LLM prompts include protocol-specific context so generated `raw_attributes` match what the Identity Normalization Service expects (JWT claims for OIDC, directory attributes for LDAP, assertion attributes for SAML).
- **Shared tool library:** Tool definitions and implementations (`query_recent_events`, `query_users`, `query_risk_assessments`, `submit_login_event`) live in `shared/naas_shared/simulation_tools.py`. Used internally by ClaudeMCPProvider (P2) and externally by the MCP Server (P2). Tool implementations accept the EventSink for event submission, ensuring all paths converge on the same ingestion pipeline.
- **Does NOT authenticate as users** (trusted internal tool, events carry metadata).
- **Endpoints:** `POST /simulate/suggest`, `POST /simulate/single`, `POST /simulate/auto/start`, `POST /simulate/auto/stop`, `POST /simulate/historical`, `GET /simulate/personas`, `GET /simulate/health`

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
- **Port:** 8008
- Exposes NAAS data as tools for Claude Desktop via Model Context Protocol
- Tools: query_recent_events, query_users, query_risk_assessments, submit_login_event
- **Shared tool implementations:** Same `TOOL_DEFINITIONS` and `ToolExecutor` from `shared/naas_shared/simulation_tools.py` used by the Persona Simulator's ClaudeMCPProvider. MCP Server is a thin SSE transport layer wrapping shared implementations — not a reimplementation.
- Transport: Server-Sent Events (SSE)
- **Purpose 1 — Context-Aware Simulation (P2):** The Persona Simulator's ClaudeMCPProvider uses the shared tools via Claude API tool-use (internal, local function calls). The LLM queries data and submits events through tools, enabling context-aware generation.
- **Purpose 2 — User-Facing AI Interaction (P2):** The MCP Server exposes the same tools externally via SSE for Claude Desktop, allowing users to query NAAS data and generate simulations via natural language conversation.

### ML Bootstrap Script (MVP) / ML Training Service (P2)
- **MVP:** Standalone script `scripts/train_bootstrap_model.py` generates synthetic training data from parameterized distribution profiles, trains a Random Forest classifier, evaluates it, and serializes `random_forest.pkl` to `services/risk-evaluator/models/`. Run once during initial setup; the `.pkl` file is committed to the repo for first-boot.
- **Feature vector:** 16 columns derived from the full evaluation context — 4 continuous pre-normalized signals, 4 boolean enrichment signals, 2 derived time features, 3 one-hot protocol columns, 3 one-hot employee_type columns. Column ordering defined in `shared/naas_shared/ml_features.py`.
- **Training data:** 12 distribution profiles (6 benign, 6 malicious) encoding IAM domain knowledge about attack patterns. 70/30 benign-to-malicious class balance. Labels are independent of rule-based scoring — avoids entanglement anti-pattern.
- **P2:** Full ML Training Service — offline retraining from production data, hyperparameter tuning, model versioning, Jupyter notebooks.

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

| Purpose                   | Redis Feature | Key/Channel             | TTL          |
| ------------------------- | ------------- | ----------------------- | ------------ |
| Event pipeline stage 1    | Stream        | `login_events`          | maxlen 10000 |
| Event pipeline stage 2    | Stream        | `normalized_events`     | maxlen 10000 |
| Event pipeline stage 3    | Stream        | `enriched_events`       | maxlen 10000 |
| Decision broadcast        | Pub/Sub       | `decisions`             | N/A          |
| Alert broadcast           | Pub/Sub       | `alerts`                | N/A          |
| Policy cache              | String        | `policy:active`         | 60s          |
| LDAP enrichment cache     | String (JSON) | `ldap_enrichment:{email}` | 60s          |
| IP reputation cache       | Hash          | `ip_rep:{ip}`           | 24h          |
| Geo cache                 | Hash          | `geo:{ip}`              | 7d           |
| JWT public key cache      | String        | `jwks:keycloak`         | 5min         |
| Feature flags             | Hash          | `feature_flags`         | 60s          |
| Simulator auto-mode queue | List          | `simulator:event_queue` | N/A          |
| Simulator auto-mode state | Hash          | `simulator:auto_state`  | N/A          |

---

## Communication Patterns

| Pattern          | When Used                                                                                           | Mechanism                              |
| ---------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------- |
| Synchronous REST | Dashboard ↔ API Gateway, Gateway → Policy Mgmt, Persona Simulator → Event Ingestion (via EventSink) | HTTP + JSON                            |
| Async Pipeline   | Ingestion → Normalization → Enrichment → Evaluation                                                 | Redis Streams + Consumer Groups        |
| Broadcast        | Decisions → Alert Service + Dashboard                                                               | Redis Pub/Sub                          |
| Real-time Push   | API Gateway → Dashboard                                                                             | WebSocket                              |
| Auth             | Dashboard → Keycloak → API Gateway                                                                  | OIDC auth code flow + JWT Bearer       |
| LLM Generation   | Persona Simulator → Claude API / Ollama                                                             | HTTPS (external) / HTTP (local Ollama) |
| LDAP Enrichment  | Identity Normalization → OpenLDAP | LDAP (tcp/389, internal Docker network) |

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
| **P0** | Infrastructure (Docker Compose, PG, Redis), Keycloak, Event Ingestion, Identity Normalization (OIDC/LDAP/SAML adapters, conflict resolution with confidence scoring), Signal Enrichment, Risk Evaluator, Policy Management (YAML), Dashboard (5 tabs + Protocol Flow Viz), Persona Simulator (4 modes: Manual, AI Suggest, Auto, Historical Bulk), EventSink + IngestionServiceSink, MockProvider (rule-based), ClaudeProvider (structured JSON), Shared tool definitions (TOOL_DEFINITIONS — defined in P0, used in P2) |
| **P1** | Shadow mode, Feature flags, Alert Service, Policy versioning, OllamaProvider, Scenario concept (named multi-persona configurations), OpenTelemetry tracing, Prometheus metrics, Integration tests, ADRs |
| **P2** | ClaudeMCPProvider (tool-use with EventSink-injected submit tool), ToolExecutor, MCP Server (SSE transport wrapping shared tools, user-facing Claude Desktop integration), ML model monitoring, Model explainability, Real-time risk heatmap, Policy diff viewer, Automated rollback, Runtime LLM provider selection in UI |
