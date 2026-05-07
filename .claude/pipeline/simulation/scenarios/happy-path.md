# Scenario: Happy Path

Every agent succeeds on first attempt across all 3 chunks. No escalations, no retries.

## Metadata

- **Description:** Validates basic phase progression, chunk sequencing, log formatting, and invocation counting. The simplest possible pipeline run.
- **Expected invocations:** 11 (1 architect + 3×3 chunk agents + 1 integration)
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
      "shared_files": [
        "docker-compose.yml"
      ],
      "do_not_touch": [
        "services/event-ingestion/"
      ],
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
      "shared_files": [
        "docker-compose.yml"
      ],
      "do_not_touch": [
        "services/event-ingestion/"
      ],
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
      "shared_files": [
        "docker-compose.yml"
      ],
      "do_not_touch": [
        "services/event-ingestion/"
      ],
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

### Step 2: test-suite-generator (chunk 1)

- **agent:** test-suite-generator
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_count: 8

---

### Step 3: feature-implementer (chunk 1, implementation)

- **agent:** feature-implementer
- **chunk:** 1
- **simulated_response:**
  - outcome: success
  - tests_passing: 8
  - tests_total: 8
  - lint_clean: true

---

### Step 4: code-security-reviewer (chunk 1)

- **agent:** code-security-reviewer
- **chunk:** 1
- **simulated_response:**
  - verdict: PASS

---

### Step 5: test-suite-generator (chunk 2)

- **agent:** test-suite-generator
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_count: 12

---

### Step 6: feature-implementer (chunk 2, implementation)

- **agent:** feature-implementer
- **chunk:** 2
- **simulated_response:**
  - outcome: success
  - tests_passing: 12
  - tests_total: 12
  - lint_clean: true

---

### Step 7: code-security-reviewer (chunk 2)

- **agent:** code-security-reviewer
- **chunk:** 2
- **simulated_response:**
  - verdict: PASS

---

### Step 8: test-suite-generator (chunk 3)

- **agent:** test-suite-generator
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_count: 10

---

### Step 9: feature-implementer (chunk 3, implementation)

- **agent:** feature-implementer
- **chunk:** 3
- **simulated_response:**
  - outcome: success
  - tests_passing: 10
  - tests_total: 10
  - lint_clean: true

---

### Step 10: code-security-reviewer (chunk 3)

- **agent:** code-security-reviewer
- **chunk:** 3
- **simulated_response:**
  - verdict: PASS

---

### Step 11: integration-validator

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
  "invocation_count": 11,
  "chunks": [
    { "id": 1, "status": "passed", "phase": "passed", "tests": 8,  "impl_iterations": 1, "sec_iterations": 1, "sec_issues": 0 },
    { "id": 2, "status": "passed", "phase": "passed", "tests": 12, "impl_iterations": 1, "sec_iterations": 1, "sec_issues": 0 },
    { "id": 3, "status": "passed", "phase": "passed", "tests": 10, "impl_iterations": 1, "sec_iterations": 1, "sec_issues": 0 }
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
- Implementer: COMPLETE (1 iteration, 8/8 tests passing)
- Security Review: PASS

### Chunk 2: Core processing logic
- Tests Written: 12 tests (all failing)
- Implementer: COMPLETE (1 iteration, 12/12 tests passing)
- Security Review: PASS

### Chunk 3: Integration with upstream services
- Tests Written: 10 tests (all failing)
- Implementer: COMPLETE (1 iteration, 10/10 tests passing)
- Security Review: PASS

## Integration Validation: PASS
## Completed: <iso-timestamp>
## Total Implementation Iterations: 3 (across all chunks)
## Total Security Issues Caught: 0
```

## Expected Per-Spec Artifact Files

These are the per-spec artifact files mirroring CONTRACTS.md §§7–9. The simulator should verify file existence and section-header counts.

- `plan.md` — written once by the technical-architect (Step 1). Single PLAN block, no section headers required by the contract.
- `review.md` — appended by the orchestrator after every code-security-reviewer invocation. Three `## Chunk <id> — Iteration <n> — <VERDICT> — <iso-timestamp>` headers expected, in this order:
  - `## Chunk 1 — Iteration 1 — PASS — <iso>` (Step 4)
  - `## Chunk 2 — Iteration 1 — PASS — <iso>` (Step 7)
  - `## Chunk 3 — Iteration 1 — PASS — <iso>` (Step 10)
- `integration-report.md` — appended by the orchestrator after every integration-validator invocation. One `## Validation Run <n> — <VERDICT> — <iso-timestamp>` header expected:
  - `## Validation Run 1 — PASS — <iso>` (Step 11)

## Validation Focus Points

1. **invocation_count = 11** — every agent call increments exactly once; post-pipeline finalization does not increment.
2. **No human_review transitions** — top-level phase never becomes `human_review` in any snapshot.
3. **No retries** — every chunk's `impl_iterations` and `sec_iterations` end at 1.
4. **`## Implementation` H2 written exactly once** — at chunk 1's test-generation entry, not repeated for chunks 2 or 3.
