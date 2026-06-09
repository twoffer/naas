PLAN: Identity Normalization Demo (standalone CLI) + supporting product changes
SPEC REFERENCE: docs/architecture/SPEC_DEMO_Normalization_Showcase.md  (this spec doc is NEVER committed — do not add it to any chunk's scope_boundary or shared_files; list it under do_not_touch where relevant)
PREREQUISITES:
  - Specs 0–2 already implemented and committed (event-ingestion on :8001, identity-normalization on :8002, PostgreSQL, Redis, OpenLDAP via docker compose).
  - The full stack is runnable with `docker compose up -d --build`.
  - config/normalization.yaml exists with the current (pre-change) display_name block.
  - infrastructure/openldap/bootstrap.ldif seeds five users (alice/bob/charlie/diana/eve) and the empty ou=groups; no group objects, no memberOf today.
  - The dev venv cannot install python-ldap. This work involves NO Python LDAP client code (LDIF + container config + a portable demo script over httpx/psycopg), so that constraint does not block any chunk.

OVERVIEW

The spec produces a standalone CLI program at demo/demo_normalization.py that drives the live Specs 0–2 pipeline over the public HTTP ingestion API and reads results back from PostgreSQL, plus the two product changes that make its six-scene narrative real:
  1. A single config change: reorder config/normalization.yaml display_name.priority to [oidc, saml, ldap] and compress its weights to {ldap: 0.85, saml: 0.75, oidc: 0.70} with an updated rationale (§5.4). Mirrored into SPEC_2 §5.6 only. Existing tests/notes asserting the old default must be reconciled.
  2. LDAP group infrastructure: additive groupOfNames entries in bootstrap.ldif plus the memberof (+ refint) overlay configured against cn=config so the directory back-populates memberOf on alice and diana (§5.6). Mirrored into SPEC_0 §5.3 only.

The three workstreams are largely independent. They are sequenced so the config and directory changes are defined before the CLI program (which depends on both producing the frozen narrative). The CLI program is the integration-facing final chunk.

GROUND-TRUTH VALUES (reproduce exactly; these are the implementer's correctness target, verified within ±0.01):
  - display_name block (§5.4): priority [oidc, saml, ldap]; weights {ldap: 0.85, saml: 0.75, oidc: 0.70}.
  - LDAP groups (§5.6a): engineering={alice,diana}, product={bob}, security={charlie}, vpn-users={alice,diana}. alice/diana memberOf reduces to {engineering, vpn-users}.
  - Six scenes and per-scene expected confidences (§2.3, §6): Scene1 OIDC≈0.75, Scene2 SAML≈0.69, Scene3 LDAP≈0.81, Scene4 sketchy SAML≈0.45, Scene5 enriched/unanimous≈0.92, Scene6 split≈0.84. Scene6: display_name → OIDC wins (0.56), department → LDAP wins (0.72).

NOTE ON NEUTRAL FRAMING: This is a normalization demo that stands on its own technical merits. All artifacts (titles, code comments, the demo README, instructions, validation criteria) use neutral, technical descriptions. Scene 6 is "the centerpiece scene with two split conflict winners," not promotional language.

STEPS

Step 1: LDAP group entries + memberof/refint overlay configuration + SPEC_0 §5.3 mirror
  Files:
    - infrastructure/openldap/bootstrap.ldif  (MODIFY — additive only)
    - infrastructure/openldap/<overlay bootstrap script, e.g. memberof-overlay.sh>  (ADD)
    - infrastructure/openldap/Dockerfile  (MODIFY — COPY the overlay script into the osixia custom-bootstrap dir; keep the existing bootstrap.ldif COPY)
    - docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md  (MODIFY — §5.3 ONLY)
  Details:
    (a) Group entries — bootstrap.ldif. Below the existing ou=groups entry and AFTER all five user entries (member DNs must already exist; LDIF is processed top to bottom), add four groupOfNames objects under ou=groups,dc=corp,dc=com (GROUND TRUTH §5.6a):
          cn=engineering : member uid=alice,…  member uid=diana,…
          cn=product     : member uid=bob,…
          cn=security    : member uid=charlie,…
          cn=vpn-users   : member uid=alice,…  member uid=diana,…
        Each groupOfNames requires objectClass: groupOfNames, cn: <name>, and ≥1 member DN (groupOfNames mandates at least one member — all four have members). Member DN form: uid=<user>,ou=users,dc=corp,dc=com. Do NOT declare dc=corp,dc=com (the image auto-creates it). Do NOT modify any existing user entry (cn/mail/departmentNumber/employeeType/uid/sn unchanged) and do NOT remove any existing user/OU entry.
    (b) Overlay configuration — memberof + refint, against cn=config. The osixia/openldap:1.5.0 image applies LDIFs placed in .../bootstrap/ldif/custom/ against the DATA db (suffix dc=corp,dc=com) as cn=admin; cn=config changes (loading the memberof module, adding the memberof + refint overlays to the mdb database) are NOT reachable that way. Intended approach: bake a small shell script into the image (placed in the osixia custom-bootstrap dir so it runs at first-seed) that runs `ldapmodify -Y EXTERNAL -H ldapi:///` against cn=config to (1) load the `memberof` (and `refint`) module if not already loaded, and (2) add the `memberof` overlay (olcMemberOfRefInt: TRUE so reverse links are maintained) and a `refint` overlay to the mdb database, configured for the member attribute. The exact olc* DN/ordinal and module-load mechanism MUST be verified against the running container — different osixia builds preload modules differently; the implementer confirms with live ldapsearch against cn=config and adjusts. Order: overlay/module config must be in place before (or be tolerant of) data seeding so memberOf is populated on alice/diana. Touch nothing in the cn=config of unrelated databases.
    (c) SPEC_0 §5.3 mirror — update ONLY the §5.3 "OpenLDAP Bootstrap Data" section (currently the LDIF transcription + the trailing "Note: 5 users" paragraph, roughly lines 1045–1119). Add the four group entries to the transcribed LDIF, and add a short paragraph describing the overlay script + cn=config memberof/refint configuration and that it requires an image rebuild. Do NOT edit any other SPEC_0 section (leave §5.1, §6.5, §7 gaps, etc. untouched).
  Reconciliation (REQUIRED, in THIS chunk's instructions):
    - The integration-validator memory note (.claude/agent-memory/integration-validator/normalization-validation.md) and any project assumption that "the seeded directory returns memberOf=[] for all users" no longer holds for alice and diana. There is no unit test asserting the LIVE directory returns empty memberOf — the memberOf:[] occurrences in tests/services/identity_normalization/ (e.g., test_service_enrichment.py line 114, test_ldap_enrich.py fixtures) are inline mock fixtures for the adapter/enrichment code paths and are NOT assertions about the seeded directory; they do NOT require changes. Confirm this during implementation (grep for any test that performs a live ldapsearch / live enrichment of a seeded user and asserts empty groups; none found in analysis). If one is found, reconcile it to {engineering, vpn-users} for alice/diana.
  Verify:
    - `docker compose build openldap && docker compose up -d openldap` then, once healthy:
      `ldapsearch -x -H ldap://localhost -b ou=groups,dc=corp,dc=com -D cn=admin,dc=corp,dc=com -w admin "(objectClass=groupOfNames)"` lists exactly cn=engineering, cn=product, cn=security, cn=vpn-users with the listed members.
      `ldapsearch -x -H ldap://localhost -b uid=alice,ou=users,dc=corp,dc=com -D cn=admin,dc=corp,dc=com -w admin memberOf` returns memberOf for cn=engineering and cn=vpn-users (and likewise for diana). bob→{product}, charlie→{security}.
    - SPEC_0 §5.3 transcription matches the actual bootstrap.ldif group entries; no other SPEC_0 section changed (git diff scoped to §5.3).

Step 2: display_name authority config change + SPEC_2 §5.6 mirror + test reconciliation
  Files:
    - config/normalization.yaml  (MODIFY — display_name block ONLY)
    - docs/architecture/SPEC_2_Identity_Normalization_Service.md  (MODIFY — §5.6 ONLY)
    - tests/services/identity_normalization/test_config_yaml.py  (MODIFY — display_name weight/priority assertions)
    - tests/services/identity_normalization/test_scalar_resolution.py  (MODIFY — display_name single-source/unanimous/priority assertions)
    - tests/services/identity_normalization/test_confidence.py  (MODIFY — display_name-dependent confidence assertions)
  Details:
    (a) config/normalization.yaml — change ONLY the display_name attribute block to (§5.4 GROUND TRUTH):
          display_name:
            priority: [oidc, saml, ldap]
            weights: {ldap: 0.85, saml: 0.75, oidc: 0.70}
            rationale: >- (the §5.4 rationale: cloud IdP is system of record for user-presented identity; users curate their own preferred/display name there, so the IdP value wins on disagreement; weights are intentionally decoupled from priority for this attribute — they encode source reliability for the canonical record, where the directory's verified legal name remains the most reliable, so a contested IdP-sourced name resolves at correspondingly modest confidence.)
        Do NOT touch primary_email, department, employee_type, groups, defaults, or the entire enrichment block. The weight ORDER (ldap > saml > oidc) is preserved; only magnitudes tighten and priority flips.
    (b) SPEC_2 §5.6 mirror — in the §5.6 YAML transcription (lines ~362–406) replace the display_name block with the new priority list, weights, and rationale so the committed doc matches config/normalization.yaml. Update ONLY the display_name block within §5.6. Do NOT edit §3.3 or any other SPEC_2 section. The §5.6 lead-in note ("the weights tune demo behaviour and the §3.3 example assumes them") is part of §5.6 and MAY be lightly adjusted to note that the §3.3 worked example reflects the pre-change display_name weights; keep the edit confined to §5.6.
    (c) Test reconciliation — update the existing tests that load the committed config and assert the OLD display_name default, so they assert the NEW default:
        - test_config_yaml.py:
            test_display_name_ldap_weight_is_0_90  → expect 0.85
            test_display_name_saml_weight_is_0_70  → expect 0.75
            test_display_name_oidc_weight_is_0_60  → expect 0.70
            test_display_name_priority_is_ldap_saml_oidc → expect priority [oidc, saml, ldap] (rename/retitle accordingly)
          Update the docstrings' "[TRANSCRIBE EXACTLY] §5.6" weight/priority literals to match. Do NOT touch primary_email/department/employee_type/groups/defaults assertions.
        - test_scalar_resolution.py (all load _load_real_config()):
            test_single_source_display_name_oidc → confidence 0.60 → 0.70
            test_single_source_saml_display_name_weight → 0.70 → 0.75
            test_unanimous_display_name_oidc_ldap_confidence_is_max_weight → max weight 0.90 → 0.85 (max of oidc 0.70, ldap 0.85)
            test_unanimous_three_sources_max_weight_wins → display_name max 0.90 → 0.85
            test_display_name_priority_ldap_over_oidc → now OIDC wins (priority [oidc,…]); winner_source ldap → oidc; resolved_value becomes the OIDC value; confidence 0.90×0.8=0.72 → 0.70×0.8=0.56; retitle to reflect OIDC-over-LDAP.
          The fallback test that builds an INLINE custom config (no priority list, weights {ldap:0.90, saml:0.70}) is unaffected — it does not read the committed file. Leave it.
        - test_confidence.py: the display_name unanimous/overall-confidence cases hardcode display_name oidc=0.60 / ldap=0.90:
            unanimous display_name max(0.60,0.90)=0.90 → max(0.70,0.85)=0.85
            single-source display_name oidc contributions 0.15×0.60 → 0.15×0.70
            any overall-confidence expected value that sums a display_name term must be recomputed with the new weight.
          Recompute each affected expected value from the new display_name weights; leave non-display_name terms unchanged.
  Reconciliation scope note: No ADR in docs/adr/ was found asserting the display_name→LDAP default (grep found none); if one exists at implementation time, update it in lockstep. docs/FOLLOWUPS.md is repo-resident notes — if it asserts the old default, reconcile the note.
  Verify:
    - `python -c "import yaml; d=yaml.safe_load(open('config/normalization.yaml')); a=d['attributes']['display_name']; assert a['priority']==['oidc','saml','ldap']; assert a['weights']=={'ldap':0.85,'saml':0.75,'oidc':0.70}"`
    - `pytest tests/services/identity_normalization/test_config_yaml.py tests/services/identity_normalization/test_scalar_resolution.py tests/services/identity_normalization/test_confidence.py` passes.
    - git diff on config/normalization.yaml shows ONLY the display_name block changed; git diff on SPEC_2 shows ONLY §5.6 display_name block changed.

Step 3: demo/ scaffold — requirements.txt, README.md, and the CLI program skeleton
  Files:
    - demo/requirements.txt  (ADD)
    - demo/README.md  (ADD)
    - demo/demo_normalization.py  (ADD — skeleton: argument parser, env/DSN resolution, preflight, the six crafted event payloads, and the optional soft naas_shared import; full submit/poll/verify/render flow lands in Step 4)
  Details:
    - demo/requirements.txt: pin compatible versions of rich, httpx, psycopg[binary] (§5.9). No naas_shared dependency.
    - demo/README.md: document (a) start the stack (docker compose up -d) and wait for healthy services; (b) pip install -r demo/requirements.txt; (c) run `python demo/demo_normalization.py`; (d) the flags (--keep, --pace, --step, --timeout, --skip-verify, --ingest-url, --db-dsn); (e) a one-line honesty note that the script reads PostgreSQL directly because the query API is designed but not yet built. Neutral technical tone only.
    - demo_normalization.py skeleton:
        * argparse CLI surface exactly per §5.1: --keep, --pace SECONDS (default 1.5), --step, --timeout SECONDS (default 30), --skip-verify, --ingest-url URL, --db-dsn DSN.
        * Env resolution: INGEST_URL (default http://localhost:8001), NORM_URL (default http://localhost:8002), POSTGRES_HOST/PORT/DB/USER/PASSWORD (defaults localhost/5432) → DSN for psycopg, --db-dsn overrides.
        * The six crafted events as plain dicts in display order (§2.3 GROUND TRUTH): Scene1 frank/oidc, Scene2 frank/saml, Scene3 grace/ldap, Scene4 mallory/saml, Scene5 alice/oidc, Scene6 diana/oidc — each with source:"api", is_synthetic:true, client_ip a documentation-range IPv4, and protocol-specific raw_attributes key shapes (§2.2). Reproduce the raw_attributes values EXACTLY as in §2.3.
        * Optional soft import: try `from naas_shared.models import LoginEventIngest, NormalizedAttributes` guarded by try/except ImportError; DEFAULT to the plain-dict path regardless (use the import only if a future flag opts in). Must run with only the three pip deps installed.
        * Preflight (§5.2): GET {INGEST_URL}/health → 200 + healthy; GET {NORM_URL}/health → 200 + healthy; psycopg connect + SELECT 1. Fail fast on first failure with a single clear message and non-zero exit (no multi-step remediation prose).
        * `if __name__ == "__main__":` entrypoint wired to argument parsing + preflight; the submit/poll/verify/render flow is stubbed (raise NotImplementedError or call placeholder functions) — Step 4 fills it.
  Verify:
    - `python -c "import ast; ast.parse(open('demo/demo_normalization.py').read())"` (syntactically valid).
    - `python demo/demo_normalization.py --help` prints all seven flags with correct defaults (works without naas_shared, with the three pip deps installed).
    - demo/requirements.txt lists rich, httpx, psycopg[binary]; demo/README.md contains the five documented items including the honesty note.
    - The six event payload dicts match §2.3 raw_attributes exactly (a structural test can import the module and inspect the payload list).

Step 4: demo CLI program — submit → poll → narrative verification → Rich render → cleanup
  Files:
    - demo/demo_normalization.py  (MODIFY — fill the flow stubbed in Step 3)
  Details (this is the integration-facing chunk — it exercises the live ingestion API, PostgreSQL, and the normalized output):
    - Submit (§5.3): POST {INGEST_URL}/events/ingest for each of the six events sequentially in display order; capture each returned id (expect 202 {"id":…,"status":"accepted"}). Sequential submission gives deterministic enrichment negative-cache behavior between Scenes 1 and 2.
    - Poll (§2.4, §5.3): every ≈0.5s run `SELECT id, protocol, normalized_attributes FROM events WHERE id = ANY(%(ids)s)` until normalized_attributes IS NOT NULL for every captured id, or --timeout elapses. On timeout: print which ids are still unprocessed; exit non-zero.
    - Narrative verification (§5.5 GROUND TRUTH; skipped only under --skip-verify) — structural/relative checks, never exact confidence numbers; on first failure print expected vs actual naming the scene and exit non-zero BEFORE rendering:
        1. Scenes 1–4: every present attribute is single_source; enrichment.applied is false for all four.
        2. Scene 3 (native LDAP): enrichment reflects no live directory lookup (per the field's representation for protocol ldap, §6.5).
        3. Scene 4: department present, single_source, penalty/was-unmapped (value retained); employee_type null/absent (discarded). Both must hold.
        4. Single-source ordering: C(4) < C(2) < C(1) < C(3) (strict <).
        5. Scenes 5–6: enrichment.applied true for both; each has ≥1 multi-source resolution.
        6. Scene 5: multi-source scalar resolutions unanimous (no priority/conflict); groups is list_merge; C(5) > C(1).
        7. Scene 6 (the core check): display_name is a priority resolution with winner_source == "oidc"; department is a priority resolution with winner_source == "ldap"; groups is list_merge; C(6) < C(5). The two-different-winners condition is the single most important assertion.
    - Render (§3.2–§3.5): per-scene Rich Panel with caption, Before→After two-column table (left uses protocol-native key names, right the unified-schema values, show canonical transforms visibly e.g. eng → Engineering), enrichment status, resolution-detail table (attribute | resolution | resolved value | source(s)/winner | confidence with color + bar), and prominent overall normalization_confidence (color thresholds: green ≥0.80, amber 0.50–0.79, red <0.50). Scene 4 MUST annotate the two distinct unmapped-handling policies side by side (§3.3): department "Sorcery" retained with −0.2 penalty; employee_type "wizard" discarded to null with no penalty (state the discard is the enum-safe policy). Scene 6 MUST get the most visual weight (distinct border accent + explicit callout that two different sources won two different attributes + compact provenance) and MUST render a brief "Why the split?" annotation authored in the script (display_name → OIDC owns identity presentation / preferred names; department → LDAP owns organizational facts; a single global rule couldn't capture both). Per-scene values rendered are the ACTUAL persisted output — never hardcode or fake confidences/winners. After all scenes, render a single summary table (one row per scene: scene, protocol(s), enrichment yes/no, resolution mix, overall confidence color-coded).
    - Cadence (§5.1): --pace controls inter-scene delay (default 1.5, 0 = none); --step waits for Enter (overrides --pace).
    - Cleanup (§5.8): default deletes exactly the captured ids `DELETE FROM events WHERE id = ANY(%(ids)s)` and prints how many rows removed; --keep skips delete and prints retained ids. Cleanup runs after rendering completes; if rendering aborts early, captured ids are still cleaned up unless --keep, so repeated runs don't accumulate rows.
    - Robustness (§5.7): sane network/DB timeouts; any unexpected error → single clear message + non-zero exit, no stack-trace dumps. Idempotent across runs (operates only on ids captured this run).
  Verify:
    - With the stack healthy and Steps 1–2 applied (rebuild openldap + identity-normalization, wipe+reseed if needed): `python demo/demo_normalization.py --pace 0` runs to completion, renders six scenes + summary, and prints a cleanup confirmation of 6 rows removed.
    - `python demo/demo_normalization.py --keep --pace 0` preserves the six rows and prints their ids; a follow-up default run cleans them.
    - The narrative-verification function can be unit-tested in isolation against synthetic normalized_attributes payloads: it MUST reject a Scene-6 payload whose display_name winner_source != "oidc" (and whose department winner_source != "ldap"), and MUST reject results violating C(4) < C(2) < C(1) < C(3) — with a message naming the scene and the violated expectation.
    - Confidence color thresholds applied consistently; Scene 4 renders both unmapped-handling annotations; Scene 6 renders the "Why the split?" annotation conveying both ownership points plus the "a global rule couldn't capture both" point.

INTEGRATION NOTES
  - Upstream: the CLI program is a client of the event-ingestion service (POST /events/ingest on :8001) and the identity-normalization service (GET /health on :8002). It does not call any other service and adds no endpoints.
  - Pipeline path exercised: ingestion → [login_events] → normalization (+ LDAP enrichment for the OIDC scenes 5/6) → events.normalized_attributes (PostgreSQL). The program reads the persisted normalized_attributes JSONB directly; there is intentionally no query API (What NOT to Build §7).
  - Directory dependency: Scenes 5 and 6 require alice/diana to have memberOf {engineering, vpn-users} in the live directory — produced by Step 1. Without Step 1, enrichment returns empty groups, list_merge cannot occur, and the narrative-verification checks for Scenes 5/6 abort. Step 4 therefore logically depends on Step 1.
  - Config dependency: the Scene-6 split (display_name → OIDC, department → LDAP) requires the Step 2 display_name.priority change. Without it, Scene 6's display_name winner is ldap and the core verification check aborts. Step 4 logically depends on Step 2.
  - Infrastructure rebuild: bootstrap.ldif + overlay are baked into the OpenLDAP image, so Step 1 requires `docker compose build openldap` and a data-volume reset (`docker compose down -v` or the openldap-only volume wipe) for memberOf to populate. config/normalization.yaml is bind-mounted read-only into identity-normalization (compose `./config:/app/config:ro`) and loaded once at startup, so Step 2 requires an identity-normalization restart (no rebuild) to take effect.
  - Shared state / caching: the LDAP enrichment cache (Redis, 60s TTL) means back-to-back same-email lookups within the TTL hit the cache; sequential scene submission is deliberate but correctness does not depend on it.
  - Real-time / WebSocket: none. This is a Specs 0–2 normalization demo — no auth, dashboard, WebSocket, risk scoring, or signal enrichment.

KNOWN RISKS
  - [Spec file commit boundary] docs/architecture/SPEC_DEMO_Normalization_Showcase.md must NOT be committed. It appears in no chunk's scope_boundary or shared_files and is listed under do_not_touch. The committed doc edits are SPEC_0 §5.3 and SPEC_2 §5.6 only.
  - [osixia cn=config overlay mechanism — primary uncertainty] The memberof/refint overlays load against cn=config, NOT the data-bootstrap LDIF path (which targets the dc=corp,dc=com data db as cn=admin). The intended approach is a baked-in shell script that runs `ldapmodify -Y EXTERNAL -H ldapi:///` against cn=config to load the module and add the overlays to the mdb database. The exact olc* DNs/ordinals and whether the `memberof` module is preloaded differ across osixia builds; the implementer MUST verify against the running osixia/openldap:1.5.0 container with live ldapsearch on cn=config and adjust. Acceptance signal: alice and diana return memberOf {engineering, vpn-users} after a clean rebuild + volume reset. Mitigation: if the script-against-cn=config approach proves unstable on this image, fall back to placing cn=config-targeted *.ldif files in the osixia custom-config path the image documents for that version — but do NOT resort to injecting synthetic memberOf onto user entries (spec §5.6 forbids it; no existing user attribute may change).
  - [Data-volume reset required] memberOf back-population only happens at first seed of an empty ldap-data volume. Picking up Step 1 requires `docker compose build openldap` then a volume reset; an existing volume will not retroactively gain groups/memberOf. The demo README and Step 1 verify steps assume a fresh seed.
  - [SPEC_2 §3.3 worked example drift — flagged, intentionally out of scope] SPEC_2 §3.3 (lines ~125–140) shows display_name unanimous confidence 0.90, which under the new weights becomes 0.85, and §5.6's lead-in note says "the §3.3 example assumes them." The developer constraint restricts SPEC_2 edits to §5.6 ONLY, so §3.3 is left unchanged. This is a deliberate, surfaced inconsistency: the §5.6 note may be lightly adjusted (within §5.6) to point out that the §3.3 example reflects the pre-change display_name weights. Recommend a separate follow-up to reconcile §3.3 if exactness there is desired; not done here to honor the §5.6-only boundary.
  - [Test reconciliation completeness] Analysis identified the affected tests in test_config_yaml.py, test_scalar_resolution.py, and test_confidence.py (all load the committed config and assert old display_name weights/priority). The inline-custom-config fallback test in test_scalar_resolution.py is unaffected. No ADR was found asserting the old default. The implementer must re-grep at implementation time and reconcile anything new; any miss surfaces as a failing test after the config change (the change is its own detector).
  - [memberOf=[] mock fixtures are NOT live-directory assertions] The memberOf:[] occurrences in identity-normalization tests are inline mock LDAP responses exercising adapter/enrichment code paths; they are not assertions that the seeded directory returns empty groups and require no change. Confirmed in analysis; flag if a live-enrichment test asserting empty groups for a seeded user is found.
  - [python-ldap dev-venv gap — no conflict] The dev venv cannot install python-ldap, but this work has no Python LDAP client code; the LDIF/overlay live in the container and the demo program uses httpx/psycopg only. No blocker.
  - [Scene 3 enrichment field representation] The narrative check #2 and the Scene-3 render depend on how the normalization service represents "no live lookup" for protocol ldap (§6.5). The implementer reads the actual persisted enrichment substructure for a native-LDAP event to assert the right shape; the check is "no live directory lookup performed," not a specific literal, to stay robust.
  - [Confidence ±0.01 targets are guidance, not asserted at runtime] The exact per-scene confidences (Scene1 0.75 … Scene6 0.84) are the implementer's correctness target verified manually within ±0.01; the program asserts only the structural/relative checks (§5.5), so minor numeric drift in non-display_name attributes does not break the run.
