# A9 Document Change Manifest
## Normalized Attributes Pydantic Model & Configuration Rename — Document Updates

**Purpose:** Apply the design decisions defined in the A9 Specification to repo-resident and audit/meta documents. This manifest covers three coordinated changes: (1) replacement of the `NormalizedIdentity` Pydantic model with a fully typed `NormalizedAttributes` model (including discriminated-union sub-models for resolution-detail and enrichment-metadata variants); (2) rename of `config/normalization_authority.yaml` to `config/normalization.yaml`; (3) restructuring of the four flat `enrichment_*` fields into a single nested `enrichment` discriminated-union object.

**Important:** Per project convention, the A9 specification and this manifest are supplemental design documents and will NOT be added to the NAAS project repo's standard branches. All necessary information is captured in the repo-resident documents without cross-references to A1–A9 documents or other meta documents.

---

## 1. CLAUDE.md (repo document)

### 1a. Update the Project Structure tree — rename configuration file

**Location:** § Project Structure, the `config/` block

**Current text:**
```
├── config/
│   └── normalization_authority.yaml  # Normalization authority weights, attribute importance, enrichment source config
```

**Replace with:**
```
├── config/
│   └── normalization.yaml            # Normalization service config: per-attribute authority weights, attribute importance, cross-protocol enrichment source config
```

**Rationale:** The file name is updated to reflect that it now holds both authority configuration (A2-defined attribute priorities and weights) and enrichment configuration (A7-defined cross-protocol LDAP enrichment settings). The inline comment is expanded to make both purposes explicit so an agent reading the project tree alone understands what lives in the file.

### 1b. Update the Cross-Protocol Enrichment bullet in Key Conventions

**Location:** § Key Conventions, the "Cross-protocol enrichment" bullet

**Current text:**
```
- **Cross-protocol enrichment:** Identity Normalization queries OpenLDAP for OIDC/SAML events to merge directory attributes with token claims. Configurable unified schema correlation field (default: `primary_email`; adapter reverse-maps to LDAP attribute internally). Cached in Redis (60s TTL). Graceful degradation on failure. LDAP events skip enrichment. Config in `config/normalization_authority.yaml` under `enrichment.sources.ldap`.
```

**Replace with:**
```
- **Cross-protocol enrichment:** Identity Normalization queries OpenLDAP for OIDC/SAML events to merge directory attributes with token claims. Configurable unified schema correlation field (default: `primary_email`; adapter reverse-maps to LDAP attribute internally). Cached in Redis (60s TTL). Graceful degradation on failure. LDAP events skip enrichment. Config in `config/normalization.yaml` under `enrichment.sources.ldap`.
```

**Rationale:** Mechanical rename to match the new file name.

---

## 2. docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md (repo document)

### 2a. Update the Project Tree — rename configuration file

**Location:** § 1. Scope Boundary, "Files and Directories Created" — the project tree, `config/` block

**Current text:**
```
├── config/
│   └── normalization_authority.yaml  # Normalization authority weights, attribute importance, enrichment source config (file content created by Spec 2)
```

**Replace with:**
```
├── config/
│   └── normalization.yaml            # Normalization service config: per-attribute authority weights, attribute importance, cross-protocol enrichment source config (file content created by Spec 2)
```

**Rationale:** Mechanical rename matching CLAUDE.md, with the same expanded inline comment for clarity.

### 2b. Update "Files NOT Created by This Spec" — rename configuration file

**Location:** § 1. Scope Boundary, "Files NOT Created by This Spec" list

**Current text:**
```
- No `config/normalization_authority.yaml` content (the directory is scaffolded; file content is defined and created by Spec 2)
```

**Replace with:**
```
- No `config/normalization.yaml` content (the directory is scaffolded; file content is defined and created by Spec 2)
```

**Rationale:** Mechanical rename consistent with the project tree update above.

### 2c. Replace `NormalizedIdentity` with `NormalizedAttributes` and sub-models in §3.4

**Location:** § 3. Output Contracts, § 3.4 Base Pydantic Models — within `shared/naas_shared/models.py`. The `NormalizedIdentity` class block (currently the model definition starting with `class NormalizedIdentity(BaseModel):`).

**Update the `from typing import` line at the top of the `models.py` code block** to add `Annotated` and `Union`:

**Current text:**
```python
from typing import Literal, Dict, Any, Optional
```

**Replace with:**
```python
from typing import Literal, Dict, Any, Optional, Annotated, Union
```

**Then replace the `NormalizedIdentity` class block:**

**Current text:**
```python
class NormalizedIdentity(BaseModel):
    """Unified identity schema output from normalization."""
    display_name: Optional[str] = None
    primary_email: Optional[str] = None
    department: Optional[str] = None
    employee_type: Optional[Literal["FTE", "contractor", "vendor"]] = None
    groups: list[str] = Field(default_factory=list)
    source_protocol: Literal["oidc", "saml", "ldap"]
    normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    raw_source_attributes: Dict[str, Any] = Field(default_factory=dict)
```

**Replace with:**
```python
# ============================================================
# Type aliases
# ============================================================

SourceProtocol = Literal["oidc", "saml", "ldap"]


# ============================================================
# Resolution Details — discriminated union by `resolution`
# ============================================================

class ResolutionDetailBase(BaseModel):
    """Common fields for all resolution-detail variants.

    Subclasses declare a `resolution` field as a Literal discriminator
    and a `resolved_value` field typed appropriately for the attribute
    kind they describe (scalar vs. list).
    """
    confidence: float = Field(ge=0.0, le=1.0)


class UnanimousResolution(ResolutionDetailBase):
    """All sources agreed on this attribute's value."""
    resolution: Literal["unanimous"]
    resolved_value: Optional[str] = None
    sources: list[SourceProtocol]


class PriorityResolution(ResolutionDetailBase):
    """Sources disagreed; highest-priority source's value won."""
    resolution: Literal["priority"]
    resolved_value: Optional[str] = None
    winner_source: SourceProtocol
    conflicting_values: Dict[SourceProtocol, Any]
    penalty_applied: bool


class SingleSourceResolution(ResolutionDetailBase):
    """Only one source provided this attribute (no conflict possible)."""
    resolution: Literal["single_source"]
    resolved_value: Optional[str] = None
    sources: list[SourceProtocol]


class ListMergeResolution(ResolutionDetailBase):
    """List-typed attribute (e.g., groups) merged across sources by strategy."""
    resolution: Literal["list_merge"]
    resolved_value: list[str] = Field(default_factory=list)
    strategy: Literal["union", "intersection", "priority"]
    total_unique_groups: int = Field(ge=0)


ResolutionDetail = Annotated[
    Union[
        UnanimousResolution,
        PriorityResolution,
        SingleSourceResolution,
        ListMergeResolution,
    ],
    Field(discriminator="resolution"),
]


# ============================================================
# Enrichment Metadata — discriminated union by `applied`
# ============================================================

EnrichmentSkipReason = Literal[
    "ldap_disabled",            # enrichment.sources.ldap.enabled = false
    "ldap_event",               # event protocol is "ldap" (skip per design)
    "no_ldap_match",            # LDAP query returned no entries
    "ldap_timeout",             # LDAP search exceeded timeout_ms
    "ldap_connection_error",    # connect refused / network error
    "ldap_search_error",        # other LDAP-side error
    "invalid_correlation_key",  # primary attrs missing the correlation_key value
]


class EnrichmentApplied(BaseModel):
    """LDAP enrichment was attempted and a directory match was returned."""
    applied: Literal[True]
    source: Literal["ldap"]
    cache_hit: bool


class EnrichmentSkipped(BaseModel):
    """LDAP enrichment was not applied (skipped or failed)."""
    applied: Literal[False]
    skip_reason: EnrichmentSkipReason


EnrichmentMetadata = Annotated[
    Union[EnrichmentApplied, EnrichmentSkipped],
    Field(discriminator="applied"),
]


# ============================================================
# Top-level normalized attributes payload
# ============================================================

class NormalizedAttributes(BaseModel):
    """Full payload stored in events.normalized_attributes JSONB.

    Produced by the Identity Normalization Service.
    Consumed by the Risk Evaluator and the Dashboard.

    Readers MUST call NormalizedAttributes.model_validate(jsonb_dict)
    and handle pydantic.ValidationError gracefully: rows written before
    a model change may not conform to the current schema. Risk Evaluator:
    log warning, treat as normalization_risk=1.0, continue. Dashboard:
    surface as a "schema mismatch" placeholder in the Normalization tab.
    """
    # Unified identity attributes
    display_name: Optional[str] = None
    primary_email: Optional[str] = None
    department: Optional[str] = None
    employee_type: Optional[Literal["FTE", "contractor", "vendor"]] = None
    groups: list[str] = Field(default_factory=list)

    # Provenance
    source_protocol: SourceProtocol
    normalization_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    resolution_details: Dict[str, ResolutionDetail] = Field(default_factory=dict)

    # Cross-protocol enrichment metadata (always populated; even LDAP events
    # get EnrichmentSkipped(applied=False, skip_reason="ldap_event"))
    enrichment: EnrichmentMetadata
```

**Rationale:** This is the substantive change in the manifest. The legacy `NormalizedIdentity` model is replaced by a fully typed `NormalizedAttributes` model that exactly matches the on-disk JSONB shape produced by the normalization service. Sub-models capture the polymorphic structure of resolution-detail entries (four variants discriminated by `resolution`) and enrichment-metadata entries (two variants discriminated by `applied`). The shared `ResolutionDetailBase` class deduplicates the `confidence` field across all four resolution variants. The `raw_source_attributes` field is dropped because the data it carried is already stored in the adjacent `events.raw_attributes` column (eliminating a duplicate-source-of-truth pattern). The model rename from `NormalizedIdentity` to `NormalizedAttributes` aligns the type name with the database column it serializes to.

---

## 3. docs/architecture/SYSTEM_ARCHITECTURE.md (repo document)

### 3a. Update the Cross-Protocol Enrichment bullet in §3 — rename configuration file

**Location:** § 3. Identity Normalization Service, the cross-protocol enrichment bullet (added by A7)

**Current text:**
```
- **Cross-protocol enrichment:** For OIDC and SAML events, the service queries OpenLDAP to find the same user (by configurable unified schema field, default: `primary_email` — the adapter internally reverse-maps this to the corresponding LDAP attribute). If found, both the primary protocol's attributes and the LDAP directory attributes are fed into the conflict resolution algorithm, producing a multi-source normalized identity with per-attribute confidence scores. Enrichment is source-agnostic (applies equally to live and simulated events). LDAP events skip enrichment (directory data is already in the payload). Configuration lives in `config/normalization_authority.yaml` under `enrichment.sources.ldap`.
```

**Replace with:**
```
- **Cross-protocol enrichment:** For OIDC and SAML events, the service queries OpenLDAP to find the same user (by configurable unified schema field, default: `primary_email` — the adapter internally reverse-maps this to the corresponding LDAP attribute). If found, both the primary protocol's attributes and the LDAP directory attributes are fed into the conflict resolution algorithm, producing a multi-source normalized identity with per-attribute confidence scores. Enrichment is source-agnostic (applies equally to live and simulated events). LDAP events skip enrichment (directory data is already in the payload). Configuration lives in `config/normalization.yaml` under `enrichment.sources.ldap`.
```

**Rationale:** Mechanical rename consistent with the file rename in CLAUDE.md and SPEC_0.

---

## 4. docs/meta/NAAS_System_Decomposition_Guide.md (meta-document, NOT in repo)

### 4a. Update Spec 2 scope — rename configuration file

**Location:** Spec 2 scope, the cross-protocol LDAP enrichment bullet

**Current text:**
```
- Cross-protocol LDAP enrichment: unified schema correlation field lookup (configurable, default: `primary_email`; adapter reverse-maps to LDAP attribute internally), Redis cache (60s TTL), graceful degradation on failure, enrichment config in `normalization_authority.yaml`
```

**Replace with:**
```
- Cross-protocol LDAP enrichment: unified schema correlation field lookup (configurable, default: `primary_email`; adapter reverse-maps to LDAP attribute internally), Redis cache (60s TTL), graceful degradation on failure, enrichment config in `normalization.yaml`
```

**Rationale:** Mechanical rename for consistency with the repo-resident document updates.

### 4b. Update Spec 2 validation criteria — switch enrichment field path to nested form

**Location:** Spec 2 validation criteria

**Current text:**
```
**Validation:** Ingest events with different protocols → verify `normalized_attributes` JSONB in PostgreSQL contains unified schema output. LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name`. For OIDC events where the user exists in OpenLDAP: verify `enrichment_applied: true` in normalized output and multi-source `resolution_details` showing both `oidc` and `ldap` sources. For OIDC events where the user does NOT exist in OpenLDAP: verify `enrichment_applied: false` and single-source resolution.
```

**Replace with:**
```
**Validation:** Ingest events with different protocols → verify `normalized_attributes` JSONB in PostgreSQL contains unified schema output. LDAP `cn` → `display_name`, SAML `displayName` → `display_name`, OIDC `name` → `display_name`. For OIDC events where the user exists in OpenLDAP: verify `enrichment.applied: true` in normalized output and multi-source `resolution_details` showing both `oidc` and `ldap` sources. For OIDC events where the user does NOT exist in OpenLDAP: verify `enrichment.applied: false` with `enrichment.skip_reason: "no_ldap_match"` and single-source resolution.
```

**Rationale:** The validation criteria are updated to reference the new nested `enrichment` object (rather than the previous flat `enrichment_applied` field). The "no match" validation case now also references the specific `skip_reason` value, which the closed `EnrichmentSkipReason` enum makes deterministic.

---

## 5. docs/audit/A2_Normalization_Conflict_Resolution_Spec.md (audit document)

### 5a. Update §1 Overview, step 5 — rename `NormalizedIdentity` to `NormalizedAttributes`

**Location:** § 1. Overview, the numbered step list

**Current text:**
```
5. **Produces** a `NormalizedIdentity` object with the resolved values and an overall `normalization_confidence` score
```

**Replace with:**
```
5. **Produces** a `NormalizedAttributes` object with the resolved values and an overall `normalization_confidence` score
```

**Rationale:** Mechanical rename to match the new model name.

### 5b. Update §3.1 — rename configuration file in the YAML code-block comment

**Location:** § 3.1 Configuration Schema, the YAML code block

**Current text (first line of the YAML block):**
```yaml
# config/normalization_authority.yaml
```

**Replace with:**
```yaml
# config/normalization.yaml
```

**Rationale:** The header comment in the example YAML reflects the file's actual location; the rename keeps the example accurate.

### 5c. Update §5 header sentence — rename `NormalizedIdentity` to `NormalizedAttributes`

**Location:** § 5 Overall Normalization Confidence, opening sentence

**Current text:**
```
The `normalization_confidence` field on `NormalizedIdentity` is the **weighted average** of per-attribute confidences, where weights reflect attribute importance to downstream risk evaluation.
```

**Replace with:**
```
The `normalization_confidence` field on `NormalizedAttributes` is the **weighted average** of per-attribute confidences, where weights reflect attribute importance to downstream risk evaluation.
```

**Rationale:** Mechanical rename.

### 5d. Update §7 heading and opening paragraph — rename and reframe

**Location:** § 7 Normalization Output: Updated NormalizedIdentity (heading + first paragraph)

**Current text:**
```
## 7. Normalization Output: Updated NormalizedIdentity

The existing `NormalizedIdentity` Pydantic model (defined in Spec 0's `shared/naas_shared/models.py`) already has the right fields. No schema changes are needed. However, the normalization service should populate two additional pieces of data in the event record:
```

**Replace with:**
```
## 7. Normalization Output: NormalizedAttributes Model

The full normalization output is formalized as the `NormalizedAttributes` Pydantic model in `shared/naas_shared/models.py` (defined in Spec 0). The model uses discriminated unions for the polymorphic `resolution_details` and `enrichment` substructures, providing a typed contract between the normalization service (writer) and downstream consumers (the Risk Evaluator and the Spec 6 dashboard's Normalization tab). The §7.1 example below shows the JSON shape produced by serializing this model.
```

**Rationale:** The previous text contained two factual problems: it claimed the existing model "already has the right fields" (which was inaccurate — the model lacked `resolution_details` and the enrichment-provenance fields), and the heading referred to the old model name. The replacement text describes the actual current state: the JSONB shape is the serialized form of `NormalizedAttributes`, which is the canonical typed contract.

### 5e. Update §7.1 JSON example — restructure to the formalized shape

**Location:** § 7.1 What Gets Stored, the JSON example block

**Current text:**
```json
{
  "display_name": "Alice Smith",
  "primary_email": "alice@corp.com",
  "department": "Engineering",
  "employee_type": "FTE",
  "groups": ["engineering", "admin", "vpn-users"],
  "source_protocol": "oidc",
  "normalization_confidence": 0.87,
  "resolution_details": {
    "display_name": {
      "resolved_value": "Alice Smith",
      "confidence": 0.90,
      "resolution": "unanimous",
      "sources": ["oidc", "ldap"]
    },
    "primary_email": {
      "resolved_value": "alice@corp.com",
      "confidence": 0.95,
      "resolution": "unanimous",
      "sources": ["oidc", "ldap"]
    },
    "department": {
      "resolved_value": "Engineering",
      "confidence": 0.72,
      "resolution": "priority",
      "winner_source": "ldap",
      "conflicting_values": {"oidc": "Product"},
      "penalty_applied": true
    },
    "employee_type": {
      "resolved_value": "FTE",
      "confidence": 0.95,
      "resolution": "unanimous",
      "sources": ["oidc", "ldap"]
    },
    "groups": {
      "resolved_value": ["engineering", "admin", "vpn-users"],
      "confidence": 0.85,
      "strategy": "union",
      "total_unique_groups": 3
    }
  }
}
```

**Replace with:**
```json
{
  "display_name": "Alice Smith",
  "primary_email": "alice@corp.com",
  "department": "Engineering",
  "employee_type": "FTE",
  "groups": ["engineering", "admin", "vpn-users"],
  "source_protocol": "oidc",
  "normalization_confidence": 0.87,
  "enrichment": {
    "applied": true,
    "source": "ldap",
    "cache_hit": false
  },
  "resolution_details": {
    "display_name": {
      "resolution": "unanimous",
      "resolved_value": "Alice Smith",
      "confidence": 0.90,
      "sources": ["oidc", "ldap"]
    },
    "primary_email": {
      "resolution": "unanimous",
      "resolved_value": "alice@corp.com",
      "confidence": 0.95,
      "sources": ["oidc", "ldap"]
    },
    "department": {
      "resolution": "priority",
      "resolved_value": "Engineering",
      "confidence": 0.72,
      "winner_source": "ldap",
      "conflicting_values": {"oidc": "Product"},
      "penalty_applied": true
    },
    "employee_type": {
      "resolution": "unanimous",
      "resolved_value": "FTE",
      "confidence": 0.95,
      "sources": ["oidc", "ldap"]
    },
    "groups": {
      "resolution": "list_merge",
      "resolved_value": ["engineering", "admin", "vpn-users"],
      "confidence": 0.85,
      "strategy": "union",
      "total_unique_groups": 3
    }
  }
}
```

**Rationale:** The example reflects the structural changes formalized by the typed model: (a) the four flat `enrichment_*` fields previously specified by A7 are nested under a single `enrichment` object whose shape is determined by the `applied` discriminator; (b) the groups variant carries a `resolution: "list_merge"` discriminator field for uniform discrimination across all four resolution variants; (c) the discriminator field is consistently the first key in each resolution-detail entry to emphasize its role.

---

## 6. docs/audit/A3_Policy_Expression_Language_and_Scoring_Model.md (audit document)

### 6a. Update §3.1 header — rename `NormalizedIdentity` to `NormalizedAttributes`

**Location:** § 3.1 — the header line

**Current text:**
```
### 3.1 `user.*` — from NormalizedIdentity (Spec 2 output)
```

**Replace with:**
```
### 3.1 `user.*` — from NormalizedAttributes (Spec 2 output)
```

**Rationale:** Mechanical rename. The body of §3.1 already correctly states that the data is populated from `events.normalized_attributes` JSONB, which remains accurate.

---

## 7. docs/audit/A7_Cross_Protocol_Enrichment_Spec.md (audit document)

### 7a. Update §5.1 — rename configuration file in the introductory sentence and YAML code block

**Location:** § 5.1 Configuration Schema, opening sentence and YAML code block header

**Current text (sentence):**
```
LDAP enrichment is configured in the existing `normalization_authority.yaml` file (defined in A2 §3.1), extended with a new `enrichment` section:
```

**Replace with:**
```
LDAP enrichment is configured in the existing `normalization.yaml` file (defined in A2 §3.1), extended with a new `enrichment` section:
```

**Current text (YAML block first line):**
```yaml
# Appended to config/normalization_authority.yaml
```

**Replace with:**
```yaml
# Appended to config/normalization.yaml
```

**Rationale:** Mechanical rename in two places within the same section.

### 7b. Update §7.1 step 5 — rename `NormalizedIdentity` to `NormalizedAttributes`

**Location:** § 7.1 Complete Flow, the numbered pipeline step

**Current text:**
```
  ├── 5. Build NormalizedIdentity with resolution_details
```

**Replace with:**
```
  ├── 5. Build NormalizedAttributes with resolution_details and enrichment metadata
```

**Rationale:** Mechanical rename plus an accuracy improvement. Step 5 was previously silent on enrichment metadata population; the updated wording makes explicit that the `enrichment` field is also populated at this step (matching the model's requirement that `enrichment` always be present).

### 7c. Update §7.2 JSON examples — restructure flat enrichment fields to nested form

**Location:** § 7.2 Enrichment Metadata in Resolution Details, both JSON code blocks

**First example — current text:**
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

**Replace with:**
```json
{
  "normalization_confidence": 0.87,
  "enrichment": {
    "applied": true,
    "source": "ldap",
    "cache_hit": false
  },
  "resolution_details": {
    "department": {
      "resolution": "priority",
      "resolved_value": "Engineering",
      "confidence": 0.72,
      "winner_source": "ldap",
      "conflicting_values": {"oidc": "Product"},
      "penalty_applied": true
    }
  }
}
```

**Second example — current text:**
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

**Replace with:**
```json
{
  "normalization_confidence": 0.80,
  "enrichment": {
    "applied": false,
    "skip_reason": "no_ldap_match"
  },
  "resolution_details": {
    "department": {
      "resolution": "single_source",
      "resolved_value": "Product",
      "confidence": 0.80,
      "sources": ["oidc"]
    }
  }
}
```

**Rationale:** Both examples are restructured to match the formalized shape. The four flat `enrichment_*` fields collapse into a single `enrichment` object whose shape is determined by the `applied` discriminator. The `resolution` discriminator is moved to the first position of each resolution-detail entry to emphasize its role (consistent with the corresponding update to A2 §7.1).

### 7d. Update §7.2 closing description — rename and reframe enrichment fields

**Location:** § 7.2 Enrichment Metadata in Resolution Details, the closing paragraph (after the second JSON block)

**Current text:**
```
The `enrichment_applied`, `enrichment_source`, `enrichment_cache_hit`, and `enrichment_skip_reason` fields are added to the normalized output to support the Normalization dashboard tab's enrichment visualization.
```

**Replace with:**
```
The `enrichment` field (a discriminated union over `EnrichmentApplied` and `EnrichmentSkipped` variants, defined on `NormalizedAttributes` in `shared/naas_shared/models.py`) carries the enrichment-provenance information that supports the Normalization dashboard tab's enrichment visualization. The `applied: true` variant carries `source` and `cache_hit`; the `applied: false` variant carries a closed-enum `skip_reason`.
```

**Rationale:** The closing description is updated to reflect the nested structure and the typed-model contract. The `EnrichmentSkipReason` enum's closed nature is also surfaced so readers understand that the skip-reason values are not free-form strings.

---

## 8. Items Deliberately Out of Scope

The following references to `NormalizedIdentity`, `normalization_authority.yaml`, or the flat `enrichment_*` fields are NOT addressed by this manifest. Each is excluded for an explicit reason:

| Item | Reason for exclusion |
|------|----------------------|
| `docs/audit/A_Series_Reconciliation_Report.md` (multiple findings cite the old names) | Historical audit document. Updating the report's findings would corrupt the historical record of what was observed at the time of the reconciliation. The report's findings are factually correct as of their authorship; subsequent changes are tracked in the manifest series. |
| `docs/audit/A7_Document_Change_Manifest.md` (directives reference the old file name and old field names) | Historical change manifest. Manifests record the directives applied at a specific point in time; rewriting a past manifest to use the names current at the time of a later manifest erases the history of what was actually directed. |
| `docs/audit/A8_Document_Change_Manifest.md` (project-tree directive scaffolds `normalization_authority.yaml`) | Same reasoning as A7. The A8 manifest scaffolded the directory and file under the name in use at the time. The current A9 manifest's directive 2a is the correct point at which the rename takes effect in SPEC_0. |
| `AARE_v1.0_Foundation_Document.md` | Predecessor project (AARE) document that predates the NAAS-era `NormalizedIdentity` model and `normalization_authority.yaml` file. Contains no references to either name. |
| `docs/meta/NAAS_v2.0_Vision_Document.md`, `NAAS_v2.0_Tech_Stack.md`, `NAAS_v2.0_Implementation_Guide.md`, `NAAS_v2.0_Enhancement_Roadmap.md` | Verified by full-corpus search to contain no references to `NormalizedIdentity`, `normalization_authority.yaml`, or the flat `enrichment_*` field names. No changes required. |
| `.claude/` agent definitions, pipeline phase files, and contract files | Verified by full-corpus search to contain no references to any of the three rename targets. The agentic pipeline operates on file paths and JSON contracts, not on the data-model field names being changed here. |

---

## Summary of Changes

| Document | In Repo? | Section Changed | Nature of Change |
|----------|----------|-----------------|------------------|
| CLAUDE.md | Yes | Project structure tree | Rename `normalization_authority.yaml` → `normalization.yaml`; expand inline comment |
| CLAUDE.md | Yes | Key Conventions, cross-protocol enrichment bullet | Rename `normalization_authority.yaml` → `normalization.yaml` |
| SPEC_0 | Yes | § 1 Project tree, `config/` block | Rename `normalization_authority.yaml` → `normalization.yaml`; expand inline comment |
| SPEC_0 | Yes | § 1 "Files NOT Created" list | Rename `normalization_authority.yaml` → `normalization.yaml` |
| SPEC_0 | Yes | § 3.4 `models.py` typing imports | Add `Annotated` and `Union` to existing `from typing import` line |
| SPEC_0 | Yes | § 3.4 `NormalizedIdentity` class block | Replace with `NormalizedAttributes` + sub-models (`ResolutionDetailBase`, four resolution variants, `ResolutionDetail` union, `EnrichmentSkipReason` enum, two enrichment variants, `EnrichmentMetadata` union); drop `raw_source_attributes` |
| SYSTEM_ARCHITECTURE.md | Yes | § 3 cross-protocol enrichment bullet | Rename `normalization_authority.yaml` → `normalization.yaml` |
| NAAS_System_Decomposition_Guide.md | No (meta) | Spec 2 scope, enrichment bullet | Rename `normalization_authority.yaml` → `normalization.yaml` |
| NAAS_System_Decomposition_Guide.md | No (meta) | Spec 2 validation criteria | Switch `enrichment_applied` → `enrichment.applied`; reference `enrichment.skip_reason` for the no-match case |
| A2 Spec | No (audit) | § 1 Overview, step 5 | Rename `NormalizedIdentity` → `NormalizedAttributes` |
| A2 Spec | No (audit) | § 3.1 YAML block header comment | Rename file path |
| A2 Spec | No (audit) | § 5 opening sentence | Rename `NormalizedIdentity` → `NormalizedAttributes` |
| A2 Spec | No (audit) | § 7 heading + first paragraph | Rename heading; replace prose to reflect the formalized typed model |
| A2 Spec | No (audit) | § 7.1 JSON example | Restructure: nested `enrichment` object; uniform `resolution` discriminator on all four variants (including new `resolution: "list_merge"` on groups) |
| A3 Spec | No (audit) | § 3.1 header line | Rename `NormalizedIdentity` → `NormalizedAttributes` |
| A7 Spec | No (audit) | § 5.1 sentence + YAML block header comment | Rename file path in two places |
| A7 Spec | No (audit) | § 7.1 step 5 | Rename `NormalizedIdentity` → `NormalizedAttributes`; clarify that enrichment metadata is populated at this step |
| A7 Spec | No (audit) | § 7.2 JSON examples (both) | Restructure flat `enrichment_*` fields into nested `enrichment` object with discriminator |
| A7 Spec | No (audit) | § 7.2 closing description | Replace flat-field listing with description of the typed `enrichment` discriminated-union shape |

---

*End of A9 Change Manifest.*
