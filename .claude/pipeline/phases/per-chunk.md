# Per-Chunk Loop

Process each chunk sequentially through test generation, implementation, security review, and commit. This is the core of the pipeline.

## Entry

`state.json` shows `phase: "implementing"`. The `chunks` array is populated with entries from `chunks.json`.

**On resume:** Skip chunks with `status: "passed"` or `status: "failed"`. For the current in-progress chunk, read its `phase` value and enter at the corresponding sub-phase below (e.g., if chunk phase is `"security_review"`, skip directly to the Security Review sub-phase).

For each chunk from 1 to `total_chunks`, execute the sub-phases below in order. On entry to a new chunk, update `state.json`: set `current_chunk` to the chunk ID, set the chunk's `status: "in_progress"`, set the chunk's `phase: "test_generation"`.

---

## Sub-Phase: Test Generation

**Goal:** Generate failing TDD tests that define the success criteria for this chunk.

Chunk phase shows `"test_generation"`.

Invoke `test-suite-generator` via Task with a prompt that includes:
- The chunk's `title`, `validation_criteria`, `scope_boundary`, and `shared_files` (extracted from `chunks.json`)
- Instruction to write tests to the `tests/` directory mirroring the scope_boundary paths
- Instruction to run the tests and verify they ALL FAIL
- The pipeline mode instruction

After the Task completes, determine whether test generation succeeded (tests were written and all fail as expected). Increment `invocation_count`.

**If succeeded:** Record the test count in the chunk's `tests` field. Update chunk `phase: "implementation"`. Append to log: `### Chunk <id>: <title>` heading, then `- Tests Written: <n> tests (all failing)`.

**If failed** (no tests written, compilation errors, or agent could not interpret validation criteria): Escalate per `human-review.md`. The developer can provide guidance and retry test generation, or abort the pipeline. If retrying, re-invoke test-suite-generator with the developer's guidance as additional context.

---

## Sub-Phase: Implementation (max 3 iterations)

**Goal:** Make all tests pass with clean lint.

Chunk phase shows `"implementation"`.

Invoke `feature-implementer` via Task with a prompt that includes:
- The chunk's `implementation_instructions`, `scope_boundary`, and `shared_files` (extracted from `chunks.json`)
- The test file paths from test generation
- The current iteration number (1, 2, or 3) and max of 3
- If this is a retry: a summary of what failed in the previous attempt
- Instructions to run `ruff check` + `ruff format --check` on all modified Python files and fix any issues
- The pipeline mode instruction

After the Task completes, determine whether tests pass and lint is clean. Increment `invocation_count`. Increment the chunk's `impl_iterations`.

**If tests pass + lint clean:** Update chunk `phase: "security_review"`. Append to log: `- Implementer: COMPLETE (<n> iterations, <passing>/<total> tests passing)`. Proceed to security review.

**If tests fail and `impl_iterations` < 3:** Append to log: `- Implementer: FAIL (iteration <n>)`. Retry implementation with failure context from this attempt.

**If tests fail and `impl_iterations` >= 3:** Escalate per `human-review.md`. Present the summary of failing tests and attempted approaches. The developer can provide guidance and retry (which resets `impl_iterations` to 0), or abort. If retrying, re-invoke with the developer's guidance as additional context.

---

## Sub-Phase: Security Review (max 3 iterations)

**Goal:** Pass the code-security-reviewer's quality gate.

Chunk phase shows `"security_review"`.

Invoke `code-security-reviewer` via Task with a prompt that includes:
- The files to review: chunk's `scope_boundary` + `shared_files`
- The `do_not_touch` boundaries (flag any modifications as violations)
- Context about which chunk and spec this is
- The pipeline mode instruction

After the Task completes, determine PASS or FAIL from the reviewer's verdict. Increment `invocation_count`. Increment the chunk's `sec_iterations`. Update the chunk's `sec_issues` with the count of issues found by the reviewer (cumulative across iterations).

**If PASS:** Append to log: `- Security Review: PASS`. Proceed to commit.

**If FAIL and `sec_iterations` < 3:**
1. Append to log: `- Security Review: FAIL (iteration <n>) — <issue summary>`.
2. Update chunk `phase: "security_fix"`.
3. Re-invoke `feature-implementer` via Task with the specific security issues (file paths, line numbers, descriptions) and instructions to fix them, re-run the full test suite to verify no regressions, and run lint checks. This is a targeted fix invocation — not a return to the Implementation sub-phase. Do not apply the Implementation sub-phase's iteration logic or update `impl_iterations`.
4. After the fix Task completes, increment `invocation_count`. Determine whether the fix succeeded (tests pass and lint is clean).
5. **If fix succeeded:** Append to log: `- Implementer: FIX APPLIED (regression check: <passing>/<total> tests still passing)`. Update chunk `phase: "security_review"` and loop back to invoke the security reviewer again.
6. **If fix failed** (tests failing, lint errors, or agent reports failure): Append to log: `- Implementer: FIX FAILED — <failure summary>`. Escalate per `human-review.md`. Present the original security issues, what the implementer attempted, and why it failed.

**If FAIL and `sec_iterations` >= 3:** Escalate per `human-review.md`. Present the unresolved security issues. The developer can: provide guidance and retry (which resets `sec_iterations` to 0), accept the risk and proceed to commit as-is, or abort the pipeline. If retrying, loop back to the security reviewer with the developer's guidance.

---

## Sub-Phase: Commit

**Goal:** Stage and commit the chunk's files.

Stage files using targeted `git add` (NEVER `git add -A` or `git add .`):
- Each file in the chunk's `scope_boundary` from `chunks.json`
- Each file in the chunk's `shared_files` from `chunks.json`
- The corresponding test files written during test generation

Commit with the structured message template from CONTRACTS.md Section 4.

Update `state.json`: chunk `status: "passed"`, chunk `phase: "passed"`.

---

## Loop Continuation

After committing a chunk, check if there are more chunks to process. If yes, advance to the next chunk and start from the test generation sub-phase. If all chunks are complete, update `state.json`: `phase: "integration_validation"`. Proceed by reading `.claude/pipeline/phases/integration.md`.
