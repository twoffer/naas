# Integration Phase

Validate that all implemented services work together as an integrated system.

## Entry

`state.json` shows `phase: "integration_validation"`. All chunks have `status: "passed"`.

## Execution

Invoke `integration-validator` via Task with a prompt that includes:
- The spec title
- The branch name where all chunks have been committed
- Instruction to verify services work together as an integrated system
- The pipeline mode instruction

After the Task completes, read the validator's response. Increment `invocation_count`.

## Success → Post-Pipeline Phase

If the validator reports PASS: append to log `## Integration Validation: PASS`. Update `state.json`: `phase: "post_pipeline"`. Proceed by reading `.claude/pipeline/phases/post-pipeline.md`.

## Failure → Escalation

If the validator reports FAIL: append to log `## Integration Validation: FAIL`. Then escalate per `human-review.md`. Present the integration failures to the developer. The developer can retry integration validation or abort the pipeline. If retrying, re-invoke the integration-validator (with any developer guidance included).
