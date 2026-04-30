# A9 — Normalized Attributes Pydantic Model & Configuration Rename
## Specification for `shared/naas_shared/models.py` and `config/normalization.yaml`

**Purpose:** Formalize the `events.normalized_attributes` JSONB shape as a typed Pydantic model with discriminated-union sub-models for resolution-detail and enrichment-metadata variants. Rename `config/normalization_authority.yaml` to `config/normalization.yaml` to accurately reflect that the file now contains both the per-attribute authority configuration (A2) and the cross-protocol enrichment configuration (A7).

**Audience:** Claude Code agents implementing Spec 0 and Spec 2, the technical-architect agent producing the Spec 2 implementation plan, and the implementer of the Spec 6 dashboard's Normalization tab.

**Context:** This spec resolves the Tier-2 output-provenance gap identified in the A-Series Intent-vs-Application Reconciliation Report — the absence of a schema-level contract for the resolution-details and enrichment-metadata fields that A2 (§7.1) and A7 (§7.2, §8) specify as required for downstream visualization but which both leave as implicit JSONB shape. This spec also addresses an adjacent but distinct concern: the file name `normalization_authority.yaml` predates the A7 decision to colocate enrichment configuration in the same file, and "authority" no longer accurately describes the file's full contents.

---

## 1. Overview

The Identity Normalization Service writes its full output to the `events.normalized_attributes` JSONB column. Two specs contribute to that payload:

1. **A2 §7.1** specifies the unified-schema attributes, the overall `normalization_confidence`, and a per-attribute `resolution_details` object describing how each attribute was resolved (unanimous / priority / single-source / list-merge).
2. **A7 §7.2 and §8** add enrichment-provenance fields (`enrichment_applied`, `enrichment_source`, `enrichment_cache_hit`, `enrichment_skip_reason`) describing whether and how cross-protocol LDAP enrichment was applied.

Both specs leave the packaging decision implicit: the JSONB shape is documented by example, not by type. Today the only typed surface is the legacy `NormalizedIdentity` model in `shared/naas_shared/models.py`, which (a) does not include any of the provenance fields above, (b) carries a `raw_source_attributes` field that does not appear in the actual JSONB shape per A2 §7.1, and (c) is not used as a type by any consumer code defined in the architecture documents — the Risk Evaluator accesses these fields via `dict.get()` calls, not via model attribute access.

This spec replaces `NormalizedIdentity` with a fully typed `NormalizedAttributes` model whose name matches the database column and whose structure exactly matches the JSONB shape produced by A2 + A7. The model uses Pydantic discriminated unions to express the polymorphic shape of resolution-detail entries and enrichment-metadata entries, giving Spec 2 (writer), Spec 3 (Risk Evaluator), and Spec 6 (dashboard reader) a single source of truth for the contract.

---

## 2. Existing State

### 2.1 Current Pydantic Model

The current model in `shared/naas_shared/models.py`:

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

### 2.2 Gaps and Issues

1. **No `resolution_details` field.** A2 §7.1 specifies that this nested object is essential for the Normalization dashboard tab, but it has no schema-level home.
2. **No enrichment-metadata fields.** A7 §7.2 specifies four enrichment-provenance fields; none appear on the model.
3. **`raw_source_attributes` does not appear in the actual on-disk JSONB.** The A2 §7.1 example payload has no such field. The data it would carry — protocol-specific raw attributes — is already stored in the separate `events.raw_attributes` JSONB column. Carrying it on the normalized model would be a duplicate-source-of-truth pattern.
4. **Naming mismatch.** The model is named `NormalizedIdentity` but the column is named `normalized_attributes`. Renaming the model to `NormalizedAttributes` aligns the naming with the storage and with the dashboard tab name ("Normalization").
5. **Resolution variants share fields without a shared base.** All four variants (unanimous, priority, single_source, list_merge) carry a `confidence` field, but the current ad-hoc JSONB representation provides no Pydantic-level expression of this invariant.

---

## 3. Design Decisions

### 3.1 Replace `NormalizedIdentity` with `NormalizedAttributes`

The new model fully replaces the old one in `shared/naas_shared/models.py`. The naming change reflects three things: the model represents normalized attributes (not an identity record), it matches the database column it serializes to, and it eliminates the cosmetic mismatch with the A2/A7 specs which already refer to the JSONB column as `normalized_attributes`.

The `raw_source_attributes` field is dropped. The data it carried is already in `events.raw_attributes` (the column adjacent to `events.normalized_attributes`), so no information is lost.

### 3.2 Use a Discriminated Union for `resolution_details` Entries

`resolution_details` is a `dict[str, ResolutionDetail]` keyed by unified-schema attribute name. Each value is a discriminated union over four variants:

- `UnanimousResolution` — all sources agreed on the value
- `PriorityResolution` — sources disagreed; highest-priority source's value won
- `SingleSourceResolution` — only one source provided this attribute
- `ListMergeResolution` — list-typed attribute (e.g., groups) merged across sources by strategy

The discriminator field is `resolution`. This requires a small normative change to the A2 §7.1 specified shape: the groups variant in A2 §7.1 currently uses `strategy` as its discriminator and lacks a `resolution` field. To support a uniform discriminator, this spec adds `resolution: "list_merge"` to the groups variant. The cost is one additional field on one variant; the benefit is exhaustive type-checked dispatch in consumers and uniform parsing behavior across all four variants.

A shared base class `ResolutionDetailBase` declares the one field that is conceptually identical across all four variants — `confidence: float`. The discriminator field (`resolution`) and the value field (`resolved_value`, whose type differs between scalar and list variants) are declared on each subclass. The base class is not a runtime polymorphism mechanism; the discriminated union handles dispatch. The base exists solely to capture the cross-variant invariant that every resolution detail carries a confidence score.

### 3.3 Use a Discriminated Union for `enrichment` Metadata

A7 §7.2 specifies four flat fields at the top level of the normalized output:
- `enrichment_applied: bool`
- `enrichment_source: str` (present only when applied)
- `enrichment_cache_hit: bool` (present only when applied)
- `enrichment_skip_reason: str` (present only when not applied)

This shape carries an implicit invariant — `source` and `cache_hit` co-occur when applied; `skip_reason` is present only when not applied. The current flat-fields representation expresses the invariant only by convention; consumers must know the correlation to read the fields safely.

This spec restructures these four flat fields into a single nested `enrichment` field whose value is a discriminated union over two variants:

- `EnrichmentApplied` — `applied=True`, `source`, `cache_hit`
- `EnrichmentSkipped` — `applied=False`, `skip_reason`

The discriminator is `applied`. This nests the four fields under one key, captures their correlation in the type system, and gives consumers exhaustive pattern-matching access.

The two enrichment variants share no fields (`applied` differs by `Literal[True]` vs `Literal[False]`; the other fields are disjoint). No shared base class is introduced.

The `skip_reason` field is typed as a closed `Literal` enum covering all skip paths described in A7 §6.4 plus the two non-failure skip paths (`ldap_disabled`, `ldap_event`):

- `ldap_disabled` — `enrichment.sources.ldap.enabled` is `false`
- `ldap_event` — event protocol is `ldap` (skip per A7 §4.1)
- `no_ldap_match` — LDAP query returned no entries
- `ldap_timeout` — LDAP search exceeded `timeout_ms`
- `ldap_connection_error` — connection refused or network error
- `ldap_search_error` — other LDAP-side error
- `invalid_correlation_key` — primary attributes missing the correlation_key value

The closed enum forces deliberate evolution: future skip reasons require a model change rather than ad-hoc string drift.

### 3.4 Validate at Both Write and Read Sides

**Write side (Spec 2 — Identity Normalization Service):** The normalization service constructs `NormalizedAttributes` instances via the standard Pydantic `__init__`, which validates field types, value ranges, and the discriminator constraints. It then serializes to JSON via `.model_dump(mode="json")` for storage in the `events.normalized_attributes` JSONB column.

**Read side (Spec 3 — Risk Evaluator, Spec 6 — Dashboard, and any other consumer):** Consumers read the JSONB value as a dict and parse it via `NormalizedAttributes.model_validate(jsonb_dict)`. Read-side validation catches silent shape drift between writer and reader, gives consumers typed access (no `.get()` archaeology), and surfaces schema mismatches at the read boundary instead of letting them propagate as runtime errors deeper in the consumer.

Read-side consumers MUST handle `pydantic.ValidationError` gracefully. Rows written before a model change may not conform to the current schema. The expected behavior for such rows depends on the consumer:

- **Risk Evaluator (Spec 3):** Log a warning, treat the event as having maximum normalization risk (`normalization_risk = 1.0`), and continue evaluation. Failing the entire risk decision because of a stale-row schema mismatch would create an availability problem. Silent degradation here is bounded — the worst case is one event scored more conservatively than it should be.
- **Dashboard (Spec 6):** Display the affected rows with a "schema mismatch" placeholder in the Normalization tab visualization, rather than crashing the dashboard or hiding the rows entirely. The user-visible signal makes the drift discoverable.

This validation strategy does not impose a schema-versioning mechanism on the JSONB itself — the model is the schema, evolves with the model, and consumers handle ValidationError as the migration signal.

### 3.5 Configuration File Rename: `normalization_authority.yaml` → `normalization.yaml`

The file `config/normalization_authority.yaml` was introduced by A2 to hold per-attribute authority configuration. A7 added an `enrichment` section to the same file. The current name accurately describes the original A2 contents but undersells the A7 additions: the file now carries both authority configuration and enrichment configuration, and "authority" is a strict subset of what's inside.

Renaming to `normalization.yaml` covers both sections accurately under one umbrella ("configuration for the normalization service"). It is also short enough not to obscure the file's purpose to an agent searching for normalization-related configuration.

This rename is mechanical: it requires updating five repo-resident touch-points (CLAUDE.md project tree, CLAUDE.md Key Conventions bullet, SYSTEM_ARCHITECTURE.md §3 cross-protocol enrichment bullet, SPEC_0 project tree, SPEC_0 "Files NOT Created" list) plus references in the System Decomposition Guide and the A2/A7 audit specs.

---

## 4. The Proposed Model

The following replaces the existing `NormalizedIdentity` block in `shared/naas_shared/models.py`. New imports required: `Annotated`, `Union` (added to the existing `from typing import` line).

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
    conflicting_values: Dict[SourceProtocol, Any]  # losing source → losing value
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

---

## 5. The Updated JSONB Shape

The `events.normalized_attributes` JSONB column stores the serialized form of `NormalizedAttributes`. The shape below incorporates all the structural changes from §3 and §4: nested `enrichment`, uniform `resolution` discriminator across all four resolution variants (including the new `resolution: "list_merge"` on the groups variant), and the dropped `raw_source_attributes`.

### 5.1 Multi-Source OIDC + LDAP Enrichment (Cache Miss)

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

### 5.2 Single-Source OIDC (Enrichment Skipped — No LDAP Match)

```json
{
  "display_name": "Bob Jones",
  "primary_email": "bob@corp.com",
  "department": "Product",
  "employee_type": "contractor",
  "groups": ["product"],
  "source_protocol": "oidc",
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

### 5.3 LDAP Event (Enrichment Skipped — Self-Source)

```json
{
  "display_name": "Charlie Davis",
  "primary_email": "charlie@corp.com",
  "department": "Engineering",
  "employee_type": "FTE",
  "groups": ["engineering"],
  "source_protocol": "ldap",
  "normalization_confidence": 0.95,
  "enrichment": {
    "applied": false,
    "skip_reason": "ldap_event"
  },
  "resolution_details": {
    "department": {
      "resolution": "single_source",
      "resolved_value": "Engineering",
      "confidence": 0.95,
      "sources": ["ldap"]
    }
  }
}
```

---

## 6. Configuration File Rename

The `config/normalization_authority.yaml` file is renamed to `config/normalization.yaml`. The file's contents are unchanged — both the A2 authority section and the A7 enrichment section continue to live under their existing top-level keys (`defaults`, `attributes`, `enrichment`).

The rename touches every document that names the file, in both repo-resident and audit/meta positions. The complete list of touch-points is enumerated in the companion change manifest. There are no behavioral changes to the normalization service's loading logic; the only thing that changes is the file path the service reads at startup.

---

## 7. Migration Considerations

Because Spec 2 (Identity Normalization Service) has not yet been implemented, no production data exists in the `events.normalized_attributes` column to migrate. This spec is a definitional change that lands before any code reads or writes the affected payload.

However, the read-side validation strategy in §3.4 anticipates a different kind of migration: future evolution of the model itself. If a later spec adds, removes, or restructures fields in `NormalizedAttributes`, rows produced by the older model will fail `model_validate()` against the newer model. The graceful-degradation contract specified in §3.4 (Risk Evaluator: warn + max risk; Dashboard: schema-mismatch placeholder) is the project's standing answer to that scenario.

For agents implementing Spec 2 in the immediate term, this means: construct `NormalizedAttributes` instances when writing to the column, wrap any subsequent reads in `try: NormalizedAttributes.model_validate(row) except ValidationError: <degraded>`, and trust the type system rather than the JSONB.

---

## 8. What This Spec Does NOT Cover

- **The normalization algorithm itself.** Conflict resolution semantics (unanimous / priority / single-source / list-merge), the calculation of per-attribute confidence, and the calculation of overall `normalization_confidence` are defined in `A2_Normalization_Conflict_Resolution_Spec.md`. This spec only formalizes the output shape.
- **Cross-protocol enrichment behavior.** The decision to enrich, the LDAP query mechanics, the cache strategy, and the failure modes are defined in `A7_Cross_Protocol_Enrichment_Spec.md`. This spec only formalizes the output shape's enrichment-metadata representation.
- **Per-attribute narrowing of `resolved_value` types.** A theoretically stricter design would parameterize the resolution sub-models per attribute — e.g., `resolved_value: Literal["FTE", "contractor", "vendor"] | None` for the `employee_type` resolution detail. This spec uses `Optional[str]` (or `list[str]` for the list-merge variant) for `resolved_value` across all variants. The top-level `NormalizedAttributes` model already enforces the Literal constraint on the resolved value of `employee_type`; the resolution-detail entry is "how we got there" and does not need a tighter type.
- **The configuration file's contents.** Section 6 specifies only the file rename, not changes to the file's structure or field semantics. The A2 and A7 specs continue to define the `defaults`, `attributes`, and `enrichment` sections.
- **Schema versioning.** No version field is added to the JSONB. Schema evolution is managed via Pydantic model evolution + read-side ValidationError handling, as described in §3.4 and §7.

---

*End of A9 Specification.*
