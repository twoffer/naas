# Pipeline Communication Contracts

**Version:** 3
**Last updated:** 2026-05-04

This file defines the data formats used for inter-agent communication in the NAAS agentic pipeline. It is the single source of truth — orchestrator and worker prompts reference this file rather than inlining format definitions.

**Scope:** Data formats only. For pipeline architecture, implementation guidance, and design rationale, see `docs/Agentic_Workflow_Implementation_Guide.md`.

**Ownership model:** The `pipeline-orchestrator` skill (running in the main Claude Code session) is the sole writer of `state.json`, the pipeline execution log, and the per-spec quality report. Worker subagents communicate results through their `Agent` tool responses and artifact files — they never read or write pipeline state files.

---

## 1. PIPELINE_OUTPUT (Documentation Convention)

Optional structured block at the end of an agent's response. Retained for **human readability** when reviewing agent transcripts. Not parsed by any automated system — the pipeline-orchestrator reads worker results from Task responses and artifact files, not from this block.

### Format

```
## PIPELINE_OUTPUT
- status: COMPLETE | NEEDS_REVIEW | FAILED
- artifact: <path to primary output file>
- summary: <one-line description of what was done>
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `status` | enum | Yes | `COMPLETE` — task finished successfully. `NEEDS_REVIEW` — task finished but agent flagged an issue requiring human input. `FAILED` — quality gate not met or error encountered. |
| `artifact` | string | No | Relative path from project root to the primary file produced. Omit if the agent does not produce a discrete file. |
| `summary` | string | Yes | Single line, no line breaks. Concise enough for commit logs and PR descriptions. |

### Usage Notes

1. This block is **optional**. The pipeline functions correctly without it.
2. Workers may include it at the end of their responses as a readable summary.
3. No automated system parses this block. The `pipeline-orchestrator` determines next steps by reading `state.json` and worker Task responses directly.
4. The `next_agent` and `context_for_next` fields from Contract Version 1 have been removed — routing decisions are made exclusively by the orchestrator's state machine.

---

## 2. chunks.json

Machine-readable decomposition of an implementation plan into ordered, independently-verifiable chunks.

**Location:** `.claude/pipeline/chunks.json`
**Producer:** technical-architect
**Consumer:** pipeline-orchestrator (extracts chunk data, passes to workers via Task prompts)

Workers do not read this file directly. The orchestrator extracts the relevant chunk's fields and includes them in each worker's Task prompt.

### Schema

```jsonc
{
  "contract_version": 2,
  "spec": "Spec 3: Enrichment and Evaluation",   // Full spec title
  "total_chunks": 3,                               // Must equal chunks array length
  "chunks": [
    {
      "id": 1,                                     // 1-based sequential integer
      "title": "Service scaffold and stream setup", // Short title for commits
      "dependencies": [],                           // Chunk IDs that must complete first
      "scope_boundary": [                           // Primary files this chunk owns
        "services/signal-enrichment/Dockerfile",
        "services/signal-enrichment/requirements.txt",
        "services/signal-enrichment/app/__init__.py",
        "services/signal-enrichment/app/main.py",
        "services/signal-enrichment/app/consumer.py"
      ],
      "shared_files": [                             // Files also modified by other chunks
        "docker-compose.yml"
      ],
      "do_not_touch": [                             // Hard boundary — security reviewer enforces
        "services/event-ingestion/",
        "services/risk-evaluator/"
      ],
      "implementation_instructions": "...",         // Detailed build instructions
      "validation_criteria": "..."                  // Test-suite-generator writes tests from this
    }
  ]
}
```

### Field Definitions

**Top-level:**

| Field | Type | Description |
|-------|------|-------------|
| `contract_version` | integer | Schema version. Currently `2`. |
| `spec` | string | Full spec title (e.g., "Spec 3: Enrichment and Evaluation"). |
| `total_chunks` | integer | Count of elements in `chunks` array. |
| `chunks` | array | Ordered list of chunk objects. |

**Per-chunk:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | 1-based sequential identifier. Must match array position + 1. |
| `title` | string | Short descriptive title. Used in commit messages and logs. |
| `dependencies` | integer[] | IDs of chunks that must complete first. Empty array if none. |
| `scope_boundary` | string[] | Primary files this chunk creates or modifies. Non-overlapping across chunks. Paths are relative to project root. |
| `shared_files` | string[] | Files also modified by other chunks (e.g., `docker-compose.yml`, `__init__.py` re-exports). Overlap is allowed. Each chunk's `implementation_instructions` must specify exactly which section it modifies. |
| `do_not_touch` | string[] | File or directory paths this chunk must NOT modify. Trailing `/` indicates directory. |
| `implementation_instructions` | string | What to build. Detailed enough for the feature-implementer to work without re-reading the spec. References spec sections where applicable. |
| `validation_criteria` | string | What success looks like. The test-suite-generator uses this to write failing tests before implementation begins. Must be testable without the implementation existing. |

### Constraints

1. Chunk IDs are 1-based, sequential, with no gaps.
2. `dependencies` may only reference IDs lower than the current chunk's ID (no forward references, no cycles).
3. `scope_boundary` arrays must not overlap across chunks — no two chunks own the same primary file.
4. `shared_files` may overlap across chunks. The security reviewer verifies that each chunk only modifies the sections specified in its `implementation_instructions`.
5. `do_not_touch` is a hard boundary. The code-security-reviewer flags any modification to a `do_not_touch` path as a review failure.
6. `total_chunks` must equal the length of `chunks`.
7. First chunk should scaffold infrastructure (directory structure, Dockerfile, docker-compose entry, FastAPI skeleton).
8. Last chunk should be integration-facing (connects to upstream/downstream services).

---

## 3. state.json

Pipeline execution state. Tracks progress, iterations, and quality gate results. Provides resume capability after pipeline interruptions.

**Location:** `.claude/pipeline/state.json`
**Sole writer:** pipeline-orchestrator (initializes during pre-pipeline, updates after every Task completion)
**Read by:** pipeline-orchestrator (for resume, post-pipeline PR generation), developer (human visibility into pipeline progress)

Workers never read or write this file. The orchestrator extracts data from worker Task responses and artifact files, then updates state.json itself.

### Schema

```jsonc
{
  "contract_version": 2,
  "spec": "Spec 3: Enrichment and Evaluation",     // Full spec title
  "spec_slug": "spec-3-enrichment",                 // URL/branch-safe identifier
  "branch": "feature/spec-3-enrichment",            // Git branch name
  "phase": "implementing",                          // Current pipeline phase
  "current_chunk": 2,                               // Chunk being processed (0 = not started)
  "total_chunks": 5,                                // From chunks.json (0 until architecture completes)
  "invocation_count": 8,                            // Total Task invocations for budget tracking
  "chunks": [ /* ... */ ],                          // Per-chunk status records
  "started_at": "2026-03-17T10:00:00Z",             // ISO 8601 UTC
  "completed_at": null                              // ISO 8601 UTC, null until done
}
```

### Chunk Entry Schema

Each element in `chunks`:

```jsonc
{
  "id": 2,
  "status": "in_progress",           // pending | in_progress | passed | failed
  "phase": "security_review",        // Current phase within this chunk
  "tests": 12,                       // Total tests generated
  "impl_iterations": 2,              // Times the feature-implementer ran
  "sec_iterations": 1,               // Times the code-security-reviewer ran
  "sec_issues": 2                    // Total security issues found across iterations
}
```

### Field Definitions

**Top-level:**

| Field | Type | Description |
|-------|------|-------------|
| `contract_version` | integer | Schema version. Currently `2`. |
| `spec` | string | Full spec title. |
| `spec_slug` | string | Derived slug for branch names and file paths. |
| `branch` | string | Feature branch name (`feature/<spec_slug>`). |
| `phase` | string | Current pipeline phase. See Phase Values below. |
| `current_chunk` | integer | ID of chunk being processed. `0` = not yet in per-chunk loop. |
| `total_chunks` | integer | Total chunks from `chunks.json`. `0` until architecture completes. |
| `invocation_count` | integer | Count of Task invocations. Orchestrator increments after each worker Task. Used for budget monitoring. |
| `chunks` | array | Per-chunk status records. Empty until per-chunk loop starts. |
| `started_at` | string | ISO 8601 UTC timestamp of pipeline start. |
| `completed_at` | string \| null | ISO 8601 UTC timestamp of pipeline completion. `null` until done. |

**Chunk entry:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Matches chunk ID from `chunks.json`. |
| `status` | string | `pending` (not started), `in_progress`, `passed` (committed), `failed` (escalated). |
| `phase` | string | Current phase within this chunk's lifecycle. See Phase Values. |
| `tests` | integer | Total tests generated by test-suite-generator. `0` until test generation. |
| `impl_iterations` | integer | Times the feature-implementer ran during the **implementation** sub-phase (making tests pass). Not incremented during security fix passes. Reset to 0 if the developer provides guidance and retries after max iterations. |
| `sec_iterations` | integer | Times the code-security-reviewer ran for this chunk. Each security review + implementer fix cycle counts as one iteration. Reset to 0 if the developer provides guidance and retries after max iterations. |
| `sec_issues` | integer | Total security issues found across all review iterations for this chunk. |

### Phase Values

**Top-level `phase`:**

| Value | Description |
|-------|-------------|
| `starting` | Orchestrator initialized state, about to invoke architect. |
| `architecture` | Technical architect is analyzing the spec and producing chunks.json. |
| `implementing` | Per-chunk loop is active. |
| `integration_validation` | Integration validator is running. |
| `post_pipeline` | Orchestrator is pushing branch and creating PR. |
| `complete` | Pipeline finished successfully. |
| `human_review` | Pipeline paused — waiting for developer input via `AskUserQuestion`. |
| `failed` | Pipeline aborted by developer after HUMAN_REVIEW. |

**Chunk-level `phase`:**

| Value | Description |
|-------|-------------|
| `pending` | Chunk not yet started. |
| `test_generation` | Test-suite-generator is writing failing tests. |
| `implementation` | Feature-implementer is making tests pass. |
| `security_review` | Code-security-reviewer is reviewing. |
| `security_fix` | Feature-implementer is fixing issues found by security review. |
| `passed` | Chunk passed all gates and was committed. |
| `failed` | Chunk aborted by developer after escalation. |

Note: When the pipeline pauses for human review, the top-level `phase` is set to `"human_review"` while the chunk-level `phase` retains its current value (e.g., `"implementation"`, `"security_review"`). This allows the orchestrator to determine exactly where to resume after the developer responds.

### Example (Mid-Pipeline)

```json
{
  "contract_version": 2,
  "spec": "Spec 3: Enrichment and Evaluation",
  "spec_slug": "spec-3-enrichment",
  "branch": "feature/spec-3-enrichment",
  "phase": "implementing",
  "current_chunk": 2,
  "total_chunks": 3,
  "invocation_count": 8,
  "chunks": [
    {
      "id": 1,
      "status": "passed",
      "phase": "passed",
      "tests": 8,
      "impl_iterations": 1,
      "sec_iterations": 1,
      "sec_issues": 0
    },
    {
      "id": 2,
      "status": "in_progress",
      "phase": "security_review",
      "tests": 12,
      "impl_iterations": 2,
      "sec_iterations": 1,
      "sec_issues": 2
    },
    {
      "id": 3,
      "status": "pending",
      "phase": "pending",
      "tests": 0,
      "impl_iterations": 0,
      "sec_iterations": 0,
      "sec_issues": 0
    }
  ],
  "started_at": "2026-03-17T10:00:00Z",
  "completed_at": null
}
```

---

## 4. Commit Message

Structured git commit produced by the `pipeline-orchestrator` after a chunk passes the security review gate.

### Template

```
feat(<spec-slug>/chunk-<chunk-id>): <chunk-title>

Tests: <tests> written, all passing
Implementation iterations: <impl-iterations>
Security review iterations: <sec-iterations>
Security issues caught: <sec-issues>

Pipeline: auto-committed by agentic pipeline
```

### Field Sources

| Field | Source |
|-------|--------|
| `spec-slug` | `state.json` → `spec_slug` |
| `chunk-id` | `state.json` → `current_chunk` |
| `chunk-title` | `chunks.json` → `chunks[id].title` |
| `tests` | `state.json` → `chunks[id].tests` |
| `impl-iterations` | `state.json` → `chunks[id].impl_iterations` |
| `sec-iterations` | `state.json` → `chunks[id].sec_iterations` |
| `sec-issues` | `state.json` → `chunks[id].sec_issues` |

### Example

```
feat(spec-3-enrichment/chunk-2): IP reputation enrichment

Tests: 12 written, all passing
Implementation iterations: 2
Security review iterations: 2
Security issues caught: 2

Pipeline: auto-committed by agentic pipeline
```

---

## 5. Pipeline Execution Log

Human-readable Markdown log of the pipeline run. Developer-friendly artifact included in PR descriptions.

**Location:** `.claude/pipeline/logs/<spec-slug>.md`
**Sole writer:** pipeline-orchestrator (initializes during pre-pipeline, appends after every Task completion)
**Read by:** pipeline-orchestrator (post-pipeline, for PR body generation)

This file is NOT machine-parseable. All machine-readable state lives in `state.json`.

### Structure

```markdown
# Pipeline Run: <spec-title>
# Started: <iso-timestamp>

## Architecture
- Plan: <plan-summary>
- Chunks: <total-chunks>

## Chunks

### Chunk <id>: <title>
- Tests Written: <n> tests (all failing)
- Implementer: <result> (<iterations> iteration(s), <passing>/<written> tests passing)
- Security Review: <PASS|FAIL (iteration N) — issue summary>
[If FAIL, additional lines for fix + re-review:]
- Implementer: <FIX APPLIED|FIX FAILED> (...)
[If FIX APPLIED:]
- Security Review: <PASS|FAIL>
[If FIX FAILED:]
- ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: <failure summary>
- ▶ RESUMED: <decision>

## Integration Validation: <PASS|FAIL>
## Completed: <iso-timestamp>
## Total Implementation Iterations: <n> (across all chunks)
## Total Security Issues Caught: <n>
```

### Human Review Events

When the pipeline pauses for developer input, two log lines are written: an **escalation line** when the pipeline pauses, and a **resolution line** when the developer responds. These appear inline within the relevant section (Architecture, Chunk, or Integration Validation).

**Escalation line** (pipeline pauses for input):
```
- ⏸ AWAITING INPUT: <reason>
```

**Resolution line** (developer responds):
```
- ▶ RESUMED: <decision>
```

**Escalation reasons by phase:**

| Phase | Reason Format |
|-------|---------------|
| Architecture | `Architecture analysis flagged ambiguity — <summary of concern>` |
| Test generation | `Test generation failed — <summary of failure>` |
| Implementation (max iterations) | `Implementation failed — <N> tests still failing after 3 iterations` |
| Security review (max iterations) | `Security review failed — unresolved issues after 3 iterations` |
| Security fix (implementer failure) | `Security fix failed — implementer could not resolve issues: <failure summary>` |
| Integration validation | `Integration validation failed` |

**Resolution decisions:**

| Decision | Log Text |
|----------|----------|
| Retry with guidance | `Developer provided guidance, retrying` |
| Abort pipeline | `Developer aborted pipeline` |
| Accept risk (security only) | `Developer accepted risk, proceeding` |

### Example

```markdown
# Pipeline Run: Spec 3 — Enrichment and Evaluation
# Started: 2026-03-17T10:00:00Z

## Architecture
- ⏸ AWAITING INPUT: Architecture analysis flagged ambiguity — conflicting stream names in spec sections 2.1 and 3.4
- ▶ RESUMED: Developer provided guidance, retrying
- Plan: 12-step implementation plan across signal-enrichment and risk-evaluator services
- Chunks: 3

## Chunks

### Chunk 1: Service scaffold and stream setup
- Tests Written: 8 tests (all failing)
- Implementer: COMPLETE (1 iteration, 8/8 tests passing)
- Security Review: PASS

### Chunk 2: IP reputation enrichment
- Tests Written: 12 tests (all failing)
- Implementer: FAIL (iteration 1)
- Implementer: FAIL (iteration 2)
- Implementer: FAIL (iteration 3)
- ⏸ AWAITING INPUT: Implementation failed — 4 tests still failing after 3 iterations
- ▶ RESUMED: Developer provided guidance, retrying
- Implementer: COMPLETE (1 iteration, 12/12 tests passing)
- Security Review: FAIL (iteration 1) — SQL injection in query builder, missing IP validation
- Implementer: FIX APPLIED (regression check: 12/12 tests still passing)
- Security Review: PASS

### Chunk 3: Geo-location enrichment and caching
- Tests Written: 10 tests (all failing)
- Implementer: COMPLETE (1 iteration, 10/10 tests passing)
- Security Review: FAIL (iteration 1) — unsanitized cache key from user input
- Implementer: FIX FAILED — 2 tests failing after fix attempt
- ⏸ AWAITING INPUT: Security fix failed — implementer could not resolve issues: cache key sanitization broke geo-lookup tests
- ▶ RESUMED: Developer provided guidance, retrying
- Implementer: FIX APPLIED (regression check: 10/10 tests still passing)
- Security Review: PASS

## Integration Validation: PASS
## Completed: 2026-03-17T10:47:00Z
## Total Implementation Iterations: 5 (across all chunks)
## Total Security Issues Caught: 2
```

---

## 6. pipeline-quality-report.md

Human-readable Markdown report summarizing a complete pipeline run's defense-in-depth receipts. Generated by the `pipeline-orchestrator` at the end of the post-pipeline phase. Durable, version-controlled artifact.

**Location:** `.claude/pipeline/reports/<spec-slug>-quality-report.md`
**Producer:** pipeline-orchestrator (post-pipeline phase)
**Consumer:** human reviewers (developer, PR reviewer, portfolio reviewer)

### Format

```markdown
# Pipeline Quality Report — <Spec Title>

**Spec:** <spec-slug>
**Branch:** feature/<spec-slug>
**Started:** <iso-timestamp>
**Completed:** <iso-timestamp>
**Duration:** <hh:mm:ss>
**Outcome:** COMPLETED | ESCALATED | FAILED
**Total Agent invocations:** <n> / 30 (budget guard ceiling)
**Final model:** <model-id>

## Per-Chunk Metrics

| Chunk | Title | Tests Written | Tests Passing | Impl Iterations | Sec Review Iterations | Sec Issues Caught | Outcome |
|-------|-------|---------------|---------------|-----------------|----------------------|-------------------|---------|
| 1 | <chunk-1 title> | 8 | 8/8 | 1 | 1 | 0 | passed |
| 2 | <chunk-2 title> | 12 | 12/12 | 2 | 2 | 1 | passed |
| ... | | | | | | | |

## Aggregate Metrics

- **Total tests written:** <n>
- **Total tests passing at completion:** <n>/<n>
- **Total implementation iterations:** <n>
- **Total security review iterations:** <n>
- **Total security issues caught:** <n>
- **Total security issues resolved by reflection loop:** <n>
- **Total HUMAN_REVIEW escalations:** <n>

## Self-Correction Events

[List one entry per chunk where the reflection loop fired and resolved without human intervention; or "None — no reflection loops fired." if the run was clean.]

- **Chunk <n>:** Security review found <issue category> in `<file>:<line>`. Implementer applied fix in iteration <n>. Tests re-verified after fix. Security review PASS on iteration <n>.
- ...

## Escalations to HUMAN_REVIEW

[List one entry per escalation, including chunk, phase, reason, and developer resolution; or "None — no escalations." if the run was clean.]

- **Chunk <n>, phase <phase-name>:** <reason>. Developer resolved by: <resolution>.
- ...

## Defense-in-Depth Receipts

| Guard | Threshold | Maximum Observed | Status |
|-------|-----------|------------------|--------|
| Implementation iteration cap | 3 per chunk | <max-impl-iter> | respected |
| Security review iteration cap | 3 per chunk | <max-sec-iter> | respected |
| Invocation budget guard | 30 total | <invocation_count> | respected |
| Post-security-fix regression check | always | <count> performed | <all-passed-or-detail> |

## Notes

[Free-form orchestrator commentary. Empty for clean runs.]
```

### Field Sources

| Field | Source |
|-------|--------|
| `Spec`, `spec-slug`, `Started`, `Completed`, `Total Agent invocations` | `state.json` (`spec`, `spec_slug`, `started_at`, `completed_at`, `invocation_count`) |
| Per-chunk row data | `state.json` → `chunks[]` array |
| Self-correction events | Pipeline execution log entries where security review FAIL was followed by PASS in the same chunk |
| Escalations | Pipeline execution log entries with `## HUMAN_REVIEW` headers |
| Outcome | `state.json` → top-level `phase`: `complete` → COMPLETED, `failed` → FAILED, anything else with at least one `failed` chunk → ESCALATED |
| Defense-in-Depth Receipts | Computed from `state.json` chunk records: `max(impl_iterations)`, `max(sec_iterations)`, `invocation_count`, count of regression-check log entries |

### Generation Rules

1. The report is generated **once per pipeline run** at the end of the post-pipeline phase, after the draft PR is created.
2. The orchestrator overwrites any existing report at the same path (a re-run of the same spec produces a fresh report).
3. The report is committed as part of the post-pipeline finalization (no separate commit). It travels with the spec's PR for reviewer visibility.
4. If the pipeline ends with `phase: "failed"` (developer aborted after HUMAN_REVIEW), the report is still generated to record the partial run; the Outcome row reads FAILED and the report covers all completed-or-attempted chunks.
