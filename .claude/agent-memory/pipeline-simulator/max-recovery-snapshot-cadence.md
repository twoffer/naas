---
name: max-recovery-snapshot-cadence
description: Snapshot vs invocation_count cadence for the max-recovery scenario; non-Agent transitions still get snapshots
metadata:
  type: project
---

The max-recovery scenario has 20 worker-Agent invocations (invocation_count ends at 20) but the simulation produces ~28 numbered snapshots.

**Why:** The OUTPUT ARTIFACTS rule is "one snapshot after every step," and the snapshot-naming examples in the simulator prompt explicitly include non-Agent transitions like `003-chunk-1-entry.json` and the implied commit/finalization steps. Chunk entry, per-chunk commit, the loop-continuation phase flip to `integration_validation`, and post-pipeline finalization all mutate state.json without incrementing invocation_count (per CONTRACTS.md §3), so they each warrant a snapshot but do NOT bump the counter.

**How to apply:** When validating snapshot counts for this or similar scenarios, do not expect snapshot count == invocation_count. Expect snapshot count == number of distinct state-mutating transitions (Agent steps + chunk-entry + commit + loop/phase flips + finalization). For max-recovery the deterministic timestamps still advance +3 min only per Agent step (step 20 = 10:57:00Z); finalization completed_at is stamped one step later at 11:00:00Z.
