# A6 Document Change Manifest
## Explicitly Document the SAML-Is-Synthetic Decision

**Purpose:** Preempt reviewer "gotcha" by documenting that SAML events are simulator-generated as a deliberate scope decision, not an oversight.

**Scope:** This is a scope clarification, not an architectural decision between alternatives. It does not warrant a standalone ADR.

---

## 1. SYSTEM_ARCHITECTURE.md (repo document)

### 1a. Section 3 — Identity Normalization Service, SAML Adapter bullet

**Location:** Line 98

**Current text:**
```
  - **SAML Adapter:** Parses SAML assertions, extracts attributes (displayName, email, dept)
```

**Replace with:**
```
  - **SAML Adapter:** Maps SAML-convention attribute names to the unified schema (displayName, email, dept)

    > **Scope Note — SAML in the Demo Environment:**
    > There is no live SAML Identity Provider in the Docker Compose stack. SAML events are simulator-generated: the Persona Simulator constructs events with `protocol: "saml"` and SAML-convention attribute names (e.g., `displayName`, `dept`) in `raw_attributes`. The SAML Adapter maps these to the unified schema through the same normalization pipeline used for OIDC and LDAP. In a production deployment, the adapter would additionally parse raw SAML assertion XML to extract these attributes before normalization — Keycloak (already present for OIDC) could serve as the SAML IdP, or any standards-compliant SAML 2.0 provider would work. This is a deliberate scope decision: the architectural value is in the multi-protocol normalization layer, not in XML parsing or running three separate IdP containers.

```

**Rationale:** The previous description ("Parses SAML assertions, extracts attributes") overstates what the adapter actually does in the demo. Since SAML events arrive from the simulator as pre-extracted key-value pairs in `raw_attributes`, there are no XML assertions to parse. The adapter maps attribute names to the unified schema. The corrected description is honest about this while the scope note explains why it's a deliberate and defensible design choice. A reviewer reading the architecture document will encounter this note exactly when they would start wondering "where's the SAML IdP?"

### 1b. Section 3 — Identity Normalization Service, SAML Adapter bullet (secondary fix)

**Note:** The change in §1a also corrects the adapter's one-line description from "Parses SAML assertions, extracts attributes" to "Maps SAML-convention attribute names to the unified schema." This aligns the description with the actual implementation behavior and avoids the documentation gap that previously implied real XML assertion parsing.

---

## 2. NAAS_v2.0_Vision_Document.md (meta-document, NOT in repo)

### 2a. Multi-Protocol Identity Support section

**Location:** Line 289

**Current text:**
```
- ✅ **SAML 2.0**: Simulated (adapter architecture production-ready)
```

**Replace with:**
```
- ✅ **SAML 2.0**: Simulator-generated events with SAML-convention attributes, processed by production-ready adapter (no live SAML IdP required — see SYSTEM_ARCHITECTURE.md §3)
```

**Rationale:** Aligns the meta-document's summary with the detailed note now present in SYSTEM_ARCHITECTURE.md and avoids implying that the adapter does XML parsing.

---

## Summary of Changes

| Document | In Repo? | Section Changed | Nature of Change |
|----------|----------|-----------------|------------------|
| SYSTEM_ARCHITECTURE.md | Yes | §3, SAML Adapter bullet | Correct description from "parses assertions" to "maps attribute names"; add scope note explaining synthetic SAML strategy |
| NAAS_v2.0_Vision_Document.md | No | Multi-Protocol Identity Support | Expand one-liner with accurate description referencing SYSTEM_ARCHITECTURE.md |

---

## Related Finding: Multi-Protocol Enrichment Design Gap

During the development of this change manifest, a broader documentation ambiguity was identified regarding the role of all three protocol adapters and the purpose of the live OpenLDAP container. Specifically:

- The SYSTEM_ARCHITECTURE.md and Spec 2 scope describe the LDAP adapter as "Queries OpenLDAP for user attributes," but it is unclear whether this query occurs only for `protocol: "ldap"` events (which are all simulated and already carry attributes) or also as a cross-protocol enrichment step for OIDC events.
- The A2 Conflict Resolution Spec §4.2 implies cross-protocol enrichment ("OIDC event triggers an LDAP lookup"), but this is never specified as an explicit pipeline step.
- If no cross-protocol enrichment occurs, the OpenLDAP container serves no pipeline purpose.

**This gap is out of scope for A6** and should be addressed in a dedicated follow-up conversation (proposed designation: A7 — Multi-Protocol Adapter Roles and Cross-Protocol Enrichment).

---

*End of A6 Change Manifest.*
