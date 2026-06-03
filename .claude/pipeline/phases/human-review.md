# Human Review Protocol

Shared escalation and resume protocol used by all pipeline phases when the pipeline must pause for developer input.

## When to Escalate

Escalate when:
- The technical-architect flags ambiguity in the spec
- Test generation fails (no tests written, compilation errors, uninterpretable criteria)
- Implementation fails after 3 iterations (tests still failing)
- Security review fails after 3 iterations (unresolved issues)
- Feature-implementer fails to fix security issues (tests failing, lint errors, or agent reports failure)
- Integration validation fails

**Scope:** This protocol covers *failure-driven* escalations only. The budget guard is a separate, orchestrator-level pause (it does not enter the `human_review` phase and does not use the options/resume matrix below) — its behavior is defined in the `pipeline-orchestrator` skill's Budget-guard rule and CONTRACTS.md §5.2.11/§5.2.12/§5.3/§5.4. When a budget-guard pause and a failure-driven escalation arise from the same invocation, the budget-guard pause is handled first (see the skill's Budget-guard rule).

## Escalation Steps

1. Update state.json: set top-level `phase: "human_review"`. Leave the chunk-level `phase` at its current value (e.g., `"implementation"`, `"security_review"`) — this is how the orchestrator knows where to resume.
2. Append the bullet line defined in CONTRACTS.md §5.2.11 (`AWAITING INPUT`), substituting the `<reason>` from the §5.3 row that matches the current phase.
3. Use `AskUserQuestion` to present the issue to the developer. Always include:
   - What was attempted
   - What failed (specific errors, test names, security issues)
   - Suggested next steps
   - The available options (see below)

## Developer Options

The options vary by phase:

| Phase | Options |
|-------|---------|
| Architecture | (a) Provide clarification and retry, (b) Abort pipeline |
| Test generation | (a) Provide guidance and retry, (b) Abort pipeline |
| Implementation | (a) Provide guidance and retry (resets `impl_iterations` to 0), (b) Abort pipeline |
| Security review | (a) Provide guidance and retry (resets `sec_iterations` to 0), (b) Accept risk and proceed to commit, (c) Abort pipeline |
| Security fix | (a) Provide guidance and retry the security fix (does NOT reset `sec_iterations`), (b) Accept risk and proceed to commit, (c) Abort pipeline |
| Integration | (a) Retry integration validation, (b) Abort pipeline |

## Resume Steps

Each resolution appends a §5.2.12 (`RESUMED`) bullet to the log, substituting the `<decision>` from the matching §5.4 row. The "Accept risk" resolution additionally writes a §5.2.8 line immediately after.

Based on the developer's choice:

**Retry with guidance:**
- Append the §5.2.12 line with the `Retry with guidance` decision text from §5.4.
- Update state.json based on which sub-phase escalated:
  - if escalation came from the Implementation sub-phase: reset current chunk `impl_iterations` to 0
  - if escalation came from the Security Review sub-phase: reset current chunk `sec_iterations` to 0
  - if escalation came from the Architecture, Test Generation, Security Fix, or Integration phase: no counter reset
- Update state.json: set top-level `phase` to its pre-escalation value (e.g., `"implementing"`, `"architecture"`, `"integration_validation"`).
- Re-invoke the relevant worker agent with the developer's guidance included as additional context in the Task prompt.

**Accept risk** (security review or security fix):
- Append the §5.2.12 line with the `Accept risk` decision text from §5.4, immediately followed by the §5.2.8 line (`Security Review: ACCEPTED BY DEVELOPER`).
- Proceed to the commit sub-phase for this chunk.
- Update state.json: set top-level `phase: "implementing"`.

**Abort pipeline:**
- Append the §5.2.12 line with the `Abort pipeline` decision text from §5.4.
- If in a per-chunk phase, update state.json: set current chunk `status: "failed"`.
- Update state.json: set top-level `phase: "failed"`.
- STOP execution.

