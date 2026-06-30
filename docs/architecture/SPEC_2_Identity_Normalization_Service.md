# Spec 2: Identity Normalization Service

**Service:** `identity-normalization` · **HTTP port:** `8002` · **Pipeline position:** second stage (consumes `login_events`, publishes `normalized_events`).

The Identity Normalization Service is the NAAS differentiator. It consumes login events from the `login_events` Redis Stream, extracts protocol-specific attributes (OIDC, SAML, LDAP) into a single **unified schema**, optionally **enriches** OIDC and SAML events with directory data from a live OpenLDAP lookup, **resolves conflicts** when more than one source supplies the same attribute, computes a **normalization confidence** score, writes the result to `events.normalized_attributes`, and republishes the event to the `normalized_events` stream for Signal Enrichment to consume.

This spec is consumed by the technical-architect agent to produce the chunked implementation plan, and by the per-chunk implementation agents as the source of truth. Sections marked **⚠️ CRITICAL** are hard requirements: do not deviate. Code blocks are labelled **[TRANSCRIBE EXACTLY]** (reproduce the values as written) or **[EXEMPLARY]** (conveys shape and intent; the implementer may adjust idiom while preserving the stated behaviour). Where this spec is silent on internal structure, agents may apply measured judgement consistent with the project's hexagonal architecture (ADR-0009).

---

## 1. Scope Boundary

This spec **creates** the following:

```
services/identity-normalization/
├── Dockerfile                  # Option A build (repo-root context); adds python-ldap system deps
├── requirements.in             # service-direct dependency floors (fastapi, uvicorn, python-ldap, pyyaml)
├── requirements.txt            # pip-compiled lock (from requirements.in, which pins shared via the ../../shared path dep); full pinned closure (ADR-0012)
└── app/
    ├── __init__.py
    ├── main.py                 # composition root: app factory, lifespan (starts consumer loop + group), /health
    ├── ports.py                # Protocol definitions (ProtocolAdapter, LdapEnricher, NormalizationRepository, EventPublisher)
    ├── consumer.py             # Redis Stream consumer loop (XREADGROUP / XACK) — the background worker
    ├── service.py              # NormalizationService — orchestrates extract → enrich → resolve → persist → publish
    ├── adapters/
    │   ├── __init__.py
    │   ├── oidc.py             # OIDC extract
    │   ├── saml.py             # SAML extract
    │   └── ldap.py             # LDAP extract + enrich (python-ldap pool, Redis cache, sanitization)
    ├── resolution.py           # conflict resolution + confidence scoring (the algorithmic core)
    ├── normalization_values.py # mapping tables + canonical value lookups
    ├── normalization_config.py # Pydantic models + loader/validator for config/normalization.yaml
    └── repository.py           # PostgresNormalizationRepository (UPDATE events.normalized_attributes by id)

config/
└── normalization.yaml          # authority weights, attribute importance, enrichment config (directory scaffolded by Spec 0)
```

This spec **modifies** the following shared, documentation, and orchestration files (and **nothing else**):

- `shared/naas_shared/config.py` — add one field to `Settings`: `ldap_pool_size: int = Field(default=3, ge=1, le=10)`. This is the same family as the existing `ldap_*` fields and reads the `LDAP_POOL_SIZE` value already present in `.env.example`, which is currently dropped by `extra = "ignore"`. **Add only this field.**
- `shared/naas_shared/constants.py` — add one constant: `LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"`. Follows the existing cache-prefix convention. The TTL is **not** a constant — it is read from `normalization.yaml` (`enrichment.sources.ldap.cache_ttl_seconds`). **Add only this constant.**
- `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` — SPEC_0 is the canonical documentation mirror of the shared modules, so the two `shared/` additions above **must be reflected in it within this same pipeline run**: add the `ldap_pool_size` field to the `Settings` snippet's LDAP block in **§ 3.8 (Shared Config Module)**, and add the `LDAP_ENRICHMENT_CACHE_PREFIX` constant to the cache key/prefix block in **§ 3.3 (Redis Stream and Channel Names / Constants)**. **⚠️ CRITICAL — these SPEC_0 edits are in scope for this spec and MUST be planned and applied in lockstep with the corresponding module changes (ideally in the same chunk). Do NOT defer them to a separate change manifest or a follow-up session.** A shared module and its SPEC_0 mirror change together or not at all; deferring the doc update is exactly how the spec and the code drift out of sync. Spec 0 holds no special ownership over the shared foundation — a later spec that legitimately needs to extend a shared module it consumes is expected to update both the module and its SPEC_0 mirror here, as a normal part of its own work.
- `docker-compose.yml` — add the `identity-normalization` service entry. Modify only the new entry; do not touch the infrastructure or `event-ingestion` services.

The recommended module decomposition above is advisory; the technical-architect may adjust module boundaries, but **must preserve the separation of concerns** — protocol adapters, enrichment, conflict resolution, the consumer loop, and persistence are distinct responsibilities (ADR-0009).

**Do NOT touch** any other `services/*/` directory, any other `shared/naas_shared/*` module (`models.py`, `schemas.py`, `database.py`, `redis_client.py`, `logging.py` are reused as-is), or `infrastructure/`. Within `docs/`, modify **only** `SPEC_0` — and only its § 3.3 and § 3.8 mirrors as described above — to keep it in sync with the shared-module changes; leave every other document untouched. The existing `services/identity-normalization/README.md` may remain as-is.

> ⚠️ The shared `NormalizedAttributes` model and its sub-models (in `shared/naas_shared/models.py`) and the shared `EventORM` mapping (in `shared/naas_shared/schemas.py`) already exist and are the contract. **Do not redefine, re-shape, or migrate them.**

---

## 2. Input Contracts

### 2.1 Inbound stream — consume `login_events`

The service runs a long-lived background consumer on the `login_events` stream using the shared constants and helpers.

- **Stream:** `STREAM_LOGIN_EVENTS` (`"login_events"`).
- **Consumer group:** `GROUP_NORMALIZATION` (`"normalization_workers"`). **⚠️ This service owns creation of its group.** Call `ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION)` once on startup (idempotent; the Event Ingestion service does not create it).
- **Consumer name:** unique per worker instance (e.g., derived from the container hostname). [EXEMPLARY]
- **Read pattern:** `XREADGROUP` with `{STREAM_LOGIN_EVENTS: ">"}` (new messages only), a small `count` (e.g., 10), and a blocking timeout (e.g., `block=2000` ms). [EXEMPLARY]

### 2.2 Message envelope

`publish_to_stream` wraps every payload as a single stream field `data` containing a JSON string. The consumer therefore:

1. Reads the message fields, takes `fields["data"]`, and `json.loads` it.
2. Validates the result with `LoginEventRecord.model_validate(...)` (shared model).
3. Uses `record.id` (the UUID, present as a string in the JSON) as the **correlation key** — the primary key of the `events` row this message refers to.

The payload is the full `LoginEventRecord` (ADR-0011): `id`, `user_id`, `protocol`, `client_ip`, `user_agent`, `timestamp`, `source`, `is_synthetic`, `is_historical`, `raw_attributes`, and present-but-null `normalized_attributes` / `enriched_signals` / `created_at`. Normalization reads `raw_attributes` **from the payload** — it does not need to `SELECT` the row before updating it.

### 2.3 `raw_attributes` shapes by protocol

`raw_attributes` is an opaque pass-through from ingestion; this service is the first stage to interpret it. The per-protocol key shapes are:

- **OIDC:** `name`, `email`, `groups`, `department`, `employee_type`
- **SAML:** `displayName`, `email`, `dept`, `employeeType`, `groups`
- **LDAP:** `cn`, `sn`, `mail`, `uid`, `departmentNumber`, `employeeType`, `memberOf`

Any individual key may be absent; absence is handled by single-source resolution (§5.5).

### 2.4 OpenLDAP — queried live for enrichment

For OIDC and SAML events (only), the service queries the OpenLDAP container to find the same user and merge directory attributes (§5.3, §5.4). The directory holds test users (e.g., `alice`, `bob`, `charlie`) under `ou=users,dc=corp,dc=com` with LDAP-convention attributes (`cn`, `sn`, `mail`, `uid`, `departmentNumber`, `employeeType`, `memberOf`). Connection parameters come from the shared `Settings` (§4).

### 2.5 PostgreSQL — the row already exists

Event Ingestion has already `INSERT`ed the `events` row (with `normalized_attributes` NULL) before publishing to `login_events` (the dual-write, ADR-0002). This service performs an **`UPDATE` by `id`**; it does not insert rows and does not own the table DDL.

---

## 3. Output Contracts

### 3.1 PostgreSQL — update `events.normalized_attributes`

For each processed event, serialize the produced `NormalizedAttributes` model and write it to the `normalized_attributes` JSONB column of the row with the matching `id`:

```
UPDATE events SET normalized_attributes = <serialized NormalizedAttributes> WHERE id = <event.id>
```

Use the shared `EventORM` mapping and an `AsyncSession` from the shared session factory (§5.7). `normalization_confidence` is a **field inside the JSONB**, not a separate column — there is no dedicated confidence column on the table. The update is idempotent: reprocessing the same event overwrites the same row with an equivalent payload.

### 3.2 Redis Stream — publish to `normalized_events`

After the PostgreSQL update is committed (§5.7), republish the event to `normalized_events`. Per ADR-0011, the payload is the **full `LoginEventRecord`** with `normalized_attributes` now populated, carrying `id` as the correlation key:

```python
# [EXEMPLARY]
record.normalized_attributes = normalized.model_dump(mode="json")
await publish_to_stream(STREAM_NORMALIZED_EVENTS, record.model_dump(mode="json"))
```

Use the shared constant `STREAM_NORMALIZED_EVENTS` and the shared `publish_to_stream` helper; do not hand-roll the `XADD`. Signal Enrichment consumes this stream under group `enrichment_workers`.

### 3.3 The `normalized_attributes` JSONB shape

The serialized `NormalizedAttributes` is the contract for the Risk Evaluator (which derives `normalization_risk = 1.0 - normalization_confidence`) and the dashboard's Normalization tab (which renders `resolution_details`). A representative payload for an enriched OIDC event with a department conflict:

```json
{
  "display_name": "Alice Smith",
  "primary_email": "alice@corp.com",
  "department": "Engineering",
  "employee_type": "FTE",
  "groups": ["admin", "engineering", "vpn-users"],
  "source_protocol": "oidc",
  "normalization_confidence": 0.87,
  "enrichment": { "applied": true, "source": "ldap", "cache_hit": false },
  "resolution_details": {
    "display_name":  { "resolution": "unanimous", "resolved_value": "Alice Smith", "confidence": 0.90, "sources": ["ldap", "oidc"] },
    "primary_email": { "resolution": "unanimous", "resolved_value": "alice@corp.com", "confidence": 0.95, "sources": ["ldap", "oidc"] },
    "department":    { "resolution": "priority", "resolved_value": "Engineering", "confidence": 0.72, "winner_source": "ldap", "conflicting_values": {"oidc": "Product"}, "penalty_applied": true },
    "employee_type": { "resolution": "unanimous", "resolved_value": "FTE", "confidence": 0.95, "sources": ["ldap", "oidc"] },
    "groups":        { "resolution": "list_merge", "resolved_value": ["admin", "engineering", "vpn-users"], "confidence": 0.85, "strategy": "union", "total_unique_groups": 3, "sources": ["ldap", "oidc"] }
  }
}
```

The shape is governed by the shared `NormalizedAttributes` model and its discriminated unions — see §5.5 for the exact rules that produce each variant.

---

## 4. Shared Imports

All of the following already exist in `naas_shared` and **must be imported, not redefined**:

```python
# [TRANSCRIBE EXACTLY — import surface]
from naas_shared.config import get_settings
from naas_shared.constants import (
    STREAM_LOGIN_EVENTS,
    STREAM_NORMALIZED_EVENTS,
    GROUP_NORMALIZATION,
    LDAP_ENRICHMENT_CACHE_PREFIX,   # added by this spec (§1)
)
from naas_shared.database import get_session_factory, get_db_session
from naas_shared.redis_client import (
    get_redis,
    publish_to_stream,
    ensure_consumer_group,
)
from naas_shared.logging import setup_logging, get_logger
from naas_shared.models import (
    LoginEventRecord,
    NormalizedAttributes,
    UnanimousResolution,
    PriorityResolution,
    SingleSourceResolution,
    ListMergeResolution,
    EnrichmentApplied,
    EnrichmentSkipped,
    HealthResponse,
)
from naas_shared.schemas import EventORM
```

LDAP connection settings come from the shared `Settings`: `ldap_host`, `ldap_port`, `ldap_base_dn` (`"dc=corp,dc=com"`), `ldap_admin_dn`, `ldap_admin_password`, and the newly added `ldap_pool_size`. **⚠️ There is no `LDAP_URI` / `LDAP_BIND_DN` / `LDAP_BIND_PASSWORD` in this project** — construct the URI as `ldap://{settings.ldap_host}:{settings.ldap_port}`, bind with `settings.ldap_admin_dn` / `settings.ldap_admin_password`, and search from `settings.ldap_base_dn` with `SCOPE_SUBTREE` (a subtree search from the domain root covers `ou=users`).

---

## 5. Implementation Requirements

The service follows the project's hexagonal (ports/adapters) structure (ADR-0009): domain logic and port `Protocol`s in the core, concrete I/O in adapters, a thin composition root. It is **both** a FastAPI app (for `/health` on port 8002) **and** a background stream consumer; the consumer loop is started in the app lifespan, not in a request handler.

### 5.1 Service composition and the consumer loop

The composition root (`main.py`) builds the app, wires the adapters into `NormalizationService`, and on lifespan startup: (1) calls `setup_logging("identity-normalization")`; (2) calls `ensure_consumer_group(...)`; (3) loads and validates `config/normalization.yaml` (§5.6) — **invalid config aborts startup**; (4) launches the consumer loop as a background task. On shutdown it cancels the loop cleanly.

The consumer loop (`consumer.py`) processes one message at a time:

```text
# [EXEMPLARY — control flow; the ordering in steps 3–5 is ⚠️ CRITICAL]
loop:
  msgs = XREADGROUP(group=normalization_workers, consumer=<name>, {login_events: ">"}, count, block)
  for (msg_id, fields) in msgs:
    try:
      record = LoginEventRecord.model_validate(json.loads(fields["data"]))   # 1. parse
      normalized = await service.normalize(record)                           # 2. extract→enrich→resolve
      await repository.write(record.id, normalized)  # commit                 # 3. PERSIST (point of no return)
      await publisher.publish_normalized(record, normalized)                  # 4. XADD normalized_events
      XACK(login_events, normalization_workers, msg_id)                       # 5. ACK only after 3 & 4 succeed
    except Exception:
      log.error(...); # do NOT XACK — message stays in the pending-entries list (PEL)
```

**⚠️ CRITICAL ordering (ADR-0002 dual-write):** persist to PostgreSQL and commit **before** publishing to `normalized_events`, and `XACK` **only after** both the commit and the publish succeed. If any step raises, do **not** ACK; the message remains in the consumer group's pending-entries list (PEL). Note: Redis Streams do **not** auto-redeliver pending entries — there is no visibility timeout, and the exemplary loop above reads only `">"` (new messages). Reprocessing a stuck entry therefore requires an explicit claim step (`XAUTOCLAIM`/`XCLAIM`, or a startup `"0"` read), which is **deferred** to a retry / dead-letter policy (tracked in `docs/FOLLOWUPS.md`). The persist-before-publish ordering keeps the event recoverable for that future policy rather than silently dropped: because the `UPDATE` is idempotent and `normalized_events` carries the full record, the intended at-least-once reprocessing is safe (a duplicate downstream message is reprocessed idempotently). Do not drop, skip, or dead-letter a message merely because LDAP enrichment failed — enrichment failure is handled by graceful degradation (§5.4), not by failing the event.

The worker obtains DB sessions from `get_session_factory()` directly (opening and committing one session per event), **not** from the request-scoped `get_db_session` dependency — the latter is a FastAPI dependency tied to the HTTP request lifecycle and is used only by `/health` (§5.8).

### 5.2 Protocol adapters — `extract`

Each adapter maps protocol-specific raw attributes to the unified schema and applies value normalization. This is deterministic, no network I/O. The unified schema fields are: `display_name`, `primary_email`, `department`, `employee_type`, `groups`.

**Mapping table** [TRANSCRIBE EXACTLY — the mappings are the contract]:

| Unified field   | OIDC claim      | SAML attribute | LDAP attribute     | Notes                                            |
| --------------- | --------------- | -------------- | ------------------ | ------------------------------------------------ |
| `display_name`  | `name`          | `displayName`  | `cn`               | string                                           |
| `primary_email` | `email`         | `email`        | `mail`             | string                                           |
| `department`    | `department`    | `dept`         | `departmentNumber` | string, value-normalized                         |
| `employee_type` | `employee_type` | `employeeType` | `employeeType`     | normalized to `FTE` \| `contractor` \| `vendor`  |
| `groups`        | `groups`        | `groups`       | `memberOf`         | list; merge strategy `union`                     |

> ⚠️ **`groups` from LDAP `memberOf`:** `memberOf` values are typically full DNs (e.g., `cn=engineering,ou=groups,dc=corp,dc=com`). The unified `groups` is a list of **group names**, so the LDAP adapter must reduce each `memberOf` DN to its group name (the `cn` RDN). Confirm the exact `memberOf` format against `infrastructure/openldap/bootstrap.ldif` during implementation.

**Value normalization** — applied before resolution. Lookups are case-insensitive. [TRANSCRIBE EXACTLY — the canonical target values must be identical across adapters so cross-protocol values compare equal]

```python
DEPARTMENT_CANONICAL = {
    "eng": "Engineering", "engineering": "Engineering", "software engineering": "Engineering",
    "r&d": "Engineering", "product development": "Engineering",
    "fin": "Finance", "finance": "Finance", "accounting": "Finance",
    "hr": "Human Resources", "human resources": "Human Resources", "people ops": "Human Resources",
    "it": "Information Technology", "information technology": "Information Technology", "infra": "Information Technology",
    "sales": "Sales", "revenue": "Sales",
    "mktg": "Marketing", "marketing": "Marketing",
}

EMPLOYEE_TYPE_CANONICAL = {
    "fte": "FTE", "e": "FTE", "employee": "FTE", "full-time": "FTE", "full time": "FTE", "regular": "FTE",
    "contractor": "contractor", "c": "contractor", "contract": "contractor", "contingent": "contractor", "temp": "contractor",
    "vendor": "vendor", "v": "vendor", "external": "vendor", "partner": "vendor", "third-party": "vendor",
}
```

**⚠️ Unmapped-value handling (this differs by field type):**

- **`department`** (free string): an unrecognized value is **retained**, stored as-is and title-cased, and a structured `unmapped_attribute_value` warning is logged. Because the value is retained, it participates in resolution as a normal present value; the `0.2` normalization-failure penalty is applied to a resolution's confidence **only when this unmapped value is the one that wins** (see §5.5). If a validly-mapped source outranks it, the resolved value is the mapped one and the unmapped penalty does not apply.
- **`employee_type`** (typed `Literal["FTE", "contractor", "vendor"]` on the model): an unrecognized value is **discarded** (the field becomes `None` for that source) and a structured `unmapped_attribute_value` warning is logged. **No numeric confidence penalty is applied** — because the value is discarded, that source simply drops out of the present-set for `employee_type` and resolution proceeds as if the source were silent on the field (§5.5): if another source supplied a valid value, that value resolves at its own full confidence; if not, the attribute is `None` and contributes `0.0`. It must **never** be stored as the raw string — a non-Literal value would fail `NormalizedAttributes` validation.

### 5.3 LDAP adapter — `enrich` (live query)

The LDAP adapter has two methods. `extract(raw_attributes)` is the passive mapping in §5.2 (also used internally to normalize query results). `enrich(correlation_field, lookup_value) -> dict | None` is the active directory query:

- **Connection:** a small pool of `settings.ldap_pool_size` connections (default 3) to `ldap://{settings.ldap_host}:{settings.ldap_port}`, bound with `settings.ldap_admin_dn` / `settings.ldap_admin_password`. `python-ldap` is synchronous; **⚠️ wrap every blocking LDAP call in `asyncio.to_thread(...)`** so the async event loop is never blocked.
- **Reverse mapping:** `enrich` receives a **unified** field name (e.g., `primary_email`) and reverse-maps it to the LDAP attribute (`mail`) using the adapter's own mapping table — the single source of truth for LDAP↔unified translation. The enrichment config never names LDAP attributes (§5.6). The fetched attribute list is likewise the reverse-mapped set of unified fields.
- **Search:** `search_s(settings.ldap_base_dn, SCOPE_SUBTREE, filter_str, attrlist)`, where `filter_str` is built from the reverse-mapped attribute and the **sanitized** lookup value.
- **⚠️ LDAP injection sanitization (required):** escape the lookup value with `ldap.filter.escape_filter_chars` before building the filter. Never interpolate a raw value into a filter string.

```python
# [EXEMPLARY]
import ldap.filter
def build_search_filter(ldap_attr: str, lookup_value: str) -> str:
    return f"({ldap_attr}={ldap.filter.escape_filter_chars(lookup_value)})"
```

- **Result:** on a match, pass the returned LDAP attributes through `extract(...)` and return the unified-schema dict. Return `None` on no match, query failure, or an un-reverse-mappable correlation field.

**Caching** (Redis):

- **Key:** `f"{LDAP_ENRICHMENT_CACHE_PREFIX}{correlation_value}"` (e.g., `ldap_enrichment:alice@corp.com`).
- **TTL:** `enrichment.sources.ldap.cache_ttl_seconds` from `normalization.yaml` (default 60). Not a constant.
- **⚠️ Three-state semantics — implement the negative cache:** the cache must distinguish (a) **miss** — key absent (`GET` returns `None`) → query LDAP; (b) **negative hit** — key present holding a stored sentinel for "no such user" (e.g., the JSON string `"null"`) → treat as no-match without querying; (c) **positive hit** — key present holding a JSON attribute object → use it. Cache both positive results (the unified dict) and negative results (the sentinel) with the same TTL, so repeated logins for an unknown user do not hammer the directory.

### 5.4 Enrichment orchestration and skip reasons

**⚠️ Source-agnostic:** enrichment decisions depend **only** on `protocol` and config — **never** branch on `is_synthetic`. Real and simulated OIDC/SAML events are enriched identically.

Enrichment decision: attempt LDAP enrichment **iff** `enrichment.sources.ldap.enabled` **and** `protocol in ("oidc", "saml")`. LDAP-protocol events skip enrichment (their directory data is already in the payload).

The `NormalizedAttributes.enrichment` field is **always populated** (it is required on the model). Map the outcome to exactly one variant, using the closed `skip_reason` enum:

| Outcome                                            | `enrichment` value                                                     |
| -------------------------------------------------- | ---------------------------------------------------------------------- |
| Match returned (live query or positive cache hit)  | `EnrichmentApplied(applied=True, source="ldap", cache_hit=<bool>)`     |
| Enrichment disabled in config                      | `EnrichmentSkipped(skip_reason="ldap_disabled")`                       |
| Event protocol is `ldap`                           | `EnrichmentSkipped(skip_reason="ldap_event")`                          |
| Correlation value missing/empty in primary attrs   | `EnrichmentSkipped(skip_reason="invalid_correlation_key")`             |
| No directory match (live or negative cache hit)    | `EnrichmentSkipped(skip_reason="no_ldap_match")`                       |
| LDAP search exceeded `timeout_ms`                  | `EnrichmentSkipped(skip_reason="ldap_timeout")`                        |
| Connection refused / network error                 | `EnrichmentSkipped(skip_reason="ldap_connection_error")`               |
| Other LDAP-side error                              | `EnrichmentSkipped(skip_reason="ldap_search_error")`                   |

**⚠️ Graceful degradation (ADR-0008):** on any failure or miss the event is **never** rejected or delayed — normalization proceeds with primary-source-only data and the appropriate `EnrichmentSkipped` variant. Log levels: `no_ldap_match` → INFO; `invalid_correlation_key` / `ldap_timeout` → WARNING; connection/search errors → ERROR (rate-limit connection-refused logging to first occurrence to avoid spam). Transient failures (`timeout`/`connection_error`/`search_error`) are **not** negative-cached, so the service recovers automatically when LDAP returns.

> Note: `cache_hit` is surfaced only on `EnrichmentApplied`. A negative cache hit yields `EnrichmentSkipped(skip_reason="no_ldap_match")` and does not separately record its cache-hit-ness; cache-effectiveness metrics are out of scope for the per-event metadata (a future metrics layer is the proper home).

### 5.5 Conflict resolution and confidence — the algorithmic core

After extraction (and enrichment, if applied), the service holds, per unified attribute, a map of `{source_protocol: normalized_value}` for every source that supplied a non-null value. For a single-protocol event with no enrichment this map has one entry per present attribute; for an enriched OIDC/SAML event it may have two (`oidc`/`saml` plus `ldap`).

**⚠️ CRITICAL — resolution variants must match the shared model exactly.** `resolution_details` is `Dict[str, ResolutionDetail]`, a discriminated union over **exactly four** `resolution` literals: `unanimous`, `priority`, `single_source`, `list_merge`. The service must emit **only** these. (Do not emit `no_data`, `fallback`, or any other discriminator — those would fail `NormalizedAttributes` validation.) Resolve each **scalar** attribute over its set of present (non-null) sources:

- **0 present sources** → the unified attribute is `None`; it contributes `0.0` to the overall confidence (§5.5.2); and **no entry is written** to `resolution_details` for it (the dict simply omits the key).
- **Exactly 1 present source** → `SingleSourceResolution(resolution="single_source", resolved_value=<value>, confidence=<source weight for this attribute>, sources=[that one protocol])`. This is the common single-protocol path and the enriched path where only one source had the attribute.
- **≥2 present sources, all agree** (after value normalization) → `UnanimousResolution(resolution="unanimous", resolved_value=<agreed value>, confidence=<max authority weight among the agreeing sources>, sources=[the agreeing protocols])`. Every multi-element `sources` list (here and in `ListMergeResolution`) is **sorted alphabetically** — deterministic output that exact-match test assertions can rely on.
- **≥2 present sources, disagree** → `PriorityResolution(resolution="priority", resolved_value=<winner's value>, confidence=<winner weight × 0.8>, winner_source=<protocol>, conflicting_values={losing protocol: losing value, ...}, penalty_applied=True)`. The winner is the highest-priority source (per the attribute's `priority` list) that has a value; if — pathologically — no configured-priority source has a value, the highest-weight present source wins. `conflicting_values` contains only the losing **non-null** values.

**Normalization-failure penalty.** The `0.2` penalty attaches to a resolution's confidence **only when the resolved (winning) value is itself an unmapped value** (clamped to `[0.0, 1.0]`). This can happen only for `department`, whose unmapped values are retained (§5.2); it can **never** happen for `employee_type`, whose unmapped values are discarded to `None`. A source whose value was discarded — an unmapped `employee_type`, or any field simply absent — is **not** a present source for that attribute, so it neither contributes nor penalizes: a surviving valid source resolves at its own full confidence (the discarded source's failure does **not** reduce it), and if no source survives the attribute is `None` contributing `0.0`. The discarded value is recorded only as a logged warning, never as a numeric penalty carried into another source's resolution.

For the **list** attribute `groups`, use `ListMergeResolution`:

```python
# [EXEMPLARY]
ListMergeResolution(
    resolution="list_merge",
    resolved_value=<merged, de-duplicated, sorted group list>,
    confidence=<see below>,
    strategy=<config merge_strategy; default "union">,
    total_unique_groups=<len of merged list>,
    sources=<source protocols that contributed groups, sorted alphabetically>,
)
```

Merge per `merge_strategy` (`union` default; also `intersection`, `priority`). Confidence: if one source contributed, that source's weight; if multiple, `0.7 + 0.3 × (fraction of merged groups present in more than one source)`.

#### 5.5.1 Per-attribute authority weights

Authority weights and priority order come from `config/normalization.yaml` (§5.6). Each source's weight for an attribute is the per-attribute weight (or the `defaults.source_weights` value when the attribute has no explicit entry).

#### 5.5.2 Overall `normalization_confidence`

The top-level `normalization_confidence` is the **importance-weighted average** of per-attribute confidences. Attributes with no present source contribute `0.0`.

```python
# [TRANSCRIBE EXACTLY — weights sum to 1.0]
ATTRIBUTE_IMPORTANCE = {
    "display_name": 0.15,
    "primary_email": 0.25,
    "department": 0.20,
    "employee_type": 0.25,
    "groups": 0.15,
}
```

```python
# [EXEMPLARY]
confidence = sum(ATTRIBUTE_IMPORTANCE[a] * per_attribute_confidence.get(a, 0.0)
                 for a in ATTRIBUTE_IMPORTANCE)
normalization_confidence = max(0.0, min(1.0, confidence))
```

`source_protocol` on the output is the **primary event's** protocol (`oidc`/`saml`/`ldap`), even when LDAP enrichment contributed.

### 5.6 `config/normalization.yaml` and its validation

Create `config/normalization.yaml` with two top-level sections: `attributes`/`defaults` (authority) and `enrichment`. The values below are the project defaults [TRANSCRIBE EXACTLY — the weights tune runtime behaviour; note the §3.3 worked example was computed against the pre-change display_name weights and is preserved as illustrative]:

```yaml
# config/normalization.yaml

defaults:
  source_weights:
    ldap: 0.7
    saml: 0.6
    oidc: 0.8

attributes:
  display_name:
    priority: [oidc, saml, ldap]                      # changed from [ldap, saml, oidc]
    weights: {ldap: 0.85, saml: 0.75, oidc: 0.70}     # compressed band; weight ORDER ldap>saml>oidc preserved
    rationale: >-
      The cloud IdP is the system of record for user-presented identity: users curate
      their own preferred/display name there, so the IdP value wins on disagreement.
      Weights are intentionally decoupled from priority for this attribute — they encode
      source reliability for the canonical record, where the directory's verified legal
      name remains the most reliable, so a contested IdP-sourced name resolves at
      correspondingly modest confidence.
  primary_email:
    priority: [oidc, saml, ldap]
    weights: { oidc: 0.95, saml: 0.75, ldap: 0.65 }
    rationale: "OIDC has the most current email from recent SSO migration"
  department:
    priority: [ldap, oidc, saml]
    weights: { ldap: 0.90, oidc: 0.70, saml: 0.50 }
    rationale: "LDAP synced nightly from HR; OIDC updated on login; SAML may be stale"
  employee_type:
    priority: [ldap, saml, oidc]
    weights: { ldap: 0.95, saml: 0.80, oidc: 0.60 }
    rationale: "HR system (LDAP) is authoritative for employment classification"
  groups:
    merge_strategy: union
    rationale: "Groups from all sources are valid; a user may hold roles in each system"

enrichment:
  sources:
    ldap:
      enabled: true
      correlation_key: primary_email   # unified field; adapter reverse-maps to the LDAP attribute
      timeout_ms: 2000
      on_failure: continue    # only "continue" is supported; "fail" violates ADR-0008 graceful-degradation
      cache_ttl_seconds: 60
      # enrich_attributes:             # optional; unified field names. If omitted, all mapped attrs are fetched.
      #   - display_name
      #   - primary_email
      #   - department
      #   - employee_type
      #   - groups
```

Semantics: `priority` resolves disagreements; `weights` (0.0–1.0) drive confidence; `rationale` is human-readable only (surfaced in the dashboard); `defaults` apply to any attribute without an explicit entry; `merge_strategy` applies to list attributes only. `correlation_key` is a **unified** field name; `on_failure: continue` is the only supported value (see below); `cache_ttl_seconds` is the LDAP cache TTL; `enrich_attributes` (if present) lists unified field names only.

**⚠️ Startup validation (config is loaded once at startup; no hot-reload).** Validate with a Pydantic model and **abort startup with a descriptive error** on any of:

- `correlation_key` is not a unified field the LDAP adapter can reverse-map to an LDAP attribute (valid: `display_name`→`cn`, `primary_email`→`mail`, `department`→`departmentNumber`, `employee_type`→`employeeType`, `groups`→`memberOf`).
- `on_failure` is not `"continue"`. The `"fail"` option (rejecting events on enrichment failure) is not implemented — events are never rejected on enrichment failure (§5.4 / ADR-0008 graceful-degradation invariant). The option is reserved.
- `enrich_attributes` (if present) contains a name that is not a reverse-mappable unified field.
- `cache_ttl_seconds` is not a positive integer.

### 5.7 Persistence, ordering, and graceful degradation (summary)

The `NormalizationService.normalize(record)` is the domain orchestration: select the primary adapter by `record.protocol`, `extract` the primary attributes, decide and attempt enrichment (§5.4), run resolution (§5.5), and return a `NormalizedAttributes`. The consumer loop (§5.1) then persists (commit), publishes, and ACKs in that order. Keep this orchestration in the service/consumer layer, not in adapters.

### 5.8 Dockerfile, requirements, and compose entry

- **`requirements.in` (floors) / `requirements.txt` (lock):** the `.in` declares the service-direct floors `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `python-ldap>=3.4`, `pyyaml>=6.0` (data-layer deps are owned by `naas_shared`, not redeclared); the `.txt` is the pip-compiled lock of that `.in` (which pulls in shared's runtime closure via the `../../shared` path dependency), pinning the full transitive closure (ADR-0012; see `DEPENDENCIES.md`).
- **`Dockerfile`:** follow the Spec 1 Option A pattern (repo-root build context; `python:3.12-slim`; install the lockfile `RUN pip install -r requirements.txt` first, then `COPY shared/ /app/shared/` and `RUN pip install -e /app/shared/ --no-deps` so the locked versions stay authoritative; `EXPOSE 8002`; `CMD uvicorn app.main:app --host 0.0.0.0 --port 8002`). **⚠️ `python-ldap` needs system build dependencies** the Spec 1 image does not carry — add an `apt-get install` for `libldap2-dev`, `libsasl2-dev`, and `gcc` (plus `build-essential` if needed) **before** `pip install`, or the build fails compiling `python-ldap`.
- **`docker-compose.yml`:** add an `identity-normalization` entry — repo-root build context, `env_file: .env`, `${IDENTITY_NORMALIZATION_PORT:-8002}:8002`, a `/health` healthcheck on port 8002, and `depends_on` the `postgres`, `redis`, and `openldap` services with `condition: service_healthy`. Mount `./config:/app/config` (read-only) so the service can read `config/normalization.yaml`. Do not modify the infrastructure or `event-ingestion` services.
- **`/health`:** a `GET /health` returning the shared `HealthResponse` (`service="identity-normalization"`), using the request-scoped `get_db_session` for a PG `SELECT 1` and `get_redis().ping()`. Both OK → `healthy`; Redis down but PG OK → `degraded`; PG down → `unhealthy`. Return HTTP 200 with the status in the body (do not 500 on a dependency outage).

---

## 6. Validation Criteria

1. **Mapping.** Ingest one event per protocol; verify `events.normalized_attributes` carries the unified fields: LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name` (and the rest of the mapping table).
2. **Value normalization.** An event with `department: "eng"` normalizes to `"Engineering"`; `employee_type: "E"` → `"FTE"`. An unmapped `employee_type: "XYZ"` → `null`, **excluded from resolution** (no `resolution_details` entry when it is the sole source; if another source has a valid value, that source resolves at full confidence with no carried-over penalty), with a data-quality warning logged. An unmapped department is title-cased and retained, and is penalized by `0.2` only in the resolution where that unmapped value wins.
3. **Enrichment applied + conflict.** For an OIDC event whose user **exists** in OpenLDAP, with `department: "Product"` in the token while LDAP says Engineering: verify `enrichment.applied: true`, `source_protocol: "oidc"`, a `priority` resolution on `department` (`winner_source: "ldap"`, `penalty_applied: true`, conflict recorded), and `resolution_details` showing both `oidc` and `ldap` as sources for agreeing attributes.
4. **Enrichment skipped — no match.** For an OIDC event whose user does **not** exist in OpenLDAP: verify `enrichment.applied: false`, `enrichment.skip_reason: "no_ldap_match"`, single-source resolution throughout, and that the event was still processed (not dropped).
5. **LDAP event skips enrichment.** For a `protocol: "ldap"` event: verify `enrichment.applied: false`, `skip_reason: "ldap_event"`, `source_protocol: "ldap"`.
6. **Negative cache.** Two successive OIDC logins for the same absent user produce only **one** LDAP query (the second resolves from the negative cache); `XINFO`/logs confirm no second directory hit within the TTL.
7. **Pipeline + ACK semantics.** `XINFO GROUPS login_events` shows `normalization_workers`; a successfully processed message is ACKed (pending count returns to 0); a message that fails processing remains pending (not ACKed) in the PEL — Redis does not auto-redeliver it, so it is not reprocessed until the deferred claim-and-retry policy (`XAUTOCLAIM`) lands. `normalized_events` gains one message per processed event, carrying the full record with `normalized_attributes` populated.
8. **Health.** `curl -s http://localhost:8002/health` → `{"status":"healthy","service":"identity-normalization",...}`.
9. **Config validation.** Starting with an invalid `correlation_key` (e.g., `favorite_color`) aborts startup with a descriptive error.

---

## 7. What NOT to Build

- **Do NOT redefine** `NormalizedAttributes`, its resolution/enrichment sub-models, `LoginEventRecord`, `HealthResponse`, `EventORM`, or any shared constant — import them.
- **Do NOT emit** any `resolution` discriminator other than `unanimous`, `priority`, `single_source`, `list_merge`, and **never** store a non-Literal `employee_type` value.
- **Do NOT branch on `is_synthetic`.** Enrichment is source-agnostic.
- **Do NOT reject, delay, or dead-letter** an event when LDAP enrichment fails or misses — degrade gracefully to single-source.
- **Do NOT write to LDAP**, perform reverse enrichment (OIDC/SAML enriching LDAP events), or enrich from any source other than OpenLDAP.
- **Do NOT** build cross-event correlation, a persistent user-identity graph, attribute-change detection, composite/expression correlation keys, or live Active Directory enrichment — all out of scope.
- **Do NOT** make the attribute mapping table runtime-configurable, and **do NOT** hot-reload `normalization.yaml` (startup load only).
- **Do NOT** `Base.metadata.create_all`, add migrations, or alter the `events` table — insert/`SELECT`-free `UPDATE` by `id` only.
- **Do NOT** add endpoints beyond `/health`, and **do NOT** add authentication (handled upstream in a later spec).
- **Do NOT** roll back or skip the PostgreSQL commit on a publish failure in a way that loses the event — leave the message unACKed in the PEL instead, so the deferred claim-and-retry policy can reprocess it (Redis does not auto-redeliver it).
- **Do NOT** touch other services or other `naas_shared` modules beyond the modifications named in §1, and **do NOT** modify any document under `docs/` other than the SPEC_0 § 3.3 / § 3.8 mirrors named in §1.
- **Do NOT** defer the SPEC_0 documentation mirror to a separate change manifest or a later session. The § 3.3 / § 3.8 updates are part of this spec's work and are applied in the same pipeline run as the shared-module changes, so the code and its canonical mirror move in lockstep.
