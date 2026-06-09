# Code Security Review — Identity Normalization Demo

Append-only record of every code-security-reviewer invocation for this spec (CONTRACTS.md §8).

## Chunk 1 — Iteration 1 — PASS WITH NOTES — 2026-06-09T16:00:13Z

**Files reviewed:** `infrastructure/openldap/bootstrap.ldif`, `infrastructure/openldap/memberof-overlay.sh`, `infrastructure/openldap/Dockerfile`, `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md` (§5.3).

**Overall verdict:** PASS WITH NOTES — Critical: 0, High: 0, Medium: 0, Low: 2. No blocking issues.

**Scope verification:**
- Diff touches only the four in-scope files. No `do_not_touch` path modified (SPEC_DEMO doc, config/normalization.yaml, SPEC_2, services/, shared/, demo/, docker-compose.yml all untouched).
- SPEC_0 edits confined to §5.3; §5.2 and §5.4 boundaries unchanged.
- No existing LDAP user entry attribute changed/removed; the four groups are purely additive and appear after the user entries; `dc=corp,dc=com` not declared.
- No meta-language introduced in any file.

**bootstrap.ldif — PASS:** Four `groupOfNames` entries appended after the five user entries. All `member` DNs reference existing users (engineering: alice+diana; product: bob; security: charlie; vpn-users: alice+diana). No synthetic `memberOf` injected onto users (back-populated by overlay at runtime — correct approach). Every group has ≥1 member; well-formed.

**memberof-overlay.sh — PASS WITH NOTES:** Auth safe — targets `cn=config` over `ldapi:///` with `-Y EXTERNAL` (local root, no plaintext creds, no hardcoded secrets). No destructive ops (only `olcModuleLoad` + overlay `add`). Module-load idempotency via `|| true` is reasonable. osixia olc* ordinals intentionally validated live by the integration validator (out of scope here).

Non-blocking recommendations:
1. **[LOW]** `memberof-overlay.sh:48,64` — the Step 2/Step 3 overlay-add `ldapmodify` blocks are also suffixed `|| true` under `set -e`, so a genuine first-seed overlay-config failure is swallowed and the script still exits 0. Module loads legitimately need `|| true` for idempotency, but the one-time overlay adds do not. Fix: drop `|| true` from the overlay-add blocks (or match specifically on "already exists") so a real config error surfaces at seed time.
2. **[LOW]** `memberof-overlay.sh:24` — fixed `sleep 2` slapd-readiness wait is a potential race on a loaded host. Fix: replace with a bounded retry probe on `ldapsearch -Y EXTERNAL -H ldapi:/// -b cn=config -s base`.

**Dockerfile — PASS:** Additive single `COPY memberof-overlay.sh …` line alongside the existing bootstrap.ldif COPY. `FROM osixia/openldap:1.5.0` unchanged.

**SPEC_0 §5.3 — PASS:** Changes confined to §5.3. Transcribed Dockerfile fence had non-load-bearing `# comment` lines removed (to satisfy a test-extractor regex) — no substantive content dropped; FROM + both COPY lines present and match the real Dockerfile. Transcribed LDIF mirrors bootstrap.ldif; prose accurately describes the four groups, the token-only-vs-directory-group distinction, and the overlay behavior.

## Chunk 2 — Iteration 1 — PASS WITH NOTES — 2026-06-09T16:11:53Z

**Files reviewed:** `config/normalization.yaml`, `tests/services/identity_normalization/test_config_yaml.py`, `test_scalar_resolution.py`, `test_confidence.py`, `test_penalty.py`, `docs/architecture/SPEC_2_Identity_Normalization_Service.md` (§5.6).

**Overall verdict:** PASS WITH NOTES — Critical: 0, High: 0, Medium: 0, Low: 1. No blocking issues.

**Scope verification (orchestrator git diff):** Exactly six files changed since the chunk-1 commit (config + SPEC_2 + four test files). No `do_not_touch` path touched; SPEC_DEMO doc remains untracked/unmodified.

- **config/normalization.yaml — PASS:** Only the `display_name` block changed — priority `[oidc, saml, ldap]`, weights `{ldap: 0.85, saml: 0.75, oidc: 0.70}`, rationale updated. primary_email, department, employee_type, groups, defaults, and the entire enrichment block byte-for-byte unchanged. YAML valid.
- **SPEC_2 §5.6 — PASS:** Lead-in note adjusted to mark the §3.3 worked example as pre-change/illustrative; §5.6 YAML transcription matches config. §3.3 and all other sections unchanged (display_name unanimous 0.90 retained as illustrative, consistent with the note).
- **Test reconciliation — PASS:** Arithmetic verified against the new weights across all four files (single-source oidc 0.70 / saml 0.75; unanimous max 0.85; priority winner_source 'oidc' at 0.70×0.8=0.56). `test_penalty.py` (legitimate scope discovery) changed only its two display_name assertions to 0.85. Inline custom-config fallback test (hard-coded {ldap:0.90, saml:0.70}, no priority) left unchanged. No test weakened/deleted; no non-display_name assertion altered. Full identity-normalization suite: 719 passed.
- **No meta-language** introduced.

Non-blocking recommendation (follow-up):
1. **[LOW]** `tests/services/identity_normalization/test_confidence.py:425-426` — stale arithmetic comment still references the pre-change display_name ldap weight (`0.15×0.90 … = 0.91`). The test only asserts `0.0 <= conf <= 1.0`, so it passes regardless, but the comment is exactly the kind of old-default reference this chunk reconciles. Fix: update to `0.15×0.85` and total `0.9025`. Defer to follow-up (non-blocking; does not affect any assertion).

## Chunk 3 — Iteration 1 — PASS WITH NOTES — 2026-06-09T16:22:22Z

**Files reviewed:** `demo/demo_normalization.py`, `demo/requirements.txt`, `demo/README.md`.

**Overall verdict:** PASS WITH NOTES — Critical: 0, High: 0, Medium: 0, Low: 2. No blocking issues.

**Scope/decoupling verified:** Only the three `demo/` files added (`demo/__pycache__/*.pyc` gitignored). No `do_not_touch` path touched. No service-code import; the only optional import is `naas_shared.models` (line 22), wrapped in try/except with the plain-dict path as default — resolves when present, degrades cleanly when absent. Runnable with only rich/httpx/psycopg (imported lazily inside preflight).

**Security verified:** DSN assembly reads `POSTGRES_*` env into a libpq DSN; password never logged/printed. No `subprocess`/`shell=True`/`os.system`/`verify=False`. HTTP preflight `timeout=5.0`; DB preflight literal `SELECT 1`. No SQL string literals beyond `SELECT 1` (submit/poll/verify/render/cleanup flow intentionally stubbed `NotImplementedError` per chunk scope — not flagged). `SCENES` are static synthetic data, every event `source:"api"` + `is_synthetic:True`, all IPs documentation-range `203.0.113.x`. requirements.txt pins rich==13.9.4/httpx==0.28.1/psycopg[binary]==3.3.4, no naas_shared. README documents §5.9 a–e including the honesty note. No meta-language anywhere.

Non-blocking recommendations:
1. **[LOW]** `demo/demo_normalization.py:22` — soft `naas_shared` import / `NAAS_SHARED_AVAILABLE` flag is unused until chunk 4 wires in the flow (ruff currently clean; acceptable to defer to the consuming chunk).
2. **[LOW]** `demo/demo_normalization.py:189,204` — two broad `except Exception` handlers (`# noqa: BLE001`) are justified by the spec's fail-fast/clean-exit requirement (no stack-trace dumps). No change required.

## Chunk 4 — Iteration 1 — PASS WITH NOTES — 2026-06-09T16:43:08Z

**Files reviewed:** `demo/demo_normalization.py` (flow fill-in: submit/poll/verify/render/cleanup + main orchestration).

**Overall verdict:** PASS WITH NOTES — Critical: 0, High: 0, Medium: 1, Low: 1. No blocking issues.

**Standard gates — all PASS:**
- **SQL safety:** `POLL_QUERY` / `CLEANUP_QUERY` are module constants using `id = ANY(%(ids)s)`, executed with bound params `{"ids": event_ids}`. Only other execute is literal `SELECT 1`. No f-string/`%`/`.format` interpolation of ids or event data.
- **Self-DELETE-only discipline:** single DELETE scoped to `id = ANY(%(ids)s)` over ids captured this run; no broad/predicate DELETE, no UPDATE/INSERT, no other-table writes, no service/config mutation. Cleanup-on-abort honored before `sys.exit(1)` unless `--keep` (§5.8).
- **Network/DB safety:** health GET timeout 5.0s, ingest POST timeout 10.0s; no `verify=False`; DSN/password never printed (error paths print the exception only); no `shell=True`/`subprocess`/`os.system`; failures → single message + non-zero exit, no stack-trace dumps.
- **Decoupling:** `naas_shared.models` soft optional import behind try/except (`# noqa: F401`), plain-dict default path; no service-code imports; rich/httpx/psycopg imported lazily inside functions.
- **No meta-language:** none anywhere. Scene-6 "Why the split?" annotation is plainly technical (display_name → OIDC preferred/presented name; department → LDAP authoritative org facts; "No single OIDC-or-LDAP rule could capture both"). Scene-6 centerpiece framing is purely visual (DOUBLE_EDGE border accent).
- **No fabricated output:** per-scene rendered confidences/winners read from the actual `normalized_attributes` payload; `SCENES` hardcodes only the raw input side + captions. `verify_results` is pure (no I/O), returns a problems list (never raises), structural/relative checks only per §5.5.

**Findings (non-blocking, deferred to follow-up):**
1. **[MEDIUM]** `demo/demo_normalization.py:943-963` — `gc.get_referrers(globals())` + `sys.modules` self-registration block. Exists only so the test's `from demo_normalization_flow import …` resolves after `spec_from_file_location("demo_normalization_flow", …)` + `exec_module`. **Inert at real runtime** (when run as `__main__`, the `if __name__ not in sys.modules` guard is false, block skipped) — no security/functional risk, hence non-blocking. But it is test-accommodation machinery in a standalone deliverable and reads as confusing dead weight. **Correct fix is test-side:** add `sys.modules["demo_normalization_flow"] = mod` before `spec.loader.exec_module(mod)` in the fixture at `tests/demo/test_demo_flow.py:66-68`, then delete the `demo_normalization.py:943-963` block. The implementer cannot edit tests, so this is routed to a follow-up.
2. **[LOW / informational]** `demo/demo_normalization.py:563` — Pyright `str | None` vs `str` is **benign**: stale diagnostic / line-number drift; `_render_bar` returns an `int`-derived `str`, and every `-> str` helper provably returns `str`. No action required.

**Run cleanliness:** No reflection (FAIL→fix→PASS) loop fired for any chunk in this run; both follow-up items above are non-blocking and recorded here for a post-pipeline cleanup pass.
