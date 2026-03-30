# Scenario: All Failures

Every agent fails in every way possible. Human escalation at every step. Developer always provides guidance and continues. Exercises ALL 8 failure modes. Pipeline ultimately succeeds.

## Metadata

- **Description:** Validates human_review phase transitions, chunk phase retention during escalation, impl_iterations reset on guidance, sec_iterations reset on guidance (but NOT on security fix retry), accept-risk commit path, budget guard pause/resume, all escalation reason formats, and all resume decision formats.
- **Expected invocations:** 31 (see step sequence for per-step breakdown)
- **Expected final phase:** `complete`
- **Expected human escalations:** 10 (7 failure modes trigger at least once; FM4 and FM5 each trigger twice with different developer decisions; FM6 triggers twice; budget guard triggers once)

## Failure Modes Exercised

1. **(FM1)** Architecture ambiguity — Step 1
2. **(FM2)** Test generation failure — Step 4
3. **(FM3)** Implementation max iterations exceeded → escalate → guidance → succeed — Steps 6–9
4. **(FM5a)** Security fix failure (fix breaks tests) → escalate → guidance → retry fix → succeed — Steps 11–12
5. **(FM4a)** Security review max iterations exceeded → escalate → guidance → retry → succeed — Steps 17–21
6. **(FM5b)** Security fix failure (fix breaks tests) → escalate → accept risk — Steps 22–23
7. **(FM4b)** Security review max iterations exceeded → escalate → accept risk — Steps 27–31
8. **(FM6)** Integration validation failure → escalate → retry → succeed — Steps 32–34
9. **(FM7)** Budget guard threshold exceeded → pause → continue — Triggers when invocation_count > 30

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

---

### FAILURE MODE 1: Architecture Ambiguity

### Step 1: architecture — technical-architect — FAIL (ambiguity)

- **agent:** technical-architect
- **chunk:** —
- **outcome:** failure
- **details:**
  - ambiguity: "Conflicting stream names between spec sections 2.1 and 3.4"
- **state changes:**
  - invocation_count: 0 → 1
  - phase: "architecture" → "human_review"
- **log entry:**
  ```
  ## Architecture
  - ⏸ AWAITING INPUT: Architecture analysis flagged ambiguity — conflicting stream names in spec sections 2.1 and 3.4
  ```
- **escalation:**
  - reason: `Architecture analysis flagged ambiguity — conflicting stream names in spec sections 2.1 and 3.4`
  - developer options: (a) Provide clarification and retry, (b) Abort pipeline
  - **human response:** "Use the stream names from section 3.4, they are canonical"
  - **decision:** retry with guidance
- **resume state changes:**
  - phase: "human_review" → "architecture"
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 2: architecture retry — technical-architect — SUCCESS

- **agent:** technical-architect
- **chunk:** —
- **outcome:** success
- **details:**
  - plan_summary: "12-step implementation plan (using section 3.4 stream names)"
  - chunks_produced: 3
- **state changes:**
  - invocation_count: 1 → 2
  - phase: "architecture" → "implementing"
  - total_chunks: 0 → 3
  - chunks array populated with 3 pending entries
- **log entry:**
  ```
  - Plan: 12-step implementation plan (using section 3.4 stream names)
  - Chunks: 3
  ```

---

### CHUNK 1: Test gen failure (FM2) + Implementation max iterations (FM3) + Security fix failure → retry (FM5a)

### Step 3: chunk 1 entry

- **state changes:**
  - current_chunk: 0 → 1
  - chunk[1].status: "pending" → "in_progress"
  - chunk[1].phase: "pending" → "test_generation"

---

### FAILURE MODE 2: Test Generation Failure

### Step 4: test_generation — test-suite-generator (chunk 1) — FAIL

- **agent:** test-suite-generator
- **chunk:** 1
- **outcome:** failure
- **details:**
  - error: "Compilation errors in generated tests — unresolvable import for nonexistent module"
- **state changes:**
  - invocation_count: 2 → 3
  - phase: "implementing" → "human_review"
  - chunk[1].phase: "test_generation" (retained during escalation)
- **log entry:**
  ```
  ### Chunk 1: Service scaffold and stream setup
  - ⏸ AWAITING INPUT: Test generation failed — compilation errors in generated tests
  ```
- **escalation:**
  - reason: `Test generation failed — compilation errors in generated tests`
  - developer options: (a) Provide guidance and retry, (b) Abort pipeline
  - **human response:** "The module is services/sim-test/app/main.py, adjust imports accordingly"
  - **decision:** retry with guidance
- **resume state changes:**
  - phase: "human_review" → "implementing"
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 5: test_generation retry — test-suite-generator (chunk 1) — SUCCESS

- **agent:** test-suite-generator
- **chunk:** 1
- **outcome:** success
- **details:**
  - tests_written: 8
  - all_failing: true
- **state changes:**
  - invocation_count: 3 → 4
  - chunk[1].phase: "test_generation" → "implementation"
  - chunk[1].tests: 0 → 8
- **log entry:**
  ```
  - Tests Written: 8 tests (all failing)
  ```

---

### FAILURE MODE 3: Implementation Max Iterations Exceeded

### Step 6: implementation iteration 1 — feature-implementer (chunk 1) — FAIL

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - tests_passing: 3
  - tests_total: 8
  - iteration: 1
- **state changes:**
  - invocation_count: 4 → 5
  - chunk[1].impl_iterations: 0 → 1
- **log entry:**
  ```
  - Implementer: FAIL (iteration 1)
  ```

---

### Step 7: implementation iteration 2 — feature-implementer (chunk 1) — FAIL

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - tests_passing: 5
  - tests_total: 8
  - iteration: 2
- **state changes:**
  - invocation_count: 5 → 6
  - chunk[1].impl_iterations: 1 → 2
- **log entry:**
  ```
  - Implementer: FAIL (iteration 2)
  ```

---

### Step 8: implementation iteration 3 — feature-implementer (chunk 1) — FAIL → ESCALATE

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - tests_passing: 6
  - tests_total: 8
  - iteration: 3
- **state changes:**
  - invocation_count: 6 → 7
  - chunk[1].impl_iterations: 2 → 3
  - phase: "implementing" → "human_review"
  - chunk[1].phase: "implementation" (retained)
- **log entry:**
  ```
  - Implementer: FAIL (iteration 3)
  - ⏸ AWAITING INPUT: Implementation failed — 2 tests still failing after 3 iterations
  ```
- **escalation:**
  - reason: `Implementation failed — 2 tests still failing after 3 iterations`
  - developer options: (a) Provide guidance and retry (resets impl_iterations to 0), (b) Abort pipeline
  - **human response:** "The failing tests expect async generators — use async for pattern on the stream consumer"
  - **decision:** retry with guidance
- **resume state changes:**
  - phase: "human_review" → "implementing"
  - chunk[1].impl_iterations: 3 → 0 (RESET)
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 9: implementation post-guidance — feature-implementer (chunk 1) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** success
- **details:**
  - tests_passing: 8
  - tests_total: 8
  - lint_clean: true
  - iteration: 1 (post-reset)
- **state changes:**
  - invocation_count: 7 → 8
  - chunk[1].impl_iterations: 0 → 1
  - chunk[1].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (1 iteration, 8/8 tests passing)
  ```

---

### Step 10: security_review iteration 1 — code-security-reviewer (chunk 1) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 2
  - issue_summary: "Missing input validation on user_id, fail-safe not applied on enrichment error"
- **state changes:**
  - invocation_count: 8 → 9
  - chunk[1].sec_iterations: 0 → 1
  - chunk[1].sec_issues: 0 → 2
  - chunk[1].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — Missing input validation on user_id, fail-safe not applied on enrichment error
  ```

---

### FAILURE MODE 5a: Security Fix Failure → Retry With Guidance

### Step 11: security_fix — feature-implementer (chunk 1) — FIX FAIL (breaks tests)

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - fix_applied: false
  - tests_passing: 6
  - tests_total: 8
  - regression_free: false
  - failure_summary: "Input validation fix broke 2 existing tests — validator rejects previously valid test fixtures"
- **state changes:**
  - invocation_count: 9 → 10
  - phase: "implementing" → "human_review"
  - chunk[1].phase: "security_fix" (retained)
- **log entry:**
  ```
  - Implementer: FIX FAILED — Input validation fix broke 2 existing tests
  - ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: validator rejects previously valid test fixtures
  ```
- **escalation:**
  - reason: `Security fix failed — implementer could not resolve issues: validator rejects previously valid test fixtures`
  - developer options: (a) Provide guidance and retry fix (does NOT reset sec_iterations), (b) Accept risk and proceed to commit, (c) Abort pipeline
  - **human response:** "Update the test fixtures to include the required fields, then re-apply the validation fix"
  - **decision:** retry with guidance
- **resume state changes:**
  - phase: "human_review" → "implementing"
  - chunk[1].sec_iterations: 1 (NOT RESET — security fix retry per human-review.md)
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 12: security_fix retry — feature-implementer (chunk 1) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true
- **state changes:**
  - invocation_count: 10 → 11
  - chunk[1].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
  ```

---

### Step 13: security_review iteration 2 — code-security-reviewer (chunk 1) — PASS

- **agent:** code-security-reviewer
- **chunk:** 1
- **outcome:** success
- **details:**
  - verdict: "PASS"
  - issues_found: 0
- **state changes:**
  - invocation_count: 11 → 12
  - chunk[1].sec_iterations: 1 → 2
  - chunk[1].sec_issues: 2 (unchanged)
  - chunk[1].status: "in_progress" → "passed"
  - chunk[1].phase: "security_review" → "passed"
- **log entry:**
  ```
  - Security Review: PASS
  ```
- **note:** Chunk 1 committed (simulated).

---

### CHUNK 2: Security review max iterations → retry (FM4a) + Security fix failure → accept risk (FM5b)

### Step 14: chunk 2 entry

- **state changes:**
  - current_chunk: 1 → 2
  - chunk[2].status: "pending" → "in_progress"
  - chunk[2].phase: "pending" → "test_generation"

---

### Step 15: test_generation — test-suite-generator (chunk 2) — SUCCESS

- **agent:** test-suite-generator
- **chunk:** 2
- **outcome:** success
- **details:**
  - tests_written: 12
  - all_failing: true
- **state changes:**
  - invocation_count: 12 → 13
  - chunk[2].phase: "test_generation" → "implementation"
  - chunk[2].tests: 0 → 12
- **log entry:**
  ```
  ### Chunk 2: Core processing logic
  - Tests Written: 12 tests (all failing)
  ```

---

### Step 16: implementation — feature-implementer (chunk 2) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 2
- **outcome:** success
- **details:**
  - tests_passing: 12
  - tests_total: 12
  - lint_clean: true
  - iteration: 1
- **state changes:**
  - invocation_count: 13 → 14
  - chunk[2].impl_iterations: 0 → 1
  - chunk[2].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (1 iteration, 12/12 tests passing)
  ```

---

### FAILURE MODE 4a: Security Review Max Iterations → Escalate → Guidance → Retry

### Step 17: security_review iteration 1 — code-security-reviewer (chunk 2) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 2
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 2
  - issue_summary: "SQL injection in query builder, missing CORS restriction"
- **state changes:**
  - invocation_count: 14 → 15
  - chunk[2].sec_iterations: 0 → 1
  - chunk[2].sec_issues: 0 → 2
  - chunk[2].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — SQL injection in query builder, missing CORS restriction
  ```

---

### Step 18: security_fix — feature-implementer (chunk 2) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 2
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 12
  - tests_total: 12
  - regression_free: true
- **state changes:**
  - invocation_count: 15 → 16
  - chunk[2].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 12/12 tests still passing)
  ```

---

### Step 19: security_review iteration 2 — code-security-reviewer (chunk 2) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 2
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Residual SQL injection — parameterized query not applied to search endpoint"
- **state changes:**
  - invocation_count: 16 → 17
  - chunk[2].sec_iterations: 1 → 2
  - chunk[2].sec_issues: 2 → 3
  - chunk[2].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 2) — Residual SQL injection — parameterized query not applied to search endpoint
  ```

---

### Step 20: security_fix — feature-implementer (chunk 2) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 2
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 12
  - tests_total: 12
  - regression_free: true
- **state changes:**
  - invocation_count: 17 → 18
  - chunk[2].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 12/12 tests still passing)
  ```

---

### Step 21: security_review iteration 3 — code-security-reviewer (chunk 2) — FAIL → ESCALATE

- **agent:** code-security-reviewer
- **chunk:** 2
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Unsafe deserialization of Redis message payload"
- **state changes:**
  - invocation_count: 18 → 19
  - chunk[2].sec_iterations: 2 → 3
  - chunk[2].sec_issues: 3 → 4
  - phase: "implementing" → "human_review"
  - chunk[2].phase: "security_review" (retained)
- **log entry:**
  ```
  - Security Review: FAIL (iteration 3) — Unsafe deserialization of Redis message payload
  - ⏸ AWAITING INPUT: Security review failed — unresolved issues after 3 iterations
  ```
- **escalation:**
  - reason: `Security review failed — unresolved issues after 3 iterations`
  - developer options: (a) Provide guidance and retry (resets sec_iterations to 0), (b) Accept risk and proceed to commit, (c) Abort pipeline
  - **human response:** "Use json.loads() instead of pickle.loads() for the Redis payload deserialization"
  - **decision:** retry with guidance
- **resume state changes:**
  - phase: "human_review" → "implementing"
  - chunk[2].sec_iterations: 3 → 0 (RESET)
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### FAILURE MODE 5b: Security Fix Failure → Accept Risk

### Step 22: security_review post-guidance — code-security-reviewer (chunk 2) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 2
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Unsafe deserialization of Redis message payload persists after guidance"
- **state changes:**
  - invocation_count: 19 → 20
  - chunk[2].sec_iterations: 0 → 1
  - chunk[2].sec_issues: 4 → 5
  - chunk[2].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — Unsafe deserialization of Redis message payload persists after guidance
  ```

---

### Step 23: security_fix — feature-implementer (chunk 2) — FIX FAIL (breaks tests) → ACCEPT RISK

- **agent:** feature-implementer
- **chunk:** 2
- **outcome:** failure
- **details:**
  - fix_applied: false
  - tests_passing: 10
  - tests_total: 12
  - regression_free: false
  - failure_summary: "Switching to json.loads() broke 2 tests that depend on pickle-serialized complex objects"
- **state changes:**
  - invocation_count: 20 → 21
  - phase: "implementing" → "human_review"
  - chunk[2].phase: "security_fix" (retained)
- **log entry:**
  ```
  - Implementer: FIX FAILED — Switching to json.loads() broke 2 tests that depend on pickle-serialized complex objects
  - ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: json.loads() incompatible with existing test fixtures
  ```
- **escalation:**
  - reason: `Security fix failed — implementer could not resolve issues: json.loads() incompatible with existing test fixtures`
  - developer options: (a) Provide guidance and retry fix (does NOT reset sec_iterations), (b) Accept risk and proceed to commit, (c) Abort pipeline
  - **human response:** "Accept the risk — we'll address the deserialization in the next spec when we refactor the Redis layer"
  - **decision:** accept risk
- **resume state changes:**
  - phase: "human_review" → "implementing"
  - chunk[2].sec_iterations: 1 (NOT RESET — accept risk does not reset counters)
  - chunk[2].status: "in_progress" → "passed"
  - chunk[2].phase: "security_fix" → "passed"
- **resume log entries:**
  ```
  - ▶ RESUMED: Developer accepted risk, proceeding
  - Security Review: ACCEPTED BY DEVELOPER
  ```
- **note:** Chunk 2 committed (simulated) via accept-risk path on security fix failure. Key distinction from FM4b (chunk 3): this accept-risk triggers from a FAILED FIX, not from max security review iterations.

---

### CHUNK 3: Security review max iterations → accept risk (FM4b)

### Step 24: chunk 3 entry

- **state changes:**
  - current_chunk: 2 → 3
  - chunk[3].status: "pending" → "in_progress"
  - chunk[3].phase: "pending" → "test_generation"

---

### Step 25: test_generation — test-suite-generator (chunk 3) — SUCCESS

- **agent:** test-suite-generator
- **chunk:** 3
- **outcome:** success
- **details:**
  - tests_written: 10
  - all_failing: true
- **state changes:**
  - invocation_count: 21 → 22
  - chunk[3].phase: "test_generation" → "implementation"
  - chunk[3].tests: 0 → 10
- **log entry:**
  ```
  ### Chunk 3: Integration with upstream services
  - Tests Written: 10 tests (all failing)
  ```

---

### Step 26: implementation — feature-implementer (chunk 3) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** success
- **details:**
  - tests_passing: 10
  - tests_total: 10
  - lint_clean: true
  - iteration: 1
- **state changes:**
  - invocation_count: 22 → 23
  - chunk[3].impl_iterations: 0 → 1
  - chunk[3].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (1 iteration, 10/10 tests passing)
  ```

---

### FAILURE MODE 4b: Security Review Max Iterations → Accept Risk

### Step 27: security_review iteration 1 — code-security-reviewer (chunk 3) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 3
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 2
  - issue_summary: "Missing rate limiting on consumer endpoint, logging PII in debug mode"
- **state changes:**
  - invocation_count: 23 → 24
  - chunk[3].sec_iterations: 0 → 1
  - chunk[3].sec_issues: 0 → 2
  - chunk[3].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — Missing rate limiting on consumer endpoint, logging PII in debug mode
  ```

---

### Step 28: security_fix — feature-implementer (chunk 3) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true
- **state changes:**
  - invocation_count: 24 → 25
  - chunk[3].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
  ```

---

### Step 29: security_review iteration 2 — code-security-reviewer (chunk 3) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 3
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Rate limiting implemented but bypass via header injection possible"
- **state changes:**
  - invocation_count: 25 → 26
  - chunk[3].sec_iterations: 1 → 2
  - chunk[3].sec_issues: 2 → 3
  - chunk[3].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 2) — Rate limiting implemented but bypass via header injection possible
  ```

---

### Step 30: security_fix — feature-implementer (chunk 3) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true
- **state changes:**
  - invocation_count: 26 → 27
  - chunk[3].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
  ```

---

### Step 31: security_review iteration 3 — code-security-reviewer (chunk 3) — FAIL → ESCALATE

- **agent:** code-security-reviewer
- **chunk:** 3
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Edge case in rate limiter — concurrent requests can bypass window reset"
- **state changes:**
  - invocation_count: 27 → 28
  - chunk[3].sec_iterations: 2 → 3
  - chunk[3].sec_issues: 3 → 4
  - phase: "implementing" → "human_review"
  - chunk[3].phase: "security_review" (retained)
- **log entry:**
  ```
  - Security Review: FAIL (iteration 3) — Edge case in rate limiter — concurrent requests can bypass window reset
  - ⏸ AWAITING INPUT: Security review failed — unresolved issues after 3 iterations
  ```
- **escalation:**
  - reason: `Security review failed — unresolved issues after 3 iterations`
  - developer options: (a) Provide guidance and retry (resets sec_iterations to 0), (b) Accept risk and proceed to commit, (c) Abort pipeline
  - **human response:** "This is a simulation test service — the rate limiter edge case is acceptable"
  - **decision:** accept risk
- **resume state changes:**
  - phase: "human_review" → "implementing"
  - chunk[3].sec_iterations: 3 (NOT RESET — accept risk skips to commit)
  - chunk[3].status: "in_progress" → "passed"
  - chunk[3].phase: "security_review" → "passed"
- **resume log entries:**
  ```
  - ▶ RESUMED: Developer accepted risk, proceeding
  - Security Review: ACCEPTED BY DEVELOPER
  ```
- **note:** Chunk 3 committed (simulated) via accept-risk path. All chunks complete → phase transitions to integration_validation.

---

### FAILURE MODE 7: Budget Guard

**Note:** The budget guard triggers when `invocation_count` exceeds 30 after incrementing. At this point invocation_count is 28. The budget guard will trigger at invocation 31 during integration validation retries. The simulator should check the budget guard threshold after every invocation_count increment and insert the pause at the correct step.

If the budget guard triggers before the integration phase completes, insert the escalation inline:

- **budget guard check:**
  - invocation_count exceeds 30
  - phase: current phase (retained)
- **log entry:**
  ```
  - ⏸ AWAITING INPUT: Budget guard — invocation count reached <N>, threshold is 30
  ```
- **escalation:**
  - developer options: (a) Continue, (b) Stop
  - **human response:** "Continue"
  - **decision:** continue
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer approved continuation
  ```

---

### FAILURE MODE 6: Integration Validation Failure

### Step 32: integration_validation — integration-validator — FAIL

- **agent:** integration-validator
- **chunk:** —
- **outcome:** failure
- **details:**
  - verdict: "FAIL"
  - failures: "Service sim-test cannot connect to Redis — connection refused on redis:6379"
- **state changes:**
  - invocation_count: 28 → 29
  - phase: "implementing" → "integration_validation" (set before invocation)
  - phase: "integration_validation" → "human_review" (after failure)
- **log entry:**
  ```
  ## Integration Validation: FAIL
  - ⏸ AWAITING INPUT: Integration validation failed
  ```
- **escalation:**
  - reason: `Integration validation failed`
  - developer options: (a) Retry integration validation, (b) Abort pipeline
  - **human response:** "Redis container was restarting — retry now"
  - **decision:** retry
- **resume state changes:**
  - phase: "human_review" → "integration_validation"
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 33: integration_validation retry 1 — integration-validator — FAIL

- **agent:** integration-validator
- **chunk:** —
- **outcome:** failure
- **details:**
  - verdict: "FAIL"
  - failures: "Partial failure — OIDC flow works but SAML adapter returns 500"
- **state changes:**
  - invocation_count: 29 → 30
  - phase: "integration_validation" → "human_review"
- **log entry:**
  ```
  ## Integration Validation: FAIL
  - ⏸ AWAITING INPUT: Integration validation failed
  ```
- **escalation:**
  - **human response:** "SAML adapter needs config update — retry"
  - **decision:** retry
- **resume state changes:**
  - phase: "human_review" → "integration_validation"
- **resume log entry:**
  ```
  - ▶ RESUMED: Developer provided guidance, retrying
  ```

---

### Step 34: integration_validation retry 2 — integration-validator — invocation 31 triggers BUDGET GUARD, then PASS

- **agent:** integration-validator
- **chunk:** —
- **outcome:** success (but budget guard triggers first)
- **state changes:**
  - invocation_count: 30 → 31
- **budget guard triggers** (invocation_count > 30):
  - **log entry:**
    ```
    - ⏸ AWAITING INPUT: Budget guard — invocation count reached 31, threshold is 30
    ```
  - **escalation:**
    - developer options: (a) Continue, (b) Stop
    - **human response:** "Continue"
    - **decision:** continue
  - **resume log entry:**
    ```
    - ▶ RESUMED: Developer approved continuation
    ```
- **After budget guard resolved — integration result processed:**
  - verdict: "PASS"
  - phase: "integration_validation" → "post_pipeline"
- **log entry:**
  ```
  ## Integration Validation: PASS
  ```

---

### Step 35: post_pipeline (simulated)

- **agent:** — (orchestrator finalization)
- **chunk:** —
- **outcome:** success
- **details:**
  - pr_created: true (simulated — no real git push or PR)
- **state changes:**
  - phase: "post_pipeline" → "complete"
  - completed_at: set to simulation timestamp
- **log entry:**
  ```
  ## Completed: <iso-timestamp>
  ## Total Implementation Iterations: 3 (across all chunks)
  ## Total Security Issues Caught: 11
  ```

## Expected Final State

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

- **chunk[1].impl_iterations = 1**: Was 3 at escalation, reset to 0 by guidance, then succeeded on iteration 1 post-reset. Final value = 1.
- **chunk[1].sec_iterations = 2**: Started at 0, incremented to 1 at first review, NOT reset by security fix retry (per human-review.md), incremented to 2 at second review (PASS).
- **chunk[2].sec_iterations = 1**: Was 3 at FM4a escalation, reset to 0 by guidance, then incremented to 1 at post-guidance review (FAIL). NOT reset by FM5b accept-risk (accept risk does not reset counters). Final value = 1.
- **chunk[2].sec_issues = 5**: 2 from review iter 1 + 1 from review iter 2 + 1 from review iter 3 + 1 from post-guidance review = 5 cumulative.
- **chunk[3].sec_iterations = 3**: Reached 3 at escalation, NOT reset because developer chose accept-risk (not retry). Final value = 3.

## Validation Focus Points

1. **FM1 — Architecture ambiguity:** Phase goes architecture → human_review → architecture → implementing
2. **FM2 — Test gen failure:** Phase goes implementing → human_review (chunk phase "test_generation" retained) → implementing
3. **FM3 — Impl max iterations:** impl_iterations reaches 3, escalation, reset to 0 on guidance, succeeds post-reset
4. **FM4a — Sec review max iterations (retry):** sec_iterations reaches 3, escalation, reset to 0 on guidance, then continues into FM5b
5. **FM5b — Sec fix failure (accept risk):** Fix breaks tests → escalation → accept risk → chunk committed with "ACCEPTED BY DEVELOPER" log. sec_iterations NOT reset. Key contrast with FM5a (chunk 1) where developer chose retry.
6. **FM4b — Sec review max iterations (accept risk):** sec_iterations reaches 3, escalation, NOT reset, chunk committed with "ACCEPTED BY DEVELOPER" log. Key contrast with FM4a (chunk 2) where developer chose retry.
7. **FM5a — Security fix failure (retry):** Fix breaks tests → escalation → guidance → retry fix succeeds → sec_iterations NOT reset
8. **FM6 — Integration failure:** Multiple retries with escalation at each failure
9. **FM7 — Budget guard:** Triggers at invocation 31, pauses, developer approves continuation
10. **Counter reset asymmetry:** impl_iterations resets on guidance (FM3). sec_iterations resets on guidance at sec review escalation (FM4a), but does NOT reset on: security fix retry guidance (FM5a), security fix accept-risk (FM5b), or sec review accept-risk (FM4b).
11. **Accept-risk from two different escalation points:** FM5b triggers accept-risk from a failed security FIX, while FM4b triggers accept-risk from max security REVIEW iterations. Both produce the same log entries ("ACCEPTED BY DEVELOPER") but from different chunk phases (security_fix vs. security_review).
12. **Chunk phase retention:** During every human_review, chunk-level phase retains its pre-escalation value
