# Architecture Phase

Invoke the technical-architect to analyze the spec and produce a chunked implementation plan.

## Entry

`state.json` shows `phase: "architecture"`.

## Execution

On entry to this phase, append the `## Architecture` section header per CONTRACTS.md §5.1 row 3 (idempotent — only on first entry). Subsequent log lines for this phase (escalation, resume, and success summary) are appended under this heading.

Invoke `technical-architect` via the `Agent` tool with a prompt that includes:
- The path to the spec document
- Instructions to produce an implementation plan at `.claude/pipeline/plans/<spec-slug>-plan.md` and a `chunks.json` at `.claude/pipeline/chunks.json`
- The chunking requirements: each chunk needs `id`, `title`, `dependencies`, `scope_boundary`, `shared_files`, `do_not_touch`, `implementation_instructions`, `validation_criteria`
- The pipeline mode instruction

After the architect completes, read its response. If the response indicates ambiguity or an issue requiring human input, escalate per `human-review.md` with the architect's concern as the reason.

If the architect succeeded, read `.claude/pipeline/chunks.json` and verify it has valid structure per CONTRACTS.md §2. The architect also writes `.claude/pipeline/plans/<spec-slug>-plan.md` per CONTRACTS.md §7 — this is a worker-owned artifact (the orchestrator does not parse it). The plan file is staged at the finalization commit (CONTRACTS.md §4.2).

## State Updates

After the architect `Agent` invocation completes:
- Update state.json: increment top-level `invocation_count`.
- If successful, update state.json:
  - set top-level `phase: "implementing"`
  - set top-level `total_chunks` to the value from chunks.json
  - set top-level `chunks` to an array with one entry per chunk from chunks.json. For each entry, set `id` from chunks.json, `status: "pending"`, `phase: "pending"`. All counter fields take their zero defaults defined by the chunk-entry schema in CONTRACTS.md Section 3.
- Append to the pipeline execution log:
  - If successful: the lines defined in CONTRACTS.md §5.2.1 (`Plan`) and §5.2.2 (`Chunks`).
  - If failed (architect flagged ambiguity): do not append a success summary. Escalation per `human-review.md` appends the §5.2.11 (`AWAITING INPUT`) and §5.2.12 (`RESUMED`) bullets under the `## Architecture` heading.

## Success → Per-Chunk Loop

`chunks.json` exists with valid structure. `state.json` shows `phase: "implementing"` with the chunks array populated. Proceed by reading `.claude/pipeline/phases/per-chunk.md`.

## Failure → Escalation

If the architect flags ambiguity: escalate per `human-review.md`. The developer can provide clarification (retry architecture) or abort the pipeline.
