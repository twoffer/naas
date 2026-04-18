# Persona Simulator: LLM-Integrated Design
## Design Reference for Spec 6 — Dashboard & Persona Simulator

**Purpose:** Define the complete design for the NAAS Persona Simulator with transparent LLM integration, covering user experience, backend architecture, LLM provider abstraction, prompt construction, and future enhancements.

**Audience:** Claude Code agents implementing Spec 6, the technical-architect agent producing the Spec 6 implementation plan, and the project architect.

---

## 1. Design Philosophy

The Persona Simulator uses LLM intelligence transparently. The user interacts with persona and scenario controls — not with LLM selection menus. The configured LLM provider (Claude API → Ollama → rule-based mock) determines the sophistication of generated events, but the user experience is identical regardless of which provider is active. If no API keys are configured, the system gracefully degrades to rule-based generation with no broken UI, no error messages, and no visible difference in workflow.

**Key principle:** The LLM is a tool in the engine, not a feature on the dashboard.

---

## 2. User Experience: Four Generation Options

All four options are accessible from the floating Persona Simulator panel, which is available from any dashboard tab.

### 2.1 Option 1 — Manual Single Event (No LLM)

The user constructs a specific login event by setting parameters directly.

**UI Controls:**
- Protocol selector: OIDC / SAML / LDAP
- Persona selector: Office Worker / Road Warrior / Attacker
- Parameter overrides (collapsible panel):
  - User ID (dropdown of test users or free text)
  - Client IP (text input, with "Random" button)
  - Geographic location (city/country dropdown or lat/lon)
  - User Agent (dropdown of common browsers or free text)
  - VPN enabled (toggle)
  - Failed login count in last 24h (slider: 0–20)
  - Time offset (slider: generate event at current time ± N hours)
- **"AI Suggest" toggle** (see §2.2)
- Generate button

**Behavior:** Constructs a `LoginEventIngest` object directly from the user's parameter selections. No LLM call. POSTs to Event Ingestion Service via EventSink. The event flows through the full pipeline and appears in real-time on the dashboard.

**Demo use case:** "Watch what happens when a contractor logs in from Russia at 3 AM on a VPN with 6 failed attempts in the last hour."

### 2.2 Option 2 — AI Suggest Mode (LLM-Enhanced Manual)

A toggle on the manual event form. When enabled, the LLM pre-populates the parameter fields with realistic values for the selected persona and protocol.

**UI Behavior:**
1. User selects a persona and protocol
2. User toggles "AI Suggest" ON
3. System calls the configured LLM provider to generate realistic parameter values
4. Parameter fields are populated with LLM-suggested values
5. User can review and override any individual parameter
6. User clicks Generate

**If LLM call fails:** Parameter fields remain empty (or populated with basic rule-based defaults). A subtle toast notification says "AI suggestions unavailable — using defaults." No blocking error.

**Demo use case:** "Notice how the AI suggested a Moscow IP with VPN enabled for the Attacker persona? Let me change that to a Tor exit node instead and see what happens to the risk score."

### 2.3 Option 3 — Auto Mode (Continuous Background Generation)

Continuous event generation at a user-specified rate.

**UI Controls:**
- Persona selector (or Scenario selector — see §9)
- Protocol mix sliders: % OIDC / % SAML / % LDAP (must sum to 100%)
- Rate selector: 5 / 10 / 20 / 30 events per minute
- Start / Stop button
- Status indicator (running/stopped, events generated count, provider in use)

**Behavior:** The backend generates events in batches using the configured LLM provider, then drip-feeds them into the pipeline at the configured rate via the EventSink. Batch size: 10 events per LLM call (configurable). Events are submitted through the EventSink and dispatched at the specified rate.

**Batching rationale:** At 20 events/minute with individual LLM calls, that's 20 API calls/minute — expensive and slow. Generating 10 events per batch means ~2 API calls/minute, which is cost-effective and fast. The mock provider generates batches instantly with no external calls.

**Demo use case:** "While I explain the normalization layer, watch events flowing through the Protocol Flow Visualization in real-time..."

### 2.4 Option 4 — Historical Bulk Generation

Generate a large number of backdated events to populate analytics dashboards.

**UI Controls:**
- Persona selector (or Scenario selector — see §9)
- Protocol mix sliders: % OIDC / % SAML / % LDAP
- Time range: Last 7 days / Last 30 days / Last 90 days
- Event count: 100 / 500 / 1000 / 2500 / 5000
- Generate button
- Progress indicator (events generated / total)

**Behavior:** All events tagged `is_historical=true, is_synthetic=true, source=simulator`. Alert Service ignores these (critical rule). Events generated in LLM batches of 20, with timestamps distributed across the time range. Submitted through the EventSink to the Event Ingestion Service.

**Demo use case:** "Let me populate 30 days of login patterns so we can see the analytics dashboards in action."

---

## 3. Backend Architecture

### 3.1 Service: persona-simulator

The Persona Simulator is a dedicated backend service.

- **Port:** 8007
- **Container:** `naas-persona-simulator`
- **Role:** Generate login events using persona logic + configurable LLM intelligence
- **Dependencies:** Event Ingestion Service (for submitting events via EventSink), PostgreSQL (for shared tool implementations — query tools), Redis (for auto-mode state)

### 3.2 API Endpoints

```
POST /simulate/suggest         — Get AI-suggested parameters for the UI form
POST /simulate/single          — Generate one event with explicit parameters
POST /simulate/auto/start      — Start continuous background generation
POST /simulate/auto/stop       — Stop continuous generation
GET  /simulate/auto/status     — Get auto-mode status (running, rate, count)
POST /simulate/historical      — Generate backdated bulk events
GET  /simulate/personas        — List available personas and their descriptions
GET  /simulate/health          — Health check
```

### 3.3 Request/Response Models

```python
class SuggestRequest(BaseModel):
    """Request for AI-suggested parameter values (AI Suggest toggle)."""
    persona: Literal["office_worker", "road_warrior", "attacker"]
    protocol: Literal["oidc", "saml", "ldap"]

class SuggestResponse(BaseModel):
    """AI-suggested parameter values to populate the UI form."""
    user_id: str
    client_ip: str
    location_city: str
    location_country: str
    user_agent: str
    vpn_enabled: bool
    failed_login_count: int
    time_offset_hours: float
    provider_used: str  # "claude", "ollama", "mock" — so UI can show suggestion source

class SingleEventRequest(BaseModel):
    """
    Request for manual single event generation. All parameters explicit.
    
    By the time this request reaches the backend, every field has a concrete value.
    Whether those values were typed by the user or pre-populated by the AI Suggest
    endpoint is irrelevant — the backend doesn't know or care.
    """
    persona: Literal["office_worker", "road_warrior", "attacker"]
    protocol: Literal["oidc", "saml", "ldap"]
    user_id: str
    client_ip: str
    location_city: str
    location_country: str
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    vpn_enabled: bool = False
    failed_login_count: int = Field(default=0, ge=0, le=20)
    time_offset_hours: float = 0.0

class AutoModeRequest(BaseModel):
    """Request to start auto-mode generation."""
    persona: Literal["office_worker", "road_warrior", "attacker"]
    rate_per_minute: Literal[5, 10, 20, 30] = 10
    protocol_mix: ProtocolMix = ProtocolMix()

class ProtocolMix(BaseModel):
    """Protocol distribution for event generation."""
    oidc: int = Field(default=50, ge=0, le=100)
    saml: int = Field(default=25, ge=0, le=100)
    ldap: int = Field(default=25, ge=0, le=100)

    @model_validator(mode="after")
    def mix_sums_to_100(self):
        if self.oidc + self.saml + self.ldap != 100:
            raise ValueError("Protocol mix must sum to 100")
        return self

class HistoricalBulkRequest(BaseModel):
    """Request for historical bulk generation."""
    persona: Literal["office_worker", "road_warrior", "attacker"]
    protocol_mix: ProtocolMix = ProtocolMix()
    time_range_days: Literal[7, 30, 90] = 30
    event_count: int = Field(default=500, ge=100, le=5000)

class GenerationResult(BaseModel):
    """
    Summary of what the provider generated. Returned by all providers.
    
    NOTE: This is a summary, NOT the events themselves. Events enter the pipeline
    as a side effect of the generate() call via the EventSink. The caller receives
    this summary to report status to the UI.
    """
    events_generated: int
    events_submitted: int
    provider_used: str  # "claude", "ollama", "mock", "claude_mcp"
    generation_time_ms: float
    errors: list[str] = []
    metadata: dict[str, Any] = {}  # Provider-specific (tokens used, tools called, etc.)
```

---

## 4. Provider Architecture: EventSink + SimulationProvider

### 4.1 Core Design Principle

**The provider's job is to cause events to exist in the pipeline — not to return event data.**

Whether the provider constructs events in memory and pushes them through a sink, or gives the LLM tools that submit events directly, is an implementation detail. The interface accommodates both patterns through the `EventSink` abstraction.

This design is intentionally pre-primed for MCP integration (P2). When MCP tools are added, they wrap the same `EventSink` — events enter the pipeline identically regardless of whether they were constructed by Python code or submitted by an LLM tool call.

### 4.2 EventSink: The Submission Abstraction

```python
class EventSink(Protocol):
    """
    Abstraction for submitting generated events into the pipeline.
    Decouples event generation from event submission.
    
    The canonical implementation (IngestionServiceSink) POSTs events
    to the Event Ingestion Service's REST API. All providers — including
    future MCP tool implementations — submit through this same interface.
    """
    async def submit_events(self, events: list[LoginEventIngest]) -> int:
        """Submit a batch of events. Returns count successfully submitted."""
        ...

    async def submit_event(self, event: LoginEventIngest) -> bool:
        """Submit a single event. Returns True on success."""
        ...


class IngestionServiceSink(EventSink):
    """
    Production EventSink that POSTs events to the Event Ingestion Service.
    This is the only production implementation — all paths converge here.
    """
    def __init__(self, ingestion_url: str):
        self.ingestion_url = ingestion_url  # e.g., "http://event-ingestion:8001"
        self.client = httpx.AsyncClient()

    async def submit_event(self, event: LoginEventIngest) -> bool:
        response = await self.client.post(
            f"{self.ingestion_url}/events/ingest",
            json=event.model_dump(mode="json"),
        )
        return response.status_code == 202

    async def submit_events(self, events: list[LoginEventIngest]) -> int:
        response = await self.client.post(
            f"{self.ingestion_url}/events/bulk",
            json=[e.model_dump(mode="json") for e in events],
        )
        if response.status_code == 202:
            return len(events)
        return 0
```

### 4.3 SimulationProvider Interface

```python
class SimulationProvider(ABC):
    """
    Abstract base for event generation providers.
    
    Providers generate events AND submit them via the provided EventSink.
    The generate() method returns a GenerationResult summary, NOT the events.
    Events enter the pipeline as a side effect of the generate() call.
    
    This design accommodates two generation patterns:
    1. Construct-then-submit (Mock, Claude basic, Ollama): Provider builds
       LoginEventIngest objects in memory, then calls sink.submit_events().
    2. Tool-use submission (Claude MCP — P2): LLM calls tools that internally
       invoke the sink. Events enter the pipeline during the LLM's tool-use loop.
    
    Both patterns use the same EventSink. The caller doesn't need to know which
    pattern the provider used — it just gets a GenerationResult summary.
    """

    @abstractmethod
    async def generate(
        self,
        request: GenerationRequest,
        sink: EventSink,
    ) -> GenerationResult:
        """
        Generate login events and submit them via the sink.
        Returns a summary of what was generated and submitted.
        """
        ...

    @abstractmethod
    async def suggest_parameters(
        self,
        request: SuggestRequest,
    ) -> SuggestResponse:
        """
        Suggest realistic parameter values for AI Suggest mode.
        
        This is the one method that DOES return data — parameter suggestions
        for the UI form, not pipeline events. MCP tools are not involved here.
        The provider_used field on SuggestResponse is set by the implementation.
        """
        ...


class GenerationRequest(BaseModel):
    """Unified request object passed to all providers."""
    persona: PersonaProfile
    protocol: str
    count: int
    constraints: Optional[EventConstraints] = None
    time_range: Optional[TimeRange] = None
    is_historical: bool = False
```

### 4.4 Provider Implementations

**MockProvider (P0):**

```python
class MockProvider(SimulationProvider):
    """Rule-based event generation. No external calls. Always available."""

    async def generate(self, request, sink):
        start = time.monotonic()
        events = self._build_events_from_rules(request)
        submitted = await sink.submit_events(events)
        elapsed = (time.monotonic() - start) * 1000
        return GenerationResult(
            events_generated=len(events),
            events_submitted=submitted,
            provider_used="mock",
            generation_time_ms=elapsed,
        )

    async def suggest_parameters(self, request: SuggestRequest) -> SuggestResponse:
        params = self._generate_parameters_from_rules(request.persona, request.protocol)
        return SuggestResponse(**params, provider_used="mock")
```

Each persona has hardcoded behavioral patterns:
- Office Worker: business hours (8-18), consistent city, stable IP range, low failed logins
- Road Warrior: varied hours, multiple cities with realistic travel gaps, multiple devices
- Attacker: odd hours, VPN/Tor IPs, high failed logins, impossible travel, rotating user agents

Protocol-aware: generates appropriate `raw_attributes` for OIDC/SAML/LDAP. Deterministic with random seed for reproducibility in tests.

**ClaudeProvider — basic mode (P0):**

```python
class ClaudeProvider(SimulationProvider):
    """Claude API with structured JSON output. Construct-then-submit pattern."""

    async def generate(self, request, sink):
        start = time.monotonic()
        prompt = self._build_prompt(request)
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        events = self._parse_events_from_response(response)
        submitted = await sink.submit_events(events)
        elapsed = (time.monotonic() - start) * 1000
        return GenerationResult(
            events_generated=len(events),
            events_submitted=submitted,
            provider_used="claude",
            generation_time_ms=elapsed,
            metadata={"tokens_used": response.usage.input_tokens + response.usage.output_tokens},
        )

    async def suggest_parameters(self, request: SuggestRequest) -> SuggestResponse:
        prompt = self._build_suggest_prompt(request.persona, request.protocol)
        response = await self.client.messages.create(...)
        params = self._parse_parameters(response)
        return SuggestResponse(**params, provider_used="claude")
```

Handles rate limits with exponential backoff (3 retries). On failure: raises exception (caught by fallback chain).

**OllamaProvider (P1):**
- Uses HTTP client to call local Ollama API (`POST /api/generate`)
- Model: configurable via `OLLAMA_MODEL` env var (default: llama3.1)
- Same prompt templates as ClaudeProvider (may produce lower quality output)
- Same construct-then-submit pattern via EventSink
- On failure (Ollama not running, model not pulled): raises exception

**ClaudeMCPProvider — tool-use mode (P2):**

```python
class ClaudeMCPProvider(SimulationProvider):
    """
    Claude API with tool use. The LLM queries data and submits events
    via tools, enabling context-aware generation.
    
    Tools are built from shared implementations (see §5) with the
    EventSink injected into the submit_login_event tool handler.
    """

    def __init__(self, api_key, model, tool_executor: ToolExecutor):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model
        self.tool_executor = tool_executor

    async def generate(self, request, sink):
        start = time.monotonic()

        # Build Anthropic API tool definitions from shared TOOL_DEFINITIONS
        tools = [{"type": "custom", **td} for td in TOOL_DEFINITIONS]
        prompt = self._build_mcp_prompt(request)

        # Tool-use loop: Claude reasons, calls tools, we execute them
        messages = [{"role": "user", "content": prompt}]
        submission_count = 0
        total_tokens = 0

        while True:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                tools=tools,
                messages=messages,
            )
            total_tokens += response.usage.input_tokens + response.usage.output_tokens

            # Process tool calls
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = await self.tool_executor.execute(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                    if block.name == "submit_login_event":
                        submission_count += 1

            if response.stop_reason == "end_turn":
                break

            # Continue conversation with tool results
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        elapsed = (time.monotonic() - start) * 1000
        return GenerationResult(
            events_generated=submission_count,
            events_submitted=submission_count,
            provider_used="claude_mcp",
            generation_time_ms=elapsed,
            metadata={"tokens_used": total_tokens},
        )
```

### 4.5 Fallback Chain

```python
async def get_provider(sink: EventSink) -> SimulationProvider:
    """
    Return the best available provider based on configuration.
    Fallback chain: Claude → Ollama → Mock
    """
    settings = get_settings()

    if settings.llm_provider == "claude":
        if settings.anthropic_api_key:
            return ClaudeProvider(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
            )
        else:
            logger.warning("Claude configured but no API key; falling back")

    if settings.llm_provider in ("claude", "ollama"):
        try:
            provider = OllamaProvider(url=settings.ollama_url, model=settings.ollama_model)
            await provider.health_check()
            return provider
        except ConnectionError:
            logger.warning("Ollama not available; falling back to mock")

    return MockProvider()
```

The provider is resolved once at service startup and cached. If the configured provider fails mid-operation (e.g., Claude rate limit), the individual `generate()` call catches the exception, logs a warning, and falls back to MockProvider for that specific batch.

### 4.6 Environment Variables

```env
# LLM Provider Configuration
LLM_PROVIDER=mock                    # claude | ollama | mock (default: mock)
LLM_MODEL=claude-sonnet-4-20250514   # Model for Claude API
ANTHROPIC_API_KEY=                    # Required if LLM_PROVIDER=claude
OLLAMA_URL=http://host.docker.internal:11434  # Ollama API URL
OLLAMA_MODEL=llama3.1                # Model for Ollama

# Simulation Defaults
SIMULATION_BATCH_SIZE=10             # Events per LLM call for auto/bulk modes
SIMULATION_MAX_RATE=30               # Max events per minute for auto mode
```

**Note on OLLAMA_URL:** When running in Docker, the simulator container can't reach `localhost` on the host. `host.docker.internal` resolves to the Docker host on Docker Desktop (Mac/Windows). On Linux, the user may need to use the host's actual IP or Docker bridge IP. This is documented in the README.

---

## 5. Shared Tool Implementations

### 5.1 Architecture: Two Layers, One Implementation

The NAAS simulation and data tools are implemented once as a shared library and exposed through two different transport layers:

```
Shared Tool Library (shared/naas_shared/simulation_tools.py)
    │
    │  Tool implementations: query_recent_events, query_users,
    │  query_risk_assessments, submit_login_event
    │
    ├── Layer A: Anthropic API tool definitions (ClaudeMCPProvider, P2)
    │   - Tools passed as `tools` parameter to messages.create()
    │   - Tool calls executed as local Python function calls
    │   - No network protocol between Claude and tools
    │   - Used internally by the Persona Simulator service
    │
    └── Layer B: MCP Server (services/mcp-server/, P2)
        - Same tool implementations wrapped in SSE transport
        - Exposed externally for Claude Desktop integration
        - User-facing conversational AI interaction with NAAS data
```

From the LLM's perspective, the experience is identical in both layers. Claude sees tool definitions with names, descriptions, and JSON input schemas. It calls tools and receives results. Whether those tool calls are executed as local function calls (Layer A) or arrive over SSE (Layer B) is invisible to the model.

**Tool use vs MCP:** Tool use is a capability of the Claude API — you pass tool definitions, Claude calls them, you execute and return results. MCP is a transport and discovery protocol that standardizes how LLM clients (like Claude Desktop) find and connect to external tool servers over SSE. Once Claude sees a tool, the interaction is identical regardless of origin. This design uses tool use (Layer A) internally and MCP protocol (Layer B) externally, with shared implementations underneath both.

### 5.2 Tool Definitions

```python
# shared/naas_shared/simulation_tools.py

TOOL_DEFINITIONS = [
    {
        "name": "query_recent_events",
        "description": (
            "Query recent login events from the NAAS database. "
            "Use this to understand patterns before generating new events. "
            "Returns events with user, protocol, IP, timestamp, and risk decision."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "Filter by user ID"},
                "protocol": {"type": "string", "enum": ["oidc", "saml", "ldap"]},
                "decision": {"type": "string", "enum": ["allow", "step_up_mfa", "deny"]},
                "time_range_hours": {"type": "integer", "description": "Look back N hours", "default": 24},
                "limit": {"type": "integer", "description": "Max events to return", "default": 20},
            },
        },
    },
    {
        "name": "query_users",
        "description": (
            "Query user information and login statistics. "
            "Use this to find users matching specific criteria "
            "(e.g., inactive users, high-risk users, contractors)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "employee_type": {"type": "string", "enum": ["FTE", "contractor", "vendor"]},
                "department": {"type": "string"},
                "inactive_days": {"type": "integer", "description": "Users with no login in N days"},
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    {
        "name": "query_risk_assessments",
        "description": (
            "Query risk assessment history. "
            "Use this to understand what risk scores and decisions have been made."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "decision": {"type": "string", "enum": ["allow", "step_up_mfa", "deny"]},
                "min_score": {"type": "number", "description": "Minimum risk score"},
                "time_range_hours": {"type": "integer", "default": 24},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "submit_login_event",
        "description": (
            "Generate and submit a login event to the NAAS pipeline. "
            "The event will be processed through normalization, enrichment, "
            "and risk evaluation. Use this to simulate realistic login attempts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User identifier (e.g., 'alice')"},
                "protocol": {"type": "string", "enum": ["oidc", "saml", "ldap"]},
                "client_ip": {"type": "string", "description": "Source IP address"},
                "user_agent": {"type": "string", "description": "Browser/device user agent string"},
                "timestamp": {"type": "string", "format": "date-time"},
                "raw_attributes": {
                    "type": "object",
                    "description": (
                        "Protocol-specific attributes. "
                        "For OIDC: name, email, groups, department, employee_type. "
                        "For LDAP: cn, sn, mail, uid, departmentNumber, employeeType, memberOf. "
                        "For SAML: displayName, email, dept, employeeType, groups."
                    ),
                },
            },
            "required": ["user_id", "protocol", "client_ip", "timestamp", "raw_attributes"],
        },
    },
]
```

Note how the `submit_login_event` tool schema encodes the protocol-specific attribute format directly in the description. This eliminates the need for verbose protocol-context prompt sections when using MCP mode — the LLM reads the tool schema and knows exactly what `raw_attributes` to provide for each protocol.

### 5.3 Tool Execution

```python
# shared/naas_shared/simulation_tools.py

class ToolExecutor:
    """
    Executes tool calls against the database and EventSink.
    Used by both ClaudeMCPProvider (internal) and MCP Server (external).
    """

    def __init__(self, db_session_factory, event_sink: EventSink):
        self.db = db_session_factory
        self.sink = event_sink

    async def execute(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool call and return the result as a JSON string."""
        handler = {
            "query_recent_events": self._query_events,
            "query_users": self._query_users,
            "query_risk_assessments": self._query_assessments,
            "submit_login_event": self._submit_event,
        }.get(tool_name)

        if not handler:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        try:
            result = await handler(tool_input)
            return json.dumps(result)
        except Exception as e:
            return json.dumps({"error": str(e)})

    async def _submit_event(self, params: dict) -> dict:
        event = LoginEventIngest(
            user_id=params["user_id"],
            protocol=params["protocol"],
            client_ip=params["client_ip"],
            timestamp=params.get("timestamp", datetime.utcnow()),
            user_agent=params.get("user_agent"),
            raw_attributes=params.get("raw_attributes", {}),
            source="simulator",
            is_synthetic=True,
            is_historical=params.get("is_historical", False),
        )
        success = await self.sink.submit_event(event)
        return {"submitted": success, "event_id": event.user_id}
```

### 5.4 Why Shared Implementations Matter

Building the tool implementations in a shared library (not inside the MCP Server or the ClaudeMCPProvider) provides three benefits:

1. **P0 value:** The query tools can be used by the basic `ClaudeProvider` in P0 — not for tool-use, but to build richer prompt context. The provider can call `_query_events()` directly to include recent activity patterns in the prompt, making even the non-MCP Claude mode more context-aware.

2. **P2 readiness:** When `ClaudeMCPProvider` is built in P2, it constructs Anthropic API tool definitions from `TOOL_DEFINITIONS` and uses `ToolExecutor` to handle calls. No new implementations needed — just wiring.

3. **MCP Server reuse:** When the MCP Server service is built in P2, it wraps `TOOL_DEFINITIONS` in MCP protocol framing and uses the same `ToolExecutor` for execution. The MCP Server becomes a thin transport layer, not a reimplementation.

---

## 6. Prompt Construction

### 6.1 Prompt Template Structure (Non-MCP Providers)

Prompts are constructed automatically in the backend — the user never writes prompts directly. Each prompt includes:

1. **System context:** "You are a login event simulator for an enterprise IAM system."
2. **Persona profile:** Behavioral description (working hours, typical locations, risk behaviors)
3. **Protocol context:** What raw attributes look like for this protocol (see §6.2)
4. **Generation instructions:** How many events, time range, any user-specified constraints
5. **Output format:** Strict JSON schema matching `LoginEventIngest`

**MCP mode note:** When `ClaudeMCPProvider` is active (P2), prompt sections 3–5 are largely replaced by tool schemas. The `submit_login_event` tool schema communicates the data format and constraints more reliably than natural language descriptions. The prompt focuses on persona context and generation goals ("generate an attack targeting inactive contractors") and lets the LLM use tools to query context and submit events.

### 6.2 Protocol-Aware Context

Each protocol has a context block included in prompts:

**OIDC Context:**
```
For OIDC events, raw_attributes should contain JWT claims:
- name: user's display name (string)
- email: user's email address (string)
- groups: list of group names (list of strings)
- department: user's department (string)
- employee_type: "FTE", "contractor", or "vendor" (string)
```

**LDAP Context:**
```
For LDAP events, raw_attributes should contain directory attributes:
- cn: common name / display name (string)
- sn: surname (string)
- mail: email address (string)
- uid: unique user identifier (string)
- departmentNumber: department name or code (string, may use abbreviations like "eng")
- employeeType: employment classification (string, may use codes like "E", "C", "V")
- memberOf: list of group DNs (list of strings, format: "cn=groupname,ou=groups,dc=corp,dc=com")
```

**SAML Context:**
```
For SAML events, raw_attributes should contain assertion attributes:
- displayName: user's full name (string)
- email: email address (string)
- dept: department (string, may differ from LDAP format)
- employeeType: employment type (string, may use full words like "Employee", "Contractor")
- groups: list of role/group names (list of strings)
```

This protocol awareness is critical — it ensures the LLM generates `raw_attributes` that the downstream Identity Normalization Service can actually process through its protocol adapters.

### 6.3 Persona Profiles

```python
PERSONA_PROFILES = {
    "office_worker": PersonaProfile(
        name="Office Worker",
        description="Regular 9-5 employee with consistent patterns",
        typical_hours=(8, 18),
        typical_cities=["New York", "Chicago"],
        device_consistency="high",       # Same device most logins
        vpn_usage="rare",
        failed_login_rate="very_low",    # < 1 per month
        travel_frequency="none",
        risk_level="low",
    ),
    "road_warrior": PersonaProfile(
        name="Road Warrior",
        description="Frequent traveler with legitimate geographic diversity",
        typical_hours=(6, 23),           # Extended hours due to time zones
        typical_cities=["San Francisco", "London", "Tokyo", "Singapore", "Dubai"],
        device_consistency="medium",     # Laptop + phone + hotel computers
        vpn_usage="frequent",
        failed_login_rate="low",         # Occasional typos while traveling
        travel_frequency="high",
        risk_level="medium",
    ),
    "attacker": PersonaProfile(
        name="Attacker",
        description="Malicious actor attempting unauthorized access",
        typical_hours=(0, 24),           # Any time
        typical_cities=["Moscow", "Beijing", "Lagos", "São Paulo"],
        device_consistency="none",       # Rotating devices/user agents
        vpn_usage="always",
        failed_login_rate="very_high",   # Credential stuffing patterns
        travel_frequency="impossible",   # Physically impossible travel
        risk_level="high",
    ),
}
```

### 6.4 Batching Strategy

For Auto and Historical Bulk modes:

- **Batch size:** 10 events per LLM call (configurable via `SIMULATION_BATCH_SIZE`)
- **Prompt includes:** "Generate {batch_size} login events for {persona} using {protocol} protocol. Distribute timestamps across {time_description}. Return as a JSON array."
- **Auto mode:** Batches generated proactively; events submitted through the EventSink and dispatched at the configured rate. When queue runs low (< 5 events remaining), trigger next batch generation.
- **Historical bulk:** All batches generated sequentially until target count reached. Progress reported to frontend via response streaming or polling endpoint.
- **Mock provider:** Generates batches instantly (no external calls), so batching is just a loop.
- **MCP mode (P2):** Batching is implicit — the LLM calls `submit_login_event` multiple times during a single conversation turn. The prompt asks for N events and the LLM decides how to generate and submit them via tools.

---

## 7. Event Flow

```
Dashboard (Simulator Panel)
    │
    │ REST API calls
    ▼
API Gateway (auth + routing)
    │
    │ proxies to persona-simulator service
    ▼
Persona Simulator Service (port 8007)
    │
    ├── Resolves LLM provider (Claude / Ollama / Mock)
    │
    ├── [Mock/Claude basic/Ollama path]:
    │   ├── Constructs protocol-aware prompt (LLM) or applies rules (mock)
    │   ├── Generates/parses LoginEventIngest objects
    │   └── Submits via EventSink ─────────────────────┐
    │                                                   │
    ├── [Claude MCP path (P2)]:                         │
    │   ├── Constructs tools from shared TOOL_DEFINITIONS│
    │   │   (with EventSink injected into submit tool)  │
    │   ├── LLM calls query tools for context           │
    │   └── LLM calls submit_login_event tool ──────────┤
    │                                                   │
    │          ┌────────────────────────────────────────┘
    │          │
    │          ▼
    │   EventSink (IngestionServiceSink)
    │          │
    │          │ POSTs to Event Ingestion Service
    │          ▼
    │   Event Ingestion Service (port 8001)
    │          │
    │          │ All events tagged: source=simulator, is_synthetic=true
    │          │ Historical events also tagged: is_historical=true
    │          │
    │          └─→ Normal pipeline continues
    │              (normalization → enrichment → evaluation → ...)
    │
    └── Returns GenerationResult summary to caller
```

---

## 8. Priority Classification

### P0 (MVP)
- Persona Simulator backend service with health endpoint
- EventSink abstraction and IngestionServiceSink implementation
- GenerationResult summary model
- Four generation options (Manual, AI Suggest, Auto, Historical Bulk)
- MockProvider (rule-based, always available)
- ClaudeProvider with structured JSON output parsing (construct-then-submit pattern)
- LLM provider fallback chain (Claude → Mock)
- Protocol-aware prompt templates for OIDC, SAML, LDAP
- Batching for Auto and Historical Bulk modes
- Floating panel UI with all four option controls
- Shared tool definitions (`TOOL_DEFINITIONS`) — defined in P0, used in P2
- Shared tool implementations (query tools) — usable by basic ClaudeProvider for prompt context enrichment

### P1 (Should Have)
- OllamaProvider (adds the middle tier of the fallback chain)
- Scenario concept (named configurations combining multiple personas — see §9)
- Runtime LLM provider selection in the UI (instead of only .env config)
- Event generation history/log in the simulator panel

### P2 (Nice to Have — High Priority)
- ClaudeMCPProvider (tool-use pattern with EventSink-injected submit tool)
- ToolExecutor integration for context-aware generation
- MCP Server service (SSE transport wrapping shared tool implementations)
- User-facing MCP endpoint for Claude Desktop interaction
- Custom persona creation via UI
- Prompt template customization via UI
- Cost tracking dashboard for LLM API usage

---

## 9. Scenario Concept (P1)

A Scenario is a named, reusable configuration combining multiple personas into a coherent narrative.

```yaml
# Predefined scenarios (shipped with NAAS)
scenarios:
  normal_business_day:
    name: "Normal Business Day"
    description: "Typical enterprise traffic mix"
    personas:
      office_worker: 70
      road_warrior: 20
      attacker: 10
    protocol_mix:
      oidc: 50
      saml: 25
      ldap: 25

  credential_stuffing_attack:
    name: "Credential Stuffing Attack"
    description: "Active attack with background noise"
    personas:
      attacker: 90
      office_worker: 10
    protocol_mix:
      oidc: 40
      ldap: 60

  migration_day:
    name: "Migration Day"
    description: "Legacy LDAP traffic transitioning to OIDC"
    personas:
      office_worker: 85
      road_warrior: 15
    protocol_mix:
      oidc: 30
      saml: 10
      ldap: 60
    # Over the simulation period, gradually shift from LDAP-heavy to OIDC-heavy
```

Scenarios appear in the Auto and Historical Bulk modes as an alternative to single-persona selection. The UI shows a dropdown: "Persona: [Office Worker ▼]" or "Scenario: [Credential Stuffing Attack ▼]".

---

## 10. MCP Integration (P2)

### 10.1 Internal MCP: ClaudeMCPProvider

The `ClaudeMCPProvider` uses Claude's native tool-use capability (Anthropic API `tools` parameter) with the shared tool implementations from §5. From the LLM's perspective, this is indistinguishable from interacting with a "real" MCP server — Claude sees tool definitions, calls them, and receives results. The difference is purely transport: local function calls vs SSE protocol.

**What Claude can do in MCP mode:**
1. Query recent events to understand patterns (`query_recent_events`)
2. Find users matching criteria — e.g., inactive contractors (`query_users`)
3. Review past risk assessments to understand what triggers alerts (`query_risk_assessments`)
4. Generate and submit targeted events based on discovered context (`submit_login_event`)

**Example interaction (internal, automated):**
```
Prompt: "Generate a credential stuffing attack targeting users who haven't 
         logged in for 30+ days."

Claude's reasoning:
  1. Calls query_users(inactive_days=30) → finds 3 inactive users
  2. Calls query_recent_events(user_id="alice") → sees Alice usually logs in from NYC
  3. Calls submit_login_event(user_id="alice", protocol="oidc", 
         client_ip="185.220.101.1", ...) → attack event from Tor exit node
  4. Repeats for remaining inactive users with varied attack patterns
```

### 10.2 External MCP: MCP Server Service

A separate service (`services/mcp-server/`, port 8008) wraps the same shared tool implementations in SSE transport for Claude Desktop compatibility.

```python
# services/mcp-server/app/main.py
from naas_shared.simulation_tools import TOOL_DEFINITIONS, ToolExecutor

# MCP Server exposes TOOL_DEFINITIONS via SSE
# Tool calls handled by ToolExecutor with production EventSink
# Same implementations as ClaudeMCPProvider — different transport
```

**User experience:** A user connects Claude Desktop to the MCP Server endpoint. Claude discovers the available tools and can engage in natural language conversation:

- "Show me the last 50 events for alice" → `query_recent_events(user_id="alice", limit=50)`
- "What was the risk score on those?" → `query_risk_assessments(user_id="alice")`
- "Now generate an attacker trying to compromise her account" → `submit_login_event(...)`
- "What happened to the risk score after the attack?" → `query_risk_assessments(...)`

This transforms NAAS from a standalone dashboard into an AI-agent-accessible platform.

### 10.3 Why Two Layers Beat One

Building both layers is stronger than either alone:

- **Layer A alone** (internal tool use) demonstrates Claude API tool-use integration but doesn't show MCP protocol knowledge.
- **Layer B alone** (MCP Server) demonstrates MCP but requires Claude Desktop for interaction — not visible in the dashboard demo.
- **Both together** demonstrate understanding of *both* tool use and MCP, with shared implementations showing architectural judgment. The interview story: "The simulator uses tool use internally and MCP externally — same tools, two transport layers."

---

## 11. What This Design Does NOT Cover

- **Real SAML/LDAP authentication flows.** The simulator generates events that *look like* SAML/LDAP authentications. It does not perform actual SAML assertion exchange or LDAP bind operations. Only OIDC has real authentication via Keycloak.
- **LLM fine-tuning.** The prompts use general-purpose LLM capabilities. No fine-tuned models.
- **Cost billing or metering.** LLM API costs are the user's responsibility. The system does not track or limit spending beyond the provider's own rate limits.
- **Multi-user simulation state.** Auto mode is singleton — one auto-generation session at a time. Multiple concurrent auto sessions are not supported in MVP.

---

*End of Persona Simulator LLM Design Specification.*
