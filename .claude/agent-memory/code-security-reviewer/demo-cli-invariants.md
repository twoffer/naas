---
name: demo-cli-invariants
description: SPEC_DEMO normalization-demo CLI (demo/demo_normalization.py) review invariants — SQL safety, self-DELETE-only discipline, decoupling, no-meta-language, and the gc.get_referrers self-registration anti-pattern (since resolved test-side)
metadata:
  type: reference
---

`demo/demo_normalization.py` is a STANDALONE developer-run deliverable (not a service). Reviewed under SPEC_DEMO_Normalization_Showcase.md. Runs only with `rich`/`httpx`/`psycopg[binary]`; `naas_shared` is an optional soft import (try/except ImportError, plain-dict default path). It POSTs synthetic events through the public ingestion API and reads/DELETEs ONLY ids it captured this run.

## Standard gates that must hold (all PASS in the chunk-4 impl)
- SQL: `POLL_QUERY`/`CLEANUP_QUERY` are module-level constants, parameterized `id = ANY(%(ids)s)`, executed with bound `{"ids": event_ids}`. No f-string/%/format of ids or event data. No other dynamic SQL.
- Self-DELETE-only: cleanup is `DELETE FROM events WHERE id = ANY(%(ids)s)` over captured ids only. No broad DELETE, no predicate DELETE, no UPDATE/INSERT, no writes to other tables.
- Cleanup-on-abort: verify_results failure path still cleans up captured ids unless `--keep` (main() calls cleanup_events before sys.exit(1)). Good.
- Network/DB: httpx timeouts 5s (health) / 10s (post); no verify=False; DSN/password never printed (errors print exc, not the DSN); no shell=True/subprocess/os.system; failures -> single message + sys.exit(non-zero), no stack dumps. POSTGRES_PASSWORD has NO default (a7c7b41 removed the hardcoded fallback) — missing password exits with guidance; do not let a default creep back in.
- verify_results is PURE (no I/O), wrapped in try/except returning a problems list (scene=-1 on unexpected), never raises.
- No fabricated output: per-scene confidences/winners read from actual `normalized_attributes` payload. Verify checks were structural/relative only at chunk-4; 1037f46/b6d7a81 added absolute directory-corroboration checks (SPEC_DEMO §5.5 check 8): corroborated fraction recovered from groups confidence (0.7 + 0.3×fraction) must be ≥ ½ on Scene 5 and ≥ ¼ on Scene 6, Scene-6 merged groups a strict superset of token groups, Scene-6 groups confidence < Scene-5's. Still pure math over the payload — no fabrication.
- No meta-language ("showcase"/"money shot"/"hiring manager"/"recruiter"/"evaluator"/"senior engineer"/employer framing) anywhere in code/comments/Rich strings. Spec uses these words but the CODE must not. Scene-6 "Why the split?" annotation is plainly technical (display_name->OIDC presentation, department->LDAP org facts, "no single rule could capture both"). Confirmed clean.

## ANTI-PATTERN (item A) — RESOLVED test-side in 1037f46; keep as reference
Original finding (MEDIUM, non-blocking): module-end block `if __name__ not in sys.modules: for _referrer in gc.get_referrers(globals()): if isinstance(_referrer, ModuleType) and _referrer.__dict__ is globals(): sys.modules[__name__] = _referrer`. Added so the test's `from demo_normalization_flow import SCENES` resolved after `spec_from_file_location("demo_normalization_flow", ...)` + `exec_module` (which does NOT auto-register into sys.modules). Test-accommodation machinery in a shipping deliverable: introspects the GC to self-register under a hard-coded test-only alias. Inert at real runtime (run as __main__ -> name IS in sys.modules -> block skipped).
RESOLUTION (1037f46): the block (and the gc/types imports) was DELETED from demo_normalization.py; the demo_mod fixture in tests/demo/test_demo_flow.py now does `sys.modules["demo_normalization_flow"] = mod` BEFORE `exec_module` — exactly the recommended test-side fix. If this GC-introspection idiom reappears anywhere, flag it the same way and route to the test owner.

## Pyright "str | None not assignable to str @ :563" (item B) — BENIGN
Line-number drift: LSP/pyright indexed a buffer offset ~22 lines from disk (and later commits 1037f46/b6d7a81 shifted the file further, so :563 means nothing now). The `-> str` render helpers (_render_bar, _render_enrichment_status, _render_resolution_type via `labels.get(res, res)` with res: Any, _format_sources, _fmt_raw) all provably return str; none return str|None. No caller breaks on None anyway (Rich add_row accepts None; bar is f-string-embedded). Not a latent bug — stale/transient diagnostic. No code change needed.
