# Integration Validation Report — Identity Normalization Demo

Append-only record of every integration-validator invocation for this spec (CONTRACTS.md §9).

## Validation Run 1 — FAIL — 2026-06-09T16:51:00Z

**Verdict:** FAIL — one blocking infrastructure-seam defect; most acceptance criteria otherwise pass.

**Level 1 — Infrastructure health:** PASS. `docker compose down -v && up -d --build` brought all 6 services healthy (~40s); `:8001/health` and `:8002/health` both 200 healthy.

**Level 2 — LDAP group infrastructure (chunk 1):**
- Four `groupOfNames` groups exist with correct members (engineering→{alice,diana}, product→{bob}, security→{charlie}, vpn-users→{alice,diana}). PASS.
- No user attribute altered. PASS.
- **`memberOf` back-population: FAIL (BLOCKING)** — `ldapsearch ... memberOf` returns nothing for any user; enrichment-style lookup of alice returns cn + departmentNumber but no memberOf.

**Level 2 — Demo end-to-end (chunks 2+3+4):**
- Default run: mechanically PASS — preflight ok (with `--db-dsn` override, see non-blocking #3), 6 events submitted + normalized, narrative verification passed, 6 panels + summary rendered, "removed 6 event(s)".
- Scene-6 split-winner: PASS — display_name priority winner=oidc "Di Prince" (0.56); department priority winner=ldap "Engineering" (0.72); "Why the split?" annotation present with both ownership points + global-rule punchline.
- Confidence arc: PASS — C(4)=0.450 < C(2)=0.690 < C(1)=0.752 < C(3)=0.812; Scene 6 overall 0.823 (~0.84).
- `--keep` run: PARTIAL — preserves the 6 rows but does NOT print retained ids (non-blocking #1). Validator cleaned up all rows; 0 demo rows remain.

**Level 5 — Regressions:** Targeted suites 1118 passed, 2 skipped. Full repo suite 1519 passed, 2 skipped.

**Doc mirror (light):** SPEC_2 §5.6 = priority [oidc,saml,ldap] / weights {ldap:0.85,saml:0.75,oidc:0.70}; SPEC_0 §5.3 documents the four groups + overlay. (SPEC_0 §5.3 asserts alice/diana carry memberOf after seed — contradicted by the live infra defect; same root cause.)

### BLOCKING ISSUE — `memberOf` never back-populated; LDAP enrichment merges zero directory groups
**Seam:** `infrastructure/openldap/Dockerfile` ↔ osixia/openldap entrypoint hook contract (chunk 1).
Diagnostic evidence:
- The live `cn=config` overlay is osixia's **built-in default** memberof overlay, configured for `olcMemberOfGroupOC: groupOfUniqueNames` / `olcMemberOfMemberAD: uniqueMember`. The seeded groups are `groupOfNames`/`member`, so the default overlay never matches them.
- `memberof-overlay.sh` **never executed**: no trace in `docker logs naas-openldap`; osixia `rm -rf`s the bootstrap dir post-seed. The Dockerfile copies it to `/container/service/slapd/assets/config/bootstrap/memberof-overlay.sh`, but osixia does NOT auto-run arbitrary `.sh` files there — it runs LDIF under `bootstrap/ldif/` and scripts only from its own designated hook locations.
- Even had it run, `ldapmodify -a olcOverlay={0}memberof,…` would collide with the already-present default overlay slot; the `|| true` swallows the error silently.
- Downstream symptom (end-to-end proof): for an alice OIDC event, `enrichment.applied=true` but `resolution_details.groups` = union of OIDC token groups only (`total_unique_groups:3`, confidence **0.80**), nothing from the directory. Spec §6.6 expects Scene-5 `list_merge` ≈ **0.90** (two corroborated). Scene 6 same pattern.

**Suspected fix (feature-implementer, chunk 1):** make osixia actually execute the overlay configuration at first seed via a supported mechanism (e.g. osixia's `environment`/startup hook, or a custom entrypoint step), and ensure the memberof overlay watches `groupOfNames`/`member` (not the default `groupOfUniqueNames`/`uniqueMember`). Re-validate on a fresh `ldap-data` volume: `ldapsearch -x -b uid=alice,ou=users,dc=corp,dc=com memberOf` must return `{engineering, vpn-users}` and the live `(objectClass=olcMemberOf)` config must show `groupOfNames`/`member`.

### NON-BLOCKING ISSUES
1. **`--keep` does not print retained event ids (demo, chunk 3/4).** `main()` skips `cleanup_events` entirely on `--keep`, so neither the count nor the ids print. `cleanup_events`' docstring claims it prints retained ids on the keep path, but that branch is unreachable. Events ARE preserved correctly; only the printout is missing. Violates spec §3.6 / Validation Criterion #8.
2. **Demo's narrative verification cannot detect the broken overlay.** §5.5 asserts `groups` is structurally `list_merge` (token ∪ ∅ still qualifies), so the demo PASSes even with zero directory corroboration. Recommendation: add a check that merged groups / `list_merge` confidence reflect directory corroboration, so this infra regression cannot ship silently.
3. **Demo DB connection defaults don't match the stack.** Demo defaults `POSTGRES_PASSWORD=naas`; stack uses `naas_dev_password`. `.env` has the right value but sets `POSTGRES_HOST=postgres` (docker-internal, unreachable from host) and isn't exported to a host shell. From the host the demo needs an explicit `--db-dsn`. Not a code defect (script honors env/override), but `demo/README.md` should document the host-shell DSN/credential reality.

**Cleanup confirmed:** zero `source='api' is_synthetic=true` rows remain in the events table.

## Validation Run 2 — PASS — 2026-06-09T22:12:46Z

**Verdict:** PASS — the Run-1 blocking defect is resolved; both Run-1 non-blocking items confirmed fixed; no regressions.

**Trigger:** Re-validation after the ad-hoc integration fix (overlay execution mechanism + the two non-blocking items), applied between Run 1 and Run 2.

**Level 1 — Infrastructure health:** PASS. Fresh-volume rebuild (`down -v && up -d --build`); postgres/redis/openldap/event-ingestion/identity-normalization all healthy; `:8001/health` and `:8002/health` 200 healthy. (keycloak `health: starting` — known-benign, not exercised by this demo.)

**memberOf back-population (the Run-1 blocker) — PASS:**
- Live overlay config on `olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config`: `olcMemberOfGroupOC: groupOfNames`, `olcMemberOfMemberAD: member` (Run 1 had the osixia default groupOfUniqueNames/uniqueMember).
- `memberOf`: alice → {engineering, vpn-users}; diana → {engineering, vpn-users}; bob → {product}; charlie → {security}; eve → none. All correct.
- No existing user attribute altered (memberOf is operational/computed, only returned when explicitly requested).
- Seam confirmed: `00-memberof-overlay.ldif` (name-sorted before `bootstrap.ldif`) reconfigures the built-in overlay via osixia's custom-LDIF hook (`ldapmodify -Y EXTERNAL`) before groups load, so back-links populate.

**Demo end-to-end — PASS:** `--pace 0` (with explicit host `--db-dsn`) → exit 0; preflight ok; 6 events submitted + normalized; narrative verification PASSED without `--skip-verify`; 6 panels + summary rendered; 6 rows removed.

**Corroboration beat now real (key check) — PASS:**
- Scene 5 (alice/oidc): enrichment applied (source=ldap, live lookup); groups `list_merge` = {engineering, product-admins, vpn-users}, **confidence 0.90** (Run 1 was 0.80); overall 0.917. Token ∪ directory = union of 3, 2 corroborated.
- Scene 6 (diana/oidc): enrichment applied; groups `list_merge` = {engineering, oncall, vpn-users}, confidence 0.90. Split winners correct: display_name → oidc "Di Prince" (loser ldap "Diana Prince"); department → ldap "Engineering" (loser oidc "Marketing").

**`--keep` retained-ids printout — PASS:** preserves 6 rows and prints the count + six retained ids. Validator cleaned up afterward; 0 demo rows remain.

**Regressions — PASS:** full `pytest` 1519 passed, 2 skipped, 0 failed. Only benign deprecation warnings.

**Blocking issues:** none. **Non-blocking:** none outstanding (both Run-1 non-blocking items fixed). Pre-existing benign keycloak "starting" health state and deprecation warnings unchanged/out of scope.
