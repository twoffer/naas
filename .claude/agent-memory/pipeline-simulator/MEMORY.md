## Project
- [max-recovery-snapshot-cadence.md](max-recovery-snapshot-cadence.md) — max-recovery has 20 Agent invocations but ~28 snapshots; non-Agent transitions (chunk entry/commit/finalize) get snapshots too
- [all-failures-snapshot-cadence.md](all-failures-snapshot-cadence.md) — all-failures has 31 Agent invocations, 38 snapshots; budget guard fires on step 30 before the validator FAIL
