# Per-Chunk Loop

Process each chunk sequentially through test generation, implementation, security review, and commit. This is the core of the pipeline.

## Entry

`state.json` shows `phase: "implementing"`. The `chunks` array is populated with entries from `chunks.json`.

**On resume:** Skip chunks with `status: "passed"` or `status: "failed"`. For the current in-progress chunk, read its `phase` value and enter at the corresponding sub-phase below — each chunk-phase value maps 1:1 to a sub-phase header (e.g., `"security_review"` → Security Review sub-phase; `"security_fix"` → Security Fix sub-phase, which re-invokes the `feature-implementer` fix, NOT the reviewer).

On loop entry (before chunk 1), append the `## Implementation` section header per CONTRACTS.md §5.1 row 4 (idempotent — only on first entry). All chunk H3 headings below are nested under this section.

For each chunk from 1 to `total_chunks`, execute the sub-phases below in order. On entry to a new chunk:
- Update state.json:
  - set top-level `current_chunk` to the chunk ID
  - set current chunk `status: "in_progress"`
  - set current chunk `phase: "test_generation"`
- Append the `### Chunk <id>: <title>` heading per CONTRACTS.md §5.1 row 5 (idempotent). Subsequent log lines for this chunk (from any sub-phase, including escalations) are appended under this heading.

---

## Sub-Phase: Test Generation

**Goal:** Generate failing TDD tests that define the success criteria for this chunk.

Chunk phase shows `"test_generation"`.

Invoke `test-suite-generator` via the `Agent` tool with a prompt that includes:
- The chunk's `title`, `validation_criteria`, `scope_boundary`, and `shared_files` (extracted from `chunks.json`)
- Instruction to write tests to the `tests/` directory mirroring the scope_boundary paths
- Instruction to run the tests and verify they ALL FAIL
- The pipeline mode instruction

After the `Agent` invocation completes, determine whether test generation succeeded (tests were written and all fail as expected).

- Update state.json: increment top-level `invocation_count`.
- If succeeded, update state.json:
  - set current chunk `tests` to the test count reported by test-suite-generator
  - set current chunk `phase: "implementation"`
- Append to the pipeline execution log:
  - If succeeded: the line defined in CONTRACTS.md §5.2.3 (`Tests Written`).
  - If failed (no tests written, compilation errors, or agent could not interpret validation criteria): do not append a success summary. Escalation per `human-review.md` appends the §5.2.11 (`AWAITING INPUT`) and §5.2.12 (`RESUMED`) bullets under the chunk heading.

**If failed:** escalate per `human-review.md`. The developer can provide guidance and retry test generation, or abort the pipeline. If retrying, re-invoke test-suite-generator with the developer's guidance as additional context.

---

## Sub-Phase: Implementation (max 3 iterations)

**Goal:** Make all tests pass with clean lint.

Chunk phase shows `"implementation"`.

Invoke `feature-implementer` via the `Agent` tool with a prompt that includes:
- The chunk's `implementation_instructions`, `scope_boundary`, and `shared_files` (extracted from `chunks.json`)
- The test file paths from test generation
- The current iteration number (1, 2, or 3) and max of 3
- If this is a retry: a summary of what failed in the previous attempt
- Instructions to run `ruff check` + `ruff format --check` on all modified Python files and fix any issues
- The pipeline mode instruction

After the `Agent` invocation completes, determine whether tests pass and lint is clean.

- Update state.json:
  - increment top-level `invocation_count`
  - increment current chunk `impl_iterations`
  - If tests pass + lint clean: set current chunk `phase: "security_review"`.
- Append to the pipeline execution log:
  - If tests pass + lint clean: the line defined in CONTRACTS.md §5.2.4 (`Implementer: COMPLETE`).
  - If tests fail or lint fails (any iteration, including the third): the line defined in CONTRACTS.md §5.2.5 (`Implementer: FAIL`).

**If tests pass + lint clean:** proceed to security review.

**If tests fail and `impl_iterations` < 3:** retry implementation with failure context from this attempt.

**If tests fail and `impl_iterations` >= 3:** escalate per `human-review.md`. Present the summary of failing tests and attempted approaches. The developer can provide guidance and retry (which resets `impl_iterations` to 0), or abort. If retrying, re-invoke with the developer's guidance as additional context.

---

## Sub-Phase: Security Review (max 3 iterations)

**Goal:** Pass the code-security-reviewer's quality gate.

Chunk phase shows `"security_review"`.

Invoke `code-security-reviewer` via the `Agent` tool with a prompt that includes:
- The files to review: chunk's `scope_boundary` + `shared_files`
- The `do_not_touch` boundaries (flag any modifications as violations)
- Context about which chunk and spec this is — include the `spec_slug` and the `chunk_id` so the reviewer can ground its findings
- The pipeline mode instruction

After the `Agent` invocation completes, determine PASS or FAIL from the reviewer's verdict.

- Append a section to `.claude/pipeline/reviews/<spec-slug>-review.md` per CONTRACTS.md §8: write the canonical section header (substituting `<id>` = current `chunk_id`, `<n>` = the post-update value of `state.json` → `chunks[id].sec_iterations`, `<VERDICT>` = the reviewer's overall verdict, `<ISO 8601 UTC timestamp>` = current UTC time), followed by the reviewer's findings as captured in its `Agent` response. Body format under the header is at the orchestrator's discretion (CONTRACTS.md §8) — verbatim copy is the simplest approach. Create `.claude/pipeline/reviews/` if missing. Append both PASS and FAIL outcomes. The orchestrator does not parse this file; it is staged at the finalization commit (CONTRACTS.md §4.2).

- Update state.json:
  - increment top-level `invocation_count`
  - increment current chunk `sec_iterations`
  - set current chunk `sec_issues` to the cumulative count of issues found by the reviewer across all iterations of this chunk
  - If FAIL and `sec_iterations` < 3: set current chunk `phase: "security_fix"`.
- Append to the pipeline execution log:
  - If PASS: the line defined in CONTRACTS.md §5.2.6 (`Security Review: PASS`).
  - If FAIL (any iteration, including the third): the line defined in CONTRACTS.md §5.2.7 (`Security Review: FAIL`).

**If PASS:** proceed to commit.

**If FAIL and `sec_iterations` < 3:** proceed to the Security Fix sub-phase below (the chunk `phase` was set to `"security_fix"` in the state update above).

**If FAIL and `sec_iterations` >= 3:** escalate per `human-review.md`. Present the unresolved security issues. The developer can: provide guidance and retry (which resets `sec_iterations` to 0), accept the risk and proceed to commit as-is, or abort the pipeline. If retrying, loop back to the security reviewer with the developer's guidance.

---

## Sub-Phase: Security Fix

**Goal:** Resolve the issues found by security review so the chunk can pass its quality gate.

Chunk phase shows `"security_fix"`.

Re-invoke `feature-implementer` via the `Agent` tool with the specific security issues (file paths, line numbers, descriptions) and instructions to fix them, re-run the full test suite to verify no regressions, and run lint checks. This is a targeted fix invocation — not a return to the Implementation sub-phase. Do not apply the Implementation sub-phase's iteration logic or update `impl_iterations`.

After the fix `Agent` invocation completes, determine whether the fix succeeded (tests pass and lint is clean).

- Update state.json:
  - increment top-level `invocation_count`
  - If fix succeeded: set current chunk `phase: "security_review"`.
- Append to the pipeline execution log:
  - If fix succeeded: the line defined in CONTRACTS.md §5.2.9 (`Implementer: FIX APPLIED`).
  - If fix failed (tests failing, lint errors, or agent reports failure): the line defined in CONTRACTS.md §5.2.10 (`Implementer: FIX FAILED`).

**If fix succeeded:** loop back to the Security Review sub-phase to re-invoke the security reviewer.

**If fix failed:** escalate per `human-review.md`. Present the original security issues, what the implementer attempted, and why it failed. The developer can: provide guidance and retry the fix (which does NOT reset `sec_iterations`), accept the risk and proceed to commit as-is, or abort the pipeline. If retrying, the chunk phase remains `"security_fix"`, so re-invoke the feature-implementer fix with the developer's guidance — do not return to the reviewer.

---

## Sub-Phase: Commit

**Goal:** Stage and commit the chunk's files.

Stage files using targeted `git add` (NEVER `git add -A` or `git add .`):
- Each file in the chunk's `scope_boundary` from `chunks.json`
- Each file in the chunk's `shared_files` from `chunks.json`
- The corresponding test files written during test generation

Commit with the structured message template from CONTRACTS.md Section 4.

Update state.json:
- set current chunk `status: "passed"`
- set current chunk `phase: "passed"`

---

## Loop Continuation

After committing a chunk, check if there are more chunks to process. If yes, advance to the next chunk and start from the test generation sub-phase. If all chunks are complete, update state.json: set top-level `phase: "integration_validation"`. Proceed by reading `.claude/pipeline/phases/integration.md`.
