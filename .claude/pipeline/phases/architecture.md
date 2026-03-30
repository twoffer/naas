# Architecture Phase

Invoke the technical-architect to analyze the spec and produce a chunked implementation plan.

## Entry

`state.json` shows `phase: "architecture"`.

## Execution

Invoke `technical-architect` via Task with a prompt that includes:
- The path to the spec document
- Instructions to produce an implementation plan at `.claude/pipeline/plans/<spec-slug>-plan.md` and a `chunks.json` at `.claude/pipeline/chunks.json`
- The chunking requirements: each chunk needs `id`, `title`, `dependencies`, `scope_boundary`, `shared_files`, `do_not_touch`, `implementation_instructions`, `validation_criteria`
- The pipeline mode instruction

After the architect completes, read its Task response. If the response indicates ambiguity or an issue requiring human input, escalate per `human-review.md` with the architect's concern as the reason.

If the architect succeeded, read `.claude/pipeline/chunks.json` and verify it has valid structure per CONTRACTS.md Section 2.

## State Updates

After the architect Task completes:
- Increment `invocation_count`
- If successful: set `phase: "implementing"`, `total_chunks` from chunks.json, populate the `chunks` array with `pending` entries (one per chunk, with `status: "pending"`, `phase: "pending"`, all counters at 0)
- Append to log: `## Architecture` heading, then `- Plan: <plan-summary>` and `- Chunks: <total-chunks>`

## Success → Per-Chunk Loop

`chunks.json` exists with valid structure. `state.json` shows `phase: "implementing"` with the chunks array populated. Proceed by reading `.claude/pipeline/phases/per-chunk.md`.

## Failure → Escalation

If the architect flags ambiguity: escalate per `human-review.md`. The developer can provide clarification (retry architecture) or abort the pipeline.
