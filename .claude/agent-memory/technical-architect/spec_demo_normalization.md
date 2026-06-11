---
name: spec-demo-normalization
description: Decomposition gotchas for the standalone normalization demo spec — osixia cn=config overlay mechanism, display_name config-change test reconciliation surface, spec-doc commit exclusion
metadata:
  type: project
---

# Identity Normalization Demo — decomposition notes

Spec: `docs/architecture/SPEC_DEMO_Normalization_Showcase.md` (this demo spec doc is NEVER committed — exclude from scope_boundary/shared_files, list in do_not_touch). Edits to SPEC_0 §5.3 and SPEC_2 §5.6 ARE committed.

**Why:** A demo spec that also makes deliberate product changes (config + LDAP groups) to back its narrative. Three independent workstreams; the CLI program is the integration-facing final chunk depending on the other two.

**How to apply:** Reuse the 4-chunk shape (LDAP infra+SPEC_0 mirror / config+SPEC_2 mirror+test reconcile / demo scaffold / demo flow) for any "demo over the live pipeline" spec.

## osixia/openldap:1.5.0 overlay mechanism (memberof) — as shipped (corrected 2026-06-10)
- The planning assumption above ("`ldif/custom/` only reaches the data db; bake a shell script for cn=config") was WRONG twice over: osixia never executes `.sh` files from the bootstrap dir (the vestigial memberof-overlay.sh was deleted in 1037f46), AND osixia's `ldap_add_or_modify()` detects `changetype:` in a custom LDIF and applies it via `ldapmodify -Y EXTERNAL -Q -H ldapi:///` — which DOES write cn=config (SASL EXTERNAL maps to the cn=config write identity `gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth`).
- Shipped fix (8cadfbb): `infrastructure/openldap/00-memberof-overlay.ldif`, COPYd into `ldif/custom/`; the `00-` prefix sorts it before bootstrap.ldif in osixia's `find | sort`. It is a `changetype: modify` that `replace:`s `olcMemberOfGroupOC: groupOfNames` + `olcMemberOfMemberAD: member` on the BUILT-IN default overlay `olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config` (osixia preloads one configured for groupOfUniqueNames/uniqueMember — which is why memberOf was silently empty). Modify-not-add avoids a second-overlay collision and is idempotent.
- refint was NOT shipped (no olcMemberOfRefInt, no refint overlay anywhere in infrastructure/openldap/) — back-population alone meets the demo acceptance.
- olc* DNs/ordinals and whether `memberof` is preloaded vary by osixia build — verify against the live container with ldapsearch on cn=config; do NOT assume specific olcOverlay ordinals.
- Acceptance (validated PASS 2026-06-09 on fresh volume): alice/diana return memberOf {engineering, vpn-users} after clean rebuild + `down -v` (fresh ldap-data volume). memberOf only back-populates at first seed of an empty volume.
- bootstrap.ldif: groupOfNames entries go AFTER all user entries (member DNs must pre-exist); each groupOfNames needs ≥1 member; never declare dc=corp,dc=com.

## display_name config change → which tests assert the OLD default
A change to `config/normalization.yaml` `display_name` (priority/weights) breaks tests that load the committed config (`_load_real_config()` / cfg fixture). Inventory found 2026-06-09:
- `tests/services/identity_normalization/test_config_yaml.py`: `test_display_name_ldap_weight_is_0_90` / `_saml_weight_is_0_70` / `_oidc_weight_is_0_60` / `_priority_is_ldap_saml_oidc`.
- `tests/services/identity_normalization/test_scalar_resolution.py`: `test_single_source_display_name_oidc`, `test_single_source_saml_display_name_weight`, `test_unanimous_display_name_oidc_ldap_confidence_is_max_weight`, `test_unanimous_three_sources_max_weight_wins`, `test_display_name_priority_ldap_over_oidc`. The fallback test that builds an INLINE custom config (no priority, weights {ldap:0.90,saml:0.70}) does NOT read the file — leave it.
- `tests/services/identity_normalization/test_confidence.py`: every overall/unanimous expected value summing a display_name term (display_name oidc=0.60 / ldap=0.90 hardcoded).
- No ADR in docs/adr/ asserts the old default (none found). `memberOf:[]` in identity-normalization tests are inline MOCK fixtures, NOT live-directory assertions — no change needed.

## SPEC_2 §3.3 drift (flagged, out of scope)
SPEC_2 §3.3 worked example (~lines 125–140) shows display_name unanimous=0.90 and §5.6's lead-in note says "the §3.3 example assumes them." A display_name weight change makes that 0.85, but the "SPEC_2 §5.6 ONLY" boundary forbids editing §3.3. The §5.6 note may be lightly adjusted within §5.6. Surface as a known risk; recommend separate follow-up.

Status 2026-06-10: still open by design — §3.3 still shows 0.90; the §5.6 lead-in note explicitly marks it as computed against the pre-change weights and preserved as illustrative. ec7a42f edited §3.3 payloads (added `sources` to list_merge, sorted source lists) but intentionally kept 0.90. No FOLLOWUPS.md entry exists for it.

## Demo program contract (standalone, no service coupling)
- demo/ talks to ingestion over HTTP (POST :8001/events/ingest, 202 {id,status}) + raw SQL read-back (`SELECT id, protocol, normalized_attributes FROM events WHERE id = ANY(%(ids)s)`; cleanup `DELETE … WHERE id = ANY(%(ids)s)`). No query API exists in Specs 0–2 by design.
- Deps: rich, httpx, psycopg[binary]. Optional soft `naas_shared.models` import, default to plain-dict path.
- config/normalization.yaml is bind-mounted ro into identity-normalization (`./config:/app/config:ro`), loaded once at startup → config change needs a restart (no rebuild). LDIF/overlay are baked → need image rebuild + volume reset.
- Post-pipeline hardening (already on the branch): POSTGRES_PASSWORD has NO default in the demo CLI (a7c7b41 — exits with guidance unless the env var or --db-dsn is given); ListMergeResolution carries a `sources` field (contributing protocols, sorted — ec7a42f) and the demo summary table derives Protocol(s) from the union of resolution-detail sources; Scene 6's OIDC token omits vpn-users so enrichment visibly back-populates it (b6d7a81), with verify enforcing strict-superset + corroborated-fraction checks.
