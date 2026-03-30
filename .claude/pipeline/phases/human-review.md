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

## Escalation Steps

1. Update `state.json`: set the **top-level** `phase: "human_review"`. Leave the **chunk-level** phase at its current value (e.g., `"implementation"`, `"security_review"`) — this is how the orchestrator knows where to resume.
2. Append to the pipeline log: `- ⏸ AWAITING INPUT: <reason>` (see reason formats below).
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

Based on the developer's choice:

**Retry with guidance:**
- Append to log: `- ▶ RESUMED: Developer provided guidance, retrying`.
- Reset the relevant iteration counter if applicable (`impl_iterations` or `sec_iterations` to 0).
- Restore `state.json` top-level `phase` to its pre-escalation value (e.g., `"implementing"`, `"architecture"`, `"integration_validation"`).
- Re-invoke the relevant worker agent with the developer's guidance included as additional context in the Task prompt.

**Accept risk** (security review or security fix):
- Append to log: `- ▶ RESUMED: Developer accepted risk, proceeding`, then `- Security Review: ACCEPTED BY DEVELOPER`.
- Proceed to the commit sub-phase for this chunk.
- Restore `state.json` top-level `phase: "implementing"`.

**Abort pipeline:**
- Append to log: `- ▶ RESUMED: Developer aborted pipeline`.
- If in a per-chunk phase: update the chunk's `status: "failed"`.
- Update `state.json` top-level `phase: "failed"`.
- STOP execution.

## Escalation Reason Formats

| Phase | Reason Format |
|-------|---------------|
| Architecture | `Architecture analysis flagged ambiguity — <summary of concern>` |
| Test generation | `Test generation failed — <summary of failure>` |
| Implementation | `Implementation failed — <N> tests still failing after 3 iterations` |
| Security review | `Security review failed — unresolved issues after 3 iterations` |
| Security fix | `Security fix failed — implementer could not resolve issues: <failure summary>` |
| Integration | `Integration validation failed` |
