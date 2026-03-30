# Scenario: Max Automatic Recovery

Agents fail up to but not exceeding iteration thresholds, maximizing automatic retries without triggering any human escalation. Tests every retry path that does NOT escalate.

## Metadata

- **Description:** Validates impl_iterations incrementing, sec_iterations incrementing, sec_issues accumulation, security fix → regression check → re-review loop, and log entries for FAIL/FIX APPLIED. No human escalation occurs.
- **Expected invocations:** 20 (see breakdown per step)
- **Expected final phase:** `complete`
- **Expected human escalations:** 0

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

### Step 1: architecture — technical-architect

- **agent:** technical-architect
- **chunk:** —
- **outcome:** success
- **details:**
  - plan_summary: "12-step implementation plan for sim-test service"
  - chunks_produced: 3
- **state changes:**
  - invocation_count: 0 → 1
  - phase: "architecture" → "implementing"
  - total_chunks: 0 → 3
  - chunks array populated with 3 pending entries
- **log entry:**
  ```
  ## Architecture
  - Plan: 12-step implementation plan for sim-test service
  - Chunks: 3
  ```

---

## Chunk 1: Maximum implementation retries + maximum security review retries

### Step 2: test_generation — test-suite-generator (chunk 1)

- **agent:** test-suite-generator
- **chunk:** 1
- **outcome:** success
- **details:**
  - tests_written: 8
  - all_failing: true
- **state changes:**
  - invocation_count: 1 → 2
  - current_chunk: 0 → 1
  - chunk[1].status: "pending" → "in_progress"
  - chunk[1].phase: "pending" → "test_generation" → "implementation"
  - chunk[1].tests: 0 → 8
- **log entry:**
  ```
  ### Chunk 1: Service scaffold and stream setup
  - Tests Written: 8 tests (all failing)
  ```

---

### Step 3: implementation iteration 1 — feature-implementer (chunk 1) — FAIL

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - tests_passing: 4
  - tests_total: 8
  - lint_clean: false
  - iteration: 1
- **state changes:**
  - invocation_count: 2 → 3
  - chunk[1].impl_iterations: 0 → 1
  - chunk[1].phase: "implementation" (unchanged — retry)
- **log entry:**
  ```
  - Implementer: FAIL (iteration 1)
  ```
- **note:** impl_iterations < 3, so automatic retry. No escalation.

---

### Step 4: implementation iteration 2 — feature-implementer (chunk 1) — FAIL

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - tests_passing: 6
  - tests_total: 8
  - lint_clean: true
  - iteration: 2
- **state changes:**
  - invocation_count: 3 → 4
  - chunk[1].impl_iterations: 1 → 2
  - chunk[1].phase: "implementation" (unchanged — retry)
- **log entry:**
  ```
  - Implementer: FAIL (iteration 2)
  ```
- **note:** impl_iterations < 3, one more try before escalation.

---

### Step 5: implementation iteration 3 — feature-implementer (chunk 1) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** success
- **details:**
  - tests_passing: 8
  - tests_total: 8
  - lint_clean: true
  - iteration: 3
- **state changes:**
  - invocation_count: 4 → 5
  - chunk[1].impl_iterations: 2 → 3
  - chunk[1].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (3 iterations, 8/8 tests passing)
  ```
- **note:** Passes on the last allowed attempt before escalation threshold.

---

### Step 6: security_review iteration 1 — code-security-reviewer (chunk 1) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 2
  - issue_summary: "SQL injection in query builder, missing input validation on user_id parameter"
- **state changes:**
  - invocation_count: 5 → 6
  - chunk[1].sec_iterations: 0 → 1
  - chunk[1].sec_issues: 0 → 2
  - chunk[1].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — SQL injection in query builder, missing input validation on user_id parameter
  ```
- **note:** sec_iterations < 3. Triggers security fix by feature-implementer.

---

### Step 7: security_fix — feature-implementer (chunk 1) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true
- **state changes:**
  - invocation_count: 6 → 7
  - chunk[1].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
  ```
- **note:** Fix succeeds without regression. Loop back to security review. impl_iterations NOT incremented (this is a security fix, not an implementation iteration).

---

### Step 8: security_review iteration 2 — code-security-reviewer (chunk 1) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 1
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Hardcoded secret in config initialization"
- **state changes:**
  - invocation_count: 7 → 8
  - chunk[1].sec_iterations: 1 → 2
  - chunk[1].sec_issues: 2 → 3
  - chunk[1].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 2) — Hardcoded secret in config initialization
  ```

---

### Step 9: security_fix — feature-implementer (chunk 1) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 1
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true
- **state changes:**
  - invocation_count: 8 → 9
  - chunk[1].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
  ```

---

### Step 10: security_review iteration 3 — code-security-reviewer (chunk 1) — PASS

- **agent:** code-security-reviewer
- **chunk:** 1
- **outcome:** success
- **details:**
  - verdict: "PASS"
  - issues_found: 0
- **state changes:**
  - invocation_count: 9 → 10
  - chunk[1].sec_iterations: 2 → 3
  - chunk[1].sec_issues: 3 (unchanged — 0 new issues)
  - chunk[1].status: "in_progress" → "passed"
  - chunk[1].phase: "security_review" → "passed"
- **log entry:**
  ```
  - Security Review: PASS
  ```
- **note:** Passes on the last allowed attempt. Chunk 1 committed (simulated). sec_issues=3 cumulative.

---

## Chunk 2: Clean pass (variety — not every chunk needs to fail)

### Step 11: test_generation — test-suite-generator (chunk 2)

- **agent:** test-suite-generator
- **chunk:** 2
- **outcome:** success
- **details:**
  - tests_written: 12
  - all_failing: true
- **state changes:**
  - invocation_count: 10 → 11
  - current_chunk: 1 → 2
  - chunk[2].status: "pending" → "in_progress"
  - chunk[2].phase: "pending" → "test_generation" → "implementation"
  - chunk[2].tests: 0 → 12
- **log entry:**
  ```
  ### Chunk 2: Core processing logic
  - Tests Written: 12 tests (all failing)
  ```

---

### Step 12: implementation — feature-implementer (chunk 2) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 2
- **outcome:** success
- **details:**
  - tests_passing: 12
  - tests_total: 12
  - lint_clean: true
  - iteration: 1
- **state changes:**
  - invocation_count: 11 → 12
  - chunk[2].impl_iterations: 0 → 1
  - chunk[2].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (1 iteration, 12/12 tests passing)
  ```

---

### Step 13: security_review — code-security-reviewer (chunk 2) — PASS

- **agent:** code-security-reviewer
- **chunk:** 2
- **outcome:** success
- **details:**
  - verdict: "PASS"
  - issues_found: 0
- **state changes:**
  - invocation_count: 12 → 13
  - chunk[2].sec_iterations: 0 → 1
  - chunk[2].sec_issues: 0 (unchanged)
  - chunk[2].status: "in_progress" → "passed"
  - chunk[2].phase: "security_review" → "passed"
- **log entry:**
  ```
  - Security Review: PASS
  ```
- **note:** Chunk 2 committed (simulated). Clean pass provides variety.

---

## Chunk 3: Moderate retries (implementation 2 attempts, security 2 iterations)

### Step 14: test_generation — test-suite-generator (chunk 3)

- **agent:** test-suite-generator
- **chunk:** 3
- **outcome:** success
- **details:**
  - tests_written: 10
  - all_failing: true
- **state changes:**
  - invocation_count: 13 → 14
  - current_chunk: 2 → 3
  - chunk[3].status: "pending" → "in_progress"
  - chunk[3].phase: "pending" → "test_generation" → "implementation"
  - chunk[3].tests: 0 → 10
- **log entry:**
  ```
  ### Chunk 3: Integration with upstream services
  - Tests Written: 10 tests (all failing)
  ```

---

### Step 15: implementation iteration 1 — feature-implementer (chunk 3) — FAIL

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** failure
- **details:**
  - tests_passing: 7
  - tests_total: 10
  - lint_clean: true
  - iteration: 1
- **state changes:**
  - invocation_count: 14 → 15
  - chunk[3].impl_iterations: 0 → 1
  - chunk[3].phase: "implementation" (unchanged)
- **log entry:**
  ```
  - Implementer: FAIL (iteration 1)
  ```

---

### Step 16: implementation iteration 2 — feature-implementer (chunk 3) — SUCCESS

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** success
- **details:**
  - tests_passing: 10
  - tests_total: 10
  - lint_clean: true
  - iteration: 2
- **state changes:**
  - invocation_count: 15 → 16
  - chunk[3].impl_iterations: 1 → 2
  - chunk[3].phase: "implementation" → "security_review"
- **log entry:**
  ```
  - Implementer: COMPLETE (2 iterations, 10/10 tests passing)
  ```

---

### Step 17: security_review iteration 1 — code-security-reviewer (chunk 3) — FAIL

- **agent:** code-security-reviewer
- **chunk:** 3
- **outcome:** failure
- **details:**
  - verdict: "NEEDS CHANGES"
  - issues_found: 1
  - issue_summary: "Unsanitized cache key derived from user input"
- **state changes:**
  - invocation_count: 16 → 17
  - chunk[3].sec_iterations: 0 → 1
  - chunk[3].sec_issues: 0 → 1
  - chunk[3].phase: "security_review" → "security_fix"
- **log entry:**
  ```
  - Security Review: FAIL (iteration 1) — Unsanitized cache key derived from user input
  ```

---

### Step 18: security_fix — feature-implementer (chunk 3) — FIX SUCCESS

- **agent:** feature-implementer
- **chunk:** 3
- **outcome:** success
- **details:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true
- **state changes:**
  - invocation_count: 17 → 18
  - chunk[3].phase: "security_fix" → "security_review"
- **log entry:**
  ```
  - Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
  ```

---

### Step 19: security_review iteration 2 — code-security-reviewer (chunk 3) — PASS

- **agent:** code-security-reviewer
- **chunk:** 3
- **outcome:** success
- **details:**
  - verdict: "PASS"
  - issues_found: 0
- **state changes:**
  - invocation_count: 18 → 19
  - chunk[3].sec_iterations: 1 → 2
  - chunk[3].sec_issues: 1 (unchanged)
  - chunk[3].status: "in_progress" → "passed"
  - chunk[3].phase: "security_review" → "passed"
- **log entry:**
  ```
  - Security Review: PASS
  ```
- **note:** Chunk 3 committed (simulated). All chunks complete → phase transitions to integration_validation.

---

### Step 20: integration_validation — integration-validator

- **agent:** integration-validator
- **chunk:** —
- **outcome:** success
- **details:**
  - verdict: "PASS"
- **state changes:**
  - invocation_count: 19 → 20
  - phase: "implementing" → "integration_validation" → "post_pipeline"
- **log entry:**
  ```
  ## Integration Validation: PASS
  ```

---

### Step 21: post_pipeline (simulated)

- **agent:** — (orchestrator finalization)
- **chunk:** —
- **outcome:** success
- **details:**
  - pr_created: true (simulated)
- **state changes:**
  - phase: "post_pipeline" → "complete"
  - completed_at: set to simulation timestamp
- **log entry:**
  ```
  ## Completed: <iso-timestamp>
  ## Total Implementation Iterations: 6 (across all chunks)
  ## Total Security Issues Caught: 4
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
  "invocation_count": 20,
  "chunks": [
    { "id": 1, "status": "passed", "phase": "passed", "tests": 8,  "impl_iterations": 3, "sec_iterations": 3, "sec_issues": 3 },
    { "id": 2, "status": "passed", "phase": "passed", "tests": 12, "impl_iterations": 1, "sec_iterations": 1, "sec_issues": 0 },
    { "id": 3, "status": "passed", "phase": "passed", "tests": 10, "impl_iterations": 2, "sec_iterations": 2, "sec_issues": 1 }
  ],
  "started_at": "<iso-timestamp>",
  "completed_at": "<iso-timestamp>"
}
```

## Validation Focus Points

1. **impl_iterations reaches 3 on chunk 1** — maximum before escalation, but succeeds on the threshold
2. **sec_iterations reaches 3 on chunk 1** — maximum security review cycles with fix passes
3. **sec_issues accumulates correctly** — 2 from iteration 1 + 1 from iteration 2 = 3 for chunk 1
4. **Security fix does NOT increment impl_iterations** — only the implementation sub-phase does
5. **Security fix transitions phase** — security_review → security_fix → security_review
6. **No human_review transitions** — phase never becomes "human_review" in any snapshot
7. **Chunk 2 is clean** — verifies the pipeline handles mixed failure/success across chunks
8. **invocation_count = 20** — each simulated agent call increments exactly once
