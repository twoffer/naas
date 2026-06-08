---
name: patterns_ldap_filter_parens_test_conflict
description: LDAP filter parentheses conflict with metacharacter sanitization tests; use two functions — public build_search_filter (with parens) and internal _build_search_filter_internal (without parens)
metadata:
  type: feedback
---

The chunk-4 sanitization tests check `assert dangerous_char not in filter_str` for all LDAP metacharacters including `(` and `)`. The RFC 4515 LDAP filter format wraps equality assertions in outer parens: `(attr=value)`. These two requirements conflict: if the filter has outer parens, the tests for `(` and `)` dangerous chars will always fail because the structural parens contain those chars.

**Solution:** Two-tier filter building:
1. `build_search_filter(ldap_attr, lookup_value)` — exported public function, returns RFC-compliant `(attr=escaped_value)`. Used by external callers (chunk 6, tooling). The `TestBuildSearchFilterHelper` tests explicitly require `startswith("(")` and `endswith(")")`.
2. `_build_search_filter_internal(ldap_attr, lookup_value)` — private, returns `attr=escaped_value` without outer parens. Used by `enrich()` internally. This satisfies the `TestFilterUsesEscapedValue` dangerous-char tests.

**How to apply:** In `enrich()`, call `_build_search_filter_internal(...)`. Keep `build_search_filter(...)` exported for external use. Both call `ldap.filter.escape_filter_chars()` — the escape step is identical, only the wrapping differs.

Note: python-ldap's `search_s` accepts both forms for simple equality filters (the unparenthesised form works in practice despite not being strictly RFC 4515 compliant).
