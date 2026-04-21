# A-Series Intent-vs-Application Reconciliation Report

## Executive Summary

Six A-series items (A1, A2, A3, A4, A6, A7) were analyzed against the current repository state on the `meta-working` branch. A5 and A8 are absent from `docs/audit/` and are treated as "neither" items per the inventory taxonomy. Documentation state distribution: four items with both spec and manifest (A1, A3, A4, A7), one spec-only (A2), one manifest-only (A6). Across all items, explicit manifest directives are largely applied; the main pattern of incomplete application is in the SPEC_0 project tree (new files/paths introduced by A4 and A7 are not reflected) and in one CLAUDE.md regression where an A7 REPLACE directive was applied as an ADD. Two tier-2 gaps are worth calling out: the `NormalizedIdentity` Pydantic model in SPEC_0 does not carry the enrichment-provenance fields the A2 and A7 specs require for downstream visualization, and an A4 Vision Document directive (§6a, ML ensemble bullet) was not applied. Total discrepancies logged: 10 (1 regression, 1 missed manifest directive, 4 project-tree gaps in SPEC_0, 2 tier-2 model-field gaps, 1 tree-character formatting defect, 1 partial consolidation).

## Inventory

| Item | Spec file | Manifest file | Documentation state |
|------|-----------|---------------|---------------------|
| A1   | `A1_Persona_Simulator_LLM_Design.md` | `A1_Document_Change_Manifest.md` | Both |
| A2   | `A2_Normalization_Conflict_Resolution_Spec.md` | — | Spec only |
| A3   | `A3_Policy_Expression_Language_and_Scoring_Model.md` | `A3_Document_Change_Manifest.md` | Both |
| A4   | `A4_ML_Model_Bootstrap_Workflow.md` | `A4_Document_Change_Manifest.md` | Both |
| A5   | — | — | Neither (absent from inventory) |
| A6   | — | `A6_Document_Change_Manifest.md` | Manifest only |
| A7   | `A7_Cross_Protocol_Enrichment_Spec.md` | `A7_Document_Change_Manifest.md` | Both |

## Per-Item Findings

### A1 — Persona Simulator LLM Integration & EventSink Architecture

- **Documentation state**: Both spec and manifest
- **Stated intent**: Introduce a single, transparent LLM-backed generation layer in the Persona Simulator (Claude → Ollama → Mock fallback chain) built on an `EventSink` abstraction that funnels all generated events through the Event Ingestion service, with a shared tool library that pre-primes the implementation for P2 MCP integration without later refactoring.
- **Directives**: 14 explicit (across SYSTEM_ARCHITECTURE.md §8, MCP Server, Implementation Priority, Redis Usage, Communication Patterns; SPEC_0 `.env.example`, Settings model, shared tree; Tech Stack AI/ML section; CLAUDE.md project structure and Key Conventions; System Decomposition Guide Spec 6; default policy). 12 fully applied, 1 partially applied, 1 superseded.
- **Tier-1 implicated changes**: 5 identified (EventSink, SimulationProvider, TOOL_DEFINITIONS, `shared/naas_shared/simulation_tools.py`, `LLM_PROVIDER`). All consistent in the repo docs that reference them (SYSTEM_ARCHITECTURE.md, CLAUDE.md, Tech Stack, System Decomposition Guide).
- **Tier-2 implicated changes**: 3 identified — (a) no `is_synthetic` branching in the normalization layer (upheld), (b) transparent LLM integration without separate "AI Mode" UI (upheld per ADR-004 in Tech Stack), (c) shared tool definitions avoid reimplementation between Persona Simulator and MCP Server (upheld — SYSTEM_ARCHITECTURE.md §Optional MCP Server explicitly says "thin SSE transport layer wrapping shared implementations — not a reimplementation").
- **Discrepancies**:
  - `docs/architecture/SYSTEM_ARCHITECTURE.md` (§Communication Patterns, lines 386, 391–392): tier-1 / explicit / partial. A1 directive 1e enumerates two new rows: "LLM Generation" and "Event Submission". The "LLM Generation" row is present at line 391. The "Event Submission" row is NOT present as a standalone row — its content was instead merged into the existing "Synchronous REST" row at line 386 ("Persona Simulator → Event Ingestion (via EventSink)"). This is a consolidation rather than an omission; referential consistency is preserved but the table shape differs from the manifest.
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (line 45): explicit / tree-character defect. A1 directive 2d places `simulation_tools.py` in the shared tree, but the tree drawing is malformed: line 44's `constants.py` uses `└──` (last-entry closer), then line 45 drops the left-rail spine entirely (`        └── simulation_tools.py`). Both lines use `└──`, which produces a visually broken tree. Directive content is applied; structural rendering is not.
- **Notes**: A1 directive 6a (update to seed policy `weights` block in `init.sql`) is correctly superseded by A3, which replaces the entire seed policy with the hybrid schema. The A1 weights-only schema is obsolete; no remediation is required.

### A2 — Identity Normalization Conflict Resolution & Confidence Scoring

- **Documentation state**: Spec only
- **Stated intent**: Define the conflict resolution algorithm, attribute authority configuration (`normalization_authority.yaml`), attribute importance weighting, and overall `normalization_confidence` calculation so the Identity Normalization service produces a principled per-attribute and per-identity confidence signal consumable by the Risk Evaluator.
- **Inferred directives**: 6 (no manifest). (i) `config/normalization_authority.yaml` referenced by Spec 2 scope in repo-resident docs; (ii) `NormalizedIdentity` model carries `normalization_confidence` field; (iii) Spec 2 scope bullets include conflict resolution; (iv) `DEPARTMENT_CANONICAL` / `EMPLOYEE_TYPE_CANONICAL` lookup tables implemented inside the normalization service (implementation-level; no repo-doc mirror expected); (v) `ATTRIBUTE_IMPORTANCE` weighting implemented in the normalization service (implementation-level); (vi) `resolution_details` structure emitted alongside `normalized_attributes`.
- **Tier-1 implicated changes**: 3 identified — `normalization_authority.yaml` path (referenced in `CLAUDE.md:101`, `SYSTEM_ARCHITECTURE.md:111`, `NAAS_System_Decomposition_Guide.md:67`); `normalization_confidence` (`SPEC_0:413`); `NormalizedIdentity` (`SPEC_0:405–414`). All present and consistent where referenced.
- **Tier-2 implicated changes**: 2 identified — (a) source-agnostic processing (normalization does not branch on event source) — upheld; (b) `normalization_confidence` feeds the Risk Evaluator as `normalization_risk = 1.0 - normalization_confidence` — upheld in SPEC_0 seed policy (A3-defined) and in System Decomposition Spec 3.
- **Discrepancies**:
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (§ Project Tree, lines 20–63): inferred / tier-1. No `config/` directory appears in the SPEC_0 project tree, so the `normalization_authority.yaml` file referenced throughout the architecture has no home in the scaffold specification. Downstream Spec 2 will need to invent the location.
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (`NormalizedIdentity`, lines 405–414): inferred / tier-2. The model carries `normalization_confidence` but does not define `resolution_details` as an output field. A2 §7.1 stores `resolution_details` inside `events.normalized_attributes` JSONB (so a Pydantic field is not strictly required), but the absence of any schema-level contract for resolution provenance means Spec 2 and the Normalization dashboard tab (Spec 6) will agree on the shape only by convention.
- **Notes**: A2 has no manifest, so both discrepancies above carry medium confidence. They describe gaps in the scaffold's foresight about A2-mandated artifacts, not explicit non-application of any directive.

### A3 — Policy Expression Language & Hybrid Risk Scoring Model

- **Documentation state**: Both spec and manifest
- **Stated intent**: Unify two previously inconsistent policy schemas (weights-only and conditions-only) into a single hybrid scoring model — `signal_weights` (four continuous pre-normalized signals) plus `conditions` (boolean AST expressions over five namespaces) — with an escalating-severity threshold structure, a closed `VALID_SIGNAL_WEIGHTS` enum, and a new `login_recency_risk` signal (plus `days_since_last_login` condition input).
- **Directives**: 11 explicit (SYSTEM_ARCHITECTURE.md §4/§5/§6; SPEC_0 seed policy; A2 spec §6.1/§6.2; System Decomposition Spec 3/Spec 4; Vision policy example and scoring bullets; Enhancement Roadmap Phase 3; CLAUDE.md Key Conventions). 11 fully applied.
- **Tier-1 implicated changes**: 7 identified — `signal_weights`, `conditions`, `VALID_SIGNAL_WEIGHTS`, `login_recency_risk`, `days_since_last_login`, removal of `device_risk` / `time_of_day` / bare `ip_reputation` signal names, removal of old `weights:` / `allow`/`deny` threshold pair. All consistent; no stale terminology found in repo-resident docs.
- **Tier-2 implicated changes**: 3 identified — (a) separation of concerns: Policy Management validates expressions, Risk Evaluator evaluates them — upheld in SYSTEM_ARCHITECTURE.md §5/§6 and System Decomposition Spec 3/Spec 4; (b) hybrid score clamped to [0.0, 1.0] — upheld; (c) signal normalization lives in Risk Evaluator, not in Enrichment — upheld (Enrichment produces `days_since_last_login` as raw count; Risk Evaluator converts to `login_recency_risk`).
- **Discrepancies**: None.
- **Notes**: The A3 manifest instructs addition of a cross-reference to `A3_Policy_Expression_Language_and_Scoring_Model.md` in CLAUDE.md directive 7b, SYSTEM_ARCHITECTURE.md §5, §6, and A2 §6.1. Per the repo self-contained rule, these cross-references were correctly stripped from the repo-resident targets (CLAUDE.md:105, SYSTEM_ARCHITECTURE.md:132, 153) while preserved in the meta/audit targets (A2 spec line 388). This is the intended behavior given the rule override in the reconciliation task instructions.

### A4 — ML Model Bootstrap Workflow

- **Documentation state**: Both spec and manifest
- **Stated intent**: Specify how `random_forest.pkl` is produced (standalone bootstrap script from 12 domain-derived distribution profiles), pin the 16-column feature vector and its ordering contract in `shared/naas_shared/ml_features.py`, and establish that ML training data is independent of rule-based scoring to avoid the entanglement anti-pattern.
- **Directives**: 6 explicit (SYSTEM_ARCHITECTURE.md ML Bootstrap Script section + §6 ML-based bullet; System Decomposition Spec 3 ML bullets + Bootstrap Script block; Tech Stack Scikit-learn section; CLAUDE.md project structure + Key Conventions; A3 spec §10 cross-reference; Vision Document ML ensemble bullet). 5 fully applied, 1 missing.
- **Tier-1 implicated changes**: 3 identified — `scripts/train_bootstrap_model.py`, `shared/naas_shared/ml_features.py`, `random_forest.pkl` feature vector width (16). All consistent in SYSTEM_ARCHITECTURE.md, CLAUDE.md, System Decomposition Guide, Tech Stack.
- **Tier-2 implicated changes**: 2 identified — (a) ML graceful degradation (missing model → ML path disabled, score 0.0) — upheld; (b) no label entanglement between rule-based scoring and ML training — upheld (SYSTEM_ARCHITECTURE.md:231 and System Decomposition:98–99 both state labels are independent).
- **Discrepancies**:
  - `docs/meta/NAAS_v2.0_Vision_Document.md` (line 161): explicit / missing. A4 directive 6a instructs that the existing ASCII-diagram bullet `• ML ensemble (Random Forest)` be replaced with the expanded wording `ML ensemble (Random Forest, 16-feature vector trained on synthetic IAM distribution profiles)`. The bullet at line 161 still reads `• ML ensemble (Random Forest)` verbatim. The directive text does not fit the ASCII-box width, which may explain the omission, but no substitute text was applied.
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (§ Project Tree, lines 20–63): implicit / tier-1. Neither `scripts/` (for `train_bootstrap_model.py`) nor `ml_features.py` (inside `shared/naas_shared/`) appears in the SPEC_0 project tree, even though CLAUDE.md's own tree now includes both. SPEC_0 is the scaffold authority; a downstream agent following SPEC_0 alone will not create these paths.
- **Notes**: The A4 manifest adds a cross-reference to `A4_ML_Model_Bootstrap_Workflow.md` in SYSTEM_ARCHITECTURE.md §6 ML bullet and the ML Bootstrap Script section, and in System Decomposition Spec 3. Per the self-contained rule, these were correctly stripped from the repo-resident targets while preserved in meta/audit targets.

### A6 — SAML-Is-Synthetic Scope Decision

- **Documentation state**: Manifest only
- **Stated intent** (inferred from the manifest itself, which is a scope clarification): Preempt reviewer confusion by documenting in both SYSTEM_ARCHITECTURE.md and the Vision Document that SAML events are simulator-generated — not a bug or omission, but a deliberate scope decision — and correct the SAML adapter's description from "Parses SAML assertions, extracts attributes" to "Maps SAML-convention attribute names to the unified schema."
- **Directives**: 2 explicit (SYSTEM_ARCHITECTURE.md §3 SAML Adapter bullet + Scope Note; Vision Document Multi-Protocol Identity Support bullet line 289). 2 fully applied.
- **Tier-1 implicated changes**: 1 identified — the SAML adapter description should no longer claim XML assertion parsing. Consistent (SYSTEM_ARCHITECTURE.md:98–101, System Decomposition Spec 2 line 66).
- **Tier-2 implicated changes**: 1 identified — self-contained repo docs: the Scope Note at SYSTEM_ARCHITECTURE.md:100–101 references `SYSTEM_ARCHITECTURE.md §3` (self-reference) but does not cross to any meta/audit document. Upheld.
- **Discrepancies**: None.
- **Notes**: The manifest's final section ("Related Finding: Multi-Protocol Enrichment Design Gap") explicitly hands off a follow-up concern to A7, which closed that gap. This is correctly resolved in the repo.

### A7 — Cross-Protocol LDAP Enrichment

- **Documentation state**: Both spec and manifest
- **Stated intent**: Make the live OpenLDAP container serve a real pipeline purpose by having the Identity Normalization service actively query LDAP for OIDC and SAML events — by a configurable unified-schema correlation field (default: `primary_email`) — to produce genuine multi-source normalized identities, with connection pool, Redis cache, graceful degradation, and source-agnostic treatment of live versus simulated events.
- **Directives**: 12 explicit (SYSTEM_ARCHITECTURE.md §3 LDAP adapter bullet, enrichment bullet, Redis Usage row, Communication Patterns row; CLAUDE.md pipeline diagram, Key Conventions bullet; System Decomposition Spec 2 scope + validation; Vision Document Multi-Protocol features + demo script Act 2; SPEC_0 `.env.example` `LDAP_POOL_SIZE`; Implementation Guide demo script Act 2). 11 fully applied, 1 applied as ADD rather than REPLACE.
- **Tier-1 implicated changes**: 4 identified — `LDAP_POOL_SIZE` env var, `ldap_enrichment:{email}` Redis key pattern, `config/normalization_authority.yaml` under `enrichment.sources.ldap`, the correlation-field-on-unified-schema pattern (default: `primary_email`; adapter reverse-maps to `mail`). All consistent in SYSTEM_ARCHITECTURE.md, CLAUDE.md, System Decomposition, SPEC_0 `.env.example`.
- **Tier-2 implicated changes**: 3 identified — (a) source-agnostic processing (enrichment applies equally to live and simulated events, no `is_synthetic` branching) — upheld (stated explicitly in SYSTEM_ARCHITECTURE.md:111 and implicit everywhere else); (b) graceful degradation on LDAP lookup failure or miss — upheld (stated in SYSTEM_ARCHITECTURE.md:97, :111, CLAUDE.md:101, System Decomposition:67); (c) LDAP events skip enrichment (directory data already in payload) — upheld in all four places.
- **Discrepancies**:
  - `CLAUDE.md` (lines 72–73): explicit / **regression**. A7 directive 2a instructs that the existing Event Pipeline diagram line be REPLACED with a new line containing `(+ LDAP enrichment for OIDC/SAML)`. Both lines are now present — the original unannotated pipeline at line 72 and the A7-updated pipeline at line 73. A replace-style directive was applied additively, producing a duplicate diagram that conflicts with itself.
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (§ Project Tree, lines 20–63): explicit / tier-1. The `config/` directory (home of `normalization_authority.yaml` per A7 directive 1b, A2 §3.1) is not part of the SPEC_0 project tree. `LDAP_POOL_SIZE` is present in `.env.example` (line 106), but the config file's location is unhomed in the scaffold.
  - `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (`NormalizedIdentity`, lines 405–414): implicit / tier-2. A7 §8 specifies `enrichment_applied`, `enrichment_source`, `enrichment_cache_hit`, and `enrichment_skip_reason` as fields added to the normalized output to support the Normalization dashboard tab's enrichment visualization. System Decomposition Spec 2 validation criteria at line 75 reference `enrichment_applied`. None of these fields appear in the `NormalizedIdentity` model in SPEC_0; if they are intended to live only inside the `events.normalized_attributes` JSONB (A7 §8 supports this reading), the repo-resident doc contract is silent on the point.
- **Notes**: The A7 manifest adds a cross-reference to `A7_Cross_Protocol_Enrichment_Spec.md` in several repo-resident locations. Per the self-contained rule, those cross-references were correctly stripped. The CLAUDE.md duplicate pipeline diagram is the clearest single regression in this reconciliation; low-risk to fix (delete line 72) but left for a remediation pass per the task's diagnostic-only constraint.

## Cross-Cutting Observations

**SPEC_0 project-tree drift.** The single most consequential pattern is that SPEC_0's project tree (lines 20–63) was not updated to match the files and directories introduced by A1, A4, and A7: `scripts/train_bootstrap_model.py`, `shared/naas_shared/ml_features.py`, and `config/normalization_authority.yaml` are all absent from the scaffold tree, and the `simulation_tools.py` entry at line 45 has malformed tree characters. CLAUDE.md's project-structure section was updated (it now lists the scripts and shared files correctly), but SPEC_0 — the canonical scaffold spec — diverged from CLAUDE.md. Agents implementing SPEC_0 without also reading CLAUDE.md will not create these paths. This matches the task's explicit flag: "Give extra focus to new files and paths added by the A-series designs."

**Repo self-containment invariant is intact.** No repo-resident document (CLAUDE.md, SYSTEM_ARCHITECTURE.md, SPEC_0, or any file outside `docs/meta/` and `docs/audit/`) cross-references an A-series or meta document. All manifest directives that instructed such cross-references were correctly stripped at application time. The only A-series / "A-series" string matches outside `docs/audit/` are in meta documents, which are allowed.

**Tier-2 output-provenance gap (A2 + A7 together).** The `NormalizedIdentity` model in SPEC_0 carries `normalization_confidence` but not the richer provenance structure that both A2 (`resolution_details`) and A7 (`enrichment_applied`, `enrichment_source`, `enrichment_cache_hit`, `enrichment_skip_reason`) specify as required for downstream dashboard visualization. These fields currently have no schema-level home; if they are intended to live only as free-form JSONB under `events.normalized_attributes`, the contract is informal and the Spec 2 implementer and Spec 6 dashboard implementer will agree on field names only by convention. This is a tier-2 observation, not a directive failure — both A2 and A7 leave the packaging decision implicit.

**Directive-application mode inconsistency.** Two A7 directives (2a — CLAUDE.md pipeline diagram) and A1 (1e — Communication Patterns "Event Submission" row) exhibit different application modes than the manifest specified: A7 2a was a REPLACE but was applied as ADD, producing a duplicate; A1 1e was two-row ADD but one row was instead merged into an existing row. In both cases the referential information is present in the repo, but the structural form diverges from the manifest. Future verification passes should check application mode, not just content presence.

**Asymmetry by documentation state.** Items with both spec and manifest (A1, A3, A4, A7) have the tightest tier-1 consistency — manifest directives drive verbatim application. Spec-only A2 has consistent tier-1 coverage but its scaffold-level artifacts (the `config/` directory, the `resolution_details` structure) are homeless in SPEC_0. Manifest-only A6 is the cleanest item in the set — its narrow scope and complete application leave no gaps. This supports the pattern that heterogeneous documentation states produce asymmetric gap profiles: manifest-driven items have tight tier-1 + weaker tier-2, spec-only items have intact principles but thinner surface coverage.

## Items Without Verifiable Documentation

- **A5**: not present in `docs/audit/`. No spec, no manifest, no other trace in the repo under any A5-prefixed name. Per the task constraints, intent is not speculated.
- **A8**: not present in `docs/audit/`. Same handling as A5. The A-series numbering is contiguous from A1 through A7 (with A5 missing); no eighth item is evidenced.

## Out-of-Scope Items Noticed

- `docs/implementation-plans/` contains chunked plan documents (e.g., `plan_SPEC_0_Project_Scaffold_and_Shared_Foundation_chunk0..3.md`) that are agentic-pipeline derivatives of SPEC_0. If SPEC_0 is updated to include the missing project-tree entries (scripts/, config/, ml_features.py), the chunked plans may require regeneration to stay in sync.
- The A1 manifest directive 2e ("Verify `persona-simulator` is included in the list of directories that get placeholder READMEs") is a verification instruction, not a change — noted as satisfied at SPEC_0:61.
- The CLAUDE.md pipeline-diagram regression (A7 2a) is a single-line cleanup. Its remediation is deferred per this task's diagnostic-only constraint.
- A2 §7.1 stores `resolution_details` inside JSONB, and A7 §8 adds enrichment provenance to the same payload. A separate design discussion could formalize the `normalized_attributes` JSONB shape as a Pydantic model in `shared/naas_shared/models.py`, which would close the tier-2 provenance gap without adding fields to `NormalizedIdentity` itself.

*End of A-Series Intent-vs-Application Reconciliation Report.*
