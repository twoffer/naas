---
name: ldap-memberof-overlay
description: memberof overlay was broken (osixia .sh hook never ran); RESOLVED 2026-06-09 via 00-memberof-overlay.ldif that reconfigures the built-in overlay for groupOfNames/member
metadata:
  type: project
---

# RESOLUTION (validation run 2, 2026-06-09 — PASS)
- Fix that works: `infrastructure/openldap/00-memberof-overlay.ldif` (baked via Dockerfile
  COPY into `ldif/custom/`, name-sorts before bootstrap.ldif). It does a
  `changetype: modify / replace` on `olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config`
  setting `olcMemberOfGroupOC: groupOfNames` + `olcMemberOfMemberAD: member`. osixia's
  ldap_add_or_modify() runs custom *.ldif via `ldapmodify -Y EXTERNAL -H ldapi:///` AFTER the
  default overlay entry exists, so the modify lands (no second-overlay collision). The dead
  `memberof-overlay.sh` was deleted 2026-06-10 (script, Dockerfile COPY, pin tests, SPEC_0
  §5.3 mention all removed together).
- Verified live on fresh volume (`down -v && up -d --build`): live overlay config shows
  groupOfNames/member; memberOf back-populated: alice={engineering,vpn-users},
  diana={engineering,vpn-users}, bob={product}, charlie={security}, eve=none. No existing
  user attribute altered (memberOf is operational/computed).
- Downstream RESOLVED: Scene-5 (alice) groups list_merge confidence now **0.90** (was 0.80),
  directory {engineering,vpn-users} corroborates token groups. Scene-6 (diana) list_merge 0.90,
  split winners correct. Demo full run exit 0, verify passed, 6 rows removed. Full pytest
  1519 passed / 2 skipped.
- SUPERSEDED for Scene-6 (b6d7a81, 2026-06-10): Scene 6's OIDC token now deliberately omits
  vpn-users so enrichment visibly back-populates it. Scene-6 groups list_merge is **0.80 BY
  DESIGN** (1 of 3 groups corroborated), strictly below Scene-5's 0.90 — do not read 0.80
  there as the broken-overlay symptom again. verify_results enforces the new shape: merged
  groups strict superset of token groups, corroborated fraction ≥ ¼, Scene-6 < Scene-5.

## GOTCHA that cost me time (record for next run)
- LDAP users are under `ou=users,dc=corp,dc=com` (NOT ou=people). Admin DN
  `cn=admin,dc=corp,dc=com`, password **admin** (compose LDAP_ADMIN_PASSWORD default, NOT
  admin_password). My earlier wrong creds/base produced empty results — don't mistake that for
  a broken overlay.
- memberOf is operational: a plain ldapsearch attr dump won't show it; request `memberOf`
  explicitly.

---

# (HISTORICAL) LDAP memberof overlay seam failure (normalization-demo, found 2026-06-09 run 1)

## Symptom
- The four `groupOfNames` groups (engineering/product/security/vpn-users) seed
  correctly with the right `member` DNs (bootstrap.ldif is baked into the image,
  ordering is fine). BUT `ldapsearch ... memberOf` returns NOTHING for any user
  (alice, diana, bob, charlie, eve). Reverse `memberOf` back-population is dead.
- Downstream: LDAP enrichment of alice/diana still runs (`enrichment.applied=true`,
  `cache_hit` works), but merges an EMPTY directory group set. Scene-5 `groups`
  `list_merge` resolves to the OIDC token groups only, `total_unique_groups=3`,
  confidence **0.80** (pure union, zero corroboration) instead of the spec's
  expected **≈0.90** (3 groups, two corroborated by the directory).

## Root cause — SEAM: infrastructure/openldap Dockerfile ↔ osixia entrypoint hook contract
- `memberof-overlay.sh` is COPYd to
  `/container/service/slapd/assets/config/bootstrap/memberof-overlay.sh`, but the
  osixia/openldap entrypoint does NOT execute arbitrary `.sh` files there. It only
  runs LDIF under `bootstrap/ldif/...` and scripts from its own designated hook
  locations. The script never executes (no trace in `docker logs naas-openldap`;
  osixia `rm -rf`s the bootstrap dir after seed so it's gone at runtime).
- The overlay that IS live in cn=config is osixia's **built-in default** memberof
  overlay, configured for `olcMemberOfGroupOC: groupOfUniqueNames` /
  `olcMemberOfMemberAD: uniqueMember`. Our groups are `groupOfNames`/`member`,
  so the overlay never matches them → memberOf never populated.
- Even had the script run, its `ldapmodify -a olcOverlay={0}memberof,...` would
  collide with the already-present default overlay slot; the `|| true` swallows
  the error silently. So the script is doubly non-functional.

## Why the demo still PASSED despite this — gap since CLOSED (1037f46 + b6d7a81)
- At the time: the demo's §5.5 narrative check only asserted `groups` resolution ==
  `list_merge` structurally; token∪∅ is still a list_merge, so the check was satisfied.
  The broken overlay was INVISIBLE to the demo's own verification.
- NOW: verify_results check 8 recovers the corroborated fraction from the groups
  confidence (0.7 + 0.3×fraction) and requires ≥ ½ on Scene 5 and ≥ ¼ plus a
  strict-superset-of-token-groups check on Scene 6. A token-only union (fraction 0,
  confidence 0.70) — e.g. broken memberOf back-population — now FAILS verification.

## How to apply / how to verify
- ALWAYS verify the overlay by `ldapsearch -x ... -b uid=alice,... memberOf` AND
  by reading the LIVE overlay config:
  `ldapsearch -Y EXTERNAL -H ldapi:/// -b cn=config "(objectClass=olcMemberOf)"`
  — check `olcMemberOfGroupOC`/`olcMemberOfMemberAD` actually say groupOfNames/member.
- Do not trust group entries existing as proof memberOf works; they are independent.
- SPEC_0 §5.3 line ~1141 asserts "alice and diana will carry memberOf after seed" —
  doc describes intended behavior the infra does not deliver. Doc/infra drift.
- Fix belongs to feature-implementer (chunk 1): make osixia actually run the
  overlay config (correct hook path / use a real osixia env mechanism), and make
  the overlay watch groupOfNames/member. Re-validate on fresh ldap-data volume.

## Demo --keep gap (chunk 3) — RESOLVED (8cadfbb)
- main() now prints both the retained count and the retained event IDs on `--keep`
  ("Retained N event(s)…" + "Retained event IDs: […]"). Historical: the chunk-3 build
  preserved events but printed nothing, despite spec §3.6 / criterion #8.

## Env note for the demo (updated for a7c7b41)
- POSTGRES_PASSWORD has NO default anymore (the old hardcoded `naas` fallback was
  removed) — the demo exits with guidance unless POSTGRES_PASSWORD is exported or
  --db-dsn is passed. The stack default is `naas_dev_password` (compose). The .env
  has it but isn't exported to host shell, and POSTGRES_HOST in .env is `postgres`
  (docker alias, unreachable from host). Run with explicit override:
  `--db-dsn "host=localhost port=5432 dbname=naas user=naas password=naas_dev_password"`.
