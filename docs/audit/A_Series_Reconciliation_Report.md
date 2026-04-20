# A-Series Intent-vs-Application Reconciliation Report

## Executive Summary

Six A-series items (A1, A2, A3, A4, A6, A7) were analyzed; A5 is absent from `docs/audit/` entirely. The documentation state is heterogeneous: four items (A1, A3, A4, A7) have both a spec and a manifest; one (A2) has a spec only; one (A6) has a manifest only; one (A5) has neither. The majority of explicit manifest directives have been applied to the current repository state. The most consequential finding is a systematic pattern: every manifest directive that instructed a repo-resident document to include an inline cross-reference to an A-series spec document (e.g., "See `A3_Policy_Expression_Language_and_Scoring_Model.md`") was suppressed on application. This is the correct outcome under the project's Cross-Reference Rules, but it means the manifests as written describe a state that would violate repository discipline. A small number of additional mechanical discrepancies were found (a duplicated line in `CLAUDE.md`, a broken markdown table row in `SYSTEM_ARCHITECTURE.md`, an indentation defect and a missing entry in the `SPEC_0` shared library file tree). A latent conflict also exists between the A1 and A3 manifests regarding the seed policy schema; the repository reflects the A3 resolution.

## Inventory

Directory listing of `docs/audit/`:

- `A1_Document_Change_Manifest.md`
- `A1_Persona_Simulator_LLM_Design.md`
- `A2_Normalization_Conflict_Resolution_Spec.md`
- `A3_Document_Change_Manifest.md`
- `A3_Policy_Expression_Language_and_Scoring_Model.md`
- `A4_Document_Change_Manifest.md`
- `A4_ML_Model_Bootstrap_Workflow.md`
- `A6_Document_Change_Manifest.md`
- `A7_Cross_Protocol_Enrichment_Spec.md`
- `A7_Document_Change_Manifest.md`
- `NAAS_Cowork_A_Series_Reconciliation_Task.md` (the current task definition, not an A-series artifact)

Classification per A-series item:

- A1 — both spec and manifest present
- A2 — spec only, no manifest
- A3 — both spec and manifest present
- A4 — both spec and manifest present
- A5 — neither present (no A5 files exist in `docs/audit/`)
- A6 — manifest only, no spec
- A7 — both spec and manifest present

## Per-Item Findings

### A1 — Persona Simulator LLM Design (with EventSink + shared tools)

- **Documentation state**: both spec and manifest
- **Stated intent**: Persona Simulator generates events through a transparent LLM provider chain (Claude → Ollama → Mock) via a `SimulationProvider` interface; all providers submit events as a side effect through an `EventSink` abstraction rather than returning data, and a shared `simulation_tools.py` library is reused by both the internal ClaudeMCPProvider (P2) and the external MCP Server (P2).
- **Directives**: 13 explicit, 10 fully applied, 2 partially applied, 1 in conflict with another manifest.
- **Tier-1 implicated changes**: 7 named terms traced (EventSink, SimulationProvider, GenerationResult, simulation_tools.py, TOOL_DEFINITIONS, LLM_PROVIDER, ToolExecutor). All consistent across repo-resident docs; no stale references found outside `docs/audit/`.
- **Tier-2 implicated changes**: 4 invariants examined; all honored in current state.

Discrepancies:

- `docs/architecture/SYSTEM_ARCHITECTURE.md` §10 MCP Server (A1 directive 1b). The manifest's final bullet ("See `A1_Persona_Simulator_LLM_Design.md` for full design...") is absent from the current file. Classification: partial. The absence is correct under the Cross-Reference Rules (repo-resident documents must not reference A-series content), but it means directive 1b's trailing See-line was not applied verbatim.

- `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` shared library file tree (A1 directive 2d). The line `└── simulation_tools.py` was added at line 45 but with incorrect tree-drawing characters — the preceding line ends with `└── constants.py` (already the final sibling under `naas_shared/`), and the new line uses plain spaces instead of tree connectors, dangling visually outside the directory. The file is referenced, but the tree is malformed.

- A1 directive 6a (seed policy update) and A3 directive 2a (seed policy replacement) target the same SQL INSERT in `SPEC_0`. A1 requests weights-only keys (`ip_reputation`, `device_risk`, `impossible_travel`, `failed_logins`, `time_of_day`, `normalization_risk`) with an `ensemble` block; A3 requests the hybrid `signal_weights` + `conditions` schema with canonical signal names (`ip_reputation_risk`, `failed_login_risk`, `login_recency_risk`, `normalization_risk`) and the eight-condition demonstration policy. The current `SPEC_0` (lines 246–290) reflects A3's design. A1's seed-policy directive was correctly superseded but this is not flagged in either manifest. See Cross-Cutting Observations.

Notes: All 13 AI/ML Components additions in `docs/meta/NAAS_v2.0_Tech_Stack.md`, the A1 project-structure and key-conventions additions in `CLAUDE.md`, and the A1 Implementation Priority / Redis Usage / Persona Simulator section rewrites in `SYSTEM_ARCHITECTURE.md` are present. The manifest references `NAAS_v2_0_Tech_Stack_UPDATED.md` and `SPEC_0_Project_Scaffold_and_Shared_Foundation_UPDATED.md` — the actual file names have no `_UPDATED` suffix and use `NAAS_v2.0_Tech_Stack.md` with a dot. The directives were applied to the correctly-named files despite the manifest's stale filenames.

### A2 — Normalization Conflict Resolution

- **Documentation state**: spec only, no manifest
- **Stated intent** (high-confidence, directly stated in spec): Identity Normalization resolves per-attribute conflicts across OIDC/SAML/LDAP using a configurable authority-weights YAML, producing a per-attribute confidence that is inverted into a `normalization_risk` signal consumed by the Risk Evaluator. Data inconsistency is thereby converted into a first-class risk signal.
- **Directives** (inferred, lower-confidence): 8 inferred directives covering `resolve_attribute()`, value normalization, authority YAML, groups merge strategies, overall confidence calculation, `resolution_details` storage, downstream hand-off, and edge-case handling. These are implementation-level directives for Spec 2; they are not expected to appear in architectural documents and were not verified at file-content level.
- **Tier-1 implicated changes**: 7 named terms traced. `normalization_confidence`, `normalization_risk`, `normalization_authority.yaml`, and the concept of "configurable priority rules" appear consistently in `SYSTEM_ARCHITECTURE.md` §3 (lines 110–111), `CLAUDE.md` Key Conventions (line 101), and `SPEC_0` seed policy (line 253, `normalization_risk: 0.15`). Implementation-level identifiers (`resolve_attribute`, `ATTRIBUTE_IMPORTANCE`, `resolution_details`) are not present in repo-resident or meta documents, which is appropriate for an implementation spec.
- **Tier-2 implicated changes**: 3 invariants examined. The invariants (source agreement strengthens confidence; cross-protocol enrichment occurs at the normalization layer; adapter mappings are deterministic one-to-one) are all honored in current repo-resident documentation.

Discrepancies: None identifiable at the architectural-document level. A2 is predominantly a Spec-2 implementation directive; its integration surface (the `normalization_risk` signal, the authority config path, the cross-protocol enrichment hook) is represented correctly.

Notes: A2 cross-references are internal to `docs/audit/` (A2 §6.1–6.2 was updated by A3 manifest directive 3a/3b to point at A3). A2 spec §6.1 references `A3_Policy_Expression_Language_and_Scoring_Model.md` at line 388, which is a permitted cross-reference within `docs/audit/`.

### A3 — Policy Expression Language and Hybrid Scoring Model

- **Documentation state**: both spec and manifest
- **Stated intent**: The Risk Evaluator uses a hybrid scoring model combining continuous `signal_weights` (four pre-normalized signals) with boolean `conditions` (ast-based expression evaluator over five namespaces), clamped to [0.0, 1.0], blended with an ML score via ensemble. The policy YAML is source of truth; invalid expressions are rejected at policy-creation time.
- **Directives**: 13 explicit, 9 fully applied, 4 partially applied (all suppressed See-line cross-references to the A3 spec).
- **Tier-1 implicated changes**: 10 named terms traced (signal_weights, conditions/expression, VALID_SIGNAL_WEIGHTS, evaluation context/namespaces, days_since_last_login, login_recency_risk, ast-based/safe evaluator, contributing_factors, ensemble, thresholds). All consistent across `SYSTEM_ARCHITECTURE.md`, `SPEC_0`, `CLAUDE.md`, and the meta documents.
- **Tier-2 implicated changes**: 5 invariants examined. All honored.

Discrepancies:

- `docs/architecture/SYSTEM_ARCHITECTURE.md` §5 Policy Management (A3 directive 1b). The trailing "See `A3_Policy_Expression_Language_and_Scoring_Model.md` for full schema and validation rules" is absent from the current file (line 132 ends after "ensemble configuration"). Partial — boundary-rule-driven suppression.

- `docs/architecture/SYSTEM_ARCHITECTURE.md` §6 Risk Evaluator (A3 directive 1c). The "See `A3_...` for full expression language spec" trailing sentence after the Expression evaluator bullet is absent from the current file (line 153 ends after "lowercase Python syntax."). Partial — boundary-rule-driven suppression.

- `docs/architecture/SYSTEM_ARCHITECTURE.md` §5 Policy Management (A3 directive 1b). The "Shadow mode support" bullet is present at line 136; no discrepancy. (Noted explicitly because the Phase 1 intent model flagged it as a possible gap.)

- A3 directive 2a (seed policy replacement in `SPEC_0`) was applied in full at lines 246–290, overriding the conflicting A1 directive 6a. See Cross-Cutting Observations.

Notes: A3 directives targeting `docs/meta/NAAS_System_Decomposition_Guide.md` (Spec 3 and Spec 4 bullets), `docs/meta/NAAS_v2.0_Vision_Document.md` (policy YAML example and scoring bullets), and `docs/meta/NAAS_v2.0_Enhancement_Roadmap.md` (Phase 3 deliverables) were not verified line-by-line here; spot-checks found the hybrid-model language present in the meta documents and no stale "time_of_day" weight references in meta documents.

### A4 — ML Model Bootstrap Workflow

- **Documentation state**: both spec and manifest
- **Stated intent**: The Random Forest ML model is bootstrapped from 12 synthetic distribution profiles (six benign, six malicious) encoding IAM domain knowledge. A 16-column feature vector is shared between training and inference via `shared/naas_shared/ml_features.py`. Model labels are independent of rule-based scoring (no entanglement). The trained `.pkl` is a committed artifact; P2 adds a full training service.
- **Directives**: 8 explicit, 5 fully applied, 2 partially applied (suppressed See-line cross-references to the A4 spec), 1 inconsistent outcome (`SPEC_0` file tree).
- **Tier-1 implicated changes**: 6 named terms traced (ML_FEATURE_COLUMNS, extract_ml_features, DistributionProfile, random_forest.pkl, 70:30 class balance, entanglement anti-pattern). Architectural-level terms (16-feature vector, entanglement anti-pattern, bootstrap script path, feature-ordering contract module) are consistent across `SYSTEM_ARCHITECTURE.md`, `CLAUDE.md`, and meta docs. Implementation-level identifiers (`ML_FEATURE_COLUMNS`, `extract_ml_features`, `DistributionProfile`) appropriately do not appear in architectural documents.
- **Tier-2 implicated changes**: 4 invariants examined. All honored.

Discrepancies:

- `docs/architecture/SYSTEM_ARCHITECTURE.md` ML Bootstrap Script section (A4 directive 1a). The trailing "See `A4_ML_Model_Bootstrap_Workflow.md`" sentence is absent from the current file (section ends at line 232 with the P2 bullet). Partial — boundary-rule-driven suppression.

- `docs/architecture/SYSTEM_ARCHITECTURE.md` §6 Risk Evaluator ML-based bullet (A4 directive 1b). The trailing "See `A4_ML_Model_Bootstrap_Workflow.md`" sentence is absent from line 147. Partial — boundary-rule-driven suppression.

- `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` shared library file tree (A4 implied consequence). `CLAUDE.md` Project Structure (lines 56–59) correctly lists both `ml_features.py` and `simulation_tools.py` under `shared/naas_shared/` per A4 directive 4a. The `SPEC_0` file tree (lines 34–45), which is the canonical file-tree specification for the shared library, lists `simulation_tools.py` (line 45, with the indentation defect noted under A1) but does **not** list `ml_features.py`. This is an implicit consequence not enumerated in the A4 manifest but required for consistency: if `ml_features.py` belongs in `shared/naas_shared/` per A4, it should appear in `SPEC_0`'s canonical file tree as well as in `CLAUDE.md`.

Notes: The A3 spec §10 cross-reference update to point at A4 (A4 directive 5a) is present in `docs/audit/A3_Policy_Expression_Language_and_Scoring_Model.md` line 891. This is a cross-reference internal to `docs/audit/` and is permitted.

### A5 — (no documentation)

- **Documentation state**: neither spec nor manifest
- **Stated intent**: Not available. No file in `docs/audit/` carries the `A5_` prefix. No documentation exists to permit intent reconstruction. Per task instructions, no directive enumeration or tier-1/tier-2 analysis is produced.

### A6 — SAML Scope Documentation

- **Documentation state**: manifest only, no spec
- **Stated intent** (inferred from manifest): The SAML adapter maps SAML-convention attribute names to the unified schema rather than parsing SAML assertion XML, reflecting a deliberate scope decision to emphasize the multi-protocol normalization layer's architectural value. SAML events in the demo are simulator-generated because no live SAML IdP is present in the Docker Compose stack. A scope note is added to `SYSTEM_ARCHITECTURE.md` and a one-line expansion to the Vision Document to preempt reviewer questions.
- **Directives**: 2 explicit, both fully applied.
- **Tier-1 implicated changes**: 2 named phrases traced ("SAML Adapter", "simulator-generated" / `protocol: saml`). Consistent usage.
- **Tier-2 implicated changes**: 2 invariants examined. Both honored (adapters are source-agnostic; adapters map attribute names rather than parsing protocol-specific wire formats).

Discrepancies: None.

Notes: The A6 manifest distinguishes "repo document" from "meta-document, NOT in repo" (manifest §2 header, line 38). This terminology predates the current repo layout in which `docs/meta/` is in-repo on the `meta-working` branch. The directive itself targets `docs/meta/NAAS_v2.0_Vision_Document.md`, and the content is present there; the label in the manifest is stale but the change landed correctly.

### A7 — Cross-Protocol LDAP Enrichment

- **Documentation state**: both spec and manifest
- **Stated intent**: Identity Normalization performs LDAP enrichment for OIDC and SAML events. The LDAP adapter is dual-role (extract for `protocol: ldap`, enrich for OIDC/SAML). The correlation lookup uses a configurable unified-schema field (default `primary_email`); the adapter reverse-maps to the LDAP attribute internally. Results cached in Redis; failures degrade gracefully; LDAP events skip enrichment.
- **Directives**: 11 explicit, 10 fully applied, 1 with a markdown-rendering defect.
- **Tier-1 implicated changes**: 6 named terms traced (cross-protocol enrichment, correlation_key, `enrich` method, `ldap_enrichment:{key}` cache pattern, enrichment metadata fields, `should_enrich_from_ldap`). Architectural-level concepts consistent across `SYSTEM_ARCHITECTURE.md`, `CLAUDE.md`, `SPEC_0`. Implementation-level identifiers appropriately absent from architectural docs.
- **Tier-2 implicated changes**: 5 invariants examined. All honored.

Discrepancies:

- `docs/architecture/SYSTEM_ARCHITECTURE.md` Communication Patterns table (A7 directive 1e / Phase 2 designation directive 4). Line 392 reads: `| LDAP Enrichment  | Identity Normalization → OpenLDAP | LDAP (tcp/389, internal Docker network) |`. The manifest (A7 manifest line 59) specifies the row as `| LDAP Enrichment | Identity Normalization → OpenLDAP | LDAP (tcp/389, internal Docker network) |`. Both forms contain an internal `|` character in the "When Used" cell content before "LDAP", which breaks the 3-column markdown table into 4 cells on rendering. This affects every other row in the table by reference (alignment looks fine in a plain editor but rendered markdown will show the row with an extra column). The manifest's source text has the same bug, so this is a directive-level defect that was applied faithfully.

- `CLAUDE.md` Event Pipeline diagram (A7 directive 5a). The directive instructs replacing the original `Ingestion → [login_events] → Normalization → [normalized_events] → ...` line with a version annotated `Normalization (+ LDAP enrichment for OIDC/SAML)`. The current file (lines 72–73) contains **both** lines — the original at line 72 and the annotated version at line 73. The replacement was additive rather than in-place. This results in a duplicated pipeline line in the diagram.

Notes: All other A7 directives landed correctly. The `LDAP_POOL_SIZE=3` addition is present in `SPEC_0` at line 106. The LDAP Adapter dual-role rewrite in `SYSTEM_ARCHITECTURE.md` §3 is present at line 97. The cross-protocol enrichment bullet is at line 111. The Redis cache row `ldap_enrichment:{email}` is at line 372. The `CLAUDE.md` cross-protocol enrichment convention is at line 101.

## Cross-Cutting Observations

**Systematic suppression of A-series cross-references in repo-resident documents.** The A1, A3, and A4 manifests each contain directives whose applied text would violate the project's Cross-Reference Rules (repo-resident documents must not reference A-series or meta-branch-only content). Every such "See `A{N}_*.md` for..." trailing sentence was omitted on application. The affected directives are: A1 manifest 1b (line 52), A3 manifest 1b (line 43), A3 manifest 1c (line 70), A4 manifest 1a (line 22), and A4 manifest 1b (line 36). This is the correct outcome under repository discipline; the report classifies these as partial rather than missing because the substantive content was applied and only the boundary-violating suffix was omitted. Consider either amending the manifests to remove these suffixes or moving these cross-references into `docs/audit/`-resident connector documents.

**Seed-policy directive conflict between A1 and A3.** A1 manifest §6 (lines 312–331) and A3 manifest §2a (lines 80–144) both specify complete replacements of the `SPEC_0` seed policy but with incompatible schemas. A1 requires a weights-only schema with six keys including `device_risk` and `time_of_day`; A3 requires the hybrid `signal_weights` + `conditions` schema with four signal keys and eight demonstration conditions. The repository state reflects A3's design. Neither manifest acknowledges the other. The A1 directive should be treated as superseded by A3 and annotated as such to prevent future re-application.

**Manifest file-path drift.** A1's manifest targets "`NAAS_v2_0_Tech_Stack_UPDATED.md`" (manifest line 155) and "`SPEC_0_Project_Scaffold_and_Shared_Foundation_UPDATED.md`" (manifest line 89); A4 references "`NAAS_v2.0_Tech_Stack.md`" (correct); A6 and A7 headers tag some of their targets as "NOT in repo" (A6 manifest line 38; A7 manifest lines 146, 220). The actual file paths have no `_UPDATED` suffix, and `docs/meta/` documents are in-repo on the `meta-working` branch. Directives were applied against the correct files despite these labels, but the manifests themselves are internally inconsistent about file locations.

**`SPEC_0` shared library file tree is out of sync with `CLAUDE.md`.** Both documents attempt to enumerate the contents of `shared/naas_shared/`. `CLAUDE.md` (lines 56–59) lists `ml_features.py` and `simulation_tools.py`. `SPEC_0` (lines 34–45) lists only `simulation_tools.py`, and with the indentation defect described under A1. Since `SPEC_0` is the scaffolding spec whose file tree is the authoritative definition of the directory structure, the omission of `ml_features.py` there is the more consequential gap.

**Asymmetry by documentation state.** Items with both spec and manifest (A1, A3, A4, A7) have the largest directive footprint and the tightest architectural-level term consistency, but also concentrate the boundary-rule directives-vs-rules tension. The single manifest-only item (A6) has the cleanest application — two small, local directives, both landed exactly. The single spec-only item (A2) has no directly-verifiable directive surface because its intent is almost entirely at the implementation-spec level (Spec 2), and its integration hooks (`normalization_risk` signal, authority config path, cross-protocol enrichment) appear consistently in architectural documents. The neither-document item (A5) is entirely opaque.

**Mechanical application defects are localized and small.** Two minor application bugs were found in otherwise-applied directives: a duplicated line in the `CLAUDE.md` event pipeline diagram (A7 directive 5a), and a broken markdown table row in `SYSTEM_ARCHITECTURE.md` Communication Patterns (A7 directive 1e, where the directive source itself also has the bug). A third mechanical defect (indentation in the `SPEC_0` file tree) affects A1's `simulation_tools.py` entry. None of these affect the described architectural intent; all are cosmetic or structural.

## Items Without Verifiable Documentation

- **A5**: absent from `docs/audit/` entirely. No spec, no manifest, no referenced file. No intent reconstruction is attempted. The item exists only as a gap in the A-series numbering; it may have been resolved in design discussion without producing documentation, or the number may simply have been skipped.

## Out-of-Scope Items Noticed

- **Manifests themselves instruct boundary-rule violations.** The project's Cross-Reference Rules are not reflected in the language of the manifests. A future design discussion should decide whether to amend existing manifests, establish a convention for where such cross-references belong (e.g., only in `docs/audit/`-resident connector notes), or define an exception where repo-resident documents may reference A-series content.

- **Latent manifest conflicts have no explicit resolution record.** The A1 vs A3 seed-policy conflict was resolved in practice (A3 won) but is not acknowledged in either manifest. A future A-series resolution protocol may benefit from a convention for recording conflicts between manifests and noting which directive supersedes which.

- **The A7 manifest's own Communication Patterns table row has a pre-existing markdown-table bug** that was faithfully transcribed into `SYSTEM_ARCHITECTURE.md`. This suggests manifest review should include a rendered-markdown check, not just source-level inspection.

- **A5's absence is undocumented.** If A5 was intentionally skipped, a single-line note in `docs/audit/` would eliminate future confusion. If it was resolved in design discussion, a short stub document would preserve traceability.

- **File-tree specifications duplicated across `SPEC_0` and `CLAUDE.md`** are a maintenance hazard; any future change to `shared/naas_shared/` requires updates to both. A single canonical location (likely `SPEC_0`) with `CLAUDE.md` linking to it would reduce drift risk — though note this would require `CLAUDE.md` to link to a repo-resident target, not an A-series or meta document.
