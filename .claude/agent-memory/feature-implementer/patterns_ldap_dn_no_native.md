---
name: patterns_ldap_dn_no_native
description: python-ldap requires gcc/libldap build deps not available in venv; use regex for DN parsing instead
metadata:
  type: project
---

python-ldap (required by identity-normalization service) cannot be pip-installed in the dev venv — it requires gcc and libldap C headers (`x86_64-linux-gnu-gcc` not on PATH in WSL dev env). It IS in the service's requirements.txt and will build inside the Docker container.

For unit tests that need DN parsing (`cn=engineering,ou=groups,dc=corp,dc=com` → `engineering`), implement a regex-based parser: `re.compile(r"(?:^|,)\s*cn=([^,]+)", re.IGNORECASE)`. The pattern handles:
- Full DNs: extracts first cn= RDN value verbatim
- Bare names (no `=`): return as-is
- Malformed DNs (has `=` but no `cn=`): return None and log warning

**Why:** python-ldap build fails at venv install time; native ldap.dn.str2dn is unavailable for tests. Regex approach produces equivalent results for the DN formats used in production (RFC 2253 style).

**How to apply:** Any chunk requiring LDAP DN parsing in tests should use the regex approach, not `import ldap.dn`.
