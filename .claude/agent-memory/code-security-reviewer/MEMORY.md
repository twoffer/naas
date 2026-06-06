# Code Security Reviewer — Memory Index

## NAAS Conventions
- [naas_shared structure](naas-shared-structure.md) — verified canonical shared-library module layout, models, and Spec-0 placeholders
- [LDAP enrichment invariants](ldap-enrichment-invariants.md) — ADR-0008/SPEC_2 §5.3 enrich invariants (injection escape, three-state cache, pool, graceful degradation); chunk-4 anti-patterns all resolved in final impl
- [Resolution + confidence invariants](resolution-confidence-invariants.md) — SPEC_2 §5.5/§5.5.2 conflict-resolution + confidence math for resolution.py; §3.3 payload illustrative not binding; chunk-5 conftest tempfile patch scoping
- [Consumer + dual-write invariants](spec2-consumer-dualwrite-invariants.md) — SPEC_2 §5.1 chunk-6 ordering/XACK-last, empty-batch sleep CPU-peg fix, §5.4 outcome→skip_reason map, dead-table drift hazard (resolved post-spec-2)
- [Normalization poison-message paths](normalization-poison-message-paths.md) — non-str raw_attributes paths all guarded post-spec-2 (incl. display_name/primary_email scalars); reference for not regressing the guards
