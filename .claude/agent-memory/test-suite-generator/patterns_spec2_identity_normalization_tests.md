---
name: patterns-spec2-identity-normalization-tests
description: Durable, reusable test patterns for the identity-normalization service (Spec 2) — fake-ldap injection, three-state cache contract, sanitization assertions, resolve() shape, outcome→skip_reason mapping. Consolidated from the per-chunk TDD notes after Spec 2 merged.
metadata:
  type: project
---

Reusable patterns for writing or extending tests against `services/identity-normalization`.
Spec: `docs/architecture/SPEC_2_Identity_Normalization_Service.md`. The transient
TDD bookkeeping (exact test counts, "all failing until implementation",
pre-implementation pass lists) has been dropped — Spec 2 is fully implemented and
those numbers are stale. What remains below is verified against the merged code.

## fake-`ldap` injection (enrich/adapter tests)

python-ldap is a C extension NOT installed in the dev venv; the adapter lazy-imports
`ldap` inside functions, so `app.adapters.ldap` is importable without it. To unit-test
`enrich()`, inject a fake module BEFORE importing the adapter:

```python
fake_ldap = MagicMock(name="ldap")
fake_ldap.SCOPE_SUBTREE = 2
# Exception classes MUST be real classes (not MagicMock) so `except` clauses match:
class LDAPError(Exception): pass
class SERVER_DOWN(LDAPError): pass
class TIMEOUT_EXCEEDED(LDAPError): pass
fake_ldap.LDAPError, fake_ldap.SERVER_DOWN, fake_ldap.TIMEOUT_EXCEEDED = (
    LDAPError, SERVER_DOWN, TIMEOUT_EXCEEDED)
fake_ldap.filter = MagicMock()
fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
# Clear cached adapter modules so the fake is picked up on import:
for key in ("app.adapters.ldap", "app.adapters"):
    monkeypatch.delitem(sys.modules, key, raising=False)
```

LDAP search results are bytes-valued: `[(dn_str, {"cn": [b"Alice"], "mail": [b"a@corp.com"], ...})]`.
The adapter decodes bytes→str (`_normalise_ldap_attrs`/`_decode_first`/`_decode_list`).

Redis seam: patch `naas_shared.redis_client.get_redis` with
`MagicMock(return_value=fake_redis)` (returns the fake directly, not a coroutine —
the adapter handles both via `inspect.isawaitable`). Use a `_FakeRedis` with real
`async def get/set/setex` recording calls, so you can assert key/value/TTL.

## Three-state Redis cache contract (§5.3)

| Redis GET    | State        | Action                              |
|--------------|--------------|-------------------------------------|
| `None`       | MISS         | query LDAP via pool                 |
| `'"null"'`   | NEGATIVE HIT | return None, NO query               |
| `'{...}'`    | POSITIVE HIT | decode JSON, return dict, NO query  |

Sentinel = JSON string `"null"`. Positive AND negative both written with the same
config TTL. Transient errors (timeout / SERVER_DOWN / search error / unexpected)
write NOTHING to Redis, so a retry succeeds once LDAP recovers.

## Injection-sanitization assertion technique (§5.3)

Don't assert RFC 4515 escaping bytes (that's the real library's job) — assert the
CONTRACT: `escape_filter_chars` is called with the raw `lookup_value` and its output
is what lands in the filter.
- Marking escape: `side_effect=lambda v: "SAFE_" + v`, then assert `"SAFE_..."` is in
  the filter string.
- Neutralizing escape: strip the metacharacter in the fake, then assert the char is
  absent from the filter string.
Note the two-tier filter builder: `build_search_filter()` is parenthesised (RFC, for
external callers); `_build_search_filter_internal()` is unparenthesised (used by
`enrich()` so structural `(`/`)` don't mask metachar assertions).

## resolve() shape (resolution.py — pure core)

```python
def resolve(attribute_sources, config, source_protocol, enrichment) -> NormalizedAttributes
```
`attribute_sources` = `{attr: {source_protocol: value}}`, only non-null values present:
- scalars (display_name / primary_email / employee_type): plain `str`
- department: `(normalized_str, was_mapped: bool)` tuple — was_mapped drives the penalty
- groups: `list[str]` per source

Resolution variants & confidence: 0 src → None/omit/0.0; 1 → single_source @ weight_for;
≥2 agree → unanimous @ max agreeing weight; ≥2 disagree → priority @ winner_weight×0.8.
0.2 unmapped penalty applies ONLY to department when the WINNING value is unmapped
(never employee_type — unmapped discarded to None upstream). Groups: single → weight_for;
multi → `0.7 + 0.3×(fraction merged groups present in >1 source)` ∈ [0.7,1.0]. Overall =
`sum(ATTRIBUTE_IMPORTANCE[a] × per_attr_conf)` clamped [0,1].

§3.3 payload values (0.87, groups 0.85) are ILLUSTRATIVE; the §5.5 FORMULA is binding
(same inputs → ~0.889 / groups 0.90). Assert the formula, not the illustrative payload.

## outcome → skip_reason mapping (service.py, §5.4)

`enrich()` returns `(attrs, outcome)`. Match outcomes → `EnrichmentApplied`:
`ldap_match`→cache_hit=False, `cache_hit_positive`→cache_hit=True. Non-match → `EnrichmentSkipped`:
`ldap_no_match`/`cache_hit_negative`→`no_ldap_match`; `ldap_timeout`→`ldap_timeout`;
`ldap_connection_error`→`ldap_connection_error`;
`ldap_search_error`/`ldap_unexpected_error`/`unmappable_field`→`ldap_search_error` (folded;
no dedicated Literal). Context-based (no enrich call): disabled→`ldap_disabled`,
protocol=="ldap"→`ldap_event`, empty correlation value→`invalid_correlation_key`.

Critical invariants to test: `is_synthetic` NEVER affects the enrichment decision
(assert via enrich call_count); consumer ordering parse→normalize→write+commit→publish→XACK
with XACK LAST; enrichment skip ≠ processing failure (skipped events still persist+publish+XACK);
repository `write()` is UPDATE-only (no `session.add()`, no `create_all`, one `execute()`);
publisher sends the FULL record (ADR-0011) via shared `publish_to_stream`.

## tempfile flush in this service's conftest (still required)

`tests/services/identity-normalization/conftest.py` autouse-patches
`tempfile.NamedTemporaryFile` to flush-on-write, because some helpers call
`load_config(Path(f.name))` while still inside the `with` block (unflushed buffer →
empty read). See [[patterns-tempfile-flush-conftest]] and [[resolution-confidence-invariants]].

## Spec quick-reference (transcribed from §5.2 / §5.6 / §5.5.2)

Mapping (unified ← oidc | saml | ldap):
display_name←name|displayName|cn; primary_email←email|email|mail;
department←department|dept|departmentNumber; employee_type←employee_type|employeeType|employeeType;
groups←groups|groups|memberOf (DN-reduce to cn RDN).

§5.6 weights (ldap/saml/oidc): display_name .90/.70/.60; primary_email .65/.75/.95;
department .90/.50/.70; employee_type .95/.80/.60; groups fallback .70/.60/.80.
Defaults ldap .7 / saml .6 / oidc .8. Priority lists: display_name [ldap,saml,oidc];
primary_email [oidc,saml,ldap]; department [ldap,oidc,saml]; employee_type [ldap,saml,oidc];
groups none (→[]).

`ATTRIBUTE_IMPORTANCE` (sum = 1.0): display_name .15, primary_email .25, department .20,
employee_type .25, groups .15.

memberOf bootstrap caveat: `infrastructure/openldap/bootstrap.ldif` seeds NO memberOf on
any user, so live LDAP enrichment yields groups=[]; test DN-reduction with synthetic DNs,
never assert non-empty enriched groups from the live directory.
