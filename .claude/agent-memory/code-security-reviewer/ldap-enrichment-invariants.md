---
name: ldap-enrichment-invariants
description: ADR-0008 / SPEC_2 §5.3-5.4 invariants for the identity-normalization LDAP enrichment adapter (pool, three-state cache, injection, graceful degradation)
metadata:
  type: reference
---

LDAP enrichment lives in `services/identity-normalization/app/adapters/ldap.py`. Spec: `docs/architecture/SPEC_2_Identity_Normalization_Service.md` §5.3 (enrich), §5.4 (degradation). See [[naas-shared-structure]].

## Hard invariants (verify every review)
- **Injection:** filter value MUST go through `ldap.filter.escape_filter_chars` before interpolation. Attribute side comes from the fixed `UNIFIED_TO_LDAP` map in `app/normalization_values.py` (not attacker-controlled). Raw interpolation = blocking SECURITY CONCERN.
- **Three-state cache:** miss→query; negative sentinel (`'"null"'`)→None no-query; positive JSON dict→return. Positive AND negative use the SAME `cache_ttl_seconds`. Transient failures (timeout/SERVER_DOWN/search error/unexpected) MUST NOT be negative-cached (else a blip poisons the TTL).
- **Event-loop safety:** every blocking python-ldap call wrapped in `asyncio.to_thread`. `import ldap` is LAZY inside functions (top-level import breaks the dev venv, which lacks python-ldap).
- **Graceful degradation:** `enrich` never propagates an LDAP exception; returns None on any failure/no-match/unmappable field.
- **Cache key:** `f"{LDAP_ENRICHMENT_CACHE_PREFIX}{lookup_value}"`. TTL bounds cardinality of attacker-influenceable email keys — acceptable, not a finding.

## Resolved in final impl (do NOT re-flag)
The three chunk-4 review findings were all fixed before Spec 2 merged (commit `f77d950`); verify they are still satisfied rather than re-reporting them:
- **Bounded connection pool now exists.** `_get_pool` builds an `asyncio.Queue` sized by `settings.ldap_pool_size`; `_pool_search` acquires/returns connections and discards broken ones (returns `None` to the slot). No per-call `ldap.initialize` leak.
- **No `last_enrich_outcome` side-channel.** `enrich()` returns a `(attrs, outcome)` 2-tuple, so concurrent calls on a shared adapter are safe.
- **No PII in logs.** `enrich()` log lines key on `ldap_attr=`, never the email `lookup_value`.
