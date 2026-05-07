# Scenario: Max Automatic Recovery

Agents fail up to but not exceeding iteration thresholds, maximizing automatic retries without triggering any human escalation. Tests every retry path that does NOT escalate.

## Metadata

- **Description:** Validates impl_iterations incrementing, sec_iterations incrementing, sec_issues accumulation, security fix → regression check → re-review loop, and log entries for FAIL/FIX APPLIED. No human escalation occurs.
- **Expected invocations:** 20
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

### Step 1: technical-architect

- **agent:** technical-architect
- **chunk:** —
- **simulated_response:**
  - outcome: success
  - plan_summary: "12-step implementation plan for sim-test service"
  - chunks_produced: 3

---

## Chunk 1: Maximum implementation retries + maximum security review retries

### Step 2: test-suite-generator (chunk 1)

- **agent:** test-suite-generator
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_count: 8

---

### Step 3: feature-implementer (chunk 1, implementation iteration 1)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - tests_passing: 4
  - tests_total: 8
  - lint_clean: false

---

### Step 4: feature-implementer (chunk 1, implementation iteration 2)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: failure
  - tests_passing: 6
  - tests_total: 8
  - lint_clean: true

---

### Step 5: feature-implementer (chunk 1, implementation iteration 3)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_passing: 8
  - tests_total: 8
  - lint_clean: true

Passes on the last allowed attempt before the escalation threshold.

---

### Step 6: code-security-reviewer (chunk 1, iteration 1)

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 2
  - issue_summary: "SQL injection in query builder, missing input validation on user_id parameter"

---

### Step 7: feature-implementer (chunk 1, security_fix)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true

Loops back to security review. `impl_iterations` is NOT incremented (per per-chunk.md, only the implementation sub-phase increments it).

---

### Step 8: code-security-reviewer (chunk 1, iteration 2)

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Hardcoded secret in config initialization"

---

### Step 9: feature-implementer (chunk 1, security_fix)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 8
  - tests_total: 8
  - regression_free: true

---

### Step 10: code-security-reviewer (chunk 1, iteration 3)

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: PASS

Passes on the last allowed attempt. Cumulative `sec_issues` = 3.

---

## Chunk 2: Clean pass (variety — not every chunk needs to fail)

### Step 11: test-suite-generator (chunk 2)

- **agent:** test-suite-generator
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_count: 12

---

### Step 12: feature-implementer (chunk 2, implementation)

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_passing: 12
  - tests_total: 12
  - lint_clean: true

---

### Step 13: code-security-reviewer (chunk 2)

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: PASS

---

## Chunk 3: Moderate retries (implementation 2 attempts, security 2 iterations)

### Step 14: test-suite-generator (chunk 3)

- **agent:** test-suite-generator
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_count: 10

---

### Step 15: feature-implementer (chunk 3, implementation iteration 1)

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - outcome: failure
  - tests_passing: 7
  - tests_total: 10
  - lint_clean: true

---

### Step 16: feature-implementer (chunk 3, implementation iteration 2)

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_passing: 10
  - tests_total: 10
  - lint_clean: true

---

### Step 17: code-security-reviewer (chunk 3, iteration 1)

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: NEEDS CHANGES
  - new_sec_issues: 1
  - issue_summary: "Unsanitized cache key derived from user input"

---

### Step 18: feature-implementer (chunk 3, security_fix)

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - fix_applied: true
  - tests_passing: 10
  - tests_total: 10
  - regression_free: true

---

### Step 19: code-security-reviewer (chunk 3, iteration 2)

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: PASS

---

### Step 20: integration-validator

- **agent:** integration-validator
- **chunk:** —
- **simulated_response:**
  - verdict: PASS

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

## Expected Pipeline Execution Log

```markdown
# Pipeline Run: Spec 99: Simulation Test
# Started: <iso-timestamp>

## Architecture
- Plan: 12-step implementation plan for sim-test service
- Chunks: 3

## Implementation

### Chunk 1: Service scaffold and stream setup
- Tests Written: 8 tests (all failing)
- Implementer: FAIL (iteration 1)
- Implementer: FAIL (iteration 2)
- Implementer: COMPLETE (3 iterations, 8/8 tests passing)
- Security Review: FAIL (iteration 1) — SQL injection in query builder, missing input validation on user_id parameter
- Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
- Security Review: FAIL (iteration 2) — Hardcoded secret in config initialization
- Implementer: FIX APPLIED (regression check: 8/8 tests still passing)
- Security Review: PASS

### Chunk 2: Core processing logic
- Tests Written: 12 tests (all failing)
- Implementer: COMPLETE (1 iteration, 12/12 tests passing)
- Security Review: PASS

### Chunk 3: Integration with upstream services
- Tests Written: 10 tests (all failing)
- Implementer: FAIL (iteration 1)
- Implementer: COMPLETE (2 iterations, 10/10 tests passing)
- Security Review: FAIL (iteration 1) — Unsanitized cache key derived from user input
- Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
- Security Review: PASS

## Integration Validation: PASS
## Completed: <iso-timestamp>
## Total Implementation Iterations: 6 (across all chunks)
## Total Security Issues Caught: 4
```

## Expected Per-Spec Artifact Files

These are the per-spec artifact files mirroring CONTRACTS.md §§7–9. The simulator should verify file existence and section-header counts.

- `plan.md` — written once by the technical-architect (Step 1). Single PLAN block.
- `review.md` — appended by the orchestrator after every code-security-reviewer invocation. Six `## Chunk <id> — Iteration <n> — <VERDICT> — <iso-timestamp>` headers expected, in this order:
  - `## Chunk 1 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 6)
  - `## Chunk 1 — Iteration 2 — NEEDS CHANGES — <iso>` (Step 8)
  - `## Chunk 1 — Iteration 3 — PASS — <iso>` (Step 10)
  - `## Chunk 2 — Iteration 1 — PASS — <iso>` (Step 13)
  - `## Chunk 3 — Iteration 1 — NEEDS CHANGES — <iso>` (Step 17)
  - `## Chunk 3 — Iteration 2 — PASS — <iso>` (Step 19)
- `integration-report.md` — appended by the orchestrator after every integration-validator invocation. One `## Validation Run <n> — <VERDICT> — <iso-timestamp>` header expected:
  - `## Validation Run 1 — PASS — <iso>` (Step 20)

## Validation Focus Points

1. **impl_iterations reaches 3 on chunk 1** — maximum before escalation, but succeeds on the threshold.
2. **sec_iterations reaches 3 on chunk 1** — maximum security review cycles with fix passes.
3. **sec_issues accumulates correctly** — 2 from iteration 1 + 1 from iteration 2 = 3 for chunk 1.
4. **Security fix does NOT increment impl_iterations** — only the implementation sub-phase does.
5. **Security fix transitions phase** — security_review → security_fix → security_review.
6. **No human_review transitions** — phase never becomes `human_review` in any snapshot.
7. **Chunk 2 is clean** — verifies the pipeline handles mixed failure/success across chunks.
8. **invocation_count = 20** — each simulated agent call increments exactly once.
