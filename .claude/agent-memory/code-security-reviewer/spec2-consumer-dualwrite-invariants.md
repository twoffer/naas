---
name: spec2-consumer-dualwrite-invariants
description: SPEC_2 §5.1 chunk-6 consumer/dual-write/lifespan invariants for identity-normalization (consumer.py, service.py, repository.py, main.py)
metadata:
  type: reference
---

Chunk-6 integration layer of identity-normalization. Spec: `docs/architecture/SPEC_2_Identity_Normalization_Service.md` §5.1 (ordering), §5.4 (skip_reason), §3.1/§3.2 (persist/publish), ADR-0002 (dual-write), ADR-0011 (full record on streams). See [[ldap-enrichment-invariants]], [[resolution-confidence-invariants]].

## Hard invariants (verify every review)
- **Dual-write ordering (§5.1, ADR-0002):** in `consumer.py::_process_message` order MUST be parse → `service.normalize` → `repository.write`+commit → `publisher.publish_normalized` → `redis.xack`. XACK is the LAST step and only after BOTH write and publish. On ANY exception: log, NO xack (message stays pending). Confirmed correct as of 2026-06.
- **Consumer CPU-peg hardening:** empty-batch path (`if not batches:`) MUST `await asyncio.sleep(_EMPTY_BATCH_SLEEP_S)` with a real non-zero value (0.5s) before `continue`. `sleep(0)` is NOT sufficient (only yields once). Sleep must be ONLY on empty path — never delays message processing. Reason: a non-blocking/mocked Redis that ignores `block=2000` would busy-spin the loop at 100% CPU (availability/DoS).
- **Graceful degradation (§5.4):** `service.normalize()` NEVER raises on enrichment failure — enrichment exceptions caught in `_determine_enrichment` → `EnrichmentSkipped(skip_reason="ldap_search_error")`. Enrichment skip ≠ processing failure; skipped events still persist+publish+xack.
- **Source-agnostic:** NO branch on `is_synthetic` anywhere in service.py. Decision = protocol + config only.
- **Repository (§3.1):** bare `sqlalchemy.update(EventORM).where(id==event_id).values(normalized_attributes=...)` — no INSERT, no SELECT, no add(), no create_all/DDL. Bound params (ORM, not string interpolation). `async with session_factory()` per event + commit. Uses injected `get_session_factory()`, NOT request-scoped `get_db_session`.
- **Publish (§3.2, ADR-0011):** `NormalizationPublisher.publish_normalized` sets `record.normalized_attributes = normalized.model_dump(mode="json")` then `publish_to_stream(STREAM_NORMALIZED_EVENTS, record.model_dump(mode="json"))` — full record, shared helper, no hand-rolled XADD.
- **Lifespan (§5.1):** invalid config propagates (aborts startup); `ensure_consumer_group(STREAM_LOGIN_EVENTS, GROUP_NORMALIZATION)` called once; consumer launched via `asyncio.create_task`; cancelled+awaited on shutdown (CancelledError swallowed). create_app/`/health`/module-level `app` intact.

## §5.4 outcome→skip_reason mapping (enrich() returns (attrs, outcome) tuple)
ldap_match→Applied(cache_hit=False); cache_hit_positive→Applied(cache_hit=True); ldap_no_match/cache_hit_negative→no_ldap_match; ldap_timeout→ldap_timeout; ldap_connection_error→ldap_connection_error; ldap_search_error/ldap_unexpected_error/unmappable_field→ldap_search_error (catch-all). Decision-level: disabled→ldap_disabled; protocol==ldap→ldap_event; empty correlation value→invalid_correlation_key. All 7 skip_reasons must be members of shared `EnrichmentSkipReason` Literal in models.py (Pydantic validates).

## Drift hazard seen (chunk-6, 2026-06)
- `service.py` defines `_MATCH_OUTCOMES` (frozenset) and `_OUTCOME_TO_SKIP_REASON` (dict) at module top but they are DEAD (grep shows defs only; the real mapping is inline in `_map_outcome_to_enrichment`). Two copies of the §5.4 table that can silently diverge. Recommend deleting the unused constants OR routing the inline code through the table. Non-blocking LOW.
