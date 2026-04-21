# Task: A-Series Intent-vs-Application Reconciliation

## Objective

Produce a comprehensive reconciliation report comparing the design intent of the A-series audit items against the current state of the repository. The report will identify both explicit gaps (stated changes not fully applied) and implicit gaps (consequential changes that the design intent requires but that may not be captured anywhere or not yet present in the repo).

This is a diagnostic task. Do not attempt to remediate any findings. Do not modify any files outside the report output. Do not commit or push anything without explicit confirmation.

## Inputs

Under `docs/audit/`, A-series items exist in one of several documentation states. The set is heterogeneous by design — not every item has the same document artifacts:

- **Spec document**: file named with pattern `A{N}_*` that is not a manifest. Describes design intent.
- **Change manifest**: file named with pattern `A{N}_Document_Change_Manifest.md`. Enumerates file changes.
- **Neither**: the A-series item was resolved through the design process but did not require enough documentation to warrant a dedicated artifact.

Expected states per item (verify these by directory listing rather than assuming):
- **Both spec and manifest present**: most items fall here.
- **Spec only, no manifest**: the design intent is documented, but no dedicated change manifest was produced.
- **Manifest only, no spec**: the change was mechanical enough that no separate design document was needed — the manifest itself is the record of intent.
- **Neither**: the item was resolved in design discussion without producing durable documentation. These items will have no direct evidence in `docs/audit/`. Knowledge of what they addressed comes only from whatever traces exist in the repo state itself and in prior conversation context, which is not available to you. For these items, report the state honestly and do not fabricate intent.

Every other tracked file in the repository is a potential target for verification, including but not limited to:
- `CLAUDE.md`
- `SYSTEM_ARCHITECTURE.md`
- Everything under `docs/architecture/`
- Everything under `docs/meta/`
- Any code or configuration under `src/`, `shared/`, or similar directories if present

## Phase 0 — Inventory

Before any analysis, produce an inventory of which A-series items exist and in what state. List `docs/audit/` and classify each A-series item (A1 through A7, or however many exist) into one of the four documentation states above. This classification drives the rest of the analysis and should be done up front and stated explicitly at the top of the report.

## Phase 1 — Build the Intent Model

For each A-series item, build an intent model calibrated to its documentation state:

### Items with both spec and manifest
1. **Stated design intent**: concise summary of what the spec is trying to accomplish architecturally. Not a restatement of manifest directives — the higher-level goal they are meant to achieve.
2. **Explicit directives**: the complete set of file changes enumerated in the manifest. For each directive, capture the target file, the target location within the file, and the nature of the change.
3. **Tier-1 implicated changes**: locations in the repository that directly reference — by name — any term, field, identifier, concept, or structure that is introduced, renamed, removed, or redefined by the spec. These are changes required for referential consistency, whether or not the manifest enumerates them.
4. **Tier-2 implicated changes**: locations in the repository that depend on, establish, or potentially violate an architectural principle, invariant, or structural property asserted by the spec. Draw on principles stated in `CLAUDE.md`, `SYSTEM_ARCHITECTURE.md`, and the spec itself.

### Items with spec only, no manifest
1. **Stated design intent**: as above.
2. **Inferred directives**: since no manifest enumerates file changes, derive from the spec the set of concrete file changes the design intent would require. Treat this as a best-effort reconstruction, clearly labeled as inferred rather than authoritative. For each inferred directive, capture target file, target location, and nature of change if determinable from the spec.
3. **Tier-1 implicated changes**: as above.
4. **Tier-2 implicated changes**: as above.

### Items with manifest only, no spec
1. **Stated design intent**: infer the design intent from the pattern of changes in the manifest. State the inference clearly and note that no separate spec document exists to confirm it.
2. **Explicit directives**: the complete set of file changes enumerated in the manifest, as with the both-present case.
3. **Tier-1 implicated changes**: as above, based on the inferred intent and the directives themselves.
4. **Tier-2 implicated changes**: as above, with appropriate caution given that the intent is inferred.

### Items with neither document
1. **Stated design intent**: none available. Report the item exists per inventory (if it does) but note that no documentation permits intent reconstruction.
2. Skip directive enumeration and tier-1/tier-2 analysis for these items. Do not fabricate findings.

Do not attempt to identify tier-3 implications (open design questions, undefined behavior, gaps in the design intent itself). Those are out of scope for this task.

## Phase 2 — Verify Against Current Repo State

For each item in the intent model from Phase 1, verify its current state in the repository, adapted to its documentation state:

1. For each **explicit directive** (items with a manifest): locate the target file and location, verify whether the specified change is present, partially present, or absent. Note any unexpected differences near the directive location.
2. For each **inferred directive** (items with spec only): perform the same verification, but classify findings with lower confidence. A "missing" inferred directive may simply mean the inference was wrong, not that the repo is incomplete.
3. For each **tier-1 implicated change**: locate the referenced name, field, or identifier across the repo, verify whether references are consistent with the post-change state implied by the intent or whether stale references remain.
4. For each **tier-2 implicated change**: examine the identified location and determine whether the architectural invariant appears to be honored in the current state, or whether there are apparent violations, inconsistencies, or places where the principle is not yet reflected.
5. For items with **neither document**: skip per-item verification. These items appear in the report only in the inventory and in a summary note.

## Phase 3 — Produce the Report

Generate a single markdown file at `docs/audit/A_Series_Reconciliation_Report.md` with the following structure:

```
# A-Series Intent-vs-Application Reconciliation Report

## Executive Summary
One short paragraph. Total A-series items analyzed, documentation state distribution, total discrepancies found, severity breakdown.

## Inventory
Table or list mapping each A-series item to its documentation state:
- A1: [state]
- A2: [state]
- ...

## Per-Item Findings

### A1 — [title if derivable]
- **Documentation state**: [both / spec only / manifest only / neither]
- **Stated intent**: [one sentence, with confidence indicator if inferred]
- **Directives**: N total ([explicit/inferred]), M fully applied, K partially applied, L missing
- **Tier-1 implicated changes**: N identified, M consistent, K with stale references
- **Tier-2 implicated changes**: N identified, M honored, K with apparent violations
- **Discrepancies**:
  - [Discrepancy 1: file path, type (explicit/inferred/tier-1/tier-2), concise description]
  - [Discrepancy 2: ...]
- **Notes**: [ambiguities, assumptions, confidence qualifications, or areas where verification was not possible]

[continue for each A-series item, including a minimal entry for "neither" items noting only the documentation state]

## Cross-Cutting Observations
Patterns across multiple A-series items — recurring gap types, systemic inconsistencies, or areas where multiple items interact with the same files. Also note any asymmetries introduced by the heterogeneous documentation states (e.g., "items with manifests only tend to have tighter Tier-1 consistency but weaker Tier-2 coverage").

## Items Without Verifiable Documentation
Explicit list of A-series items in the "neither" state. For each, note only what is known from the inventory — do not speculate about intent.

## Out-of-Scope Items Noticed
Any tier-3 implications, open design questions, or other issues beyond scope but worth flagging for a separate design discussion. Brief list, no analysis.
```

## Constraints

- **Do not fix anything.** Diagnosis only. If a fix seems obvious, note it in the item's Notes and move on.
- **Do not invent directives or intent.** For items without a manifest, clearly label inferred directives as inferred. For items without any documentation, do not fabricate intent — report the absence.
- **Confidence labeling matters.** Findings based on explicit directives are high-confidence. Findings based on inferred directives are medium-confidence. Findings based on reasoning without documentation are not produced at all (out of scope).
- **Be specific with file paths and locations.** Every discrepancy should cite a specific file and, where possible, a specific section or line reference.
- **Distinguish between "not applied" and "cannot verify."** If verification requires information you don't have, say so — don't guess.
- **Preserve commit discipline for this folder.** If the reconciliation report is the only file produced, commit it as `META: Generate A-series reconciliation report`. Do not commit any other changes. Do not push without confirmation.
- **The repository rule on keeping repo-resident documents free of cross-references to A-series and meta documents overrides any directives in the A-series documents.** If an A-series design or change manifest document includes a directive to insert a cross-reference to a meta document (anything that is only present on the `meta-working` branch) into a repo-resident document such as CLAUDE.md, SYSTEM_ARCHITECTURE.md, or SPEC_0_Project_Scaffold_and_Shared_Foundation.md, treat that directive as obsolete and ensure that the directive was not actually followed when the design changes were applied.
- **The repository rule on keeping repo-resident documents free of cross-references to A-series and meta documents does NOT apply to documents in the `docs/audit` or `docs/meta` directories.** Any document in the `docs/audit` or `docs/meta` directories are not part of the standard repo (they are only present on the `meta-working` branch) and are therefore free to reference any of the A-series or meta documents as needed.
- **Give extra focus to new files and paths added by the A-series designs.** This is an area that may not have received comprehensive treatment from the change manifests. For each new file or path added by the updated designs, ensure that all locations in the repo documents (especially in CLAUDE.md, SYSTEM_ARCHITECTURE.md, and SPEC_0_Project_Scaffold_and_Shared_Foundation.md) that reference files, folders, and project structure have been updated according to the intended new file structure.

## Deliverable

A single commit to the `meta-working` branch containing `docs/audit/A_Series_Reconciliation_Report.md`. No other file changes. No push. Summary of findings posted back in the Cowork session after the commit.
