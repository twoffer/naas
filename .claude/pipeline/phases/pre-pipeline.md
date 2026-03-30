# Pre-Pipeline Phase

Set up the feature branch, pipeline state, and execution log before any worker agents are invoked.

## Entry

This is the first phase of a fresh pipeline run. No state.json exists yet.

## Execution

1. Parse the spec identifier from the developer's prompt. Derive the spec slug (e.g., "Spec 3: Enrichment and Evaluation" → `spec-3-enrichment`).
2. Locate the spec document in `docs/` or `docs/architecture/`.
3. Create the feature branch: `git checkout main && git pull origin main && git checkout -b feature/<spec-slug>`.
4. Create `.claude/pipeline/state.json` with initial values per CONTRACTS.md Section 3 — set `phase: "architecture"`, `current_chunk: 0`, `total_chunks: 0`, `invocation_count: 0`, `chunks: []`, `started_at` to the current ISO 8601 UTC timestamp.
5. Create `.claude/pipeline/logs/<spec-slug>.md` with the header: `# Pipeline Run: <spec-title>` and `# Started: <iso-timestamp>`.
6. Create `.claude/pipeline/plans/` directory if it does not exist.

## Success → Architecture Phase

All of the above artifacts exist. `state.json` shows `phase: "architecture"`. Proceed by reading `.claude/pipeline/phases/architecture.md`.

## Failure → Escalation

If the spec document cannot be found, or the branch cannot be created (e.g., it already exists), report the issue to the developer via `AskUserQuestion` and await guidance. Do not set `phase: "human_review"` — this is a pre-pipeline setup issue, not a pipeline escalation.
