# Post-Pipeline Phase

Push the feature branch, create a draft PR, and finalize the pipeline.

## Entry

`state.json` shows `phase: "post_pipeline"`. Integration validation has passed.

## Execution

1. **Finalize the execution log.** Append the three closing headings defined in CONTRACTS.md §5.1 rows 7–9 (`## Completed`, `## Total Implementation Iterations`, `## Total Security Issues Caught`). The "Total Security Issues Caught" count is aggregated from all chunks' `sec_issues`.
2. **Generate the per-spec quality report** at `.claude/pipeline/reports/<spec-slug>-quality-report.md` using the schema defined in `.claude/pipeline/CONTRACTS.md` §6. Compute aggregates from `state.json` and parse self-correction / escalation events from the execution log. Populate the `## Related Artifacts` section with paths to the plan file (§7), review file (§8), and integration validation report (§9).
3. **Create the finalization commit.** Targeted-stage exactly the five durable per-spec artifacts (in this order):
   - `.claude/pipeline/logs/<spec-slug>.md`
   - `.claude/pipeline/reports/<spec-slug>-quality-report.md`
   - `.claude/pipeline/plans/<spec-slug>-plan.md`
   - `.claude/pipeline/reviews/<spec-slug>-review.md`
   - `.claude/pipeline/reports/<spec-slug>-integration-report.md`

   Then commit using the template in `CONTRACTS.md` §4.2. Never `git add -A` or `git add .`. This is the last commit on the branch before push. If any of the plan, review, or integration-report file is unexpectedly missing, stage what exists and note the omission in the developer summary in step 7 — do not fabricate placeholder content.
4. **Push the branch:** `git push -u origin feature/<spec-slug>`.
5. **Create the draft PR** via `gh pr create --draft` with an appropriate title and a body generated from the (now-committed) execution log.
6. **Update `state.json`:**
   - set top-level `phase: "complete"`
   - set top-level `completed_at` to the current ISO 8601 UTC timestamp

   `state.json` is gitignored and is intentionally not part of the finalization commit.
7. **Report to the developer:** "Draft PR created for <spec title>. The finalization commit includes the execution log, quality report, implementation plan, code security review, and integration validation report — review the security review and integration report for non-blocking issues and recommendations the orchestrator did not surface inline. Squash-merge when ready."

## Success → Done

`state.json` shows `phase: "complete"` with `completed_at` set. The pipeline is finished.

## Failure → Escalation

- **Finalization commit fails** (e.g., pre-commit hook rejects, unexpected staged content): do not push. Report the error to the developer via `AskUserQuestion` so they can inspect the working tree before retrying. The execution log and quality report already exist on disk.
- **Push or PR creation fails** after a successful finalization commit (e.g., network issue, missing `gh` auth): report the error to the developer via `AskUserQuestion`. All pipeline artifacts — including the execution log and quality report — are preserved in the local commit. The developer may resolve the finalization issue and resume the post-pipeline phase manually without losing any state.
