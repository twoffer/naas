# NAAS System Decomposition Guide
## Functional Spec Planning for Claude Code Implementation

**Purpose:** Define how to decompose NAAS into functional specs optimized for Claude Code agent implementation.

---

## Decomposition Principles

### Why Not 1:1 Service-to-Spec

A separate spec per service creates three problems:

1. **Shared foundations get built N times.** Every service needs the same DB connection pattern, Redis client, Pydantic base models, Dockerfile template, and structlog config. Independent specs either reinvent these or require copy-pasting boilerplate instructions into every spec.

2. **Integration seams get orphaned.** The contract between services (e.g., the Redis Stream message schema for `login_events`) belongs to neither spec individually. It falls between the cracks.

3. **Uneven complexity.** The Alert Service is ~100 lines of meaningful logic. The Identity Normalization Service with three protocol adapters is a beast. Equal-weight specs waste planning effort on simple services and underspecify the hard ones.

### Optimal Unit of Work for an AI Agent

Claude Code works best with **clear boundaries, well-defined inputs/outputs, and a scope it can hold in context at once.** Specs should represent coherent units of deliverable work, grouped by dependency order, where each can be validated independently before moving on.

---

## Recommended Specs (7 Total)

### Spec 0: Project Scaffold & Shared Foundation

**Scope:**
- Docker Compose orchestration (all service containers, networks, volumes)
- PostgreSQL schema initialization (`init.sql`)
- Redis configuration
- Keycloak container setup + realm configuration
- OpenLDAP container setup + bootstrap data (LDIF)
- Shared Python library (`shared/`): DB connection, Redis client, Pydantic base models, structlog config, common utilities
- `.env.example`, `.gitignore`, project directory structure

**Why this grouping:** Every service depends on this. Build once, import everywhere. Eliminates redundant boilerplate across all subsequent specs.

**Validation:** `docker-compose up` brings up PG, Redis, Keycloak, OpenLDAP. Can connect to each. Keycloak OIDC discovery endpoint responds. OpenLDAP returns test users via `ldapsearch`.

---

### Spec 1: Event Ingestion Service

**Scope:**
- REST API (`POST /events/ingest`, `POST /events/bulk`)
- Pydantic request/response models for login events
- Dual-write: PostgreSQL `events` table + Redis Stream `login_events`
- Metadata handling (`source`, `is_synthetic`, `is_historical`, `protocol`)
- Health endpoint

**Why this grouping:** First pipeline stage. Clean, self-contained. Validates the infrastructure from Spec 0 actually works end-to-end.

**Validation:** POST a login event via curl → verify row in PostgreSQL `events` table + message in Redis Stream `login_events`.

---

### Spec 2: Identity Normalization Service

**Scope:**
- Redis Stream consumer (reads `login_events`, writes `normalized_events`)
- OIDC adapter (extract JWT claims from `raw_attributes`)
- LDAP adapter — dual role: (1) extract LDAP attributes from `raw_attributes` for `protocol: "ldap"` events; (2) query live OpenLDAP server for cross-protocol enrichment of OIDC/SAML events
- SAML adapter (map SAML-convention attribute names from `raw_attributes`)
- Cross-protocol LDAP enrichment: unified schema correlation field lookup (configurable, default: `primary_email`; adapter reverse-maps to LDAP attribute internally), Redis cache (60s TTL), graceful degradation on failure, enrichment config in `normalization_authority.yaml`
- LDAP connection pool (`python-ldap`, async-wrapped, pool size 3)
- Unified schema definition and attribute mapping engine
- Conflict resolution logic (multi-source attributes — triggered by cross-protocol enrichment)
- Update PostgreSQL `events.normalized_attributes`

**Why this grouping:** This is the NAAS differentiator — the most important code in the project. Complex enough to deserve its own spec. Must be high quality.

**Validation:** Ingest events with different protocols → verify `normalized_attributes` JSONB in PostgreSQL contains unified schema output. LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name`. For OIDC events where the user exists in OpenLDAP: verify `enrichment_applied: true` in normalized output and multi-source `resolution_details` showing both `oidc` and `ldap` sources. For OIDC events where the user does NOT exist in OpenLDAP: verify `enrichment_applied: false` and single-source resolution.

---

### Spec 3: Signal Enrichment + Risk Evaluator

**Scope:**
- **Enrichment Service:**
  - Redis Stream consumer (reads `normalized_events`, writes `enriched_events`)
  - IP reputation enricher (multi-provider with fallback + Redis cache)
  - Geolocation enricher (MaxMind GeoLite2 + Redis cache)
  - Device fingerprinting (User-Agent parsing)
  - Impossible travel detection (Haversine distance calculation)
  - Failed login tracking (24h window, PostgreSQL query)
  - Login recency calculation (days since last successful login for this user)
  - Update PostgreSQL `events.enriched_signals`
- **Risk Evaluator Service:**
  - Redis Stream consumer (reads `enriched_events`)
  - Hybrid scoring: signal weights (4 continuous pre-normalized signals) + conditions (boolean expression evaluation)
  - Expression evaluator (Python ast-based, safe evaluation with AST node whitelist)
  - Evaluation context assembly (5 namespaces: user, device, signals, time, event)
  - Signal normalization (ip_reputation_risk, normalization_risk, failed_login_risk, login_recency_risk)
  - ML scoring (Random Forest, joblib model loading, 16-feature vector from full evaluation context)
  - ML feature extraction (extract_ml_features function, column ordering from shared/naas_shared/ml_features.py)
  - ML graceful degradation (if model file missing, ml_score returns 0.0)
  - Ensemble calculation (configurable rule/ML blend)
  - Decision thresholds (escalating severity: step_up_mfa/deny, allow implicit below all thresholds)
  - Contributing factors logging (signals + conditions breakdown for dashboard explainability)
  - Shadow mode dual evaluation (if shadow policy exists)
  - Write to PostgreSQL `risk_assessments` table
  - Publish to Redis Pub/Sub `decisions` channel
  - Fail-safe: score 1.0 (DENY) on error
- **Bootstrap Script:**
  - `scripts/train_bootstrap_model.py` — standalone CLI, not a service
  - Generates synthetic training data from 12 distribution profiles (6 benign, 6 malicious)
  - Trains RandomForestClassifier, evaluates, serializes to `services/risk-evaluator/models/random_forest.pkl`

**Why this grouping:** Enrichment output schema IS the evaluator input schema. Building both together eliminates contract mismatches. Tightly coupled data flow.

**Risk note:** This is the largest spec. If it proves too much for one agent session, the natural split point is between enrichment and evaluation — they communicate via Redis Stream `enriched_events`, so the contract is clean.

**Validation:** Ingest an event → verify it flows through normalization → enrichment → evaluation. Check `risk_assessments` table has a row with scores and decision. Check Redis Pub/Sub `decisions` channel receives the decision message.

---

### Spec 4: Policy Management + Alert Service

**Scope:**
- **Policy Management Service:**
  - YAML policy schema definition
  - Policy parser and validator
  - Expression validation engine (parse and validate condition expressions at policy creation time using ast-based safe evaluator; reject invalid expressions with descriptive errors)
  - signal_weights key validation against VALID_SIGNAL_WEIGHTS enum (ip_reputation_risk, normalization_risk, failed_login_risk, login_recency_risk)
  - YAML schema validation (Pydantic model: required fields, type checks, threshold ordering, ensemble weight sum)
  - CRUD REST API (`GET/POST/PUT/DELETE /policies`, `POST /policies/{id}/activate`)
  - Policy versioning
  - Shadow mode flag (`is_shadow`)
  - Policy caching (Redis, 60s TTL)
- **Alert Service:**
  - Redis Pub/Sub subscriber (listens to `decisions` channel)
  - Alert criteria filtering (deny → CRITICAL, high score → HIGH, impossible travel → HIGH, failed logins → HIGH)
  - Historical event filter (NEVER alert on `is_historical = true`)
  - Write to PostgreSQL `alerts` table
  - Publish to Redis Pub/Sub `alerts` channel

**Why this grouping:** Policy is the configuration that drives the evaluator. Alert is simple but depends on understanding policy decisions. Both are "supporting services" to the core pipeline. Neither is large enough to justify its own spec.

**Validation:** Create a YAML policy via API → verify it parses and stores. Activate it → verify Redis cache updates. Trigger a high-risk event → verify alert appears in `alerts` table and on `alerts` Pub/Sub channel. Trigger a historical event → verify NO alert generated.

---

### Spec 5: API Gateway + WebSocket Layer

**Scope:**
- FastAPI application as single entry point for dashboard
- JWT validation middleware (Keycloak JWKS, cached public keys)
- Request routing/proxying to backend services (ingestion, policy management, analytics queries)
- WebSocket endpoint management (subscribe to Redis Pub/Sub `decisions` + `alerts`, broadcast to connected clients)
- Rate limiting (per-user)
- Circuit breaker pattern (for downstream service calls)
- CORS configuration
- Health/readiness endpoints

**Why this grouping:** This is the integration layer. It needs to know about every upstream service's API. Build it after the services exist so the contracts are already defined.

**Validation:** Authenticate via Keycloak → receive JWT → make authenticated request through gateway to a backend service → receive response. Connect WebSocket → trigger an event through pipeline → verify decision appears on WebSocket.

---

### Spec 6: Dashboard + Persona Simulator

**Scope:**
- **Dashboard (React SPA):**
  - OIDC auth flow with Keycloak (authorization code grant)
  - 5-tab layout (Identity Sources, Normalization, Risk Engine, Migration Tools, Live Activity)
  - WebSocket client (connect to API Gateway, display real-time events + alerts)
  - Protocol Flow Visualization (React Flow library)
  - Charts and analytics (Recharts)
  - Policy management UI (CRUD forms)
  - Shadow mode comparison view
- **Persona Simulator Backend Service (port 8007):**
  - EventSink abstraction + IngestionServiceSink (submits events to Event Ingestion)
  - SimulationProvider interface (generate via sink, return GenerationResult summary)
  - LLM provider implementations (ClaudeProvider, MockProvider; OllamaProvider is P1)
  - Provider fallback chain with graceful degradation
  - Protocol-aware prompt templates for OIDC, SAML, LDAP
  - Persona profiles (office worker, road warrior, attacker)
  - Batched event generation for auto/bulk modes
  - Auto-mode background generation with event queue
  - REST API: /simulate/suggest, /simulate/single, /simulate/auto/*, /simulate/historical
- **Shared Tool Library (shared/naas_shared/simulation_tools.py):**
  - TOOL_DEFINITIONS: schemas for query and submit tools (defined in P0, used by P2 MCP)
  - PersonaProfile data classes
  - ToolExecutor stub (P2: full implementation with DB queries and EventSink injection)
- **Persona Simulator Floating Panel UI:**
  - Manual mode with parameter overrides
  - AI Suggest toggle (LLM pre-populates parameters)
  - Auto mode controls (persona, rate, protocol mix, start/stop)
  - Historical bulk mode controls (persona, time range, count)

**Why this grouping:** Frontend is one deliverable. The simulator UI, its backend service, and the LLM integration are tightly coupled to the dashboard experience. Building them together ensures the UX is coherent. The shared tool library is included because it defines the contract between the simulator and future MCP integration.

**Validation:** Full end-to-end demo flow: login via Keycloak → see dashboard → open simulator → generate events (all four modes) → watch them flow through Protocol Flow Viz → see risk decisions in real-time stream → see alerts pop up. Verify mock provider works without API keys. If Claude API key is configured, verify AI Suggest populates fields and auto mode generates higher-quality events. Verify EventSink correctly POSTs to Event Ingestion Service for all generation paths.

---

## Dependency Order

```
Spec 0 (foundation) ──→ everything depends on this
  │
  ▼
Spec 1 (ingestion) ──→ first pipeline entry point
  │
  ▼
Spec 2 (normalization) ──→ consumes from Spec 1's output stream
  │
  ▼
Spec 3 (enrichment + evaluator) ──→ consumes from Spec 2's output stream
  │
  ▼
Spec 4 (policy + alerts) ──→ evaluator loads policies; alerts subscribe to decisions
  │
  ▼
Spec 5 (API gateway) ──→ routes to all services from Specs 1-4
  │
  ▼
Spec 6 (dashboard + simulator) ──→ talks to gateway from Spec 5
```

Each spec can be validated independently before moving on. No big-bang integration at the end.

---

## Functional Spec Document Template

Each spec document should contain these 7 sections to keep Claude Code on the rails:

### 1. Scope Boundary
Exactly which files and directories this spec creates or modifies. Explicit list. Prevents the agent from wandering into other services or creating unexpected files.

### 2. Input Contracts
What this component consumes. Redis Stream message schemas (exact field names and types), API request shapes (Pydantic models), database table structures it reads from. Provide concrete examples.

### 3. Output Contracts
What this component produces. Redis Stream message schemas it publishes, API response shapes, database tables/columns it writes to, Pub/Sub channel message formats. Provide concrete examples.

### 4. Shared Imports
Which modules from Spec 0's shared library to use (DB session factory, Redis client, base Pydantic models, logging setup). Prevents reinventing common infrastructure.

### 5. Implementation Requirements
Business logic, algorithms, edge cases, error handling behavior. The substantive "what this thing actually does" section. Include pseudocode or algorithm descriptions for non-trivial logic (e.g., Haversine formula, ensemble scoring, expression evaluation).

### 6. Validation Criteria
How to verify it works. Concrete curl commands, test scripts, expected outputs, database queries to check results. Gives the agent a "definition of done" rather than leaving it to hallucinate success.

### 7. What NOT to Build
Explicit exclusions to prevent scope creep. "Do NOT implement X. Do NOT create a separate service for Y. Do NOT add endpoints beyond those listed." Critical for keeping the agent focused.
