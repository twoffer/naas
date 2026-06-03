# Pipeline Communication Contracts

**Version:** 5
**Last updated:** 2026-05-06

This file defines the data formats used for inter-agent communication in the NAAS agentic pipeline. It is the single source of truth — orchestrator and worker prompts reference this file rather than inlining format definitions.

**Scope:** Data formats only. For pipeline architecture, implementation guidance, and design rationale, see `docs/Agentic_Workflow_Implementation_Guide.md`.

**Ownership model:** The `pipeline-orchestrator` skill (running in the main Claude Code session) is the sole writer of `state.json`, the pipeline execution log, the per-spec quality report (§6), the code security review file (§8), and the integration validation report file (§9). The technical-architect writes the implementation plan file (§7) and `chunks.json` (§2) directly so the feature-implementer can read the plan during implementation without orchestrator reinterpretation. Worker subagents otherwise communicate results through their `Agent` tool responses — they never read or write pipeline state files.

---

## 1. PIPELINE_OUTPUT (Documentation Convention)

Optional structured block at the end of an agent's response. Retained for **human readability** when reviewing agent transcripts. Not parsed by any automated system — the pipeline-orchestrator reads worker results from `Agent` responses and artifact files, not from this block.

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
3. No automated system parses this block. The `pipeline-orchestrator` determines next steps by reading `state.json` and worker `Agent` responses directly.
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
**Sole writer:** pipeline-orchestrator (initializes during pre-pipeline, updates after every `Agent` invocation)
**Read by:** pipeline-orchestrator (for resume, post-pipeline PR generation), developer (human visibility into pipeline progress)

Workers never read or write this file. The orchestrator extracts data from worker `Agent` responses and artifact files, then updates state.json itself.

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
  "invocation_count": 8,                            // Total `Agent` invocations for budget tracking
  "budget_guard_triggered": false,                  // Set true the first time the budget guard fires; prevents re-firing
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
| `invocation_count` | integer | Count of `Agent` invocations. Orchestrator increments after each worker `Agent` invocation only; non-`Agent` steps (chunk entry, commit, post-pipeline finalization) do not increment it. Used for budget monitoring. |
| `budget_guard_triggered` | boolean | `false` until the budget guard fires. The orchestrator pauses for the budget guard exactly once — the first time `invocation_count` reaches the threshold (`>= 30`) while this flag is `false` — then sets it `true` so the guard does not re-fire as the count keeps climbing. |
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
  "budget_guard_triggered": false,
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

## 4. Commit Messages

The `pipeline-orchestrator` produces two kinds of structured commits during a run: a **per-chunk commit** after each chunk passes the security review gate, and a single **finalization commit** at the end of the post-pipeline phase that captures the execution log and the quality report. Both use conventional-commit prefixes consistent with `CLAUDE.md`.

### 4.1 Per-Chunk Commit Message

Produced by the orchestrator after a chunk passes its security review gate.

#### Template

```
feat(<spec-slug>/chunk-<chunk-id>): <chunk-title>

Tests: <tests> written, all passing
Implementation iterations: <impl-iterations>
Security review iterations: <sec-iterations>
Security issues caught: <sec-issues>

Pipeline: auto-committed by agentic pipeline
```

#### Field Sources

| Field | Source |
|-------|--------|
| `spec-slug` | `state.json` → `spec_slug` |
| `chunk-id` | `state.json` → `current_chunk` |
| `chunk-title` | `chunks.json` → `chunks[id].title` |
| `tests` | `state.json` → `chunks[id].tests` |
| `impl-iterations` | `state.json` → `chunks[id].impl_iterations` |
| `sec-iterations` | `state.json` → `chunks[id].sec_iterations` |
| `sec-issues` | `state.json` → `chunks[id].sec_issues` |

#### Example

```
feat(spec-3-enrichment/chunk-2): IP reputation enrichment

Tests: 12 written, all passing
Implementation iterations: 2
Security review iterations: 2
Security issues caught: 2

Pipeline: auto-committed by agentic pipeline
```

### 4.2 Finalization Commit Message

Produced by the orchestrator once during the post-pipeline phase, after the execution log has been finalized and the quality report has been generated. This commit stages the five durable per-spec artifacts (execution log, quality report, plan file, security review file, integration validation report) so they travel with the spec's PR. It is created **before** `git push` and PR creation; per-chunk commits already on the branch are not re-staged.

#### Template

```
chore(<spec-slug>): finalize pipeline run

Pipeline execution log: .claude/pipeline/logs/<spec-slug>.md
Quality report: .claude/pipeline/reports/<spec-slug>-quality-report.md
Implementation plan: .claude/pipeline/plans/<spec-slug>-plan.md
Code security review: .claude/pipeline/reviews/<spec-slug>-review.md
Integration validation report: .claude/pipeline/reports/<spec-slug>-integration-report.md

Total chunks: <total-chunks>
Total implementation iterations: <total-impl-iterations>
Total security review iterations: <total-sec-iterations>
Total security issues caught: <total-sec-issues>

Pipeline: auto-committed by agentic pipeline
```

#### Field Sources

| Field | Source |
|-------|--------|
| `spec-slug` | `state.json` → `spec_slug` |
| `total-chunks` | `state.json` → `total_chunks` |
| `total-impl-iterations` | Sum of `state.json` → `chunks[].impl_iterations` |
| `total-sec-iterations` | Sum of `state.json` → `chunks[].sec_iterations` |
| `total-sec-issues` | Sum of `state.json` → `chunks[].sec_issues` |

#### Example

```
chore(spec-3-enrichment): finalize pipeline run

Pipeline execution log: .claude/pipeline/logs/spec-3-enrichment.md
Quality report: .claude/pipeline/reports/spec-3-enrichment-quality-report.md
Implementation plan: .claude/pipeline/plans/spec-3-enrichment-plan.md
Code security review: .claude/pipeline/reviews/spec-3-enrichment-review.md
Integration validation report: .claude/pipeline/reports/spec-3-enrichment-integration-report.md

Total chunks: 3
Total implementation iterations: 4
Total security review iterations: 4
Total security issues caught: 2

Pipeline: auto-committed by agentic pipeline
```

#### Staging Rules

1. Stage exactly five paths, in this order:
   - `.claude/pipeline/logs/<spec-slug>.md`
   - `.claude/pipeline/reports/<spec-slug>-quality-report.md`
   - `.claude/pipeline/plans/<spec-slug>-plan.md`
   - `.claude/pipeline/reviews/<spec-slug>-review.md`
   - `.claude/pipeline/reports/<spec-slug>-integration-report.md`

   Never `git add -A` or `git add .`.
2. `state.json` and `chunks.json` must not appear in the commit (they are gitignored; verify with `git status` before committing if uncertain).
3. If any of the plan, review, or integration-report file is unexpectedly absent (e.g., the architect never produced a plan, or the orchestrator never appended a review section for a spec that ran), the orchestrator stages the files that exist and notes the omission in the developer-facing summary; it does not fabricate placeholder content.
4. The finalization commit is the last commit on the feature branch before push.

---

## 5. Pipeline Execution Log

Human-readable Markdown log of the pipeline run. Developer-friendly artifact included in PR descriptions.

**Location:** `.claude/pipeline/logs/<spec-slug>.md`
**Sole writer:** pipeline-orchestrator (initializes during pre-pipeline, appends after every `Agent` invocation)
**Read by:** pipeline-orchestrator (post-pipeline, for PR body generation)

This file is NOT machine-parseable. All machine-readable state lives in `state.json`.

The execution log is a canonical, schema-defined artifact. Every line and section header that any producer (phase doc, human-review protocol, orchestrator skill, simulator scenario) writes to this file is registered in the sub-sections below. Producers reference entries by ID and never restate literal formats — CONTRACTS.md is the single source of truth.

### 5.1 File-Level Structure

The execution log's section headers, in canonical order. A producer writes each header once; conditional headers (e.g., `## Architecture`) are appended only on first entry to that section.

| Order | Heading | Depth | Producer | When emitted |
|-------|---------|-------|----------|--------------|
| 1 | `# Pipeline Run: <spec-title>` | H1 | pre-pipeline | initialization (file create) |
| 2 | `# Started: <iso-timestamp>` | H1 | pre-pipeline | initialization (file create) |
| 3 | `## Architecture` | H2 | architecture | on phase entry, idempotent |
| 4 | `## Implementation` | H2 | per-chunk | on loop entry, before chunk 1, idempotent |
| 5 | `### Chunk <id>: <title>` | H3 | per-chunk | on each chunk entry, idempotent |
| 6 | `## Integration Validation: <PASS\|FAIL>` | H2 | integration | once, after validator returns |
| 7 | `## Completed: <iso-timestamp>` | H2 | post-pipeline | finalization |
| 8 | `## Total Implementation Iterations: <n> (across all chunks)` | H2 | post-pipeline | finalization |
| 9 | `## Total Security Issues Caught: <n>` | H2 | post-pipeline | finalization |

The three top-level H2 sections — `## Architecture`, `## Implementation`, `## Integration Validation` — mirror the pipeline's main phases and group all bullet lines beneath their corresponding phase.

### 5.2 Bullet-Line Registry

Every bullet line written to the execution log. Producers reference these by ID (e.g., "append the line per CONTRACTS.md §5.2.3"). Placeholders in angle brackets are substituted at write time.

| ID | Format String | Producer | Trigger |
|----|---------------|----------|---------|
| 5.2.1 | `- Plan: <plan-summary>` | architecture | architect succeeds |
| 5.2.2 | `- Chunks: <total-chunks>` | architecture | architect succeeds |
| 5.2.3 | `- Tests Written: <n> tests (all failing)` | per-chunk (test gen) | test-suite-generator succeeds |
| 5.2.4 | `- Implementer: COMPLETE (<n> iteration\|iterations, <passing>/<total> tests passing)` | per-chunk (impl) | tests pass + lint clean. Use `iteration` when `<n>` = 1, `iterations` otherwise. |
| 5.2.5 | `- Implementer: FAIL (iteration <n>)` | per-chunk (impl) | tests fail or lint fails in iteration `<n>`. No test-count tail. |
| 5.2.6 | `- Security Review: PASS` | per-chunk (sec review) | reviewer returns PASS |
| 5.2.7 | `- Security Review: FAIL (iteration <n>) — <issue summary>` | per-chunk (sec review) | reviewer returns FAIL; em-dash precedes issue summary |
| 5.2.8 | `- Security Review: ACCEPTED BY DEVELOPER` | human-review | accept-risk resolution; always written immediately after the §5.2.12 line carrying the `Developer accepted risk, proceeding` decision (§5.4) |
| 5.2.9 | `- Implementer: FIX APPLIED (regression check: <passing>/<total> tests still passing)` | per-chunk (sec fix) | fix succeeds; parenthesized regression check |
| 5.2.10 | `- Implementer: FIX FAILED — <failure summary>` | per-chunk (sec fix) | fix fails; em-dash precedes free-form summary |
| 5.2.11 | `- ⏸ AWAITING INPUT: <reason>` | human-review / orchestrator (budget guard) | any escalation; `<reason>` is the literal text from the matching §5.3 row |
| 5.2.12 | `- ▶ RESUMED: <decision>` | human-review / orchestrator (budget guard) | any resolution; `<decision>` is the literal text from the matching §5.4 row |

Notes on shape asymmetry: 5.2.4 (COMPLETE) and 5.2.5 (FAIL) have different shapes — only the success form carries test counts. 5.2.9 (FIX APPLIED) uses parentheses around a regression check while 5.2.10 (FIX FAILED) uses an em-dash with a free-form summary. These are intentional and load-bearing.

### 5.3 Escalation Reasons

The literal text substituted into `<reason>` in §5.2.11. The orchestrator selects a row by the phase that escalated.

| Phase | Reason Format |
|-------|---------------|
| Architecture | `Architecture analysis flagged ambiguity — <summary of concern>` |
| Test generation | `Test generation failed — <summary of failure>` |
| Implementation | `Implementation failed — <n> tests still failing after 3 iterations` |
| Security review | `Security review failed — unresolved issues after 3 iterations` |
| Security fix | `Security fix failed — implementer could not resolve issues: <failure summary>` |
| Integration | `Integration validation failed` |
| Budget guard | `Budget guard — invocation count reached <n>, threshold is <threshold>` |

### 5.4 Resolution Decisions

The literal text substituted into `<decision>` in §5.2.12. The orchestrator selects a row by the developer's response to the escalation.

| Decision | Log Text |
|----------|----------|
| Retry with guidance | `Developer provided guidance, retrying` |
| Abort pipeline | `Developer aborted pipeline` |
| Accept risk (security review or security fix only) | `Developer accepted risk, proceeding` — the orchestrator must immediately follow the §5.2.12 line with a §5.2.8 line (`- Security Review: ACCEPTED BY DEVELOPER`) |
| Budget-guard continuation | `Developer approved continuation` |

### 5.5 Example

```markdown
# Pipeline Run: Spec 3 — Enrichment and Evaluation
# Started: 2026-03-17T10:00:00Z

## Architecture
- ⏸ AWAITING INPUT: Architecture analysis flagged ambiguity — conflicting stream names in spec sections 2.1 and 3.4
- ▶ RESUMED: Developer provided guidance, retrying
- Plan: 12-step implementation plan across signal-enrichment and risk-evaluator services
- Chunks: 3

## Implementation

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
**Consumer:** human reviewers (developer, PR reviewer, project reviewer)

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

## Related Artifacts

- Implementation plan: `.claude/pipeline/plans/<spec-slug>-plan.md` (technical-architect)
- Code security review: `.claude/pipeline/reviews/<spec-slug>-review.md` (pipeline-orchestrator, append-only across chunks/iterations)
- Integration validation report: `.claude/pipeline/reports/<spec-slug>-integration-report.md` (pipeline-orchestrator, append-only across runs)
- Pipeline execution log: `.claude/pipeline/logs/<spec-slug>.md` (this run)
```

### Field Sources

| Field | Source |
|-------|--------|
| `Spec`, `spec-slug`, `Started`, `Completed`, `Total Agent invocations` | `state.json` (`spec`, `spec_slug`, `started_at`, `completed_at`, `invocation_count`) |
| Per-chunk row data | `state.json` → `chunks[]` array |
| Self-correction events | Pipeline execution log entries where security review FAIL was followed by PASS in the same chunk |
| Escalations | Pipeline execution log entries written per §5.2.11 (`- ⏸ AWAITING INPUT:` bullet lines), each paired with the immediately following §5.2.12 (`- ▶ RESUMED:`) line that records the developer's resolution |
| Outcome | `state.json` → top-level `phase`: `complete` → COMPLETED, `failed` → FAILED, anything else with at least one `failed` chunk → ESCALATED |
| Defense-in-Depth Receipts | Computed from `state.json` chunk records: `max(impl_iterations)`, `max(sec_iterations)`, `invocation_count`, count of regression-check log entries |

### Generation Rules

1. The report is generated **once per pipeline run** during the post-pipeline phase, after the execution log has been finalized and before the finalization commit defined in §4.2. The finalization commit is the last commit on the branch, so the report is written before `git push` and before PR creation.
2. The orchestrator overwrites any existing report at the same path (a re-run of the same spec produces a fresh report).
3. The report is committed by the finalization commit defined in §4.2, alongside the execution log and the §§7–9 artifacts. A single commit covers all five so they travel with the spec's PR for reviewer visibility.
4. If the pipeline ends with `phase: "failed"` (developer aborted after HUMAN_REVIEW), the report is still generated to record the partial run; the Outcome row reads FAILED and the report covers all completed-or-attempted chunks.

---

## 7. Implementation Plan File

Human-readable Markdown narrative of the technical-architect's spec interpretation: ordered implementation steps, integration notes, and known risks. Companion to `chunks.json` — `chunks.json` is the machine-readable decomposition consumed by the orchestrator; the plan file is the prose narrative the feature-implementer (and human reviewers) can read for context that the per-chunk `implementation_instructions` field cannot fully convey.

**Location:** `.claude/pipeline/plans/<spec-slug>-plan.md`
**Producer:** technical-architect (architecture phase, single write per pipeline run)
**Consumers:** feature-implementer (during implementation, for cross-chunk context); human reviewers (post-pipeline, for spec interpretation review)

The orchestrator does not parse this file. Its presence is informational; the orchestrator extracts data from `chunks.json` and worker `Agent` responses.

### Format

The file follows the OUTPUT FORMAT defined in `.claude/agents/technical-architect.md` (`PLAN`, `SPEC REFERENCE`, `PREREQUISITES`, `STEPS`, `INTEGRATION NOTES`, `KNOWN RISKS`). The agent prompt is the single source of truth for the format — it is not duplicated here to avoid drift.

### Generation Rules

1. Written by the technical-architect during the architecture phase, alongside `chunks.json`.
2. The architect runs once per spec, so the file is written once per pipeline (no append, no overwrite within a run).
3. The architect creates `.claude/pipeline/plans/` if it does not exist. The pre-pipeline phase also ensures the directory exists; the agent's `mkdir -p`-equivalent is defensive.
4. In manual mode the architect still produces this file by default unless the developer specifies an alternate output path in the Task prompt.

---

## 8. Code Security Review File

Append-only Markdown file accumulating every code-security-reviewer invocation for a spec. Preserves the detail surfaced in the reviewer's `Agent` response — including non-blocking (LOW/MEDIUM-severity) findings, recommended improvements, and other context that the orchestrator's PASS/FAIL parsing and the §5.2.6/§5.2.7 execution-log one-liners do not preserve.

**Location:** `.claude/pipeline/reviews/<spec-slug>-review.md`
**Producer:** pipeline-orchestrator (after each code-security-reviewer invocation, once per invocation). The orchestrator records the reviewer's response under the canonical section header below; body format is at the orchestrator's discretion (see Format below).
**Consumer:** human reviewers (post-pipeline). The pipeline-orchestrator does NOT read this file back — it parses verdict and blocking-issue summary from the reviewer's `Agent` response.

### Why This File Exists

A chunk passes its security gate when the reviewer returns `PASS`. `PASS` does not mean the reviewer found no issues — only that none were blocking. Recommended improvements (LOW-severity findings, style nits, defensive-programming suggestions in the `Recommended Improvements (non-blocking)` section of the reviewer's output) are visible only in the reviewer's `Agent` response transcript, which is ephemeral. This file preserves them as a durable, version-controlled artifact the developer can consult after the pipeline finishes to address lower-priority issues in a follow-up commit.

### Format

Each invocation appends a new section to the same file. The section header is canonical:

```
## Chunk <id> — Iteration <n> — <VERDICT> — <ISO 8601 UTC timestamp>
```

Where:
- `<id>` is the integer chunk ID from `chunks.json`.
- `<n>` is the security-review iteration for that chunk; matches `state.json` → `chunks[id].sec_iterations` after this invocation. Because `sec_iterations` resets to 0 when the developer retries with guidance after max iterations (per `human-review.md`), `<n>` can restart at `1` for a chunk that already has higher-numbered sections earlier in the file. The resulting duplicate `Iteration <n>` header is expected — the append-only chronological order (Generation Rule 1) disambiguates it.
- `<VERDICT>` is one of `PASS`, `PASS WITH NOTES`, `NEEDS CHANGES`, `SECURITY CONCERN` — the reviewer's overall verdict for this invocation.
- `<ISO 8601 UTC timestamp>` is the time the review completed (e.g., `2026-05-06T14:23:11Z`).

Only the section header is normative. The body content under each header is at the orchestrator's discretion — this file is for human consumption only, so any format that preserves the reviewer's findings is acceptable. The simplest approach is to copy the relevant portion of the reviewer's `Agent` response verbatim, but the orchestrator may reformat or summarize as it sees fit.

### Generation Rules

1. **Append-only.** Never truncate or rewrite earlier sections. Retries, fixes, and re-reviews each produce a new appended section so the file becomes a chronological audit trail across all chunks and iterations for the spec.
2. Written by the orchestrator immediately after each code-security-reviewer `Agent` invocation in pipeline mode — `PASS` and FAIL outcomes both append.
3. The orchestrator creates `.claude/pipeline/reviews/` if it does not exist. The pre-pipeline phase also ensures the directory exists.
4. In manual mode this file is NOT written. The reviewer returns its review in the `Agent` response only; the developer captures the output if they want a durable copy.
5. The orchestrator never reads this file back. Its existence is a post-pipeline convenience for human reviewers.

---

## 9. Integration Validation Report File

Append-only Markdown file accumulating every integration-validator invocation for a spec. Preserves the detail surfaced in the validator's `Agent` response — including per-seam failure context, non-blocking issues, and recommendations that the orchestrator's PASS/FAIL parsing and the §5.1 row 6 execution-log heading do not preserve.

**Location:** `.claude/pipeline/reports/<spec-slug>-integration-report.md`
**Producer:** pipeline-orchestrator (after each integration-validator invocation, once per invocation; multiple invocations on retry). The orchestrator records the validator's response under the canonical section header below; body format is at the orchestrator's discretion (see Format below).
**Consumer:** human reviewers (post-pipeline). The pipeline-orchestrator does NOT read this file back — it parses `PASS`/`FAIL` from the validator's `Agent` response.

### Why This File Exists

The validator may surface non-blocking issues (consumer-group lag, log-noise patterns, environment drift between `docker-compose` and prod) and recommendations (e.g., "add retry to OIDC callback handler") that do not block the spec from completing but are worth acting on. These are visible only in the validator's `Agent` response transcript, which is ephemeral. This file preserves them as a durable artifact for follow-up.

### Format

Each invocation appends a new section. The section header is canonical:

```
## Validation Run <n> — <VERDICT> — <ISO 8601 UTC timestamp>
```

Where:
- `<n>` is the validator invocation count for the spec, 1-based. The first invocation is run 1; each retry after a failed integration validation increments by one.
- `<VERDICT>` is `PASS` or `FAIL`.
- `<ISO 8601 UTC timestamp>` is the time the validation completed.

Only the section header is normative. The body content under each header is at the orchestrator's discretion — this file is for human consumption only, so any format that preserves the validator's findings is acceptable. The simplest approach is to copy the relevant portion of the validator's `Agent` response verbatim, but the orchestrator may reformat or summarize as it sees fit.

### Generation Rules

1. **Append-only.** Retries after failure append a new section; previous sections are preserved as the validation history.
2. Written by the orchestrator immediately after each integration-validator `Agent` invocation in pipeline mode — `PASS` and `FAIL` outcomes both append.
3. The orchestrator creates `.claude/pipeline/reports/` if it does not exist. The pre-pipeline phase also ensures the directory exists.
4. In manual mode this file is NOT written. The validator returns its report in the `Agent` response only; the developer captures the output if they want a durable copy.
5. The orchestrator never reads this file back. Its existence is a post-pipeline convenience for human reviewers.
