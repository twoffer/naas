# A7 Document Change Manifest
## Cross-Protocol LDAP Enrichment — Document Updates

**Purpose:** Specify the exact text changes required in existing NAAS project documents to integrate the cross-protocol LDAP enrichment design defined in the A7 spec.

**Important:** Per project convention, the A7 spec itself is a supplemental design document and will NOT be added to the NAAS project repo. All necessary information must be captured in the repo-resident documents (SYSTEM_ARCHITECTURE.md, CLAUDE.md, functional specs) without cross-references to A1–A7 documents.

---

## 1. SYSTEM_ARCHITECTURE.md (repo document)

### 1a. Section 3 — Identity Normalization Service: Replace LDAP Adapter bullet

**Location:** Line 97

**Current text:**
```
  - **LDAP Adapter:** Queries OpenLDAP for user attributes (cn, mail, departmentNumber, employeeType). Handles Active Directory vs OpenLDAP schema variations.
```

**Replace with:**
```
  - **LDAP Adapter:** Dual-role adapter. (1) **Extract:** Maps LDAP-convention attribute names from `raw_attributes` to the unified schema — used as the primary adapter for `protocol: "ldap"` events. (2) **Enrich:** Queries the live OpenLDAP server to fetch directory attributes for cross-protocol enrichment — used for OIDC and SAML events to merge directory data with token/assertion claims. The correlation lookup uses a configurable unified schema field (default: `primary_email`); the adapter internally reverse-maps this to the corresponding LDAP attribute (`mail`). Handles Active Directory vs OpenLDAP schema variations. Enrichment results cached in Redis (60s TTL). Graceful degradation: if LDAP lookup fails or no match is found, normalization proceeds with single-source data only.
```

**Rationale:** The current description says "Queries OpenLDAP for user attributes" without specifying when or for which events. The replacement makes both roles explicit: passive extraction for LDAP events, active enrichment queries for OIDC/SAML events.

### 1b. Section 3 — Identity Normalization Service: Add cross-protocol enrichment bullet after conflict resolution

**Location:** After line 110 (after the "Conflict resolution" bullet)

**Add:**
```
- **Cross-protocol enrichment:** For OIDC and SAML events, the service queries OpenLDAP to find the same user (by configurable unified schema field, default: `primary_email` — the adapter internally reverse-maps this to the corresponding LDAP attribute). If found, both the primary protocol's attributes and the LDAP directory attributes are fed into the conflict resolution algorithm, producing a multi-source normalized identity with per-attribute confidence scores. Enrichment is source-agnostic (applies equally to live and simulated events). LDAP events skip enrichment (directory data is already in the payload). Configuration lives in `config/normalization_authority.yaml` under `enrichment.sources.ldap`.
```

**Rationale:** Cross-protocol enrichment is a new pipeline step that must be documented at the architecture level. This bullet sits naturally between the adapter descriptions and the attribute mapping table.

### 1c. Section 3 — Identity Normalization Service: Add LDAP enrichment to Redis Usage table

**Location:** Redis Usage table (approximately line 200+)

**Add this row:**
```markdown
| LDAP enrichment cache | String (JSON) | `ldap_enrichment:{email}` | 60s |
```

**Rationale:** The LDAP enrichment cache is a new Redis key pattern that should be documented alongside existing cache entries.

### 1d. Section 3 — Identity Normalization Service: Add LDAP connection to Communication Patterns table

**Location:** Communication Patterns table

**Add this row:**
```markdown
| LDAP Enrichment | Identity Normalization → OpenLDAP | LDAP (tcp/389, internal Docker network) |
```

**Rationale:** This is a new inter-component communication path that didn't previously exist.

---

## 2. CLAUDE.md (repo document)

### 2a. Update Event Pipeline diagram annotation

**Location:** Line 72 (the pipeline diagram)

**Current text:**
```
Ingestion → [login_events] → Normalization → [normalized_events] → Enrichment → [enriched_events] → Risk Evaluator
```

**Replace with:**
```
Ingestion → [login_events] → Normalization (+ LDAP enrichment for OIDC/SAML) → [normalized_events] → Enrichment → [enriched_events] → Risk Evaluator
```

**Rationale:** The pipeline diagram should indicate that normalization includes a cross-protocol enrichment step, distinguishing it from the downstream Signal Enrichment Service.

### 2b. Add normalization enrichment to Key Conventions section

**Location:** After line 99 (after the "Metadata on every event" bullet)

**Add:**
```
- **Cross-protocol enrichment:** Identity Normalization queries OpenLDAP for OIDC/SAML events to merge directory attributes with token claims. Configurable unified schema correlation field (default: `primary_email`; adapter reverse-maps to LDAP attribute internally). Cached in Redis (60s TTL). Graceful degradation on failure. LDAP events skip enrichment. Config in `config/normalization_authority.yaml` under `enrichment.sources.ldap`.
```

**Rationale:** CLAUDE.md is the agent's primary reference. This convention ensures agents building on or modifying the normalization service understand the enrichment step without needing to read the full SYSTEM_ARCHITECTURE.md.

---

## 3. NAAS_System_Decomposition_Guide.md (repo document)

### 3a. Update Spec 2 scope

**Location:** Lines 62–69 (Spec 2 scope)

**Current text:**
```
**Scope:**
- Redis Stream consumer (reads `login_events`, writes `normalized_events`)
- OIDC adapter (extract JWT claims)
- LDAP adapter (query OpenLDAP, handle schema variations: AD vs OpenLDAP)
- SAML adapter (parse assertions, extract attributes)
- Unified schema definition and attribute mapping engine
- Conflict resolution logic (multi-source attributes)
- Update PostgreSQL `events.normalized_attributes`
```

**Replace with:**
```
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
```

**Rationale:** Spec 2's scope must explicitly include the enrichment step, LDAP connection pool, and Redis cache — these are significant implementation work items that the agent needs to plan for.

### 3b. Update Spec 2 validation criteria

**Location:** Line 73 (Spec 2 validation)

**Current text:**
```
**Validation:** Ingest events with different protocols → verify `normalized_attributes` JSONB in PostgreSQL contains unified schema output. LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name`.
```

**Replace with:**
```
**Validation:** Ingest events with different protocols → verify `normalized_attributes` JSONB in PostgreSQL contains unified schema output. LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name`. For OIDC events where the user exists in OpenLDAP: verify `enrichment_applied: true` in normalized output and multi-source `resolution_details` showing both `oidc` and `ldap` sources. For OIDC events where the user does NOT exist in OpenLDAP: verify `enrichment_applied: false` and single-source resolution.
```

**Rationale:** Validation criteria must cover the enrichment path (match found, no match found) to ensure implementation is verifiable.

---

## 4. NAAS_v2.0_Vision_Document.md (meta-document, NOT in repo)

### 4a. Update Multi-Protocol Identity Support section

**Location:** Key Features list under Multi-Protocol Identity Support (approximately line 289+)

**Current text:**
```
**Key Features:**
- Protocol-specific adapters handle extraction
- Attribute schema mapping (handle variations)
- Conflict resolution (multi-source attributes)
- Provenance tracking (which system provided what)
```

**Replace with:**
```
**Key Features:**
- Protocol-specific adapters handle extraction
- Attribute schema mapping (handle variations)
- Cross-protocol LDAP enrichment (OIDC/SAML events enriched with directory data)
- Conflict resolution (multi-source attributes with per-attribute confidence scoring)
- Provenance tracking (which system provided what)
```

**Rationale:** Cross-protocol enrichment is now a key feature of the normalization layer and belongs in the feature summary.

### 4b. Update demo script Act 2

**Location:** Act 2 in the Design Narrative section

**Current text:**
```
**Act 2: The Normalization** (60 seconds)
> "NAAS acts as a bridge. Watch: here's a login via Keycloak OIDC... and here's one from legacy LDAP. Different protocols, different attribute schemas. But NAAS normalizes them into the same unified identity representation. `cn` from LDAP becomes `display_name`. `mail` becomes `primary_email`. Same schema, regardless of source."
```

**Replace with:**
```
**Act 2: The Normalization** (60 seconds)
> "NAAS acts as a bridge. Watch: here's a login via Keycloak OIDC. NAAS doesn't just normalize the OIDC token — it cross-references the user against the LDAP directory. OIDC says department is 'Product,' but LDAP — synced from HR — says 'Engineering.' NAAS resolves the conflict using configured authority weights and produces a confidence score. Same unified schema, regardless of source, with full provenance tracking."
```

**Rationale:** The updated demo script highlights the enrichment and conflict resolution features, which are more compelling than simple attribute mapping.

---

## 5. Spec 0 (`.env.example`) — No Changes Required

The existing `.env.example` already defines the LDAP connection variables that the normalization service needs:

```env
LDAP_HOST=openldap
LDAP_PORT=389
LDAP_BASE_DN=dc=corp,dc=com
LDAP_ADMIN_DN=cn=admin,dc=corp,dc=com
LDAP_ADMIN_PASSWORD=admin
```

The normalization service will use these same variables for its LDAP client connection. An additional optional variable should be added:

### 5a. Add LDAP pool size to `.env.example`

**Location:** After `LDAP_DOMAIN=corp.com` in the OpenLDAP section

**Add:**
```env
LDAP_POOL_SIZE=3                               # LDAP connection pool size for enrichment (normalization service)
```

**Rationale:** Pool size is the only new LDAP-related environment variable. All other connection parameters already exist.

---

## 6. NAAS_v2.0_Implementation_Guide_UPDATED.md (meta-document, NOT in repo)

### 6a. Update demo script Act 2

**Location:** The demo script in the Portfolio Presentation section, Act 2

**Current text:**
```
**Act 2: Multi-Protocol Normalization (90 seconds)**
> [Open dashboard, Identity Sources tab]  
> "Here are my three identity sources: Keycloak for OIDC, OpenLDAP for legacy directory, and SAML.  
> [Click login]  
> Watch: I'm authenticating via Keycloak OIDC. See the Protocol Flow Visualization? OIDC path lights up.  
> [Open simulator, generate LDAP events]  
> Now let me generate some legacy LDAP activity. Watch the orange LDAP path light up.  
> [Open Normalization tab]  
> Here's the key: whether OIDC, SAML, or LDAP, all attributes normalize to the same schema. `cn` from LDAP becomes `display_name`. `mail` becomes `primary_email`. One schema, regardless of source."
```

**Replace with:**
```
**Act 2: Multi-Protocol Normalization (90 seconds)**
> [Open dashboard, Identity Sources tab]  
> "Here are my three identity sources: Keycloak for OIDC, OpenLDAP for legacy directory, and SAML.  
> [Click login]  
> Watch: I'm authenticating via Keycloak OIDC. See the Protocol Flow Visualization? OIDC path lights up — and notice the secondary LDAP lookup. NAAS cross-references my OIDC token against the LDAP directory automatically.  
> [Open Normalization tab]  
> Here's the key: OIDC says my department is 'Product,' but LDAP — synced from HR — says 'Engineering.' See the conflict resolution? LDAP wins because it has higher authority weight for department. Confidence score: 0.72 with a disagreement penalty. That confidence feeds directly into risk assessment.  
> [Open simulator, generate LDAP events]  
> Now let me generate some legacy LDAP activity. These skip enrichment — the directory data is already in the login payload. Same unified output, different path."
```

**Rationale:** The updated demo highlights the enrichment and conflict resolution features, which are the primary value proposition of the A7 design.

---

## Summary of Changes

| Document | In Repo? | Section Changed | Nature of Change |
|----------|----------|-----------------|------------------|
| SYSTEM_ARCHITECTURE.md | Yes | §3, LDAP Adapter bullet | Rewrite to describe dual role (extract + enrich) |
| SYSTEM_ARCHITECTURE.md | Yes | §3, new enrichment bullet | Add cross-protocol enrichment pipeline step |
| SYSTEM_ARCHITECTURE.md | Yes | Redis Usage table | Add LDAP enrichment cache entry |
| SYSTEM_ARCHITECTURE.md | Yes | Communication Patterns table | Add LDAP enrichment communication path |
| CLAUDE.md | Yes | Pipeline diagram | Annotate normalization with enrichment note |
| CLAUDE.md | Yes | Key Conventions | Add cross-protocol enrichment convention |
| NAAS_System_Decomposition_Guide.md | Yes | Spec 2 scope | Add enrichment, LDAP pool, cache to scope |
| NAAS_System_Decomposition_Guide.md | Yes | Spec 2 validation | Add enrichment-specific validation criteria |
| NAAS_v2.0_Vision_Document.md | No | Key Features list | Add cross-protocol enrichment feature |
| NAAS_v2.0_Vision_Document.md | No | Demo script Act 2 | Rewrite to highlight enrichment + conflict |
| Spec 0 `.env.example` | Yes | OpenLDAP section | Add LDAP_POOL_SIZE variable |
| Implementation Guide | No | Demo script Act 2 | Rewrite to highlight enrichment + conflict |

---

*End of A7 Change Manifest.*
