# Scenario: All Failures

Every agent fails in every way possible. Human escalation at every step. Developer always provides guidance and continues. Exercises ALL 8 failure modes. Pipeline ultimately succeeds.

## Metadata

- **Description:** Validates human_review phase transitions, chunk phase retention during escalation, impl_iterations reset on guidance, sec_iterations reset on guidance (but NOT on security fix retry), accept-risk commit path, budget guard pause/resume, all escalation reason formats, and all resume decision formats.
- **Expected invocations:** 31
- **Expected final phase:** `complete`
- **Expected human escalations:** 10 (7 failure modes trigger at least once; FM4 and FM5 each trigger twice with different developer decisions; FM6 triggers twice; budget guard triggers once)

## Failure Modes Exercised

1. **(FM1)** Architecture ambiguity — Step 1
2. **(FM2)** Test generation failure — Step 3
3. **(FM3)** Implementation max iterations exceeded → guidance → succeed — Steps 5–7
4. **(FM5a)** Security fix failure → guidance → retry fix → succeed — Step 10
5. **(FM4a)** Security review max iterations exceeded → guidance → continue — Step 19
6. **(FM5b)** Security fix failure → accept risk — Step 21
7. **(FM4b)** Security review max iterations exceeded → accept risk — Step 28
8. **(FM6)** Integration validation failure → retry → succeed — Steps 29–31
9. **(FM7)** Budget guard threshold reached → continue — Triggers on Step 30's increment (invocation_count reaches 30)

## Simulated Spec

- **spec:** "Spec 99: Simulation Test"
- **spec_slug:** "spec-99-simulation"
- **branch:** "feature/spec-99-simulation"

## Simulated Chunks

```json
{
  "contract_version": 2,
  "spec": "Spec 99: Simulation Test",
  "total_chunks": 3,
  "chunks": [
    {
      "id": 1,
      "title": "Service scaffold and stream setup",
      "dependencies": [],
      "scope_boundary": [
        "services/sim-test/Dockerfile",
        "services/sim-test/requirements.txt",
        "services/sim-test/app/__init__.py",
        "services/sim-test/app/main.py"
      ],
      "shared_files": ["docker-compose.yml"],
      "do_not_touch": ["services/event-ingestion/"],
      "implementation_instructions": "Scaffold the sim-test service with FastAPI skeleton, health endpoint, Dockerfile, and docker-compose entry.",
      "validation_criteria": "Health endpoint returns 200. Docker container starts and passes health check."
    },
    {
      "id": 2,
      "title": "Core processing logic",
      "dependencies": [1],
      "scope_boundary": [
        "services/sim-test/app/processor.py",
        "services/sim-test/app/models.py"
      ],
      "shared_files": ["docker-compose.yml"],
      "do_not_touch": ["services/event-ingestion/"],
      "implementation_instructions": "Implement the event processing pipeline with Pydantic models and async processing functions.",
      "validation_criteria": "Events are processed correctly. Error handling returns fail-safe defaults. Pydantic validation rejects malformed input."
    },
    {
      "id": 3,
      "title": "Integration with upstream services",
      "dependencies": [1, 2],
      "scope_boundary": [
        "services/sim-test/app/consumer.py",
        "services/sim-test/app/producer.py"
      ],
      "shared_files": ["docker-compose.yml"],
      "do_not_touch": ["services/event-ingestion/"],
      "implementation_instructions": "Connect to Redis Streams for upstream consumption and downstream production. Use XREADGROUP with consumer groups.",
      "validation_criteria": "End-to-end message flow works. Consumer reads from upstream stream, producer writes to downstream stream. Consumer group ACKs on success."
    }
  ]
}
```

## Step Sequence

### Step 1 (FM1): technical-architect — ambiguity flagged

- **agent:** technical-architect
- **chunk:** —
- **simulated_response:**
  - outcome: ambiguity_flagged
  - ambiguity_summary: "conflicting stream names in spec sections 2.1 and 3.4"
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "Use the stream names from section 3.4, they are canonical"

---

### Step 2: technical-architect retry — success

- **agent:** technical-architect
- **chunk:** —
- **simulated_response:**
  - outcome: success
  - plan_summary: "12-step implementation plan (using section 3.4 stream names)"
  - chunks_produced: 3

---

### Step 3 (FM2): test-suite-generator (chunk 1) — failure

- **agent:** test-suite-generator
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - failure_summary: "compilation errors in generated tests"
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "The module is services/sim-test/app/main.py, adjust imports accordingly"

---

### Step 4: test-suite-generator (chunk 1) retry — success

- **agent:** test-suite-generator
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_count: 8

---

### Step 5 (FM3 part 1): feature-implementer (chunk 1, implementation iteration 1)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - tests_passing: 3
  - tests_total: 8
  - lint_clean: false

---

### Step 6 (FM3 part 2): feature-implementer (chunk 1, implementation iteration 2)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - tests_passing: 5
  - tests_total: 8
  - lint_clean: true

---

### Step 7 (FM3 part 3): feature-implementer (chunk 1, implementation iteration 3) — escalates

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - tests_passing: 6
  - tests_total: 8
  - lint_clean: true
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "The failing tests expect async generators — use async for pattern on the stream consumer"

After resume, `chunk[1].impl_iterations` is reset to 0 per human-review.md.

---

### Step 8: feature-implementer (chunk 1, implementation post-guidance) — success

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_passing: 8
  - tests_total: 8
  - lint_clean: true

---

### Step 9: code-security-reviewer (chunk 1, iteration 1) — failure

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 2
  - issue_summary: "Missing input validation on user_id, fail-safe not applied on enrichment error"

---

### Step 10 (FM5a): feature-implementer (chunk 1, security_fix) — fix failure → guidance → retry

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - fix_applied: false
  - tests_passing: 6
  - tests_total: 8
  - regression_free: false
  - failure_summary: "validation fix broke 2 existing test fixtures"
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "Update the test fixtures to include the required fields, then re-apply the validation fix"

`chunk[1].sec_iterations` is NOT reset on security-fix retry per human-review.md.

---

### Step 11: feature-implementer (chunk 1, security_fix retry) — success

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true

---

### Step 12: code-security-reviewer (chunk 1, iteration 2) — pass

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: PASS

---

### Step 13: test-suite-generator (chunk 2)

- **agent:** test-suite-generator
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_count: 12

---

### Step 14: feature-implementer (chunk 2, implementation)

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_passing: 12
  - tests_total: 12
  - lint_clean: true

---

### Step 15: code-security-reviewer (chunk 2, iteration 1) — failure

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 2
  - issue_summary: "SQL injection in query builder, missing CORS restriction"

---

### Step 16: feature-implementer (chunk 2, security_fix) — success

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 12
  - tests_total: 12
  - regression_free: true

---

### Step 17: code-security-reviewer (chunk 2, iteration 2) — failure

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Residual SQL injection — parameterized query not applied to search endpoint"

---

### Step 18: feature-implementer (chunk 2, security_fix) — success

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 12
  - tests_total: 12
  - regression_free: true

---

### Step 19 (FM4a): code-security-reviewer (chunk 2, iteration 3) — escalates

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Unsafe deserialization of Redis message payload"
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "Use json.loads() instead of pickle.loads() for the Redis payload deserialization"

After resume, `chunk[2].sec_iterations` is reset to 0 per human-review.md (sec-review escalation, retry-with-guidance).

---

### Step 20: code-security-reviewer (chunk 2, post-guidance) — failure

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Unsafe deserialization of Redis message payload persists after guidance"

---

### Step 21 (FM5b): feature-implementer (chunk 2, security_fix) — fix failure → accept risk

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - fix_applied: false
  - tests_passing: 10
  - tests_total: 12
  - regression_free: false
  - failure_summary: "json.loads() incompatible with existing pickle-serialized test fixtures"
- **human_response:**
  - choice: accept-risk

After resume, chunk 2 is committed via accept-risk path. `chunk[2].sec_iterations` is NOT reset (accept-risk does not reset counters). Key contrast with FM5a (chunk 1) where developer chose retry-with-guidance.

---

### Step 22: test-suite-generator (chunk 3)

- **agent:** test-suite-generator
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_count: 10

---

### Step 23: feature-implementer (chunk 3, implementation)

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_passing: 10
  - tests_total: 10
  - lint_clean: true

---

### Step 24: code-security-reviewer (chunk 3, iteration 1) — failure

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 2
  - issue_summary: "Missing rate limiting on consumer endpoint, logging PII in debug mode"

---

### Step 25: feature-implementer (chunk 3, security_fix) — success

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true

---

### Step 26: code-security-reviewer (chunk 3, iteration 2) — failure

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Rate limiting implemented but bypass via header injection possible"

---

### Step 27: feature-implementer (chunk 3, security_fix) — success

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true

---

### Step 28 (FM4b): code-security-reviewer (chunk 3, iteration 3) — escalates → accept risk

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Edge case in rate limiter — concurrent requests can bypass window reset"
- **human_response:**
  - choice: accept-risk

After resume, chunk 3 is committed via accept-risk path. `chunk[3].sec_iterations` is NOT reset and stays at 3. Key contrast with FM4a (chunk 2) where developer chose retry-with-guidance.

---

### Step 29 (FM6 first run): integration-validator — failure

- **agent:** integration-validator
- **chunk:** —
- **simulated_response:**
  - verdict: FAIL
  - failure_summary: "Service sim-test cannot connect to Redis — connection refused on redis:6379"
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "Redis container was restarting — retry now"

---

### Step 30 (FM6 second run + FM7 budget guard): integration-validator retry — failure, budget guard fires

- **agent:** integration-validator
- **chunk:** —
- **simulated_response:**
  - verdict: FAIL
  - failure_summary: "Partial failure — OIDC flow works but SAML adapter returns 500"
- **budget_guard_response:**
  - choice: continue
- **human_response:**
  - choice: retry-with-guidance
  - guidance: "SAML adapter needs config update — retry"

This step's `invocation_count` increment (29 → 30) reaches the §5.3 Budget guard threshold. The simulator pauses for budget guard, resumes on the developer's continue choice, then processes the validator's FAIL verdict and pauses again for FM6 retry-with-guidance. The budget-guard ⏸/▶ pair and the FM6 ⏸/▶ pair are emitted in that order in `log.md`.

---

### Step 31 (FM6 third run): integration-validator retry — success

- **agent:** integration-validator
- **chunk:** —
- **simulated_response:**
  - verdict: PASS

The validator's PASS verdict is processed and `## Integration Validation: PASS` is emitted in `log.md`. No budget guard fire — `invocation_count` was already past the threshold on Step 30.

---

## Expected Final state.json

```json
{
  "contract_version": 2,
  "spec": "Spec 99: Simulation Test",
  "spec_slug": "spec-99-simulation",
  "branch": "feature/spec-99-simulation",
  "phase": "complete",
  "current_chunk": 3,
  "total_chunks": 3,
  "invocation_count": 31,
  "chunks": [
    { "id": 1, "status": "passed", "phase": "passed", "tests": 8,  "impl_iterations": 1, "sec_iterations": 2, "sec_issues": 2 },
    { "id": 2, "status": "passed", "phase": "passed", "tests": 12, "impl_iterations": 1, "sec_iterations": 1, "sec_issues": 5 },
    { "id": 3, "status": "passed", "phase": "passed", "tests": 10, "impl_iterations": 1, "sec_iterations": 3, "sec_issues": 4 }
  ],
  "started_at": "<iso-timestamp>",
  "completed_at": "<iso-timestamp>"
}
```

### Notes on Expected Final State

- **chunk[1].impl_iterations = 1**: Reached 3 at escalation in Step 7, reset to 0 by guidance, then succeeded on iteration 1 post-reset (Step 8).
- **chunk[1].sec_iterations = 2**: Started at 0, incremented to 1 at Step 9, NOT reset by Step 10 security fix retry (per human-review.md), incremented to 2 at Step 12 PASS.
- **chunk[2].sec_iterations = 1**: Reached 3 at Step 19 escalation, reset to 0 by guidance, incremented to 1 at Step 20 post-guidance review (FAIL). NOT reset by Step 21 FM5b accept-risk (accept-risk does not reset counters).
- **chunk[2].sec_issues = 5**: 2 (Step 15) + 1 (Step 17) + 1 (Step 19) + 1 (Step 20) = 5 cumulative.
- **chunk[3].sec_iterations = 3**: Reached 3 at Step 28 escalation, NOT reset because developer chose accept-risk (not retry).

## Expected Pipeline Execution Log

```markdown
# Pipeline Run: Spec 99: Simulation Test
# Started: <iso-timestamp>

## Architecture
- ⏸ AWAITING INPUT: Architecture analysis flagged ambiguity — conflicting stream names in spec sections 2.1 and 3.4
- ▶ RESUMED: Developer provided guidance, retrying
- Plan: 12-step implementation plan (using section 3.4 stream names)
- Chunks: 3

## Implementation

### Chunk 1: Service scaffold and stream setup
- ⏸ AWAITING INPUT: Test generation failed — compilation errors in generated tests
- ▶ RESUMED: Developer provided guidance, retrying
- Tests Written: 8 tests (all failing)
- Implementer: FAIL (iteration 1)
- Implementer: FAIL (iteration 2)
- Implementer: FAIL (iteration 3)
- ⏸ AWAITING INPUT: Implementation failed — 2 tests still failing after 3 iterations
- ▶ RESUMED: Developer provided guidance, retrying
- Implementer: COMPLETE (1 iteration, 8/8 tests passing)
- Security Review: FAIL (iteration 1) — Missing input validation on user_id, fail-safe not applied on enrichment error
- Implementer: FIX FAILED — validation fix broke 2 existing test fixtures
- ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: validation fix broke 2 existing test fixtures
- ▶ RESUMED: Developer provided guidance, retrying
- Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
- Security Review: PASS

### Chunk 2: Core processing logic
- Tests Written: 12 tests (all failing)
- Implementer: COMPLETE (1 iteration, 12/12 tests passing)
- Security Review: FAIL (iteration 1) — SQL injection in query builder, missing CORS restriction
- Implementer: FIX APPLIED (regression check: 12/12 tests still passing)
- Security Review: FAIL (iteration 2) — Residual SQL injection — parameterized query not applied to search endpoint
- Implementer: FIX APPLIED (regression check: 12/12 tests still passing)
- Security Review: FAIL (iteration 3) — Unsafe deserialization of Redis message payload
- ⏸ AWAITING INPUT: Security review failed — unresolved issues after 3 iterations
- ▶ RESUMED: Developer provided guidance, retrying
- Security Review: FAIL (iteration 1) — Unsafe deserialization of Redis message payload persists after guidance
- Implementer: FIX FAILED — json.loads() incompatible with existing pickle-serialized test fixtures
- ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: json.loads() incompatible with existing pickle-serialized test fixtures
- ▶ RESUMED: Developer accepted risk, proceeding
- Security Review: ACCEPTED BY DEVELOPER

### Chunk 3: Integration with upstream services
- Tests Written: 10 tests (all failing)
- Implementer: COMPLETE (1 iteration, 10/10 tests passing)
- Security Review: FAIL (iteration 1) — Missing rate limiting on consumer endpoint, logging PII in debug mode
- Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
- Security Review: FAIL (iteration 2) — Rate limiting implemented but bypass via header injection possible
- Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
- Security Review: FAIL (iteration 3) — Edge case in rate limiter — concurrent requests can bypass window reset
- ⏸ AWAITING INPUT: Security review failed — unresolved issues after 3 iterations
- ▶ RESUMED: Developer accepted risk, proceeding
- Security Review: ACCEPTED BY DEVELOPER

## Integration Validation: FAIL
- ⏸ AWAITING INPUT: Integration validation failed
- ▶ RESUMED: Developer provided guidance, retrying
## Integration Validation: FAIL
- ⏸ AWAITING INPUT: Integration validation failed
- ▶ RESUMED: Developer provided guidance, retrying
- ⏸ AWAITING INPUT: Budget guard — invocation count reached 31, threshold is 30
- ▶ RESUMED: Developer approved continuation
## Integration Validation: PASS
## Completed: <iso-timestamp>
## Total Implementation Iterations: 3 (across all chunks)
## Total Security Issues Caught: 11
```

## Expected Per-Spec Artifact Files

These are the per-spec artifact files mirroring CONTRACTS.md §§7–9. The simulator should verify file existence and section-header counts.

Two iteration-numbering subtleties show up in this scenario and the simulator should verify both:

- The review file's `<n>` is the chunk's `sec_iterations` value AFTER this invocation. When `sec_iterations` is reset to 0 on retry-with-guidance (per human-review.md), the next review's section header restarts at `Iteration 1` even though it is not the first review of that chunk. The append-only file preserves the chronological order, so the duplicate iteration number is unambiguous.
- A failed architect invocation that escalates due to ambiguity (Step 1 here) does NOT write the plan file. The plan file is written only by the successful architect invocation (Step 2).

### Files

- `plan.md` — written once by the technical-architect (Step 2 only — the failed Step 1 invocation does not write). Single PLAN block.
- `review.md` — appended by the orchestrator after every code-security-reviewer invocation (PASS and FAIL alike). Nine `## Chunk <id> — Iteration <n> — <VERDICT> — <iso-timestamp>` headers expected, in this order:
  - `## Chunk 1 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 9)
  - `## Chunk 1 — Iteration 2 — PASS — <iso>` (Step 12)
  - `## Chunk 2 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 15)
  - `## Chunk 2 — Iteration 2 — NEEDS CHANGES — <iso>` (Step 17)
  - `## Chunk 2 — Iteration 3 — NEEDS CHANGES — <iso>` (Step 19, escalation)
  - `## Chunk 2 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 20, post-guidance — sec_iterations was reset to 0 then incremented to 1)
  - `## Chunk 3 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 24)
  - `## Chunk 3 — Iteration 2 — NEEDS CHANGES — <iso>` (Step 26)
  - `## Chunk 3 — Iteration 3 — NEEDS CHANGES — <iso>` (Step 28, escalation → accept-risk)
- `integration-report.md` — appended by the orchestrator after every integration-validator invocation. Three `## Validation Run <n> — <VERDICT> — <iso-timestamp>` headers expected:
  - `## Validation Run 1 — FAIL — <iso>` (Step 29)
  - `## Validation Run 2 — FAIL — <iso>` (Step 30)
  - `## Validation Run 3 — PASS — <iso>` (Step 31)

## Validation Focus Points

1. **FM1 — Architecture ambiguity:** Phase goes architecture → human_review → architecture → implementing.
2. **FM2 — Test gen failure:** Phase goes implementing → human_review (chunk phase `test_generation` retained) → implementing.
3. **FM3 — Impl max iterations:** impl_iterations reaches 3, escalation, reset to 0 on guidance, succeeds post-reset.
4. **FM4a — Sec review max iterations (retry):** sec_iterations reaches 3, escalation, reset to 0 on guidance, then continues into FM5b.
5. **FM5b — Sec fix failure (accept risk):** Fix breaks tests → escalation → accept-risk → chunk committed with `Security Review: ACCEPTED BY DEVELOPER` log line. sec_iterations NOT reset. Key contrast with FM5a (chunk 1) where developer chose retry-with-guidance.
6. **FM4b — Sec review max iterations (accept risk):** sec_iterations reaches 3, escalation, NOT reset, chunk committed with `Security Review: ACCEPTED BY DEVELOPER` log line. Key contrast with FM4a (chunk 2) where developer chose retry-with-guidance.
7. **FM5a — Security fix failure (retry):** Fix breaks tests → escalation → guidance → retry fix succeeds → sec_iterations NOT reset.
8. **FM6 — Integration failure:** Multiple retries with escalation at each failure.
9. **FM7 — Budget guard:** Triggers on Step 31's increment to 31, pauses, developer approves continuation, then verdict is processed.
10. **Counter reset asymmetry:** impl_iterations resets on guidance (FM3). sec_iterations resets on guidance at sec-review escalation (FM4a), but does NOT reset on: security fix retry guidance (FM5a), security fix accept-risk (FM5b), or sec-review accept-risk (FM4b).
11. **Accept-risk from two different escalation points:** FM5b triggers accept-risk from a failed security fix, while FM4b triggers accept-risk from max security review iterations. Both produce the same `Security Review: ACCEPTED BY DEVELOPER` log line but from different chunk phases (`security_fix` vs. `security_review`).
12. **Chunk phase retention:** During every human_review pause, chunk-level phase retains its pre-escalation value.
