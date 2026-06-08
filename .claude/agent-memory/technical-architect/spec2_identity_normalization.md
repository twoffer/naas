---
name: spec2-identity-normalization
description: Spec 2 Identity Normalization Service decomposition gotchas — bootstrap.ldif fixture gaps, lockstep shared+SPEC_0 chunk, python-ldap build deps, hexagonal seams
metadata:
  type: project
---

Spec 2 (`identity-normalization`, port 8002) decomposition notes. The service is BOTH a FastAPI app (/health only) AND a background `login_events` consumer; hexagonal (ADR-0009).

**Why:** These are non-obvious traps that would otherwise produce broken chunks or unreproducible acceptance tests.

**How to apply:** Reuse when planning this service or any later spec that touches LDAP enrichment, the shared `NormalizedAttributes` model, or extends a shared module.

- **bootstrap.ldif fixture gaps (verified, current):** seeded users (alice/bob/charlie/diana/eve under `ou=users,dc=corp,dc=com`) have NO `memberOf` attribute and there are no member-populated group entries. So LIVE LDAP enrichment returns no groups — the §3.3 example payload (groups ["admin","engineering","vpn-users"]) is illustrative, NOT reproducible from the directory. Test `memberOf`→cn DN-reduction at the UNIT level with synthetic DNs; never assert non-empty enriched groups from live LDAP.
- **LDAP department canonicalization mismatch:** seeded `departmentNumber` values are full words partly OUTSIDE `DEPARTMENT_CANONICAL` — alice/diana=Engineering (maps), bob=Product, charlie=Security, eve=External (all retained+title-cased, unmapped). For the §6.3 conflict test pick a user whose LDAP dept IS canonical (alice=Engineering) and put a conflicting canonical value in the OIDC token; test "unmapped value wins → 0.2 penalty" as a SEPARATE case.
- **Lockstep chunk (CRITICAL, spec §1):** the two shared additions — `LDAP_ENRICHMENT_CACHE_PREFIX = "ldap_enrichment:"` (constants.py) and `ldap_pool_size: int = Field(default=3, ge=1, le=10)` (config.py) — MUST land in the SAME chunk as their SPEC_0 mirrors (§3.3 after CACHE_FEATURE_FLAGS_TTL; §3.8 after ldap_admin_password). I put both in the LDAP-enrichment chunk (where they are consumed), NOT the scaffold. Do not split module change from its SPEC_0 mirror.
- **.env already ready:** `LDAP_POOL_SIZE=3` and `IDENTITY_NORMALIZATION_PORT=8002` already exist in .env.example; `ldap_pool_size` is currently dropped by `extra="ignore"` until the field is added.
- **python-ldap build deps:** the Spec 1 slim image does NOT carry them. Dockerfile must `apt-get install -y gcc libldap2-dev libsasl2-dev` (add build-essential if still failing) BEFORE pip install, or the wheel build fails.
- **No LDAP_URI/BIND_DN/BIND_PASSWORD in this project:** construct `ldap://{ldap_host}:{ldap_port}`, bind with `ldap_admin_dn`/`ldap_admin_password`, search from `ldap_base_dn` SCOPE_SUBTREE.
- **timeout_ms vs search_s:** spec EXEMPLARY snippet shows `search_s` but §5.4 requires honoring `timeout_ms` → use `search_st(...)` or set OPT_NETWORK_TIMEOUT/OPT_TIMEOUT; §5.4 (timeout) is authoritative over the exemplary call name.
- **python-ldap is synchronous:** wrap every blocking call in `asyncio.to_thread(...)`.
- **Three-state negative cache:** key `ldap_enrichment:<correlation_value>`; MISS (None)→query; NEGATIVE HIT (JSON "null" sentinel)→no-match without query; POSITIVE HIT (JSON dict)→use. Cache positive AND negative with same TTL (from yaml, default 60). Transient failures (timeout/conn/search error) NOT negative-cached.
- **Resolution/orchestration boundary I fixed:** `resolution.py` builds the full `NormalizedAttributes` but takes the enrichment metadata variant + primary protocol as PARAMETERS (so it stays pure, no I/O); `service.py` constructs the EnrichmentApplied/EnrichmentSkipped variant and the {source:value} maps, then calls resolve(). Keeps chunk 5 and chunk 6 from both owning model construction.
- **shared `__init__.py` is a bare package marker** — no re-exports to maintain, so shared changes only touch config.py + constants.py (no `__init__.py` edit).
- **6-chunk decomposition used:** (1) scaffold+health+ports, (2) value-norm+OIDC/SAML/LDAP extract, (3) config model+loader+validation+yaml, (4) LDAP enrich+cache+shared additions+SPEC_0 mirrors, (5) resolution+confidence, (6) service+repository+consumer+main wiring (integration-facing). Chunks 4 and 5 both depend on [2,3] and are independent of each other.
