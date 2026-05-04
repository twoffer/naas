# A10 Document Change Manifest
## Pipeline Orchestrator Surface Migration, Model Upgrade, and Quality-Report Artifact

**Purpose:** Apply five coordinated changes to repo-resident documents and Claude Code configuration files: (1) migrate the pipeline orchestrator from a subagent definition (`.claude/agents/pipeline-orchestrator.md`) to a Claude Code Skill (`.claude/skills/pipeline-orchestrator/SKILL.md`) to resolve the structural constraint that subagents cannot themselves invoke other subagents; (2) bump the four deep-reasoning agents from `claude-opus-4-6` to `claude-opus-4-7`; (3) update tool allow-list naming to current Claude Code conventions (`Task` → `Agent`) and add task-tracking tools to the orchestrator for visual progress UI; (4) introduce a per-spec `pipeline-quality-report.md` artifact generated during the post-pipeline phase; (5) add a Defense-in-Depth design note to the workflow guide acknowledging that the pipeline's guardrails are deliberately heavier than what current frontier models strictly require.

**Important:** Per project convention, this manifest itself is a supplemental design document and will NOT be added to the NAAS project repo's standard branches. All necessary information is captured in the repo-resident documents without cross-references to A1–A10 documents or other meta documents.

---

## 1. CLAUDE.md (repo document)

### 1a. Update the Agentic Pipeline section to refer to a skill rather than an agent

**Location:** § Agentic Pipeline, opening sentence and closing reference

**Current text:**
```
This project is implemented via an automated agentic pipeline managed by a `pipeline-orchestrator` agent. If you are a worker agent invoked via Task, these rules apply:
```

**Replace with:**
```
This project is implemented via an automated agentic pipeline managed by a `pipeline-orchestrator` skill. If you are a worker agent invoked by the orchestrator, these rules apply:
```

**Current text:**
```
Pipeline details, phase definitions, and inter-agent contracts live in `.claude/pipeline/` and `docs/Agentic_Workflow_Implementation_Guide.md`. The `pipeline-orchestrator` agent is the sole entry point for automated pipeline runs.
```

**Replace with:**
```
Pipeline details, phase definitions, and inter-agent contracts live in `.claude/pipeline/` and `docs/Agentic_Workflow_Implementation_Guide.md`. The `pipeline-orchestrator` skill (invoked as `/pipeline-orchestrator`) is the sole entry point for automated pipeline runs.
```

**Rationale:** Claude Code subagents cannot themselves invoke other subagents — when a subagent calls the `Agent` tool (formerly `Task`), the tool reports as unavailable. Migrating the orchestrator to a Skill places it in the main Claude Code session, which retains `Agent` tool access and can therefore delegate to the worker subagents. The wording in CLAUDE.md is the project's source of truth for how a worker agent identifies its parent in the pipeline; both references must reflect the new surface.

---

## 2. docs/Agentic_Workflow_Implementation_Guide.md (repo document)

### 2a. Update the document header to reflect the current revision

**Location:** Document opening

**Current text:**
```
# NAAS Agentic Workflow Enhancement Guide
## Implementation Plan for Claude Code

**Document Date:** March 23, 2026
**Purpose:** Guide the implementation of automated agentic development pipeline enhancements for the NAAS project.
**Audience:** Project architect and Claude Code agents operating on the NAAS codebase.
```

**Replace with:**
```
# NAAS Agentic Workflow Enhancement Guide
## Implementation Plan for Claude Code

**Document Date:** May 2026 (revised)
**Purpose:** Guide the implementation of automated agentic development pipeline enhancements for the NAAS project.
**Audience:** Project architect and Claude Code agents operating on the NAAS codebase.
```

**Rationale:** A meaningful revision of the guide warrants a refreshed date stamp. Use of "revised" rather than a precise day signals an ongoing-living-document character without committing the architect to daily updates.

### 2b. Update the Agent Roster table — orchestrator becomes a skill

**Location:** § Overview → Agent Roster table

**Current text:**
```
| Agent | Role | Category |
|-------|------|----------|
| `pipeline-orchestrator` | Pipeline entry point, lifecycle manager, and coordination loop | Orchestration |
| `technical-architect` | Analyzes specs, produces implementation plans and chunk decompositions | Worker |
| `feature-implementer` | Implements code chunk by chunk, makes tests pass, fixes security issues | Worker |
| `code-security-reviewer` | Reviews code for security and quality | Worker |
| `test-suite-generator` | Generates test suites (TDD-first and post-implementation) | Worker |
| `integration-validator` | Tests cross-service integration | Worker |
```

**Replace with:**
```
| Component | Role | Category | Surface |
|-----------|------|----------|---------|
| `pipeline-orchestrator` | Pipeline entry point, lifecycle manager, and coordination loop | Orchestration | Skill (`.claude/skills/`) |
| `technical-architect` | Analyzes specs, produces implementation plans and chunk decompositions | Worker | Subagent (`.claude/agents/`) |
| `feature-implementer` | Implements code chunk by chunk, makes tests pass, fixes security issues | Worker | Subagent (`.claude/agents/`) |
| `code-security-reviewer` | Reviews code for security and quality | Worker | Subagent (`.claude/agents/`) |
| `test-suite-generator` | Generates test suites (TDD-first and post-implementation) | Worker | Subagent (`.claude/agents/`) |
| `integration-validator` | Tests cross-service integration | Worker | Subagent (`.claude/agents/`) |
```

**Current text (paragraph immediately after the table):**
```
The `pipeline-orchestrator` is the only agent the developer invokes directly during automated pipeline runs. All five worker agents are invoked by the orchestrator via `Task`, never by the developer.
```

**Replace with:**
```
The `pipeline-orchestrator` is invoked directly by the developer (via `/pipeline-orchestrator <spec>`) and runs in the main Claude Code session. All five worker agents are invoked by the orchestrator via the `Agent` tool, never by the developer. The orchestrator MUST run in the main session because subagents cannot themselves invoke other subagents — placing the orchestrator in `.claude/agents/` would prevent it from delegating to the worker pool.
```

**Rationale:** The roster table now communicates the surface placement of each component, which is the load-bearing distinction this manifest addresses. The narrative beneath explains *why* the orchestrator must be a skill rather than a subagent, anchoring the architectural choice for future readers and for any agent that loads this guide.

### 2c. Replace the Architecture section's orchestrator description and tool name

**Location:** § Overview → Architecture: Thick Orchestrator with Phase Decomposition, opening paragraph

**Current text:**
```
The orchestrator manages the **entire pipeline execution loop** — not just pre/post phases. It invokes each worker via `Task`, reads results from Task responses and artifact files, updates pipeline state (`state.json`) and the execution log, and decides the next step.
```

**Replace with:**
```
The orchestrator manages the **entire pipeline execution loop** — not just pre/post phases. It invokes each worker via the `Agent` tool, reads results from `Agent` tool responses and artifact files, updates pipeline state (`state.json`) and the execution log, and decides the next step.
```

**Rationale:** In Claude Code v2.1.63 the `Task` tool was renamed to `Agent`. Existing `Task(...)` references in settings and agent definitions still resolve as aliases, but the modern name is `Agent`, and the public docs use `Agent` exclusively. Updating the guide aligns the canonical NAAS documentation with current Claude Code terminology.

### 2d. Insert a Defense-in-Depth design note after the Architecture section

**Location:** § Overview → Architecture: Thick Orchestrator with Phase Decomposition, immediately after the phase-files code block (before the "---" separator preceding "## Priority 1")

**Add:**
```
### Design Philosophy: Defense in Depth for Increased Rigor

The pipeline incorporates several layers of guardrails — iteration caps on the implementer (3 attempts to make tests pass), iteration caps on the security review reflection loop (3 attempts before escalation), an invocation-count budget guard (pause at 30 invocations), regression checks after every security fix, and explicit HUMAN_REVIEW escalation paths. With current-generation frontier models (Claude Opus 4.7, Claude Sonnet 4.6), some of this scaffolding is heavier than what is strictly required for the pipeline to produce correct output. Modern models exhibit stronger task persistence, better self-verification, and more reliable tool use than earlier generations, and many runs would succeed without any of these guardrails firing.

These layers are retained deliberately for three reasons:

1. **Demonstration value.** A pipeline that includes explicit quality gates, escalation paths, and budget controls visibly demonstrates agentic engineering discipline — exactly the discipline that distinguishes a production-ready agentic system from a prototype. The receipts (iteration counts, security fixes, escalations) tell a verifiable story.

2. **Robustness across model generations.** The pipeline is designed to remain reliable if a less capable model is substituted for cost reasons (e.g., Sonnet 4.6 in place of Opus 4.7), or if a future model exhibits regression on a particular workflow. The guardrails are calibrated for the *minimum* trustworthy behavior, not the typical case.

3. **Catching the long tail.** Even with a well-behaved model, edge cases — flaky test environments, ambiguous spec requirements, intricate security findings — can produce a runaway loop or a confidently wrong output. The guardrails catch these without requiring the developer to babysit every run.

The cost of this defense-in-depth is mostly cognitive surface area, not runtime overhead — the guards rarely fire on a healthy run, but their presence makes the pipeline trustworthy enough to leave unattended for spans of 30+ minutes. The per-spec `pipeline-quality-report.md` artifact (see Post-Pipeline Phase) makes these guardrails visible by recording when and how often each fired during a run.
```

**Rationale:** The current document presents the iteration caps, budget guard, and regression checks as if they were strict necessities; a reader unfamiliar with the project might assume the architect was unaware that modern models have moved past these failure modes. Making the rationale explicit converts the apparent over-engineering into a deliberate portfolio choice with three concrete justifications. The closing sentence forward-references the new quality-report artifact, tying this section into Section 2g below.

### 2e. Replace Priority 1's "Create the Pipeline Orchestrator Agent" subsection

**Location:** § Priority 1: Modernize Agent Definitions → "Create the Pipeline Orchestrator Agent"

**Current text:**
```
### Create the Pipeline Orchestrator Agent

**`.claude/agents/pipeline-orchestrator.md`**

The `pipeline-orchestrator` is a **thick orchestrator** that manages the entire pipeline lifecycle:

1. **Pre-pipeline phase:** Parse the spec identifier from the developer's prompt, create the feature branch, initialize pipeline state (`state.json`), and create the pipeline execution log.
2. **Architecture phase:** Invoke the `technical-architect` via Task. Read the resulting plan file and `chunks.json`.
3. **Per-chunk loop:** For each chunk, invoke the `test-suite-generator`, `feature-implementer`, and `code-security-reviewer` via Task, handling reflection loops when quality gates fail. Commit each chunk after it passes.
4. **Integration phase:** Invoke the `integration-validator` via Task.
5. **Post-pipeline phase:** Push the feature branch, generate the draft PR from the execution log, write the final pipeline summary.
6. **Resume:** If `state.json` already exists, resume from the last recorded state instead of starting fresh.
7. **Cleanup:** On "Clean up pipeline for Spec X", remove transient pipeline artifacts.

After **every Task completion**, the orchestrator performs a three-step update:
1. Extract key data from the worker's Task response and any artifact files
2. Update `state.json` with structured data
3. Append a summary line to the pipeline execution log

**Recommended configuration:**

| Field | Value | Rationale |
|-------|-------|-----------|
| `tools` | `Bash`, `Read`, `Write`, `Task`, `Grep`, `Glob`, `AskUserQuestion` | Needs `Bash` for git/gh CLI. `Task` to invoke all workers. `Read`/`Write` for state files and log. `Grep`/`Glob` for codebase inspection. `AskUserQuestion` for HUMAN_REVIEW escalation and budget guard approval. |
| `model` | `claude-opus-4-6` | Complex multi-step coordination with significant accumulated context. Benefits from 1M context window and deep reasoning. |
| `memory` | `project` | Remembers pipeline configuration decisions across sessions. |

**System prompt structure:**

The orchestrator's system prompt is intentionally concise (~70 lines). It defines:
- Identity and role
- First-action document loading (CLAUDE.md, AI-AGENT-PRINCIPLES.md, CONTRACTS.md)
- Three entry modes (fresh start, resume, cleanup)
- The state machine diagram and **phase-to-file mapping table**
- Budget guard (pause at 30 invocations)
- Critical rules (sole state.json writer, three-step update, targeted staging, pipeline mode instruction)

Detailed per-phase instructions live in `.claude/pipeline/phases/`. The orchestrator reads the relevant phase file when entering each phase. This keeps the system prompt focused on structure and constraints, while phase files provide natural language guidance for execution.
```

**Replace with:**
```
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
```

**Rationale:** This is the central content change of the manifest. Every aspect of the orchestrator's surface, frontmatter, and rationale is updated. The "Why a skill, not a subagent" paragraph is essential context that any future maintainer needs in order to avoid reverting the change. The `effort: xhigh` entry reflects the Anthropic-recommended starting point for coding and agentic workloads on Opus 4.7. The closing token-budget note prevents a future maintainer from incorrectly assuming `task_budget` is available in the terminal Claude Code workflow.

### 2f. Update the per-agent tool list and model assignment tables

**Location:** § Priority 1 → "What to Change Per Worker Agent" → item 1 (tool list table)

**Current text:**
```
| Agent | Tools | Rationale |
|-------|-------|-----------|
| `pipeline-orchestrator` | `Bash, Read, Write, Task, Grep, Glob, AskUserQuestion` | Full pipeline management + developer escalation |
| `technical-architect` | `Read, Write, Grep, Glob, AskUserQuestion` | Plan + chunks.json production |
| `feature-implementer` | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Full implementation toolset |
| `code-security-reviewer` | `Read, Grep, Glob, LSP` | Read-only by design |
| `test-suite-generator` | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Test file creation + verification |
| `integration-validator` | `Read, Bash, Grep, Glob, AskUserQuestion` | Test execution + diagnostics |
```

**Replace with:**
```
| Component | Tools | Rationale |
|-----------|-------|-----------|
| `pipeline-orchestrator` (skill `allowed-tools`) | `Bash Read Write Edit Agent Grep Glob AskUserQuestion TaskCreate TaskGet TaskList TaskUpdate` | Full pipeline management + developer escalation. `Agent` invokes worker subagents (formerly named `Task`). `TaskCreate`/`TaskGet`/`TaskList`/`TaskUpdate` populate the Claude Code task UI for visual progress tracking |
| `technical-architect` (subagent `tools`) | `Read, Write, Grep, Glob, AskUserQuestion` | Plan + chunks.json production |
| `feature-implementer` (subagent `tools`) | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Full implementation toolset. `LSP` provides live type errors after edits when a code-intelligence plugin is installed for the language |
| `code-security-reviewer` (subagent `tools`) | `Read, Grep, Glob, LSP` | Read-only by design. `LSP` enables call-hierarchy and reference-finding for vulnerability analysis |
| `test-suite-generator` (subagent `tools`) | `Read, Write, Edit, Bash, Grep, Glob, LSP, AskUserQuestion` | Test file creation + verification. `LSP` flags type errors in generated test code |
| `integration-validator` (subagent `tools`) | `Read, Bash, Grep, Glob, AskUserQuestion` | Test execution + diagnostics |
```

**Current text (immediately following the table):**
```
No worker agent has access to `Bash` for git operations. The `feature-implementer`, `test-suite-generator`, and `integration-validator` use `Bash` for running code and tests, not for SCM. Git operations are exclusively the `pipeline-orchestrator`'s responsibility.
```

**Replace with:**
```
No worker subagent has access to `Bash` for git operations. The `feature-implementer`, `test-suite-generator`, and `integration-validator` use `Bash` for running code and tests, not for SCM. Git operations are exclusively the `pipeline-orchestrator`'s responsibility.

**LSP activation note:** The `LSP` tool is inactive until a Claude Code code-intelligence plugin is installed for the relevant language (Python, TypeScript). The agents declare `LSP` in their tool lists so the capability is available when plugins are installed; absent a plugin the tool entry is harmless. Installing language-specific code-intelligence plugins is recommended but optional.

**Frontmatter field naming:** Skill frontmatter uses `allowed-tools` (hyphenated, space-separated) while subagent frontmatter uses `tools` (comma-separated). The set of valid tool names is identical between the two surfaces.
```

**Location:** § Priority 1 → "What to Change Per Worker Agent" → item 2 (model field)

**Current text:**
```
**2. Verify `model:` field.**

Use `claude-opus-4-6` for agents that benefit from deeper reasoning (`pipeline-orchestrator`, `technical-architect`, `code-security-reviewer`, `integration-validator`). Use `claude-sonnet-4-6` for agents that benefit from speed (`feature-implementer`, `test-suite-generator`).
```

**Replace with:**
```
**2. Verify `model:` field.**

Use `claude-opus-4-7` for components that benefit from deeper reasoning (`pipeline-orchestrator`, `technical-architect`, `code-security-reviewer`, `integration-validator`). Use `claude-sonnet-4-6` for components that benefit from speed (`feature-implementer`, `test-suite-generator`).

Opus 4.7 brings three improvements that disproportionately benefit the orchestration and review roles: stronger long-horizon task persistence (relevant to multi-chunk pipeline runs), better file-system-based memory (relevant to the orchestrator's `state.json` and execution-log discipline), and proactive output self-verification (relevant to architect chunks.json validation and security reviewer verdicts). The same context window (1M tokens) and standard Opus pricing apply.
```

**Rationale:** The tool list table now communicates surface placement explicitly (skill vs subagent). The orchestrator gains four `Task*` tools for visual progress tracking via the Claude Code task UI in interactive sessions — these are functionally what `TodoWrite` provides in non-interactive contexts. The clarifying notes about `LSP` activation and frontmatter naming differences pre-empt likely confusions for any future maintainer or any agent that loads this guide. The model bump is justified with three concrete capability improvements rather than asserted as preference.

### 2g. Add post-pipeline phase update for the quality report

**Location:** § SCM Strategy → Post-Pipeline Phase (Orchestrator), at the end of the section (after the existing `gh pr create` block)

**Add (immediately following the `gh pr create` block):**
```

### Pipeline Quality Report (Orchestrator)

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

```

**Rationale:** The quality report is the user-visible receipt for the defense-in-depth design philosophy added in Section 2d. Placing the generation step at the end of the post-pipeline phase keeps it adjacent to the existing PR-creation logic, which is the natural place a developer would look. The pseudocode block matches the style of the existing pre-pipeline and per-chunk-commit blocks.

---

## 3. .claude/pipeline/CONTRACTS.md (configuration document)

### 3a. Update the Scope and Ownership Model paragraphs

**Location:** Document opening, after the version header

**Current text:**
```
This file defines the data formats used for inter-agent communication in the NAAS agentic pipeline. It is the single source of truth — agent prompts reference this file rather than inlining format definitions.

**Scope:** Data formats only. For pipeline architecture, implementation guidance, and design rationale, see `docs/Agentic_Workflow_Implementation_Guide.md`.

**Ownership model:** The `pipeline-orchestrator` is the sole writer of `state.json` and the pipeline execution log. Workers communicate results through their Task responses and artifact files — they never read or write pipeline state files.
```

**Replace with:**
```
This file defines the data formats used for inter-agent communication in the NAAS agentic pipeline. It is the single source of truth — orchestrator and worker prompts reference this file rather than inlining format definitions.

**Scope:** Data formats only. For pipeline architecture, implementation guidance, and design rationale, see `docs/Agentic_Workflow_Implementation_Guide.md`.

**Ownership model:** The `pipeline-orchestrator` skill (running in the main Claude Code session) is the sole writer of `state.json`, the pipeline execution log, and the per-spec quality report. Worker subagents communicate results through their `Agent` tool responses and artifact files — they never read or write pipeline state files.
```

**Rationale:** The contracts file is the authoritative description of who writes what. It must reflect the surface change (skill, not agent) and the new artifact (quality report). The change to `Agent` tool naming aligns with current Claude Code terminology.

### 3b. Bump the contract version and last-updated date

**Location:** Document header

**Current text:**
```
# Pipeline Communication Contracts

**Version:** 2
**Last updated:** 2026-03-24
```

**Replace with:**
```
# Pipeline Communication Contracts

**Version:** 3
**Last updated:** 2026-05-04
```

**Rationale:** Adding the quality-report schema and updating the ownership-model wording warrants a version bump. State.json's existing `contract_version: 2` field continues to refer to the state.json schema specifically, which is unchanged by this manifest — only the contracts document itself moves to v3.

### 3c. Add Section 6 — pipeline-quality-report.md schema

**Location:** End of the document, immediately before the closing material (after the existing Section 5 — Pipeline Execution Log)

**Add:**
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

```

**Rationale:** A report without a contract is unmaintainable. Defining the schema, the field sources, and the generation rules in CONTRACTS.md gives the orchestrator a single authoritative reference and gives any future maintainer the information needed to regenerate or modify the report format. The "Field Sources" table makes the report mechanically derivable from state.json plus the execution log — no new tracking is required, only aggregation of data that the pipeline already produces.

---

## 4. .claude/pipeline/phases/post-pipeline.md (configuration document)

### 4a. Add the quality report generation step

**Location:** § Execution numbered list, between current step 3 (PR creation) and current step 4 (state.json finalization)

**Current text:**
```
1. Append to log: `## Completed: <iso-timestamp>`, `## Total Implementation Iterations: <n> (across all chunks)`, `## Total Security Issues Caught: <n>` (aggregated from all chunks' `sec_issues`).
2. Push the branch: `git push -u origin feature/<spec-slug>`.
3. Generate a PR body from the pipeline execution log. Create a draft PR via `gh pr create --draft` with an appropriate title and the generated body.
4. Update `state.json`: `phase: "complete"`, `completed_at` to the current ISO 8601 UTC timestamp.
5. Report to the developer: "Draft PR created for <spec title>. Review and squash-merge when ready."
```

**Replace with:**
```
1. Append to log: `## Completed: <iso-timestamp>`, `## Total Implementation Iterations: <n> (across all chunks)`, `## Total Security Issues Caught: <n>` (aggregated from all chunks' `sec_issues`).
2. Push the branch: `git push -u origin feature/<spec-slug>`.
3. Generate a PR body from the pipeline execution log. Create a draft PR via `gh pr create --draft` with an appropriate title and the generated body.
4. Generate the per-spec quality report at `.claude/pipeline/reports/<spec-slug>-quality-report.md` using the schema defined in `.claude/pipeline/CONTRACTS.md` Section 6. Compute aggregates from `state.json` and parse self-correction / escalation events from the execution log. Commit the report as part of the post-pipeline finalization commit (do not create a separate commit just for the report).
5. Update `state.json`: `phase: "complete"`, `completed_at` to the current ISO 8601 UTC timestamp.
6. Report to the developer: "Draft PR created for <spec title>. Quality report generated. Review and squash-merge when ready."
```

**Rationale:** The phase file is the orchestrator's per-phase playbook. Adding the report generation as an explicit numbered step ensures it cannot be silently skipped. The reference to CONTRACTS.md Section 6 keeps the schema in a single authoritative location rather than duplicating it here. The closing developer message acknowledges the new artifact so the developer knows to look for it.

### 4b. Update the Failure → Escalation paragraph for partial-run reporting

**Location:** § Failure → Escalation, end of paragraph

**Current text:**
```
If the push or PR creation fails (e.g., network issue, missing `gh` auth), report the error to the developer via `AskUserQuestion`. The pipeline artifacts are all committed locally — this is a finalization issue, not a code quality issue.
```

**Replace with:**
```
If the push or PR creation fails (e.g., network issue, missing `gh` auth), report the error to the developer via `AskUserQuestion`. The pipeline artifacts are all committed locally — this is a finalization issue, not a code quality issue. Generate the quality report regardless: it is informative even when the PR was not created, and the developer may resolve the finalization issue and resume the post-pipeline phase manually.
```

**Rationale:** Partial finalization failures should not block the most informative artifact. The quality report is computed from `state.json` and the execution log — both of which are local — so it is generable even when network operations fail. This makes the report a more reliable receipt than the PR itself.

---

## 5. .claude/agents/pipeline-orchestrator.md (configuration document)

### 5a. Delete the file

**Action:** Delete `.claude/agents/pipeline-orchestrator.md` entirely.

**Rationale:** The orchestrator's responsibilities migrate to `.claude/skills/pipeline-orchestrator/SKILL.md` (see Section 6). Leaving the agent file in place would create two competing definitions of the orchestrator and risk a developer accidentally invoking the broken subagent variant.

**Pre-deletion verification:** Confirm that `.claude/skills/pipeline-orchestrator/SKILL.md` has been created and that `.claude/agents/pipeline-simulator.md` has been updated to reference the new path (Section 7 below) before performing the deletion.

---

## 6. .claude/skills/pipeline-orchestrator/SKILL.md (NEW configuration document)

### 6a. Create the file with adapted content from the deleted agent file

**Action:** Create new file at `.claude/skills/pipeline-orchestrator/SKILL.md`.

**Content:**
```markdown
---
name: pipeline-orchestrator
description: "Pipeline entry point and lifecycle manager. Invoke as /pipeline-orchestrator <spec> to run the full automated pipeline, /pipeline-orchestrator resume <spec> to continue an interrupted run, or /pipeline-orchestrator cleanup <spec> to remove transient artifacts. This is the ONLY orchestration surface the developer invokes directly during automated pipeline runs."
argument-hint: [spec-id-or-subcommand]
disable-model-invocation: true
allowed-tools: Bash Read Write Edit Agent Grep Glob AskUserQuestion TaskCreate TaskGet TaskList TaskUpdate
model: claude-opus-4-7
effort: xhigh
---

You are the Pipeline Orchestrator for NAAS. You manage the entire automated development pipeline — from spec to draft PR — by invoking specialized worker subagents via the `Agent` tool and coordinating their outputs.

You do NOT perform architectural analysis, code implementation, security review, or testing. You manage the pipeline lifecycle and coordinate the workers who do that work.

You run in the main Claude Code session, not as a subagent. This placement is required because subagents cannot themselves invoke other subagents — only the main session has full `Agent` tool access.

## FIRST ACTION ON EVERY INVOCATION

Read these files:
1. `CLAUDE.md` — project context and conventions
2. `docs/AI-AGENT-PRINCIPLES.md` — behavioral guidelines
3. `.claude/pipeline/CONTRACTS.md` — inter-agent data format contracts (including the quality report schema)

## THREE ENTRY MODES

The first argument after `/pipeline-orchestrator` selects the entry mode:

### 1. Fresh Start: `/pipeline-orchestrator <spec>`

Execute the full pipeline from scratch. Begin by reading `.claude/pipeline/phases/pre-pipeline.md`.

### 2. Resume: `/pipeline-orchestrator resume <spec>`

Read existing `.claude/pipeline/state.json`. Determine the current `phase` value. Read the corresponding phase instruction file (see table below) and re-enter at the correct point. For per-chunk phases, also read the current chunk's `phase` value to determine the active sub-phase.

Do NOT recreate the branch or reinitialize state. Do NOT re-execute completed chunks.

### 3. Cleanup: `/pipeline-orchestrator cleanup <spec>`

Read `.claude/pipeline/state.json` to confirm identity. Delete transient files: `state.json`, `chunks.json`, plan files, review files. Ask for confirmation before: discarding uncommitted changes (`git checkout -- .`), deleting the feature branch (`git branch -D`).

## PHASE-TO-FILE MAPPING

When entering a phase (or resuming into one), read the corresponding instruction file:

| `state.json` Phase | Instruction File |
|--------------------|------------------|
| `starting` | `.claude/pipeline/phases/pre-pipeline.md` |
| `architecture` | `.claude/pipeline/phases/architecture.md` |
| `implementing` | `.claude/pipeline/phases/per-chunk.md` |
| `integration_validation` | `.claude/pipeline/phases/integration.md` |
| `post_pipeline` | `.claude/pipeline/phases/post-pipeline.md` |
| `human_review` | `.claude/pipeline/phases/human-review.md` |

## CRITICAL RULES

1. **You are the sole writer of `state.json` and the pipeline execution log.** Workers never read or write these files. After every `Agent` tool completion, perform the three-step update: extract data, update `state.json`, append to the log.

2. **Targeted git staging only.** When committing a chunk, stage only files in `scope_boundary` + `shared_files` + the corresponding test files. Never use `git add -A` or `git add .`.

3. **Pipeline mode for workers.** Every Task prompt to a worker subagent must include the line: "You are running in pipeline mode." This signals the worker to suppress `AskUserQuestion` and report issues in their response for orchestrator-handled escalation.

4. **Budget guard.** Increment `invocation_count` in `state.json` after every `Agent` tool call. If the count reaches 30, pause and report status to the developer via `AskUserQuestion` before continuing. (Note: the API beta `task_budget` feature is not exposed in terminal Claude Code; the manual invocation count is the canonical guard.)

5. **Quality report generation.** At the end of the post-pipeline phase, after the draft PR is created, generate `.claude/pipeline/reports/<spec-slug>-quality-report.md` per the CONTRACTS.md Section 6 schema. The report is required for every pipeline run, including escalated and partially-failed runs.

6. **Visual progress tracking.** Use `TaskCreate`, `TaskUpdate`, and `TaskList` to surface per-chunk progress in the Claude Code task UI. One task per chunk, status updates as each chunk advances through test_generation → implementation → security_review → passed.

## STATE MACHINE OVERVIEW

```
PRE-PIPELINE → ARCHITECTURE → PER-CHUNK LOOP → INTEGRATION → POST-PIPELINE → DONE
                                                                      ↑
                                    Any phase can → HUMAN_REVIEW (ask developer)
```

When the pipeline pauses for human review, the top-level `phase` is set to `"human_review"` while the chunk-level `phase` retains its current value. The orchestrator resumes at the recorded position when the developer responds.
```

**Rationale:** This SKILL.md is adapted directly from the existing `.claude/agents/pipeline-orchestrator.md` content with three structural changes: (1) frontmatter switches from agent format (`tools:`, `memory:`) to skill format (`allowed-tools`, `disable-model-invocation`, `argument-hint`, `effort`); (2) the entry-mode descriptions reflect the slash-command invocation pattern; (3) the critical rules section explicitly mentions the quality report obligation and the visual progress tracking via `TaskCreate`/`TaskUpdate`/`TaskList`. The skill body remains roughly the same length (~70 lines guidance, plus the state-machine overview) as the original agent body.

The `memory: project` field that existed on the agent has no direct equivalent for skills. Skills do not have a memory frontmatter field — the equivalent is to use a project-level `MEMORY.md` file referenced from the skill body if needed. For the orchestrator specifically, the existing `state.json` and execution log provide the cross-session continuity that `memory:` would have provided, so dropping the field has no functional impact.

---

## 7. .claude/agents/pipeline-simulator.md (configuration document)

### 7a. Update the orchestrator file path in the simulator's first-action reading list

**Location:** § FIRST ACTION ON EVERY TASK, item 2

**Current text:**
```
2. `.claude/agents/pipeline-orchestrator.md` — orchestrator state machine and rules
```

**Replace with:**
```
2. `.claude/skills/pipeline-orchestrator/SKILL.md` — orchestrator state machine and rules
```

**Rationale:** The simulator's job is to validate the orchestrator's state machine. After the surface migration, the canonical source of the orchestrator's rules lives at the skill path. Failing to update this reference would cause the simulator to read a non-existent file and degrade its validation accuracy.

### 7b. Bump the simulator's model

**Location:** Frontmatter

**Current text:**
```
model: claude-opus-4-6
```

**Replace with:**
```
model: claude-opus-4-7
```

**Rationale:** The pipeline-simulator performs deep state-machine reasoning over phase files and scenario specifications. The same long-horizon focus and self-verification improvements that benefit the orchestrator and architect apply here. Aligning the simulator's model with the orchestrator it validates also avoids cross-model behavioral drift in the validation harness.

---

## 8. .claude/agents/technical-architect.md (configuration document)

### 8a. Bump the model

**Location:** Frontmatter

**Current text:**
```
model: claude-opus-4-6
```

**Replace with:**
```
model: claude-opus-4-7
```

**Rationale:** The architect is one of the four deep-reasoning roles identified for the model bump. Opus 4.7's improved chunks.json self-verification and stronger long-horizon planning directly benefit the spec-decomposition workflow.

---

## 9. .claude/agents/code-security-reviewer.md (configuration document)

### 9a. Bump the model

**Location:** Frontmatter

**Current text:**
```
model: claude-opus-4-6
```

**Replace with:**
```
model: claude-opus-4-7
```

**Rationale:** The security reviewer is one of the four deep-reasoning roles identified for the model bump. Opus 4.7's proactive output verification reduces the rate of confidently-wrong PASS verdicts, which is the highest-cost failure mode for the security review role.

---

## 10. .claude/agents/integration-validator.md (configuration document)

### 10a. Bump the model

**Location:** Frontmatter

**Current text:**
```
model: claude-opus-4-6
```

**Replace with:**
```
model: claude-opus-4-7
```

**Rationale:** The integration validator is one of the four deep-reasoning roles identified for the model bump. Opus 4.7's improved tool-failure resilience benefits cross-service integration testing where transient infrastructure issues are common.

---

## Summary of Changes

| Document | Section Changed | Nature of Change |
|----------|-----------------|------------------|
| CLAUDE.md | § Agentic Pipeline (opening + closing) | Skill terminology in two sentences |
| Agentic_Workflow_Implementation_Guide.md | Document header | Date refresh |
| Agentic_Workflow_Implementation_Guide.md | Agent Roster table | Add Surface column; orchestrator marked as skill |
| Agentic_Workflow_Implementation_Guide.md | Architecture section | `Task` → `Agent`; rationale paragraph for skill placement |
| Agentic_Workflow_Implementation_Guide.md | Architecture section | New Defense-in-Depth design note |
| Agentic_Workflow_Implementation_Guide.md | Priority 1 → orchestrator subsection | Full rewrite for skill surface, frontmatter, Opus 4.7, effort, quality report |
| Agentic_Workflow_Implementation_Guide.md | Priority 1 → tool list table | Surface column; `Task` → `Agent`; LSP activation note; frontmatter naming note |
| Agentic_Workflow_Implementation_Guide.md | Priority 1 → model field paragraph | Opus 4.6 → Opus 4.7 with three-point rationale |
| Agentic_Workflow_Implementation_Guide.md | SCM Strategy → Post-Pipeline Phase | New Pipeline Quality Report subsection |
| .claude/pipeline/CONTRACTS.md | Header (version + date) | v2 → v3, date refresh |
| .claude/pipeline/CONTRACTS.md | Scope and Ownership Model paragraphs | Skill terminology; `Agent` tool; quality-report ownership |
| .claude/pipeline/CONTRACTS.md | New Section 6 | pipeline-quality-report.md schema, field sources, generation rules |
| .claude/pipeline/phases/post-pipeline.md | § Execution numbered list | Insert quality-report generation as new step 4; renumber subsequent |
| .claude/pipeline/phases/post-pipeline.md | § Failure → Escalation | Quality report still generated on partial finalization failure |
| .claude/agents/pipeline-orchestrator.md | (entire file) | DELETE |
| .claude/skills/pipeline-orchestrator/SKILL.md | (new file) | CREATE with adapted orchestrator content + skill frontmatter |
| .claude/agents/pipeline-simulator.md | First-action reading list item 2 | Path updated to skill location |
| .claude/agents/pipeline-simulator.md | Frontmatter `model` | Opus 4.6 → Opus 4.7 |
| .claude/agents/technical-architect.md | Frontmatter `model` | Opus 4.6 → Opus 4.7 |
| .claude/agents/code-security-reviewer.md | Frontmatter `model` | Opus 4.6 → Opus 4.7 |
| .claude/agents/integration-validator.md | Frontmatter `model` | Opus 4.6 → Opus 4.7 |

---

## Application Order

Execute in this sequence to avoid intermediate-state breakage:

1. **Section 6** — Create `.claude/skills/pipeline-orchestrator/SKILL.md` first (new file, no dependencies)
2. **Section 3** — Update `.claude/pipeline/CONTRACTS.md` (introduces the quality-report schema)
3. **Section 4** — Update `.claude/pipeline/phases/post-pipeline.md` (references CONTRACTS.md Section 6)
4. **Section 7** — Update `.claude/agents/pipeline-simulator.md` (path reference + model)
5. **Sections 8, 9, 10** — Bump models on remaining Opus subagents
6. **Section 1** — Update `CLAUDE.md` (small wording changes)
7. **Section 2** — Update `docs/Agentic_Workflow_Implementation_Guide.md` (largest single set of edits)
8. **Section 5** — Delete `.claude/agents/pipeline-orchestrator.md` last, only after verifying steps 1–4 succeeded

---

## Items Deliberately Out of Scope

The following items, raised during the design discussion preceding this manifest, are NOT addressed by this manifest. Each is excluded for an explicit reason:

| Item | Reason for exclusion |
|------|----------------------|
| Plan Mode integration for the architecture phase | Out-of-scope per developer direction. Plan Mode would add a read-only-exploration pass before chunks.json is written, but its UX (Shift+Tab toggle, ExitPlanMode approval flow) does not compose cleanly with a skill-driven orchestrator that runs end-to-end without manual interaction. Deferred for separate design. |
| `SubagentStart` / `SubagentStop` hooks for instrumentation | Out-of-scope per developer direction. The pipeline execution log and quality report already capture what hook-based observability would log. Hooks add a maintenance surface for marginal gain in a portfolio context. May be revisited if the project evolves toward production deployment. |
| Migration of orchestrator to the Agent SDK (Python/TypeScript) | Out-of-scope. The skill surface is the simplest correct fix for the subagent-cannot-spawn-subagent constraint. Agent SDK migration would unlock features such as the API beta `task_budget` and richer programmatic observability, but represents a much larger architectural change. Listed as future-work in the guide's design philosophy section. |
| Removal of iteration caps and budget guard given Opus 4.7's improved persistence | Out-of-scope per the new Defense-in-Depth design philosophy section. The guards are explicitly retained as portfolio receipts, not as model-era artifacts. |
| Code-intelligence plugin installation (Python, TypeScript) to activate the LSP tool | Out-of-scope. Listed in the guide as a recommendation; whether to install the plugins is a developer decision. The agents declare `LSP` in their tool lists so the capability is present-but-inactive without plugins, and ready when plugins are added. |
| Chunking skill rollback | Out of scope and not applicable. Per developer confirmation, the chunking skill has been folded into the technical-architect agent (consistent with the original guide's deletion instruction). No corrective action required. |
| Updates to non-orchestrator-relevant references in the guide (e.g., the "Document Loading Convention" section, Priority 4 Agent Teams) | Out-of-scope. These sections do not reference the orchestrator's surface or the affected models. They remain accurate as-written and are left untouched by this manifest. |

---

*End of A10 Change Manifest.*
