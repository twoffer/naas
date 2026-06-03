---
name: all-failures-snapshot-cadence
description: Snapshot vs invocation_count cadence for the all-failures scenario; 31 Agent invocations produce 38 snapshots
metadata:
  type: project
---

The all-failures scenario has 31 worker-Agent invocations (invocation_count ends at 31) but the simulation produces 38 numbered snapshots (001–038).

**Why:** Same rule as [[max-recovery-snapshot-cadence]] — "one snapshot after every step," where non-Agent state-mutating transitions also get snapshots without bumping invocation_count. The 7 extra snapshots beyond the 31 Agent steps are: pre-pipeline init (001), 3 chunk entries (004, 016, 026), 1 chunk-1 commit (015), the loop-complete flip to integration_validation (034), and post-pipeline finalization (038). Chunk 2 and chunk 3 commits are folded into their accept-risk step snapshots (025, 033) rather than separate snapshots, because accept-risk resolution + commit happen within the same simulated step.

**How to apply:** Deterministic timestamps advance +3 min per Agent step starting 10:00:00Z as started_at; step N review/integration-report timestamps = 10:00:00Z + N*3min (step 31 = 11:33:00Z). completed_at is stamped one step later at 11:36:00Z. The budget guard fires on step 30's increment to 30 (before processing the validator FAIL), so its ⏸/▶ pair lands under the FIRST `## Integration Validation: FAIL` heading, after run-1's FM6 resume and before run-2's FAIL heading.
