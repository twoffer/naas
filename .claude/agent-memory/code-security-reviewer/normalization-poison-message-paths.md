---
name: normalization-poison-message-paths
description: identity-normalization non-str raw_attributes type-confusion paths — all now guarded (incl. display_name/primary_email scalars) post-spec-2; reference for not regressing the guards
metadata:
  type: reference
---

The "post-spec-2-followups" remediation (item A) hardened identity-normalization against non-str `raw_attributes` (attacker-influenceable IdP claims / event payloads, since `LoginEventBase.raw_attributes` is `Dict[str, Any]` — no per-value validation at ingest). See [[ldap-enrichment-invariants]], [[resolution-confidence-invariants]].

## Guarded (fixed, verify still present)
- `normalize_department(value: object)` / `normalize_employee_type(value: object)` in `app/normalization_values.py` short-circuit non-str → `(None, False)` / `None`.
- All three adapter `extract()` `groups` lists filtered to `isinstance(g, str)` (oidc.py, saml.py, ldap.py).
- LDAP `extract()` `memberOf` filtered to str before `_reduce_dn_to_group_name` (which calls `.strip()`).

## RESIDUAL GAP — CLOSED (verified 2026-06, item G of test_remediation.py)
Was: `display_name`/`primary_email` scalars not isinstance-guarded → non-str scalar reached `resolution.resolve()` → `NormalizedAttributes` `string_type` ValidationError inside resolve (no try/except in `service.normalize`) → propagated to `consumer._process_message` `except` → logged, NOT xacked → stuck-pending event forever (no XAUTOCLAIM/reclaim).
Now FIXED: all three adapter `extract()` guard both scalars with `v if isinstance(v := raw_attributes.get(<key>), str) else None` (oidc: name/email; saml: displayName/email; ldap: cn/mail). `resolution.resolve()` is the SOLE `NormalizedAttributes(...)` constructor in the service (grep-confirmed). Both feed paths now str-clean: `_build_attribute_sources` (guarded extract) and `_merge_ldap_attrs` (enrich → guarded extract on live results, or `json.loads` of a cache value that was itself `json.dumps(self.extract(...))` — cache is write-controlled, no poison vector). employee_type Literal already guarded by `normalize_employee_type`; department by `normalize_department`; groups list-filtered to str. Poison-message/stuck-pending path fully closed.

## Note on F/H (consumer PII redaction) — HARDENED (verified 2026-06)
`consumer.py` `_process_message` except now two-branch: `isinstance(exc, pydantic.ValidationError)` → logs `error_locations=[e["loc"] for e in exc.errors()]` + error_type ONLY (no `str(exc)`; Pydantic v2 `loc` tuples carry field names/indices, never `input`/`input_value`, so no PII). Non-ValidationError branch unchanged: `error=str(exc)[:200]`. XACK ordering (write→publish→xack inside try) and no-ACK-on-failure invariant unchanged. Top-level `import pydantic` (already a core dep) is fine.
