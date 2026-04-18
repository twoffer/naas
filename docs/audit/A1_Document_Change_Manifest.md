# A1 Document Change Manifest (Updated)
## Exact Updates Required for Existing NAAS Project Documents

**Purpose:** This document lists the specific sections to update in existing project documents to integrate the Persona Simulator LLM design with EventSink architecture and shared tool implementations.

**Updated:** Reflects EventSink/GenerationResult interface redesign and shared tool library for MCP pre-priming.

---

## 1. SYSTEM_ARCHITECTURE.md

### 1a. Replace §8 (Persona Simulator) — currently lines ~163–170

**Remove** the current §8 content and **replace with:**

```markdown
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
```

### 1b. Update §10/Optional (MCP Server) — currently lines ~198–201

**Remove** the current MCP Server section and **replace with:**

```markdown
### MCP Server (P2 — Not in MVP)
- **Port:** 8008
- Exposes NAAS data as tools for Claude Desktop via Model Context Protocol
- Tools: query_recent_events, query_users, query_risk_assessments, submit_login_event
- **Shared tool implementations:** Same `TOOL_DEFINITIONS` and `ToolExecutor` from `shared/naas_shared/simulation_tools.py` used by the Persona Simulator's ClaudeMCPProvider. MCP Server is a thin SSE transport layer wrapping shared implementations — not a reimplementation.
- Transport: Server-Sent Events (SSE)
- **Purpose 1 — Context-Aware Simulation (P2):** The Persona Simulator's ClaudeMCPProvider uses the shared tools via Claude API tool-use (internal, local function calls). The LLM queries data and submits events through tools, enabling context-aware generation.
- **Purpose 2 — User-Facing AI Interaction (P2):** The MCP Server exposes the same tools externally via SSE for Claude Desktop, allowing users to query NAAS data and generate simulations via natural language conversation.
- See `A1_Persona_Simulator_LLM_Design.md` for full design including EventSink architecture, provider interface, and shared tool library.
```

### 1c. Update Implementation Priority table — currently at end of document

**Replace** the Implementation Priority table with:

```markdown
## Implementation Priority

| Priority | Components |
|----------|-----------|
| **P0** | Infrastructure (Docker Compose, PG, Redis), Keycloak, Event Ingestion, Identity Normalization (OIDC/LDAP/SAML adapters, conflict resolution with confidence scoring), Signal Enrichment, Risk Evaluator, Policy Management (YAML), Dashboard (5 tabs + Protocol Flow Viz), Persona Simulator (4 modes: Manual, AI Suggest, Auto, Historical Bulk), EventSink + IngestionServiceSink, MockProvider (rule-based), ClaudeProvider (structured JSON), Shared tool definitions (TOOL_DEFINITIONS — defined in P0, used in P2) |
| **P1** | Shadow mode, Feature flags, Alert Service, Policy versioning, OllamaProvider, Scenario concept (named multi-persona configurations), OpenTelemetry tracing, Prometheus metrics, Integration tests, ADRs |
| **P2** | ClaudeMCPProvider (tool-use with EventSink-injected submit tool), ToolExecutor, MCP Server (SSE transport wrapping shared tools, user-facing Claude Desktop integration), ML model monitoring, Model explainability, Real-time risk heatmap, Policy diff viewer, Automated rollback, Runtime LLM provider selection in UI |
```

### 1d. Add to Redis Usage table

**Add these rows** to the Redis Usage table:

```markdown
| Simulator auto-mode queue | List | `simulator:event_queue` | N/A |
| Simulator auto-mode state | Hash | `simulator:auto_state` | N/A |
```

### 1e. Add to Communication Patterns table

**Add these rows:**

```markdown
| LLM Generation | Persona Simulator → Claude API / Ollama | HTTPS (external) / HTTP (local Ollama) |
| Event Submission | Persona Simulator → Event Ingestion (via EventSink) | HTTP + JSON (internal) |
```

---

## 2. SPEC_0_Project_Scaffold_and_Shared_Foundation_UPDATED.md

### 2a. Add LLM environment variables to §2 (`.env.example`) — after the Dashboard section

**Add these lines** to the `.env.example` section:

```env
# LLM Provider Configuration (Persona Simulator)
LLM_PROVIDER=mock                              # claude | ollama | mock
LLM_MODEL=claude-sonnet-4-20250514             # Model for Claude API
ANTHROPIC_API_KEY=                              # Required only if LLM_PROVIDER=claude
OLLAMA_URL=http://host.docker.internal:11434   # Ollama API URL (external to Docker)
OLLAMA_MODEL=llama3.1                          # Model for Ollama
SIMULATION_BATCH_SIZE=10                       # Events per LLM call for auto/bulk modes
SIMULATION_MAX_RATE=30                         # Max events per minute for auto mode
```

### 2b. Add persona-simulator to service port listing

In the Service Ports section of `.env.example`, **add:**

```env
PERSONA_SIMULATOR_PORT=8007
```

### 2c. Add to Shared Config model

In §3.5 or the shared config section, **add these fields** to the Settings model:

```python
# LLM Provider Configuration
llm_provider: str = Field(default="mock", pattern="^(claude|ollama|mock)$")
llm_model: str = Field(default="claude-sonnet-4-20250514")
anthropic_api_key: Optional[str] = None
ollama_url: str = Field(default="http://host.docker.internal:11434")
ollama_model: str = Field(default="llama3.1")
simulation_batch_size: int = Field(default=10, ge=1, le=50)
simulation_max_rate: int = Field(default=30, ge=1, le=60)
```

### 2d. Add simulation_tools.py to shared library file tree

In the shared library directory listing, **add:**

```
shared/
└── naas_shared/
    ├── __init__.py
    ├── database.py
    ├── redis_client.py
    ├── models.py
    ├── schemas.py
    ├── logging.py
    ├── config.py
    ├── constants.py
    └── simulation_tools.py       # Shared tool definitions + ToolExecutor (P0: definitions, P2: executor)
```

**Note:** In P0, `simulation_tools.py` contains `TOOL_DEFINITIONS` (the tool schemas) and basic `PersonaProfile` data classes. The `ToolExecutor` class is added in P2 when MCP integration is built. Defining the tool schemas in P0 ensures they're available for the ClaudeProvider's prompt context enrichment and establishes the contract for P2 tool-use integration.

### 2e. Update the service directory placeholders section

**Verify** `persona-simulator` is included in the list of directories that get placeholder READMEs.

---

## 3. NAAS_v2_0_Tech_Stack_UPDATED.md

### 3a. Add new section: "AI/ML Components"

**Insert after** the "External Services" section (before "Development Tools"):

```markdown
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

**ADR-004: Why Transparent LLM Integration (Not Separate "AI Mode")**

**Context:** The AARE predecessor had separate "Simple", "AI", and "MCP" simulator modes exposed to the user.

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

### ML Framework: Scikit-learn

- Random Forest classifier for risk scoring (see Risk Evaluator)
- Model serialized via joblib (`random_forest.pkl`)
- Fast inference (< 10ms per prediction)
- Pre-trained model shipped with repository

### Model Context Protocol (P2)

- Shared tool implementations exposed via two transport layers:
  - Internal: Anthropic API tool-use (ClaudeMCPProvider in persona-simulator)
  - External: MCP Server service with SSE transport (Claude Desktop integration)
- From the LLM's perspective, both layers are identical — same tool definitions, same behavior
- Demonstrates understanding of both tool use (API capability) and MCP (transport protocol)
```

---

## 4. CLAUDE_UPDATED.md

### 4a. Update Project Structure

**Replace** the services section in the project structure with:

```markdown
├── services/
│   ├── api-gateway/                # JWT auth, routing, WebSocket, rate limiting
│   ├── event-ingestion/            # Accept + validate login events, dual-write PG + Redis
│   ├── identity-normalization/     # OIDC/SAML/LDAP adapters → unified schema ★ KEY DIFFERENTIATOR
│   ├── signal-enrichment/          # IP reputation, geo, device, impossible travel
│   ├── risk-evaluator/             # Rule-based + ML scoring → allow/MFA/deny
│   ├── policy-management/          # YAML policy CRUD, versioning, shadow mode
│   ├── alert-service/              # High-risk event alerting (never on historical events)
│   └── persona-simulator/          # LLM-powered event generation (Claude/Ollama/mock fallback)
```

### 4b. Add to Key Conventions

**Add:**

```markdown
- **LLM Integration:** Persona Simulator uses configurable LLM provider (Claude API → Ollama → mock). Set via `LLM_PROVIDER` env var. Default: `mock` (no API keys needed). Events submitted via EventSink abstraction.
- **Shared tools:** `shared/naas_shared/simulation_tools.py` contains tool definitions and executor used by persona-simulator (internal) and MCP server (external, P2).
```

---

## 5. NAAS_System_Decomposition_Guide.md

### 5a. Update Spec 6 description

**Replace** the Spec 6 section with:

```markdown
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
```

---

## 6. Default Policy Update (Spec 0 init.sql)

### 6a. Add normalization_risk weight to default seed policy

In the seed policy YAML within `init.sql`, **update the weights section:**

```yaml
weights:
  ip_reputation: 0.20
  device_risk: 0.15
  impossible_travel: 0.25
  failed_logins: 0.15
  time_of_day: 0.10
  normalization_risk: 0.15
ensemble:
  rule_weight: 0.6
  ml_weight: 0.4
```

Note: This change incorporates the A2 normalization confidence signal (normalization_risk = 1.0 - normalization_confidence). The weights have been rebalanced to sum to 1.0.

---

*End of Change Manifest.*
