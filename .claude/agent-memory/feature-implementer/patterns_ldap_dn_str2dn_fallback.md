---
name: patterns_ldap_dn_str2dn_fallback
description: _reduce_dn_to_group_name uses ldap.dn.str2dn primary + regex fallback to keep dev-venv tests green when python-ldap is not installed
metadata:
  type: feedback
---

`_reduce_dn_to_group_name` in `app/adapters/ldap.py` must use `ldap.dn.str2dn` as the primary path (RFC-4514 correct escaped-comma handling) with `_CN_RDN_RE` regex as a fallback when `ldap.dn` raises `ImportError`.

**Why:** The remediation spec says use str2dn; but chunk-2 tests call `LdapAdapter().extract()` directly without injecting a fake ldap module (no monkeypatch). In that context `import ldap.dn` raises `ImportError` and the original `except Exception` block returned `None`, breaking those tests. The fix: catch `ImportError` separately and `pass` to fall through to regex fallback; only for non-ImportError exceptions do we log a warning and return None.

**How to apply:** Whenever you modify `_reduce_dn_to_group_name`, preserve the two-tier structure:
1. Try `import ldap.dn` → str2dn → extract cn value
2. `except ImportError: pass` (fall through, don't log)
3. `except Exception:` → log warning, return None
4. Regex fallback (`_CN_RDN_RE.search`) for ImportError case

Keep `_CN_RDN_RE` in the module — it is still used by the fallback path.
