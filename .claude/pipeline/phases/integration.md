# Integration Phase

Validate that all implemented services work together as an integrated system.

## Entry

`state.json` shows `phase: "integration_validation"`. All chunks have `status: "passed"`.

## Execution

Invoke `integration-validator` via the `Agent` tool with a prompt that includes:
- The spec title and `spec_slug`
- The branch name where all chunks have been committed
- Instruction to verify services work together as an integrated system
- The pipeline mode instruction

After the `Agent` invocation completes, read the validator's response.

- Append a section to `.claude/pipeline/reports/<spec-slug>-integration-report.md` per CONTRACTS.md §9: write the canonical section header (substituting `<n>` = 1-based count of validator invocations for this spec — i.e., the prior count of `## Validation Run` headers in the file, plus one — `<VERDICT>` = `PASS` or `FAIL` per the validator's response, `<ISO 8601 UTC timestamp>` = current UTC time), followed by the validator's findings as captured in its `Agent` response. Body format under the header is at the orchestrator's discretion (CONTRACTS.md §9) — verbatim copy is the simplest approach. Create `.claude/pipeline/reports/` if missing. Append both PASS and FAIL outcomes. The orchestrator does not parse this file; it is staged at the finalization commit (CONTRACTS.md §4.2).
- Update state.json: increment top-level `invocation_count`.

## Success → Post-Pipeline Phase

If the validator reports PASS: append the `## Integration Validation: PASS` heading per CONTRACTS.md §5.1 row 6. Update state.json: set top-level `phase: "post_pipeline"`. Proceed by reading `.claude/pipeline/phases/post-pipeline.md`.

## Failure → Escalation

If the validator reports FAIL: append the `## Integration Validation: FAIL` heading per CONTRACTS.md §5.1 row 6. Then escalate per `human-review.md`. Present the integration failures to the developer. The developer can retry integration validation or abort the pipeline. If retrying, re-invoke the integration-validator (with any developer guidance included).
