---
name: normalization-validation
description: How to inject+trace identity-normalization events live, and the adapter rule-table refactor regression result
metadata:
  type: project
---

# Identity-Normalization Live Validation Notes

## Inject + trace recipe (works without host python-ldap / host redis client)
- Inject via REAL ingestion REST: `POST http://localhost:8001/events/ingest` (LoginEventIngest:
  required user_id/client_ip/protocol/timestamp; optional source/is_synthetic/is_historical/raw_attributes).
  Returns 202 `{"id": <uuid>, "status":"accepted"}`. The `id` is the correlation key.
- Trace by scanning `normalized_events`: the stream message has one field `data` = full JSON record;
  `rec["id"]` == ingestion id; `rec["normalized_attributes"]` carries the unified output.
- IMPORTANT host gotcha: a redis client run INSIDE identity-normalization defaults to host
  `localhost` and fails. Run the scan from a container that resolves the `redis` service alias, e.g.
  `docker exec naas-event-ingestion python -c '... redis.Redis(host="redis"...)'`. Or use
  `docker exec naas-redis redis-cli`. Do NOT assume `localhost` inside app containers.
- LDAP test users (bootstrap.ldif): alice@corp.com(Eng/FTE), bob@corp.com(Product/FTE),
  charlie@corp.com(Security/contractor), diana@corp.com(Eng/vendor), eve@partner.com(External/contractor).
  Note "Product"/"Security"/"External" are NOT in DEPARTMENT_CANONICAL → title-cased passthrough.

## Refactor: adapters extract() → declarative FieldRule rule-table + shared engine (2026-06-07)
- PASS (regression). `app/adapters/_mapping.py` (FieldRule NamedTuple, coerce_str, coerce_str_list,
  apply_field_rules) is UNTRACKED working-tree code; adapters+normalization_values modified, not committed.
  The 12h-old running image did NOT contain it — had to `docker compose up -d --build
  identity-normalization` to put the refactor in the live container before validating. Always rebuild
  when validating uncommitted working-tree changes; check `docker inspect --format {{.Created}}` vs edits.
- Verified live end-to-end (real ingestion→login_events→normalization→normalized_events + PG write):
  OIDC+LDAP-enrich(alice), SAML+LDAP-enrich(charlie), LDAP-native, both hardening cases. All correct.
- HARDENING confirmed live: OIDC `groups="admin"` (bare str) → `groups=[]` (NOT char-iterated);
  LDAP `memberOf="cn=..."` (bare str) → `groups=[]`. coerce_str_list is strict list-only.
- LDAP memberOf DN reduction intact: `["cn=engineering,...","cn=all-staff,..."]` → `["all-staff","engineering"]`.
- Cross-protocol enrich path (enrich()→self.extract() runs new coercion) merges dir attrs: confirmed
  via resolution_details priority(display_name ldap wins)/unanimous(dept,emp_type)/list_merge(groups).
- Cache path intact: back-to-back same email within 60s TTL → 1st cache_hit=false, 2nd cache_hit=true.
- No import errors from `_mapping`; consumer_loop_started clean; pending=0 lag=0; zero error logs.
