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

## Spec-2 review remediation (chore/spec-2-review-remediation) — full live validation PASS (2026-06-12)
- Branch changes: enrich() now uses parenthesised RFC-4515 filter `(mail=...)` (build_search_filter wraps
  in parens, escapes via ldap.filter.escape_filter_chars); timeout_ms from YAML → set_option(OPT_NETWORK_TIMEOUT
  /OPT_TIMEOUT, float seconds) on new pooled conns; cache_ttl_seconds + enrich_attributes threaded YAML→enrich();
  connection-error logging rate-limited to STATE CHANGES (first ERROR `ldap_enrichment_connection_error` in
  service.py:215, then DEBUG; INFO `ldap_enrichment_recovered` on first success after degraded). Adapter logs
  conn errors at DEBUG (`ldap_enrich_error`) so service owns the single ERROR. on_failure restricted to "continue".
- Canonical integration suite cmd: `python -m pytest tests/integration --integration -v` (CI ci.yml line 74).
  Harness (tests/integration/conftest.py) self-manages a SEPARATE compose project `naas-it` with `up --build
  --wait` + app-health poll, tears down `down -v --remove-orphans` (its OWN volumes only — default `naas_*`
  volumes untouched). Result: 30/30 passed ~66s; teardown clean. Default service subset = postgres/redis/openldap/
  event-ingestion/identity-normalization (NO keycloak — 60s start_period skipped).
- COMPOSE STACK SCOPE (this point in project): docker-compose.yml defines ONLY 6 services — postgres, keycloak,
  openldap, redis, event-ingestion, identity-normalization. Downstream pipeline (signal-enrichment, risk-evaluator,
  alert-service, etc.) NOT yet in compose. "all services healthy" = these 6. Full `up -d --build` → all 6 healthy
  in ~45-56s (keycloak healthcheck now works, ~45s).
- LIVE CHECKS PASS (manual, default-project stack): (2) parenthesised filter matches real OpenLDAP via real
  python-ldap — alice@corp.com OIDC → PG+stream enrichment.applied=true source=ldap cache_hit=false, all attrs
  sources=[ldap,oidc]; ghost email → skip_reason=no_ldap_match + negative sentinel `"null"` cached (2nd ingest
  same email short-circuits, 1 live query). (3) timeout float 2.0 accepted — ldap_enrich_match, zero set_option/
  bind errors. (4) openldap stop + 4 distinct seeded-email OIDC events → ALL ACKed (pending=0 lag=0), all published
  with skip_reason=ldap_connection_error (SERVER_DOWN→connection_error), EXACTLY ONE error-level
  ldap_enrichment_connection_error for burst (rest DEBUG, hidden); restart → diana@corp.com applied=true + exactly
  one INFO ldap_enrichment_recovered. Total error-level lines across whole run = 1. (5) /health healthy, consumer
  loop clean. Note: SERVER_DOWN maps to ldap_connection_error skip_reason (NOT ldap_search_error) — both accepted.
- Distinct-email gotcha: to force live LDAP attempts under failure, use DIFFERENT seeded emails (cache key is
  ldap_enrichment:{email}); same email within 60s TTL short-circuits and won't re-attempt.

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
