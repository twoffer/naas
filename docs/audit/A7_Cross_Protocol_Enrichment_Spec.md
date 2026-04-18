# A7 — Multi-Protocol Adapter Roles and Cross-Protocol Enrichment
## Specification for Spec 2 — Identity Normalization Service

**Purpose:** Define the role of each protocol adapter for both live and simulated events, specify the cross-protocol LDAP enrichment step, and establish the OpenLDAP container's pipeline role.

**Audience:** Claude Code agents implementing Spec 2, and the technical-architect agent producing the Spec 2 implementation plan.

**Context:** This spec resolves a documentation ambiguity identified during A6 development. SYSTEM_ARCHITECTURE.md §3 describes the LDAP adapter as "Queries OpenLDAP for user attributes," but never specifies *when* that query occurs or *which events* trigger it. The A2 Conflict Resolution Spec §4.2 implies cross-protocol enrichment ("OIDC event triggers an LDAP lookup") without specifying it as an explicit pipeline step. This spec resolves both gaps.

---

## 1. Problem Statement

The NAAS Identity Normalization Service receives login events tagged with one of three protocols (`oidc`, `saml`, `ldap`). Each protocol adapter maps protocol-specific attribute names to the unified schema. However, the existing documentation leaves three questions unanswered:

1. **Does the LDAP adapter ever query the live OpenLDAP server?** The SYSTEM_ARCHITECTURE.md says it does, but all LDAP events are simulator-generated with pre-populated `raw_attributes`, making a live query redundant for those events.
2. **Does the normalization service perform cross-protocol enrichment?** The A2 spec implies it but never specifies it as a pipeline step.
3. **What is the OpenLDAP container's role in the pipeline?** If neither question above results in a live LDAP query, the container serves no pipeline purpose.

---

## 2. Design Decision: Cross-Protocol LDAP Enrichment

### 2.1 Decision

The Identity Normalization Service performs **cross-protocol LDAP enrichment** for all OIDC and SAML events. When an OIDC or SAML login event arrives, the normalization service:

1. Extracts attributes from the event payload via the primary protocol adapter
2. Looks up the same user in OpenLDAP via the LDAP adapter's enrichment method
3. If a match is found, feeds both attribute sets into the A2 conflict resolution algorithm
4. If no match is found or the lookup fails, proceeds with single-source normalization

This makes OpenLDAP an active participant in the normalization pipeline — not just infrastructure for the LDAP adapter to query on `protocol: "ldap"` events.

### 2.2 Rationale

1. **Justifies the OpenLDAP container's existence.** The container is already defined in Spec 0's Docker Compose stack. Without enrichment, it serves no pipeline purpose.
2. **Exercises the A2 conflict resolution algorithm on live traffic.** Without enrichment, multi-source resolution only fires when the simulator happens to generate overlapping data from different protocols. With enrichment, every OIDC/SAML login for a user who also exists in LDAP triggers genuine multi-source conflict resolution, making the `normalization_confidence` score meaningful.
3. **Models real enterprise behavior.** In production IAM, OIDC tokens carry a subset of user attributes; the authoritative HR data lives in the directory. Cross-referencing the token against the directory is standard practice.
4. **Enables compelling demo scenarios.** Creating an OIDC event with `department: "Product"` for a user whose LDAP entry has `departmentNumber: "Engineering"` triggers visible conflict resolution with confidence penalties — a live demonstration of the normalization layer doing real work.

### 2.3 Scope Boundaries

- **Enrichment source: LDAP only.** The configuration schema supports multiple enrichment sources (see §5), but only the LDAP provider is implemented. Additional sources (e.g., HR API) are a future enhancement.
- **Enrichment direction: one-way.** LDAP enriches OIDC/SAML events. There is no reverse enrichment (OIDC data does not enrich LDAP events).
- **No user profile aggregation.** Enrichment is per-event. The system does not build a persistent "best known" user profile across events. That would be a P2 enhancement (user identity graph).

---

## 3. Protocol Adapter Roles

### 3.1 Role Summary

| Adapter | Primary Role (`extract`) | Enrichment Role (`enrich`) | Live Server Dependency |
|---------|--------------------------|----------------------------|----------------------|
| **OIDC** | Extract JWT claims from `raw_attributes` → unified schema | None | No (claims are in the event payload) |
| **SAML** | Map SAML-convention attribute names from `raw_attributes` → unified schema | None | No (events are simulator-generated) |
| **LDAP** | Map LDAP attribute names from `raw_attributes` → unified schema | Query OpenLDAP by correlation key, return unified-schema attributes | **Yes** — queries OpenLDAP for enrichment |

### 3.2 LDAP Adapter: Dual Responsibility

The LDAP adapter has two distinct methods:

**`extract(raw_attributes: dict) → dict`**
- Passive mapping. Takes LDAP-convention attributes from the event payload and maps them to the unified schema.
- Called for `protocol: "ldap"` events as the primary adapter.
- Also called internally by `enrich()` to normalize the LDAP query results.
- No network I/O. Deterministic. Fast.

**`enrich(correlation_field: str, lookup_value: str) → dict | None`**
- Active query. Receives a unified schema field name (e.g., `"primary_email"`) and lookup value (e.g., `"alice@corp.com"`). Internally reverse-maps the unified field name to the corresponding LDAP attribute (e.g., `primary_email` → `mail`) using its own mapping table, constructs the LDAP search filter, queries OpenLDAP, fetches attributes, passes them through `extract()` for normalization, and returns the unified-schema result.
- Called by the normalization orchestrator for OIDC and SAML events when enrichment is enabled.
- Returns `None` if no matching user is found, if the LDAP query fails, or if `correlation_field` cannot be reverse-mapped to a known LDAP attribute.
- Involves network I/O (LDAP search). Subject to timeout and caching (see §6).
- **Single source of truth:** The LDAP adapter's mapping table is the sole authority for LDAP↔unified schema translation. The enrichment configuration never references LDAP-specific attribute names — it operates entirely in unified schema space.

Both methods output unified-schema dictionaries. This ensures the conflict resolution algorithm always works with consistently shaped data regardless of how the attributes were obtained.

### 3.3 OIDC and SAML Adapters

These adapters have a single responsibility: `extract(raw_attributes: dict) → dict`. They map protocol-specific attribute names to the unified schema and apply value normalization per A2 §2.2.

- **OIDC Adapter:** Maps `name` → `display_name`, `email` → `primary_email`, `department` → `department`, `employee_type` → `employee_type`, `groups` → `groups`.
- **SAML Adapter:** Maps `displayName` → `display_name`, `email` → `primary_email`, `dept` → `department`, `employeeType` → `employee_type`, `groups` → `groups`.

Neither adapter has an `enrich()` method. Neither communicates with an external server.

---

## 4. Enrichment Rules by Event Type

### 4.1 Decision Matrix

| Event Protocol | `is_synthetic` | LDAP Enrichment? | Rationale |
|---------------|----------------|-------------------|-----------|
| `oidc` | `false` (live Keycloak login) | **Yes** | Primary use case. OIDC token carries partial identity; LDAP provides authoritative HR data. |
| `oidc` | `true` (simulator-generated) | **Yes** | The normalization service is source-agnostic. Enriching simulated events enables demo scenarios (attribute conflicts, confidence scoring) and avoids conditional branching on `is_synthetic`. |
| `saml` | `true` (always simulated) | **Yes** | Same reasoning as simulated OIDC. Demonstrates cross-protocol enrichment for SAML events. |
| `ldap` | `true` (always simulated) | **No** | Simulated LDAP events represent the result of a completed LDAP authentication, which would have already fetched attributes from the directory. Re-querying the same directory is redundant. |
| `ldap` | `false` (hypothetical live) | **No** | Same reasoning. A live LDAP bind would return attributes directly. Not applicable in the demo environment (no live LDAP authentication flow exists). |

### 4.2 Implementation Rule

The normalization orchestrator applies this logic:

```python
def should_enrich_from_ldap(event_protocol: str, enrichment_config) -> bool:
    """Determine whether to attempt LDAP enrichment for this event."""
    if not enrichment_config.sources.ldap.enabled:
        return False
    # Enrich OIDC and SAML events only. LDAP events already carry directory data.
    return event_protocol in ("oidc", "saml")
```

Note: `is_synthetic` is deliberately not checked. The normalization service does not branch on event provenance.

---

## 5. Enrichment Configuration

### 5.1 Configuration Schema

LDAP enrichment is configured in the existing `normalization_authority.yaml` file (defined in A2 §3.1), extended with a new `enrichment` section:

```yaml
# Appended to config/normalization_authority.yaml

enrichment:
  sources:
    ldap:
      enabled: true

      # Correlation: which unified schema field to use for user matching.
      # The LDAP adapter reverse-maps this to the corresponding LDAP attribute
      # (e.g., "primary_email" → "mail") using its own mapping table.
      # No LDAP-specific attribute names appear here — the adapter owns that mapping.
      correlation_key: "primary_email"

      # Operational settings
      timeout_ms: 2000                   # LDAP search timeout
      on_failure: "continue"             # "continue" = graceful degradation; "fail" = reject event
      cache_ttl_seconds: 60              # Redis cache TTL for LDAP lookup results

      # Which normalized attributes to fetch from LDAP.
      # Values are unified schema field names (NOT LDAP attribute names).
      # The LDAP adapter reverse-maps these to LDAP attributes via its mapping table.
      # If omitted, all attributes the adapter knows how to map are fetched.
      # enrich_attributes:
      #   - display_name
      #   - primary_email
      #   - department
      #   - employee_type
      #   - groups
```

### 5.2 Configuration Semantics

- **`correlation_key`**: A unified schema field name (e.g., `"primary_email"`). The normalization orchestrator extracts the value of this field from the primary adapter's output and passes it to the LDAP adapter's `enrich()` method. The adapter internally reverse-maps the field name to the corresponding LDAP attribute (e.g., `primary_email` → `mail`) using its own mapping table and constructs the LDAP search filter. No LDAP-specific attribute names ever appear in the enrichment configuration — the adapter is the single source of truth for protocol-to-schema mapping.
- **`timeout_ms`**: LDAP search timeout in milliseconds. If exceeded, enrichment is skipped per `on_failure` policy.
- **`on_failure`**: Behavior when LDAP enrichment fails (connection error, timeout, no match). `"continue"` means proceed with single-source normalization (recommended). `"fail"` means reject the event (not recommended for demo use).
- **`cache_ttl_seconds`**: Redis cache TTL for LDAP lookup results. Set to 60 seconds. Eliminates redundant LDAP queries for the same user across rapid successive events.
- **`enrich_attributes`**: Optional list of unified schema field names to fetch from LDAP. The LDAP adapter reverse-maps these to LDAP attributes (e.g., `department` → `departmentNumber`) using its existing mapping table. If omitted, all mapped attributes are fetched. The explicit list exists for cases where only a subset of LDAP data is needed.

### 5.3 Startup Validation

At service startup, the normalization service validates the enrichment configuration:

1. **`correlation_key`** must be a recognized unified schema field name that the LDAP adapter can reverse-map to an LDAP attribute. If the field name is unknown or has no LDAP mapping, startup fails with a descriptive error:
   ```
   EnrichmentConfigError: Correlation key 'favorite_color' cannot be reverse-mapped
   to an LDAP attribute. Valid unified schema fields with LDAP mappings:
   display_name (→ cn), primary_email (→ mail), department (→ departmentNumber),
   employee_type (→ employeeType), groups (→ memberOf)
   ```
2. **`on_failure`** must be `"continue"` or `"fail"`.
3. **`enrich_attributes`** (if present) must contain only unified schema field names that the LDAP adapter knows how to reverse-map. Unknown fields cause a startup failure with a descriptive error:
   ```
   EnrichmentConfigError: Unknown normalized attribute 'favorite_color' in
   enrichment.sources.ldap.enrich_attributes. Valid attributes:
   display_name, primary_email, department, employee_type, groups
   ```
4. **`cache_ttl_seconds`** must be a positive integer.

Invalid enrichment configuration prevents service startup, consistent with the A2 authority config validation behavior.

### 5.4 Composable Attribute Mapping: Future Enhancement (P2)

The current protocol adapters use hardcoded 1:1 attribute name mappings (e.g., LDAP `mail` → `primary_email`). A P2 enhancement could extend the adapter mapping tables to support composable expressions for constructing unified schema values from multiple raw attributes, e.g.:

```yaml
# Hypothetical P2 adapter mapping config (lives in adapter, NOT in enrichment config)
ldap_adapter:
  mappings:
    primary_email:
      expression: "{uid}@{LDAP_DOMAIN}"   # Composite construction
    display_name:
      expression: "{givenName} {sn}"       # Concatenation
```

This would allow, for example, LDAP directories that don't store a `mail` attribute to still produce a `primary_email` by composing `uid` and domain. The enrichment system would require no changes — it operates entirely in unified schema space and is unaware of how adapters produce their output. The composable expression capability belongs in the protocol adapters because they are the single source of truth for protocol↔schema translation.

---

## 6. LDAP Connection and Caching

### 6.1 Connection Management

The normalization service maintains an LDAP connection pool to OpenLDAP:

- **Library:** `python-ldap` (synchronous; wrapped in `asyncio.to_thread()` for async compatibility)
- **Pool size:** 2–5 connections (configurable via environment variable `LDAP_POOL_SIZE`, default 3)
- **Connection parameters:** Configured via environment variables:
  - `LDAP_URI` (default: `ldap://openldap:389`)
  - `LDAP_BIND_DN` (default: `cn=admin,dc=corp,dc=com`)
  - `LDAP_BIND_PASSWORD` (default: `admin`)
  - `LDAP_BASE_DN` (default: `ou=users,dc=corp,dc=com`)
- **Search operation:** `ldap.search_s(base_dn, SCOPE_SUBTREE, filter_str, attrlist)` where:
  - `filter_str` is constructed by the LDAP adapter: it reverse-maps the unified `correlation_key` field to the LDAP attribute (e.g., `primary_email` → `mail`), then builds the filter: `(mail=alice@corp.com)`
  - `attrlist` is derived from `enrich_attributes` reverse-mapped to LDAP attribute names by the adapter, or all mapped attributes if `enrich_attributes` is omitted

### 6.2 LDAP Input Sanitization

The correlation key lookup value (from the primary event's attributes) is used to construct an LDAP search filter. The LDAP adapter reverse-maps the unified schema field name to the corresponding LDAP attribute, then builds the filter. The lookup value **must be sanitized** to prevent LDAP injection:

```python
import ldap.filter

def build_search_filter(correlation_field: str, lookup_value: str) -> str:
    """Build a safe LDAP search filter with escaped user input.
    
    correlation_field is already reverse-mapped to the LDAP attribute name
    by the adapter before this function is called.
    """
    escaped_value = ldap.filter.escape_filter_chars(lookup_value)
    return f"({correlation_field}={escaped_value})"
```

This is critical even in a demo environment — it demonstrates security awareness and prevents unexpected behavior from malformed email addresses in simulated events.

### 6.3 Caching Strategy

LDAP lookup results are cached in Redis to avoid redundant directory queries:

- **Cache key pattern:** `ldap_enrichment:{correlation_key_value}` (e.g., `ldap_enrichment:alice@corp.com`)
- **Cache value:** JSON-serialized unified-schema attribute dictionary (the output of `enrich()`)
- **TTL:** Configurable via `cache_ttl_seconds` (default: 60 seconds)
- **Cache miss behavior:** Query LDAP, cache the result, return it
- **Cache hit behavior:** Return cached result without querying LDAP
- **Negative cache:** If LDAP returns no match, cache `null` with the same TTL to avoid repeated lookups for unknown users
- **Cache invalidation:** No explicit invalidation mechanism. The 60-second TTL ensures eventual consistency. For demo scenarios requiring immediate LDAP data changes, restart the normalization service or wait for TTL expiry.

### 6.4 Graceful Degradation

When LDAP enrichment fails, the normalization service proceeds with single-source normalization:

| Failure Mode | Behavior | Logged? |
|-------------|----------|---------|
| User not found in LDAP | Proceed with primary-source-only normalization | Yes (INFO level) |
| LDAP connection timeout | Proceed with primary-source-only normalization | Yes (WARNING level) |
| LDAP connection refused | Proceed with primary-source-only normalization | Yes (ERROR level, first occurrence only to avoid log spam) |
| LDAP search error | Proceed with primary-source-only normalization | Yes (ERROR level) |
| Invalid correlation key value (empty/null) | Skip enrichment entirely | Yes (WARNING level) |

In all failure cases, the `resolution_details` in the normalized output indicates single-source resolution. The event is not rejected or delayed.

---

## 7. Normalization Orchestration: Updated Pipeline Flow

### 7.1 Complete Flow

```
Event arrives on Redis Stream `login_events`
  │
  ├── 1. Identify event protocol from event metadata
  │
  ├── 2. Select primary adapter (OIDC / SAML / LDAP)
  │      └── Call adapter.extract(raw_attributes) → primary_attributes: dict
  │
  ├── 3. Should enrich from LDAP?
  │      └── Protocol is "oidc" or "saml" AND enrichment.sources.ldap.enabled?
  │           │
  │           ├── YES:
  │           │    ├── Extract lookup value: primary_attributes[correlation_key]
  │           │    ├── Check Redis cache: ldap_enrichment:{lookup_value}
  │           │    │    ├── Cache HIT → ldap_attributes = cached value
  │           │    │    └── Cache MISS → Call ldap_adapter.enrich(correlation_key, lookup_value)
  │           │    │         ├── Match found → ldap_attributes = result; cache it
  │           │    │         └── No match / failure → ldap_attributes = None; cache null
  │           │    │
  │           │    ├── ldap_attributes is not None?
  │           │    │    ├── YES → Multi-source conflict resolution (A2 §4.2)
  │           │    │    │         Input: {event_protocol: primary_attributes, ldap: ldap_attributes}
  │           │    │    └── NO → Single-source resolution (A2 §4.1)
  │           │    │
  │           │
  │           └── NO:
  │                └── Single-source resolution (A2 §4.1)
  │
  ├── 4. Calculate overall normalization_confidence (A2 §5)
  │
  ├── 5. Build NormalizedIdentity with resolution_details
  │
  ├── 6. Write to PostgreSQL events.normalized_attributes (JSONB)
  │
  └── 7. Publish to Redis Stream `normalized_events`
```

### 7.2 Enrichment Metadata in Resolution Details

When LDAP enrichment occurs, the `resolution_details` in the normalized output reflects the multi-source resolution:

```json
{
  "normalization_confidence": 0.87,
  "enrichment_applied": true,
  "enrichment_source": "ldap",
  "enrichment_cache_hit": false,
  "resolution_details": {
    "department": {
      "resolved_value": "Engineering",
      "confidence": 0.72,
      "resolution": "priority",
      "winner_source": "ldap",
      "conflicting_values": {"oidc": "Product"},
      "penalty_applied": true
    }
  }
}
```

When enrichment is skipped or fails:

```json
{
  "normalization_confidence": 0.80,
  "enrichment_applied": false,
  "enrichment_skip_reason": "no_ldap_match",
  "resolution_details": {
    "department": {
      "resolved_value": "Product",
      "confidence": 0.80,
      "resolution": "single_source",
      "sources": ["oidc"]
    }
  }
}
```

The `enrichment_applied`, `enrichment_source`, `enrichment_cache_hit`, and `enrichment_skip_reason` fields are added to the normalized output to support the Normalization dashboard tab's enrichment visualization.

---

## 8. Impact on Existing Design

### 8.1 A2 Conflict Resolution Algorithm

The A2 spec's conflict resolution algorithm (§4.2) already handles multi-source input correctly. The `resolve_attribute()` function accepts a `source_values` dict keyed by protocol. With LDAP enrichment, the input becomes:

```python
# OIDC event enriched with LDAP data
source_values = {
    "oidc": "Product",       # From OIDC adapter extract()
    "ldap": "Engineering",   # From LDAP adapter enrich()
}
```

No changes to the A2 algorithm are required. The enrichment step is a data-gathering concern upstream of conflict resolution.

### 8.2 A2 §4.2 Multi-Source Trigger Clarification

A2 §4.2 lists three ways multi-source conflicts occur. The second item ("The service queries a secondary source to enrich the primary event's data") is now explicitly specified by this document. The A2 spec's description of this trigger is accurate but under-specified; this spec provides the missing operational detail.

### 8.3 Spec 0: No Changes Required

The OpenLDAP container configuration in Spec 0 is already correct. The five seed users (alice, bob, charlie, diana, eve) deliberately overlap with Keycloak users, which was designed for cross-protocol identity correlation. The LDAP environment variables in `.env.example` already exist. The normalization service's LDAP client configuration uses the same connection parameters.

### 8.4 Spec 2: Scope Expansion

Spec 2's scope (defined in the System Decomposition Guide) must be updated to explicitly include the LDAP enrichment step, the LDAP connection pool, the Redis cache, and the enrichment configuration schema. See the A7 Change Manifest for the specific text changes.

### 8.5 A1 Persona Simulator: No Changes Required

The simulator generates events with `raw_attributes` appropriate to each protocol. The enrichment step is entirely within the normalization service — the simulator neither knows nor cares about it. Simulated OIDC and SAML events will be enriched from LDAP identically to live events.

---

## 9. What This Spec Does NOT Cover

- **Multiple enrichment sources.** The configuration schema supports multiple sources under `enrichment.sources`, but only the `ldap` provider is implemented. Additional providers (HR API, SCIM, etc.) are a future enhancement.
- **Bidirectional enrichment.** LDAP enriches OIDC/SAML events; there is no reverse direction.
- **User identity graph.** Enrichment is per-event, not cumulative. Building a persistent user profile from multiple events across time is a P2 feature.
- **Composite correlation key expressions.** The P2 enhancement described in §5.4 for constructing lookup values from multiple fields or expressions.
- **LDAP write-back.** The normalization service reads from LDAP. It never writes to LDAP.
- **Active Directory schema support.** The LDAP adapter handles AD vs OpenLDAP attribute name variations (defined in SYSTEM_ARCHITECTURE.md §3), but enrichment in the demo environment targets OpenLDAP only. AD enrichment would work identically with different attribute mappings.

---

*End of A7 Cross-Protocol Enrichment Specification.*
