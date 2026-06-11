# Code Security Reviewer — Memory Index

## NAAS Conventions
- [naas_shared structure](naas-shared-structure.md) — verified canonical shared-library module layout, models, and Spec-0 placeholders
- [LDAP enrichment invariants](ldap-enrichment-invariants.md) — ADR-0008/SPEC_2 §5.3 enrich invariants (injection escape, three-state cache, pool, graceful degradation); chunk-4 anti-patterns all resolved in final impl
- [Resolution + confidence invariants](resolution-confidence-invariants.md) — SPEC_2 §5.5/§5.5.2 conflict-resolution + confidence math for resolution.py; §3.3 payload illustrative not binding; chunk-5 conftest tempfile patch scoping
- [Consumer + dual-write invariants](spec2-consumer-dualwrite-invariants.md) — SPEC_2 §5.1 chunk-6 ordering/XACK-last, empty-batch sleep CPU-peg fix, §5.4 outcome→skip_reason map, dead-table drift hazard (resolved post-spec-2)
- [Normalization poison-message paths](normalization-poison-message-paths.md) — non-str raw_attributes paths all guarded post-spec-2 (incl. display_name/primary_email scalars); reference for not regressing the guards
- [Demo CLI invariants](demo-cli-invariants.md) — SPEC_DEMO demo_normalization.py gates (SQL safety, self-DELETE-only, no-default password, decoupling, no meta-language, verify corroboration checks) + gc.get_referrers self-registration anti-pattern (RESOLVED — block deleted, fixture self-registers) + benign str|None pyright drift
- [Integration harness invariants](integration-harness-invariants.md) — live-docker harness (tests/integration/conftest.py): compose `-p naas-it` isolation on every invocation, container_name/port concurrency-conflict-by-design, .env precedence pitfalls (`or` vs empty, inline-comment stripping), module-scoped cleanup ordering, testsfailed-delta capture
