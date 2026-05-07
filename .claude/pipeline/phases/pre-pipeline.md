# Pre-Pipeline Phase

Set up the feature branch, pipeline state, and execution log before any worker agents are invoked.

## Entry

This is the first phase of a fresh pipeline run. No state.json exists yet.

## Execution

1. Parse the spec identifier from the developer's prompt. Derive the spec slug (e.g., "Spec 3: Enrichment and Evaluation" → `spec-3-enrichment`).
2. Locate the spec document in `docs/` or `docs/architecture/`.
3. Create the feature branch: `git checkout main && git pull origin main && git checkout -b feature/<spec-slug>`.
4. Create `.claude/pipeline/state.json` per the schema in CONTRACTS.md Section 3. Set the top-level operational values:
   - `contract_version: 2`
   - `spec` to the full spec title
   - `spec_slug` to the derived slug
   - `branch` to `feature/<spec-slug>`
   - `phase: "architecture"`
   - `started_at` to the current ISO 8601 UTC timestamp

   All other required top-level fields take their zero/empty defaults defined by the schema (`current_chunk`, `total_chunks`, `invocation_count`, `chunks`, `completed_at`).
5. Create `.claude/pipeline/logs/<spec-slug>.md` with the headers defined in CONTRACTS.md §5.1 rows 1–2 (`# Pipeline Run` and `# Started`).
6. Ensure the per-spec artifact directories exist (created if absent — no-op if already present):
   - `.claude/pipeline/plans/` — destination for the implementation plan file written by the technical-architect (CONTRACTS.md §7).
   - `.claude/pipeline/reviews/` — destination for the code security review file appended by the orchestrator after each code-security-reviewer invocation (CONTRACTS.md §8).
   - `.claude/pipeline/reports/` — destination for the per-spec quality report (CONTRACTS.md §6) and the integration validation report appended by the orchestrator after each integration-validator invocation (CONTRACTS.md §9).

## Success → Architecture Phase

All of the above artifacts exist. `state.json` shows `phase: "architecture"`. Proceed by reading `.claude/pipeline/phases/architecture.md`.

## Failure → Escalation

If the spec document cannot be found, or the branch cannot be created (e.g., it already exists), report the issue to the developer via `AskUserQuestion` and await guidance. Do not set `phase: "human_review"` — this is a pre-pipeline setup issue, not a pipeline escalation.
