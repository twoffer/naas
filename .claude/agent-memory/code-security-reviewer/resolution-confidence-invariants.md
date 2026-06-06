---
name: resolution-confidence-invariants
description: SPEC_2 §5.5/§5.5.2 conflict-resolution + confidence-scoring invariants for identity-normalization/app/resolution.py (pure domain core)
metadata:
  type: reference
---

`services/identity-normalization/app/resolution.py` is the pure domain core (no I/O) for SPEC_2 §5.5. Reads weights/priority/merge_strategy ONLY via `NormalizationConfig` accessors (`weight_for`, `priority_for`, `merge_strategy_for`). `ATTRIBUTE_IMPORTANCE` is the one allowed transcribed constant. See [[naas-shared-structure]].

## Confidence math invariants (a wrong value silently corrupts downstream `normalization_risk = 1 - confidence`)
- Only 4 discriminators emitted: `unanimous`/`priority`/`single_source`/`list_merge`. Anything else fails `NormalizedAttributes` validation downstream.
- Scalar: 0 src → None, omit from resolution_details, 0.0 contribution. 1 → single_source @ weight_for. ≥2 agree → unanimous @ max agreeing weight. ≥2 disagree → priority @ winner_weight×0.8; conflicting_values = losing non-null only; penalty_applied=True.
- Winner = first present source in `priority_for(attr)`; fallback = highest `weight_for`.
- 0.2 unmapped penalty: department ONLY (via was_mapped tuple), clamped [0,1], stacks with ×0.8. NEVER on employee_type (unmapped → discarded to None upstream, never reaches resolve). Department unanimous penalty keys on `all(was_mapped)` — safe because was_mapped is a deterministic fn of the normalized string (mixed mapped/unmapped on one agreed string is unreachable).
- groups: single → weight_for; multi → `0.7 + 0.3×(fraction of merged groups present in >1 source)`. Division-by-zero guarded by `if merged:` (disjoint intersection → []  → fraction 0.0 → 0.7). conf ∈ [0.7,1.0] always.
- Overall: `sum(IMPORTANCE[a] * per_attr.get(a,0.0))` clamped [0,1]. IMPORTANCE = {display_name .15, primary_email .25, department .20, employee_type .25, groups .15}.
- source_protocol = passed primary protocol (not enriching source). enrichment passed through unchanged (resolve does NOT compute it).

## §3.3 payload is ILLUSTRATIVE, not binding
The §3.3 example shows normalization_confidence 0.87 and groups 0.85; the §5.5 FORMULA gives ~0.889 / 0.90 for the same inputs. chunk-5 tests correctly assert the formula, not the illustrative payload values. Do not flag this divergence as a bug.

## conftest tempfile monkeypatch (chunk-5)
`tests/services/identity-normalization/conftest.py` autouse-patches `tempfile.NamedTemporaryFile` to flush-on-write, working around `test_chunk5_groups_merge.py:99-101` reading the temp file via `load_config` while still inside the `with` block (unflushed buffer → empty read). Scoped fine: chunk-3 config-validation tests use pytest `tmp_path` + `write_text`, NOT NamedTemporaryFile, so they are unaffected. The cleaner fix (one-line `f.flush()` in the helper) needs a test-file edit blocked by pipeline rules. Non-blocking; weakens no assertion.
