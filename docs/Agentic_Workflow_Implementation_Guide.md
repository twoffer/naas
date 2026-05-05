# NAAS Agentic Workflow Enhancement Guide
## Implementation Plan for Claude Code

**Document Date:** May 2026 (revised)
**Purpose:** Guide the implementation of automated agentic development pipeline enhancements for the NAAS project.
**Audience:** Project architect and Claude Code agents operating on the NAAS codebase.

---

## Overview

This document defines three prioritized enhancements to the NAAS project's agentic development workflow. The goal is to transform the current manual, sequential subagent invocation pattern into an automated pipeline with quality gates, structured observability, and pipeline recovery.

### Current State

Five worker subagents exist in `.claude/agents/`:
- `technical-architect` — creates implementation plans from functional specs
- `feature-implementer` — implements plans chunk by chunk
- `code-security-reviewer` — reviews code for security concerns
- `test-suite-generator` — generates test suites
- `integration-validator` — runs integration tests

**Current workflow:** Manual sequential invocation. Developer triggers each agent, waits for output, manually invokes the next.

### Target State

An automated pipeline where a single invocation (e.g., "Implement Spec 3") to a dedicated `pipeline-orchestrator` agent triggers the full chain: SCM initialization → architecture + plan decomposition → per-chunk TDD implementation with quality gate loops → final integration validation → SCM finalization (branch push, draft PR). Human intervention only required for escalated issues and the final PR merge.

### Agent Roster

| Component | Role | Category | Surface |
|-----------|------|----------|---------|
| `pipeline-orchestrator` | Pipeline entry point, lifecycle manager, and coordination loop | Orchestration | Skill (`.claude/skills/`) |
| `technical-architect` | Analyzes specs, produces implementation plans and chunk decompositions | Worker | Subagent (`.claude/agents/`) |
| `feature-implementer` | Implements code chunk by chunk, makes tests pass, fixes security issues | Worker | Subagent (`.claude/agents/`) |
| `code-security-reviewer` | Reviews code for security and quality | Worker | Subagent (`.claude/agents/`) |
| `test-suite-generator` | Generates test suites (TDD-first and post-implementation) | Worker | Subagent (`.claude/agents/`) |
| `integration-validator` | Tests cross-service integration | Worker | Subagent (`.claude/agents/`) |

The `pipeline-orchestrator` is invoked directly by the developer (via `/pipeline-orchestrator <spec>`) and runs in the main Claude Code session. All five worker agents are invoked by the orchestrator via the `Agent` tool, never by the developer. The orchestrator MUST run in the main session because subagents cannot themselves invoke other subagents — placing the orchestrator in `.claude/agents/` would prevent it from delegating to the worker pool.

### Architecture: Thick Orchestrator with Phase Decomposition

The orchestrator manages the **entire pipeline execution loop** — not just pre/post phases. It invokes each worker via the `Agent` tool, reads results from `Agent` tool responses and artifact files, updates pipeline state (`state.json`) and the execution log, and decides the next step.

Workers are stateless specialists. They receive their context via the orchestrator's Task prompt, do their work, produce artifact files, and return a summary. They never read or write pipeline state files (`state.json`, `chunks.json`).

**Phase decomposition:** Rather than encoding all pipeline logic in a single monolithic system prompt, the orchestrator's detailed per-phase instructions live in separate files under `.claude/pipeline/phases/`. The orchestrator prompt defines the phase sequence and maps each `state.json` phase value to an instruction file. When entering a phase, the orchestrator reads the corresponding file for detailed guidance.

This design:
- Reduces the orchestrator's active instruction set at any given time (one phase file vs. the entire prompt)
- Makes each phase independently reviewable and editable
- Eliminates fragile step-number cross-references — transitions reference phase names
- Centralizes the human-review escalation protocol in a single shared file

```
.claude/pipeline/phases/
├── pre-pipeline.md      # Branch creation, state init, log init
├── architecture.md      # Architect invocation, chunks.json validation
├── per-chunk.md         # Test gen, implementation, security review, commit
├── integration.md       # Integration validator invocation
├── post-pipeline.md     # Push, PR creation, finalization
└── human-review.md      # Shared escalation/resume protocol
```

### Design Philosophy: Defense in Depth for Increased Rigor

The pipeline incorporates several layers of guardrails — iteration caps on the implementer (3 attempts to make tests pass), iteration caps on the security review reflection loop (3 attempts before escalation), an invocation-count budget guard (pause at 30 invocations), regression checks after every security fix, and explicit HUMAN_REVIEW escalation paths. With current-generation frontier models (Claude Opus 4.7, Claude Sonnet 4.6), some of this scaffolding is heavier than what is strictly required for the pipeline to produce correct output. Modern models exhibit stronger task persistence, better self-verification, and more reliable tool use than earlier generations, and many runs would succeed without any of these guardrails firing.

These layers are retained deliberately for three reasons:

1. **Demonstration value.** A pipeline that includes explicit quality gates, escalation paths, and budget controls visibly demonstrates agentic engineering discipline — exactly the discipline that distinguishes a production-ready agentic system from a prototype. The receipts (iteration counts, security fixes, escalations) tell a verifiable story.

2. **Robustness across model generations.** The pipeline is designed to remain reliable if a less capable model is substituted for cost reasons (e.g., Sonnet 4.6 in place of Opus 4.7), or if a future model exhibits regression on a particular workflow. The guardrails are calibrated for the *minimum* trustworthy behavior, not the typical case.

3. **Catching the long tail.** Even with a well-behaved model, edge cases — flaky test environments, ambiguous spec requirements, intricate security findings — can produce a runaway loop or a confidently wrong output. The guardrails catch these without requiring the developer to babysit every run.

The cost of this defense-in-depth is mostly cognitive surface area, not runtime overhead — the guards rarely fire on a healthy run, but their presence makes the pipeline trustworthy enough to leave unattended for spans of 30+ minutes. The per-spec `pipeline-quality-report.md` artifact (see Post-Pipeline Phase) makes these guardrails visible by recording when and how often each fired during a run.

---

## Priority 1: Modernize Agent Definitions

### Objective

Update all five existing worker subagent files and create the new `pipeline-orchestrator` agent using the current Claude Code agent format with YAML frontmatter fields for tool scoping, model selection, and memory.

### Create the Pipeline Orchestrator Skill

**`.claude/skills/pipeline-orchestrator/SKILL.md`**

The `pipeline-orchestrator` is a **thick orchestrator** that runs in the main Claude Code session and manages the entire pipeline lifecycle:

1. **Pre-pipeline phase:** Parse the spec identifier from the developer's invocation, create the feature branch, initialize pipeline state (`state.json`), and create the pipeline execution log.
2. **Architecture phase:** Invoke the `technical-architect` via the `Agent` tool. Read the resulting plan file and `chunks.json`.
3. **Per-chunk loop:** For each chunk, invoke the `test-suite-generator`, `feature-implementer`, and `code-security-reviewer` via the `Agent` tool, handling reflection loops when quality gates fail. Commit each chunk after it passes.
4. **Integration phase:** Invoke the `integration-validator` via the `Agent` tool.
5. **Post-pipeline phase:** Push the feature branch, generate the draft PR from the execution log, write the final pipeline summary, and emit the per-spec quality report.
6. **Resume:** If `state.json` already exists, resume from the last recorded state instead of starting fresh.
7. **Cleanup:** On "Clean up pipeline for Spec X", remove transient pipeline artifacts.

After **every `Agent` tool completion**, the orchestrator performs a three-step update:
1. Extract key data from the worker's response and any artifact files
2. Update `state.json` with structured data
3. Append a summary line to the pipeline execution log

**Why a skill, not a subagent:** Claude Code subagents cannot themselves invoke other subagents. Placing the orchestrator in `.claude/agents/` would prevent it from delegating to the worker pool — the `Agent` tool is unavailable inside a subagent context. Skills, by contrast, run in the main Claude Code session, which retains full `Agent` tool access. The skill body becomes the orchestrator's operating instructions when invoked.

**Recommended configuration:**

| Frontmatter field | Value | Rationale |
|-------------------|-------|-----------|
| `name` | `pipeline-orchestrator` | Invoked as `/pipeline-orchestrator <spec>` |
| `description` | "Pipeline entry point and lifecycle manager. Invoke as `/pipeline-orchestrator <spec>` to run the full automated pipeline, `/pipeline-orchestrator resume <spec>` to continue an interrupted run, or `/pipeline-orchestrator cleanup <spec>` to remove transient artifacts." | Loaded into context so Claude knows when to apply the skill |
| `argument-hint` | `[spec-id]` | Autocomplete hint when typing the slash command |
| `disable-model-invocation` | `true` | Pipeline runs are explicit developer actions, never auto-triggered by Claude pattern-matching chat |
| `allowed-tools` | `Bash Read Write Edit Agent Grep Glob AskUserQuestion TaskCreate TaskGet TaskList TaskUpdate` | Pre-approves the toolset the orchestrator needs, eliminating per-call permission prompts during a run |
| `model` | `claude-opus-4-7` | Complex multi-step coordination with significant accumulated context. Benefits from 1M context window, improved long-horizon focus, and stronger file-system-based memory |
| `effort` | `xhigh` | Recommended for coding and agentic use cases on Opus 4.7 |

**System prompt structure (skill body):**

The skill body is intentionally concise (~70 lines). It defines:
- Identity and role
- First-action document loading (CLAUDE.md, AI-AGENT-PRINCIPLES.md, CONTRACTS.md)
- Three entry modes (fresh start, resume, cleanup) and how arguments select between them
- The state machine diagram and **phase-to-file mapping table**
- Budget guard (pause at 30 invocations) and how to surface it to the developer
- Critical rules (sole `state.json` writer, three-step update, targeted staging, pipeline mode instruction)
- The post-pipeline obligation to emit `pipeline-quality-report.md`

Detailed per-phase instructions remain at `.claude/pipeline/phases/*.md` (unchanged from prior layout). The skill reads the relevant phase file when entering each phase. This keeps the skill body focused on structure and constraints while phase files provide natural-language guidance for execution. Phase files remain at `.claude/pipeline/` rather than moving inside the skill directory in order to keep their pipeline-aligned behavior more generally consumable.

**Token budget guard note:** The Anthropic API beta `task_budget` feature (introduced with Opus 4.7) is set via API headers and is not exposed in terminal Claude Code. The pipeline therefore retains its existing `invocation_count` field in `state.json` as the budget control mechanism. If the orchestrator is ever migrated to the Agent SDK, `task_budget` becomes available as a refinement.

### Update the Technical Architect Agent

The `technical-architect` absorbs the plan decomposition responsibility that was previously handled by the `chunking` skill (`.claude/skills/chunk-plans/SKILL.md`). In a single invocation, it produces both:
1. An implementation plan at `.claude/pipeline/plans/<slug>-plan.md` (human-readable)
2. A `chunks.json` at `.claude/pipeline/chunks.json` (machine-readable, see CONTRACTS.md Section 2)

**Why merge decomposition into the architect:** The architect already has full context — the spec, the codebase, the architectural decisions. A separate decomposer would re-read this context with loss of nuance, adding a failure point and a context-loading cycle for no benefit.

**Chunking rules to absorb from the skill:**
- Each chunk: ~200-500 lines of new code, ~30-45 min to implement
- Each chunk has standalone "Done When" verification criteria
- Chunks are ordered sequentially (dependencies only reference earlier chunks)
- First chunk: scaffold (directories, Dockerfile, docker-compose entry, FastAPI skeleton, health endpoint)
- Last chunk: integration-facing (connects to upstream/downstream services)
- Shared library changes get their own chunk when significant
- `scope_boundary` files do not overlap across chunks; `shared_files` (e.g., docker-compose.yml) may overlap
- `do_not_touch` enforces hard boundaries between chunks

**Recommended configuration:**

| Field | Value | Rationale |
|-------|-------|-----------|
| `tools` | `Read`, `Write`, `Grep`, `Glob`, `AskUserQuestion` | `Write` for plan files and chunks.json. `AskUserQuestion` for manual invocation mode. No `Bash` (doesn't run code). No `Task` (doesn't invoke other agents — the orchestrator invokes it). |
| `model` | `claude-opus-4-6` | Deep reasoning for architectural analysis and plan decomposition. |
| `memory` | `project` | Remembers architectural decisions across spec implementations. |

**Delete the chunking skill:** Remove `.claude/skills/chunk-plans/SKILL.md` — its functionality is now part of the architect's standard responsibilities.

### What to Change Per Worker Agent

For each `.claude/agents/<agent-name>.md` file:

**1. Verify `tools:` field restricts capabilities appropriately.**

| Component | Tools | Rationale |
|-----------|-------|-----------|
| `pipeline-orchestrator` (skill `allowed-tools`) | `Bash Read Write Edit Agent Grep Glob AskUserQuestion TaskCreate TaskGet TaskList TaskUpdate` | Full pipeline management + developer escalation. `Agent` invokes worker subagents (formerly named `Task`). `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` populate the Claude Code task UI for visual progress tracking |
| `technical-architect` (subagent `tools`) | `Read, Write, Grep, Glob, AskUserQuestion` | Plan + chunks.json production |
| `feature-implementer` (subagent `tools`) | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Full implementation toolset. `LSP` provides live type errors after edits when a code-intelligence plugin is installed for the language |
| `code-security-reviewer` (subagent `tools`) | `Read, Grep, Glob, LSP` | Read-only by design. `LSP` enables call-hierarchy and reference-finding for vulnerability analysis |
| `test-suite-generator` (subagent `tools`) | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Test file creation + verification. `LSP` flags type errors in generated test code |
| `integration-validator` (subagent `tools`) | `Read, Bash, Grep, Glob, AskUserQuestion` | Test execution + diagnostics |

No worker subagent has access to `Bash` for git operations. The `feature-implementer`, `test-suite-generator`, and `integration-validator` use `Bash` for running code and tests, not for SCM. Git operations are exclusively the `pipeline-orchestrator`'s responsibility.

**LSP activation note:** The `LSP` tool is inactive until a Claude Code code-intelligence plugin is installed for the relevant language (Python, TypeScript). The agents declare `LSP` in their tool lists so the capability is available when plugins are installed; absent a plugin the tool entry is harmless. Installing language-specific code-intelligence plugins is recommended but optional.

**Frontmatter field naming:** Skill frontmatter uses `allowed-tools` (hyphenated, space-separated) while subagent frontmatter uses `tools` (comma-separated). The set of valid tool names is identical between the two surfaces.

**2. Verify `model:` field.**

Use `claude-opus-4-7` for components that benefit from deeper reasoning (`pipeline-orchestrator`, `technical-architect`, `code-security-reviewer`, `integration-validator`). Use `claude-sonnet-4-6` for components that benefit from speed (`feature-implementer`, `test-suite-generator`).

Opus 4.7 brings three improvements that disproportionately benefit the orchestration and review roles: stronger long-horizon task persistence (relevant to multi-chunk pipeline runs), better file-system-based memory (relevant to the orchestrator's `state.json` and execution-log discipline), and proactive output self-verification (relevant to architect chunks.json validation and security reviewer verdicts). The same context window (1M tokens) and standard Opus pricing apply.

**3. Refactor system prompts to remove duplicated project context.**

Agents automatically load `CLAUDE.md` context. For architectural details, agents should read the source documents directly via the `Read` tool as their first action (see Document Loading Convention below).

**4. Add pipeline mode instructions.**

Each worker's system prompt should include instructions for two operating modes:
- **Pipeline mode** (invoked via Task by orchestrator): Do not use `AskUserQuestion`. If encountering an issue requiring human input, clearly state the problem and what is needed in the response. The orchestrator handles escalation.
- **Manual mode** (invoked directly by developer): Use `AskUserQuestion` freely for ambiguities.

**5. Add lint/format gate to the feature-implementer.**

The feature-implementer's system prompt should include a self-verification step after all tests pass:

```
After all tests pass, run:
  Python: ruff check + ruff format --check on scope_boundary files
  TypeScript: tsc --noEmit + eslint on scope_boundary files
Fix any issues before declaring implementation complete.
```

**6. Add test quality verification to the test-suite-generator.**

In TDD mode, the test-suite-generator must run its generated tests and verify they **all fail** before completing. If any test passes before implementation exists, it is not testing new behavior — rewrite it.

**7. Workers do NOT interact with pipeline state files.**

Workers never read or write `state.json` or `chunks.json`. They receive their context from the orchestrator's Task prompt and communicate results through their Task response and artifact files. The orchestrator is the sole writer of `state.json`.

### Document Loading Convention

Each agent's system prompt should instruct it to read the relevant project documents as its first action using the `Read` tool. The NAAS documentation footprint is modest (~1,800 lines / ~69 KB across architecture doc, functional spec, and behavioral principles) and fits comfortably within context window limits.

**Do not create Skills, curated subsets, or caching layers for document loading.** Agents read the canonical source files directly.

The standard reading order for agents is:
1. `CLAUDE.md` — loaded automatically by Claude Code
2. `docs/AI-AGENT-PRINCIPLES.md` — behavioral guidelines (all agents)
3. `docs/architecture/SYSTEM_ARCHITECTURE.md` — system architecture (agents that need cross-service context)
4. The relevant functional spec file — passed via the pipeline context or specified in the agent's task prompt

### Validation

After modernization, verify that:
- The `pipeline-orchestrator` can create a branch, initialize state, and invoke the `technical-architect` via Task.
- The `technical-architect` can read a spec and produce both a plan file and a valid `chunks.json`.
- Each worker agent can still be invoked manually via `/agents` and performs its role correctly.
- Tool restrictions are working (e.g., `code-security-reviewer` cannot write files, worker agents cannot run git commands).
- Agents correctly read project documents via the `Read` tool as their first action.
- Workers do not attempt to read or write `state.json` or `chunks.json`.

---

## Priority 2: Pipeline Orchestration

### Objective

Implement the orchestrator's state machine so that completing one phase automatically proceeds to the next, with the orchestrator managing the entire execution loop via explicit Task invocations.

### Pipeline Architecture

```
┌──────────────────────────┐
│     Developer Input       │  "Implement Spec X"
│  (invokes orchestrator)   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  pipeline-orchestrator    │  PRE-PIPELINE PHASE:
│  (entry point)            │  - Parse spec slug
│                           │  - Create feature branch
│                           │  - Initialize state.json
│                           │  - Create pipeline log
│                           │  - Invoke technical-architect via Task
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  technical-architect      │  Analyze spec, produce plan + chunks.json
│  (invoked via Task)       │
└────────────┬─────────────┘
             │ Task returns to orchestrator
             │ Orchestrator reads chunks.json, updates state.json
             ▼
┌──────────────────────────────────────────────────────────────────┐
│          PER-CHUNK LOOP (Priority 3)                             │
│          Orchestrator invokes each worker via Task               │
│                                                                   │
│  ┌───────────────────┐                                           │
│  │test-suite-generator│  Write failing tests FIRST               │
│  │ (invoked via Task) │                                          │
│  └─────────┬─────────┘                                           │
│            │ Task returns, orchestrator updates state             │
│            ▼                                                      │
│  ┌───────────────────┐                                           │
│  │ feature-implementer│◄──── fix instructions (from orchestrator)│
│  │ (invoked via Task, │         │                                │
│  │  iterates until    │         │                                │
│  │  tests pass)       │         │                                │
│  └─────────┬─────────┘         │                                │
│            │ Task returns       │                                │
│            ▼                    │                                │
│  ┌────────────────────────┐    │                                │
│  │code-security-reviewer  │────┘                                │
│  │ (invoked via Task)     │  FAIL → orchestrator re-invokes     │
│  │                        │         implementer with fixes       │
│  │  PASS → orchestrator   │                                      │
│  │  commits chunk,        │                                      │
│  │  advances to next      │                                      │
│  └────────────────────────┘                                      │
└──────────────────────────────────────────────────────────────────┘
             │ All chunks complete
             ▼
┌──────────────────────────┐
│  integration-validator    │  Full integration validation
│  (invoked via Task)       │
└────────────┬─────────────┘
             │ Task returns to orchestrator
             ▼
┌──────────────────────────┐
│  pipeline-orchestrator    │  POST-PIPELINE PHASE:
│  (continues its loop)     │  - Push feature branch
│                           │  - Generate draft PR from execution log
│                           │  - Write final pipeline summary
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│     HUMAN REVIEW          │  Developer reviews and squash-merges PR
└──────────────────────────┘
```

### Orchestrator State Machine

The orchestrator drives the pipeline through these phases. Each phase's detailed instructions live in a separate file under `.claude/pipeline/phases/`:

```
PRE-PIPELINE → ARCHITECTURE → PER-CHUNK LOOP → INTEGRATION → POST-PIPELINE → DONE
                                                                      ↑
                                    Any phase can → HUMAN_REVIEW (ask developer)
```

| `state.json` Phase        | Instruction File                              | Summary |
|----------------------------|-----------------------------------------------|---------|
| `starting`                 | `phases/pre-pipeline.md`                      | Parse spec, create branch, init state + log |
| `architecture`             | `phases/architecture.md`                      | Invoke architect, validate chunks.json |
| `implementing`             | `phases/per-chunk.md`                         | Test gen → implementation → security review → commit (per chunk) |
| `integration_validation`   | `phases/integration.md`                       | Invoke integration validator |
| `post_pipeline`            | `phases/post-pipeline.md`                     | Push branch, create draft PR, finalize |
| `human_review`             | `phases/human-review.md`                      | Shared escalation/resume protocol |

Phase files use natural language guidance anchored by formal constraints (retry limits, state.json field names, phase values). They define entry conditions, execution guidance, state updates, success criteria, and escalation paths.

### Context Window Management

The orchestrator accumulates worker outputs in its conversation context — each Task response returns to the orchestrator. Over a full pipeline run:

- Each Task response: ~1-5K tokens
- 15-25 invocations (5 chunks × 3+ agents, with some reflection loops): ~15-125K tokens
- Plus orchestrator reasoning, Task prompt construction, state/log reads: ~30-60K tokens
- **Total estimated: ~50-200K tokens**

This is why the orchestrator uses `claude-opus-4-6` (1M context) — the accumulated context fits comfortably. Two mechanisms prevent context pressure:

1. **Claude Code's automatic context compression.** Older messages are compressed as context fills. The orchestrator only needs detailed access to the most recent Task response.
2. **Persistent ground truth files.** After each Task, the orchestrator writes state.json and appends to the execution log. If older context is compressed, these files serve as ground truth for any data the orchestrator needs later.

### Inter-Agent State Communication

For detailed schemas of `state.json`, `chunks.json`, commit messages, and the execution log, see `.claude/pipeline/CONTRACTS.md`.

**Key design principle: The orchestrator is the sole writer of `state.json`.** Workers never read or write it. This eliminates dual-write bugs, simplifies workers, and ensures state consistency.

**How workers communicate results to the orchestrator:**
1. **Task response text** — natural language summary of what was done
2. **Artifact files** — plan files, chunks.json, test files, review reports
3. **Test/lint results** — pass/fail counts reported in the Task response

The orchestrator synthesizes these into state.json updates and log entries.

**How the orchestrator passes context to workers:**
The orchestrator reads `chunks.json` and extracts the relevant chunk's fields into each worker's Task prompt. Workers receive self-contained, unambiguous prompts — they don't need to know about pipeline state files, chunk IDs, or the broader pipeline context.

### Pipeline Recovery / Resume

If the pipeline is interrupted (session crash, network failure), the orchestrator supports resume:

1. Developer invokes orchestrator with: "Resume pipeline for Spec X"
2. Orchestrator reads existing `state.json`
3. Orchestrator maps the recorded phase and chunk status to its state machine and re-enters the loop at the correct point
4. Previously completed chunks are not re-executed

### Budget Guard

The orchestrator tracks `invocation_count` in `state.json`, incrementing after each Task call. If the count exceeds 30, the orchestrator pauses and reports current pipeline status to the developer before continuing. This prevents runaway reflection loops from consuming excessive resources.

### Pipeline Cleanup

The orchestrator supports a cleanup command: "Clean up pipeline for Spec X"
- Deletes transient state files (`state.json`, `chunks.json`)
- Deletes plan and review files under `.claude/pipeline/`
- Asks for confirmation before discarding uncommitted changes or deleting the feature branch

### Validation

- Invoke the `pipeline-orchestrator` with a small spec (Spec 1: Event Ingestion — simplest, most self-contained).
- Verify the orchestrator creates the branch, initializes state, invokes the architect via Task, reads chunks.json, and begins the per-chunk loop.
- Verify that each worker is invoked via Task with appropriate context extracted from chunks.json.
- Verify that `state.json` updates correctly after every Task completion.
- Verify that the execution log is appended after every Task completion.
- Verify that the orchestrator commits chunks with targeted staging (not `git add -A`).
- Verify that HUMAN_REVIEW escalation works (e.g., architect flags an ambiguity).
- Verify that the orchestrator pushes the branch and creates a draft PR after all chunks pass integration.

---

## Priority 3: Quality Gate / Reflection Loop

### Objective

The per-chunk loop includes conditional feedback loops so that if the `code-security-reviewer` finds issues, the orchestrator routes back to the `feature-implementer` with specific fix instructions.

### Mechanism

The orchestrator reads the code-security-reviewer's Task response to determine PASS or FAIL. On FAIL, the orchestrator constructs a new Task prompt for the feature-implementer that includes the specific issues found, file paths, line numbers, and fix instructions.

### Reflection Loop Rules

1. **Maximum iterations per chunk:** 3 attempts at the security review stage. If the quality gate still fails after 3 iterations, the orchestrator escalates to HUMAN_REVIEW with a summary of all issues found.

2. **Iteration context:** Each reflection loop pass, the orchestrator includes in the implementer's Task prompt:
   - The original chunk implementation instructions
   - The specific issues found by the reviewer
   - The iteration count (so the implementer knows urgency increases)
   - File paths and line numbers where issues were found

3. **Loop scope:** The reflection loop runs between `feature-implementer` and `code-security-reviewer` only. Architectural issues escalate to HUMAN_REVIEW rather than trying to auto-fix.

4. **TDD-first pattern:** The `test-suite-generator` runs FIRST for each chunk, writing failing tests that define the chunk's success criteria. The implementer iterates on its implementation by running the test suite after each change until all tests pass. Only then does the security review run.

5. **Test-implementation loop:** The `feature-implementer` is allowed up to 3 internal iterations to make all tests pass. If tests are still failing after 3 iterations, the orchestrator escalates to HUMAN_REVIEW. This is separate from the security review iteration count.

6. **Post-security-fix regression check:** When the implementer receives fix instructions from a security review, it must re-run the existing test suite after applying fixes to ensure no regressions. If security fixes break tests, the implementer must resolve both issues within its iteration budget.

7. **Lint/format gate:** After all tests pass, the implementer runs `ruff check` + `ruff format --check` (Python) or `tsc --noEmit` + `eslint` (TypeScript) and fixes any issues before declaring implementation complete.

### Updated Per-Chunk Flow (TDD Pattern)

```
test-suite-generator (write failing tests for chunk N)
    │
    ▼
feature-implementer (implement until tests + lint pass, max 3 iterations)
    │
    ├── tests/lint failing → iterate (fix code, re-run, repeat)
    │                    │
    │                    ├── still failing after 3 attempts → HUMAN_REVIEW
    │                    └── passing → continue
    │
    └── tests + lint passing → continue
                          │
                          ▼
                 code-security-reviewer
                          │
                          ├── FAIL → feature-implementer (fix security issues)
                          │              │
                          │              ▼
                          │         re-run tests (regression check)
                          │              │
                          │              ├── tests broken → fix both, then back to reviewer
                          │              └── tests pass → back to reviewer
                          │
                          └── PASS → orchestrator commits chunk → next chunk
                                     (or integration-validator if last chunk)
```

### Per-Chunk Git Commit

When a chunk passes the security review gate, the **orchestrator** (not a hook script) commits all changes:

1. Read `chunks.json` → get `scope_boundary` + `shared_files` for current chunk
2. `git add` each file in `scope_boundary` and `shared_files`
3. `git add` corresponding test files (derived from scope_boundary paths using `tests/` mirror convention)
4. **Never** use `git add -A` or `git add .`
5. Commit with structured message (see CONTRACTS.md Section 4)

This produces a commit history that tells the story of iterative, quality-gated development:

```
feat(spec-3-enrichment/chunk-5): Dashboard integration for enrichment metrics
feat(spec-3-enrichment/chunk-4): Risk score aggregation pipeline
feat(spec-3-enrichment/chunk-3): Geo-location enrichment service
feat(spec-3-enrichment/chunk-2): IP reputation enrichment
feat(spec-3-enrichment/chunk-1): Redis Stream consumer setup
```

### Validation

- Intentionally introduce a security issue in a chunk's scope and verify the reflection loop catches it, feeds fix instructions to the implementer, and re-reviews.
- Verify that the max iteration count is respected and escalation to HUMAN_REVIEW works.
- Verify that iteration counts are tracked in `state.json`.
- Verify that per-chunk commits contain only files from `scope_boundary` + `shared_files` + test files.
- Verify that lint/format checks run as part of the implementation verification loop.

---

## Priority 4: Agent Teams for Parallel Test Generation (Optional)

### Objective

Use Claude Code Agent Teams to parallelize test generation for a single module, spawning teammates for unit tests, integration tests, and security tests simultaneously.

### Prerequisites

- Priorities 1-3 must be working and stable.
- Enable Agent Teams: set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in settings.json env.

### Scope

Apply Agent Teams to ONE well-bounded task only: generating the complete test suite for a single NAAS service after the feature-implementer completes all chunks for a spec.

### Team Configuration

Spawn three teammates from the `test-suite-generator` agent's completion:

| Teammate | Responsibility | File Scope |
|----------|---------------|------------|
| Unit Test Writer | Unit tests for individual functions/classes | `tests/unit/` |
| Integration Test Writer | Service-to-service integration tests | `tests/integration/` |
| Security Test Writer | Security-focused tests (injection, auth bypass, etc.) | `tests/security/` |

Teammates coordinate via the shared task list. Each teammate owns a non-overlapping file scope to prevent merge conflicts.

### Cost Considerations

Agent Teams run at approximately 15x standard token usage. Only use this for:
- Complete test suite generation after a full spec is implemented
- Not for per-chunk test generation (the sequential `test-suite-generator` handles that)

### Validation

- Run Agent Teams on Spec 1 (Event Ingestion) test generation as a proof of concept.
- Compare output quality and coverage against sequentially-generated tests.
- Measure token cost and wall-clock time savings.

---

## Implementation Order

### Phase 1: Agent Modernization (Priority 1)

**Estimated effort:** 3-4 hours

1. Create the `pipeline-orchestrator` agent with `tools:`, `model:`, and `memory:` frontmatter, and a system prompt defining the full state machine, Task prompt templates, commit logic, resume logic, cleanup logic, and budget guard.
2. Update the `technical-architect` agent to absorb plan decomposition: add chunks.json production, chunking rules, update tool list (`Read, Write, Grep, Glob, AskUserQuestion`), add pipeline mode instructions.
3. Remove the old `chunking` skill (`.claude/skills/chunk-plans/`) — its responsibilities are now owned by the `technical-architect`.
4. Update all five existing worker agent `.md` files: verify tool lists, add pipeline mode instructions (workers do not interact with state.json/chunks.json), add lint gate to implementer, add TDD verification to test-suite-generator.
5. Audit worker agent system prompts and remove duplicated project context. Ensure each agent's first-action instructions follow the Document Loading Convention.
6. Update `.gitignore` to track `.claude/pipeline/` (except `state.json` and `chunks.json`).
7. Verify the `pipeline-orchestrator` can create a branch, initialize state, and invoke the `technical-architect` via Task.
8. Verify the `technical-architect` can read a spec and produce both a plan file and a valid `chunks.json`.
9. Verify each worker agent still works correctly via manual invocation.

### Phase 2: Pipeline Orchestration (Priority 2)

**Estimated effort:** 3-4 hours

1. Implement the orchestrator's full state machine loop (pre-pipeline → architecture → per-chunk → integration → post-pipeline).
2. Implement the three-step post-Task update pattern (extract data → update state.json → append to log).
3. Implement per-chunk commit logic with targeted staging.
4. Implement resume logic (read state.json, determine position, re-enter loop).
5. Implement budget guard (pause at 30 invocations).
6. Test the full pipeline end-to-end on Spec 1 (Event Ingestion), from orchestrator invocation through draft PR creation.

### Phase 3: Quality Gates (Priority 3)

**Estimated effort:** 2-3 hours

1. Implement the reflection loop in the orchestrator's per-chunk logic: security review FAIL → re-invoke implementer with fix instructions → re-run review.
2. Implement max iteration enforcement (3 per quality gate stage).
3. Implement HUMAN_REVIEW escalation with detailed context.
4. Implement the post-security-fix regression check (implementer re-runs tests after applying security fixes).
5. Test the reflection loop by introducing deliberate issues.

### Phase 4: Agent Teams (Priority 4)

**Estimated effort:** 2 hours

1. Enable Agent Teams in settings.
2. Create a spawn prompt template for the three test-generation teammates.
3. Test on Spec 1's completed implementation.
4. Evaluate cost/benefit for continued use.

---

## SCM Strategy: Git and GitHub Integration

### Design Principle

Worker agents do not interact with git or GitHub directly. All source control operations are owned by the `pipeline-orchestrator`:
- **Pre-pipeline:** Branch creation
- **Per-chunk:** Targeted file staging and commits (after each security review PASS)
- **Post-pipeline:** Branch push and draft PR creation

This enforces a clean separation of concerns: worker agents reason about code, the orchestrator manages the development lifecycle.

### Branching Model

One feature branch per spec, squash-merged to `main` upon completion.

### Pre-Pipeline Phase (Orchestrator)

```bash
# Derived from developer prompt: "Implement Spec 3: Enrichment and Evaluation"
SPEC_SLUG="spec-3-enrichment"

git checkout main
git pull origin main
git checkout -b "feature/${SPEC_SLUG}"

mkdir -p .claude/pipeline/logs
cat > .claude/pipeline/state.json << EOF
{
  "contract_version": 2,
  "spec": "Spec 3: Enrichment and Evaluation",
  "spec_slug": "${SPEC_SLUG}",
  "branch": "feature/${SPEC_SLUG}",
  "phase": "starting",
  "current_chunk": 0,
  "total_chunks": 0,
  "invocation_count": 0,
  "chunks": [],
  "started_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "completed_at": null
}
EOF

echo "# Pipeline Run: Spec 3 — Enrichment and Evaluation" > ".claude/pipeline/logs/${SPEC_SLUG}.md"
echo "# Started: $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> ".claude/pipeline/logs/${SPEC_SLUG}.md"
```

### Per-Chunk Commits (Orchestrator)

After each chunk passes its security review quality gate, the orchestrator stages and commits with a structured message:

```bash
# Read chunk's file list from chunks.json
# Stage ONLY scope_boundary + shared_files + test files
git add services/signal-enrichment/app/consumer.py
git add services/signal-enrichment/app/models.py
git add docker-compose.yml
git add tests/unit/test_consumer.py
git add tests/unit/test_models.py

git commit -m "feat(spec-3-enrichment/chunk-1): Redis Stream consumer setup

Tests: 8 written, all passing
Implementation iterations: 1
Security review iterations: 1
Security issues caught: 0

Pipeline: auto-committed by agentic pipeline"
```

### Post-Pipeline Phase (Orchestrator)

```bash
STATE_FILE=".claude/pipeline/state.json"
SPEC_SLUG=$(jq -r '.spec_slug' "$STATE_FILE")
LOG_FILE=".claude/pipeline/logs/${SPEC_SLUG}.md"

# Push feature branch
git push -u origin "feature/${SPEC_SLUG}"

# Create draft PR with body generated from pipeline execution log
gh pr create \
  --draft \
  --title "Spec 3: Enrichment and Evaluation" \
  --body "$(cat <<EOF
## Summary
[Generated from pipeline execution log]

$(cat "${LOG_FILE}")

## Agentic Development Process
This implementation was produced by an automated agentic pipeline:
- **Orchestration:** \`pipeline-orchestrator\` managed the full pipeline lifecycle
- **Architecture:** \`technical-architect\` analyzed the spec and produced the chunked plan
- **TDD:** \`test-suite-generator\` wrote failing tests before each chunk
- **Implementation:** \`feature-implementer\` implemented each chunk iteratively
- **Security:** \`code-security-reviewer\` reviewed each chunk with reflection loops
- **Integration:** \`integration-validator\` verified cross-service behavior

See \`.claude/pipeline/logs/\` for full execution details.
EOF
)" \
  --base main \
  --head "feature/${SPEC_SLUG}"
```

**The developer's only manual git step:** review the draft PR and squash-merge to `main`.

### What Not to Do

**Do not create GitHub Issues.** The functional specs serve as the issue tracker. The `chunks.json` file serves as the task breakdown. The `state.json` file serves as the progress tracker.

**Do not create per-chunk PRs.** One PR per spec keeps the PR history clean and each PR represents a coherent, reviewable unit of functionality.

**Do not give worker agents direct access to git.** The `feature-implementer` should implement features, not manage version control. SCM operations belong in the orchestrator.

### Prerequisites

- `git` must be configured with credentials that allow push access to the NAAS repository.
- `gh` CLI must be installed and authenticated (`gh auth login`).
- Both tools should be verified during Phase 1 setup.

---

## Observability and Demonstration Artifacts

### Pipeline Execution Log

Each pipeline run produces a human-readable summary in `.claude/pipeline/logs/`. The orchestrator appends to this log after every Task completion — see CONTRACTS.md Section 5 for the format and the specific entries written at each phase.

This log is a demonstration artifact. It shows that the pipeline ran, caught real issues, and resolved them autonomously. The orchestrator includes it in the PR description during the post-pipeline phase.

### Pipeline Quality Report

After the draft PR is created, the orchestrator emits a per-spec quality report that summarizes the run's defense-in-depth receipts:

```bash
# Pseudocode — actual implementation lives in .claude/pipeline/phases/post-pipeline.md
mkdir -p .claude/pipeline/reports
REPORT_FILE=".claude/pipeline/reports/${SPEC_SLUG}-quality-report.md"

# Generate from state.json and the execution log
# Format defined in .claude/pipeline/CONTRACTS.md Section 6
```

The report is a durable, version-controlled artifact that records:
- Per-chunk metrics: tests written, implementation iterations, security review iterations, security issues caught
- Aggregate metrics: total tests, total reflection-loop firings, total HUMAN_REVIEW escalations
- Self-correction events: instances where the security review caught issues the implementer fixed without human intervention
- Defense-in-depth receipts: confirmation that iteration caps, budget guards, and regression checks operated as designed
- Time metrics: pipeline duration

The report serves three audiences: (a) the developer, who can scan it to confirm a clean run; (b) the code reviewer on the resulting PR, who can verify quality without reading the full execution log; (c) any future portfolio reviewer evaluating the agentic engineering discipline of the project. Schema details are in CONTRACTS.md Section 6.

### README Section

Add a section to the NAAS README describing the agentic development methodology:
- Link to `.claude/agents/` with brief descriptions of each agent's role, highlighting the `pipeline-orchestrator` as the entry point
- Link to `.claude/pipeline/CONTRACTS.md` for the inter-agent communication protocols
- Link to a sample pipeline execution log showing the reflection loop in action

---

## Key Design Principles

1. **The orchestrator manages the loop, workers do the work.** All pipeline control flow lives in the orchestrator's state machine. Workers are stateless specialists invoked via Task — they receive context, do their job, and return results.

2. **State is orchestrator-owned and inspectable.** The `state.json` file has a single writer (the orchestrator), is always consistent, and enables resume after interruptions. A developer can `cat state.json` at any time to see exactly where the pipeline stands.

3. **Human escalation is a feature, not a failure.** The pipeline surfaces hard problems to the developer rather than silently making bad decisions. A well-designed escalation path is more valuable than a fully autonomous loop that occasionally produces garbage.

4. **Start with the simplest spec.** Always test pipeline changes on Spec 1 (Event Ingestion) first. It's the smallest, most self-contained spec and will surface integration issues without wasting time on complex debugging.

5. **Each enhancement is independently valuable.** If time runs out after Priority 2, you still have a working automated pipeline. Priority 3 makes it smarter. Priority 4 makes one part faster.

6. **Workers are self-contained.** Workers receive everything they need in their Task prompt — they don't read pipeline state files, parse other agents' output, or know about the broader pipeline context. This makes them independently testable and reusable outside the pipeline.

7. **Let the artifacts tell the story.** Structured commit messages, rich PR descriptions auto-generated from pipeline logs, and the execution logs themselves provide all the project management visibility a demonstration project needs.
