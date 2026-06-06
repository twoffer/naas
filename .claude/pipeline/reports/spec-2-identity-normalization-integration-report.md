# Integration Validation Report — Spec 2: Identity Normalization Service

Append-only record of integration-validator invocations for this spec (CONTRACTS.md §9).

## Validation Run 1 — FAIL — 2026-06-06T01:17:04Z

**Scope:** Spec 2 §6 criteria against the integrated stack (PostgreSQL, Redis, OpenLDAP, event-ingestion upstream, identity-normalization). Branch HEAD `3a57028`. Ingest via real `event-ingestion POST /events/ingest`.

**Verdict: FAIL — one blocking deployment defect (config path), all normalization logic otherwise verified correct.**

### Blocking issue
**identity-normalization fails to start in its committed Docker config (exit code 3).**
- `FileNotFoundError: [Errno 2] No such file or directory: '/config/normalization.yaml'` at `app/main.py:103`.
- Root cause: `services/identity-normalization/app/main.py:100-102` builds the config path with a 4-parent walk (`Path(__file__).parent.parent.parent.parent / "config" / "normalization.yaml"`) that assumes the HOST layout. In the image the app is at `/app/svc/app/main.py` (Dockerfile WORKDIR `/app/svc`), so 4 parents reach `/` → `/config/normalization.yaml`, which does not exist. Compose mounts `./config → /app/config` (verified `/app/config/normalization.yaml` present). No env-var override exists.
- Fix (feature-implementer): resolve the config path to the mounted `/app/config/normalization.yaml`, preferably via an env-var override defaulting to the compose mount target (also makes it test-injectable, ADR-0009). File: `services/identity-normalization/app/main.py:100-102`.

### §6 criteria — all PASS against a throwaway probe (same image/env/network/config content, only the config path bridged); FAIL as committed only because the container can't start
- §6.8 Health: probe `/health` → `{"status":"healthy","service":"identity-normalization",...}` (real container exits before serving).
- §6.7 Pipeline + ACK: `XINFO GROUPS login_events` → `normalization_workers`, pending=0, entries-read=5, lag=0; `normalized_events` XLEN=5; payload is full LoginEventRecord with normalized_attributes populated (ADR-0011).
- §6.1 Mapping: LDAP cn→display_name, SAML displayName→display_name, OIDC name→display_name, etc.
- §6.2 Value normalization: "eng"→Engineering, "fin"→Finance; "E"→FTE, "C"→contractor; unmapped employee_type "XYZ"→null (no resolution_details entry); unmapped departmentNumber "Security" title-cased+retained, penalized only when winning (charlie penalty_applied true, confidence 0.52).
- §6.3 Enrichment applied + conflict: OIDC alice token dept "Product" vs LDAP "Engineering" → applied:true, source_protocol oidc, department priority winner_source ldap, conflicting_values {oidc:Product}, penalty_applied true, conf 0.72; other attrs unanimous over [ldap,oidc]; overall 0.874.
- §6.4 Skipped no-match: ghost OIDC → applied:false, skip_reason no_ldap_match, all single_source, processed.
- §6.5 LDAP event skips: applied:false, skip_reason ldap_event, source_protocol ldap; memberOf DNs reduced to ["admin","engineering"].
- §6.6 Negative cache: ghost #1 outcome ldap_no_match (live), ghost #2 cache_hit_negative (no 2nd directory hit); Redis sentinel `ldap_enrichment:ghost@nowhere.com` = "null".
- §6.9 Config validation: bad correlation_key → exit 3 with descriptive `ValueError: Invalid correlation_key 'favorite_color'...`.
- §6.10 Graceful degradation: no-match events processed, not dropped; pending=0.

### Non-blocking notes
1. Seeded LDAP users have no `memberOf` → LDAP contributes empty groups (as expected; §3.3 payload is illustrative). Not a defect.
2. Compose `./config` bind reports read-write despite `:ro` declared — cosmetic; service only reads.
3. event-ingestion requires `source ∈ {user, simulator, api}` (used "api").

**Repo state after run:** clean (no source/config left modified; probe containers removed). The real `naas-identity-normalization` container remains `exited (3)` as the live bug reproduction.

## Validation Run 2 — PASS — 2026-06-06T01:31:24Z

**Re-validation after the config-path fix** to `services/identity-normalization/app/main.py` (the sole blocking defect from Run 1). End-to-end on the REAL committed Docker container (not a probe).

**Verdict: PASS.** The container now starts healthy on a plain `docker compose up -d --build identity-normalization` (no volume wipe); the fix's tier-2 selection of `/app/config/normalization.yaml` resolves the startup defect. All §6 behaviors hold end-to-end.

- §1 Startup/health: `docker compose ps` → Up (healthy); `/health` → 200 healthy; logs show `consumer_loop_started` + `identity_normalization_startup_complete`, no FileNotFoundError.
- §6.7 pipeline + ACK: group `normalization_workers`, pending=0, lag=0; one full-record message per event on `normalized_events` (ADR-0011, all metadata present).
- §6.1/§6.2 mapping + value normalization: OIDC/LDAP fields mapped; `employee_type:"full-time"`→FTE.
- §6.3 enrichment + conflict: alice OIDC dept "Sales" vs LDAP "Engineering" → applied:true source ldap; department priority winner_source ldap resolved "Engineering" conflicting_values {oidc:Sales} penalty_applied true; display_name unanimous→LDAP; groups list_merge; overall confidence 0.847.
- §6.5 ldap_event skip / §6.4 no_ldap_match skip: confirmed.
- §6.6 negative cache: two successive absent-user logins → first ldap_no_match (live + "null" sentinel cached), second cache_hit_negative (one LDAP query for two logins).
- §6.9 config validation abort: bad correlation_key via tmp config + NORMALIZATION_CONFIG_PATH override → descriptive ValueError, exit 3 (committed config untouched; also confirms the fix's tier-1 env override).
- §6.10 graceful degradation: with OpenLDAP stopped, event NOT dropped → skip_reason ldap_search_error, OIDC-only normalization, published + ACKed, service stayed healthy.

**Cleanup:** `git status` shows only `services/identity-normalization/app/main.py` modified (the fix); committed config unmodified; OpenLDAP + service healthy; stack left running.
