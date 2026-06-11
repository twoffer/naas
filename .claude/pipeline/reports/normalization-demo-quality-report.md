# Pipeline Quality Report — Identity Normalization Demo

**Spec:** normalization-demo
**Branch:** feature/normalization-demo
**Started:** 2026-06-09T15:32:11Z
**Completed:** 2026-06-09T22:13:50Z
**Duration:** 06:41:39
**Outcome:** COMPLETED
**Total Agent invocations:** 15 / 30 (budget guard ceiling)
**Final model:** claude-opus-4-8[1m]

## Per-Chunk Metrics

| Chunk | Title | Tests Written | Tests Passing | Impl Iterations | Sec Review Iterations | Sec Issues Caught | Outcome |
|-------|-------|---------------|---------------|-----------------|----------------------|-------------------|---------|
| 1 | LDAP group entries + memberof/refint overlay + SPEC_0 §5.3 mirror | 70 | 70/70 | 1 | 1 | 0 | passed |
| 2 | display_name authority config change + SPEC_2 §5.6 mirror + test reconciliation | 15 | 15/15 | 1 | 1 | 0 | passed |
| 3 | demo/ scaffold — requirements, README, CLI skeleton + crafted events | 88 | 88/88 | 1 | 1 | 0 | passed |
| 4 | demo CLI flow — submit, poll, narrative verification, Rich render, cleanup | 53 | 53/53 | 1 | 1 | 0 | passed |

## Aggregate Metrics

- **Total tests written:** 226
- **Total tests passing at completion:** 226/226
- **Total implementation iterations:** 4
- **Total security review iterations:** 4
- **Total security issues caught:** 0 (blocking; non-blocking advisory findings are recorded in the code security review file)
- **Total security issues resolved by reflection loop:** 0
- **Total HUMAN_REVIEW escalations:** 1

## Self-Correction Events

None — no reflection loops fired. Every chunk passed its security review on the first iteration (each verdict PASS WITH NOTES, with only non-blocking LOW/MEDIUM advisory findings recorded in the review file).

## Escalations to HUMAN_REVIEW

- **Integration phase:** Integration validation failed (Run 1). The seeded LDAP `memberof` overlay was non-functional in the running container — the osixia image's built-in overlay targeted `groupOfUniqueNames`/`uniqueMember` while the seeded groups use `groupOfNames`/`member`, and the `memberof-overlay.sh` placed in the Dockerfile's bootstrap path was never executed. Result: `memberOf` was never back-populated, LDAP enrichment merged zero directory groups, and Scenes 5–6 `list_merge` confidence read ≈0.80 (pure token union) instead of the expected ≈0.90 with directory corroboration. Developer resolved by: **provide guidance and retry** — authorized an ad-hoc fix (feature-implementer) plus a focused code-security-reviewer pass, run as off-the-books one-off invocations (intentionally excluded from `invocation_count` and the per-chunk metrics per developer instruction), then re-validation. Integration validation Run 2 PASSED: overlay reconfigured to `groupOfNames`/`member`, alice/diana `memberOf` reduces to {engineering, vpn-users}, Scenes 5–6 `list_merge` confidence ≈0.90 with directory corroboration. The fix was committed mid-pipeline (`fix(normalization-demo): make memberof overlay back-populate memberOf for groupOfNames groups`).

## Defense-in-Depth Receipts

| Guard | Threshold | Maximum Observed | Status |
|-------|-----------|------------------|--------|
| Implementation iteration cap | 3 per chunk | 1 | respected |
| Security review iteration cap | 3 per chunk | 1 | respected |
| Invocation budget guard | 30 total | 15 | respected |
| Post-security-fix regression check | always | 0 performed | n/a — no chunk entered a security-fix loop (all passed security review on iteration 1) |

## Notes

- **Ad-hoc integration fix (off-the-books invocations).** Per developer direction, the integration-failure remediation was performed with the feature-implementer and code-security-reviewer as one-off invocations that did NOT update pipeline state (no `invocation_count` increments, no execution-log bullets, no `impl_iterations`/`sec_iterations` changes). The fix's security review returned PASS (0 findings). Normal state updates resumed for integration-validation Run 2. The "Total Agent invocations: 15" therefore counts the 14 standard worker invocations plus integration Run 2; it excludes the two off-the-books fix invocations and the two off-the-books review invocations.
- **Outstanding non-blocking follow-up (recommended for a follow-up commit):** `demo/demo_normalization.py` contains a `gc.get_referrers(globals())` + `sys.modules` self-registration block (≈ lines 958–966) that exists solely so the test fixture's `from demo_normalization_flow import …` resolves. It is **inert at real runtime** (skipped when run as `__main__`), so the demo a user runs is unaffected, but it is test-accommodation machinery in the shipped deliverable. Correct fix is test-side: add `sys.modules["demo_normalization_flow"] = mod` before `spec.loader.exec_module(mod)` in `tests/demo/test_demo_flow.py` (~line 66), then delete the block from `demo_normalization.py`. Details in the code security review file (Chunk 4 section).
- **Minor non-blocking nits** also recorded in the review file: a stale arithmetic comment in `tests/services/identity_normalization/test_confidence.py:425-426` (`0.15×0.90` → should be `0.15×0.85`), and an optional SPEC_0 §5.3 wording tightening ("running as root" → the SASL EXTERNAL peercred identity that maps to cn=config write).

## Related Artifacts

- Implementation plan: `.claude/pipeline/plans/normalization-demo-plan.md` (technical-architect)
- Code security review: `.claude/pipeline/reviews/normalization-demo-review.md` (pipeline-orchestrator, append-only across chunks/iterations)
- Integration validation report: `.claude/pipeline/reports/normalization-demo-integration-report.md` (pipeline-orchestrator, append-only across runs)
- Pipeline execution log: `.claude/pipeline/logs/normalization-demo.md` (this run)
