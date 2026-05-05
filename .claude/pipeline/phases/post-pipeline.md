# Post-Pipeline Phase

Push the feature branch, create a draft PR, and finalize the pipeline.

## Entry

`state.json` shows `phase: "post_pipeline"`. Integration validation has passed.

## Execution

1. Append to log: `## Completed: <iso-timestamp>`, `## Total Implementation Iterations: <n> (across all chunks)`, `## Total Security Issues Caught: <n>` (aggregated from all chunks' `sec_issues`).
2. Push the branch: `git push -u origin feature/<spec-slug>`.
3. Generate a PR body from the pipeline execution log. Create a draft PR via `gh pr create --draft` with an appropriate title and the generated body.
4. Generate the per-spec quality report at `.claude/pipeline/reports/<spec-slug>-quality-report.md` using the schema defined in `.claude/pipeline/CONTRACTS.md` Section 6. Compute aggregates from `state.json` and parse self-correction / escalation events from the execution log. Commit the report as part of the post-pipeline finalization commit (do not create a separate commit just for the report).
5. Update `state.json`: `phase: "complete"`, `completed_at` to the current ISO 8601 UTC timestamp.
6. Report to the developer: "Draft PR created for <spec title>. Quality report generated. Review and squash-merge when ready."

## Success → Done

`state.json` shows `phase: "complete"` with `completed_at` set. The pipeline is finished.

## Failure → Escalation

If the push or PR creation fails (e.g., network issue, missing `gh` auth), report the error to the developer via `AskUserQuestion`. The pipeline artifacts are all committed locally — this is a finalization issue, not a code quality issue. Generate the quality report regardless: it is informative even when the PR was not created, and the developer may resolve the finalization issue and resume the post-pipeline phase manually.
