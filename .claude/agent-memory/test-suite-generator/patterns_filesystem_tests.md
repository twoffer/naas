---
name: patterns-filesystem-tests
description: Conventions for scaffold/filesystem assertion tests in NAAS spec tests
metadata:
  type: project
---

## Scaffold test patterns (established in spec_0/test_chunk_1_root_scaffold.py)

### Skip vs. Fail for missing files

When a test reads *content* of a file that may not exist yet (TDD mode), use
`pytest.skip()` on the module-scoped fixture rather than failing, so that
existence tests report FAILED and content tests report SKIPPED (not a
second FAILED for the same missing file). This keeps the signal clean.

```python
@pytest.fixture(scope="module")
def env_example_text(env_example_path) -> str:
    if not env_example_path.exists():
        pytest.skip(".env.example does not exist yet — expected TDD failure")
    return env_example_path.read_text(encoding="utf-8")
```

### Parametrize over service names

Use `@pytest.mark.parametrize("service_name", EXPECTED_SERVICES)` for the
eight services so partial implementation flips individual tests green.

### Directory-contents assertion

Use `set(entry.name for entry in dir.iterdir())` to assert exact directory
contents without recursion. This catches unexpected extra files without needing
`os.walk`.

### ⚠ Evolving scope-guard maintenance — IMPLEMENTED_APP_SERVICES

The `test_service_directory_contains_only_readme` guard is a **point-in-time
tripwire**: it asserts a service dir holds *only* `README.md`. This is correct
during the spec that scaffolds it, but the moment that service's spec lands and
fills the dir with code, the guard breaks (it fires as a false positive).

Resolution chosen for this repo (do NOT re-tighten it): the file keeps a
maintained set and parametrizes the guard over the complement —

```python
IMPLEMENTED_APP_SERVICES = {"event-ingestion"}  # Spec 1 — append per landed spec
SCAFFOLD_ONLY_SERVICES = [s for s in EXPECTED_SERVICES if s not in IMPLEMENTED_APP_SERVICES]
@pytest.mark.parametrize("service_name", SCAFFOLD_ONLY_SERVICES)
```

**When generating/refreshing tests after a new spec lands, you MUST add that
spec's service name to `IMPLEMENTED_APP_SERVICES`** in `test_chunk_1_root_scaffold.py`
(and the mirror set in `test_chunk_5_docker_compose.py`). The README
existence/content tests still parametrize over ALL eight `EXPECTED_SERVICES` —
only the "only README" guard uses `SCAFFOLD_ONLY_SERVICES`.

**General rule:** never write a forward-looking "directory contains ONLY X" /
"exactly N entries" guard without an escape hatch (a maintained allow-set), or
it becomes a recurring false-failure every time the project legitimately grows.

### .gitignore line matching

Strip trailing whitespace per line with `line.rstrip()` — do NOT strip leading
whitespace, since `.gitignore` patterns are position-sensitive.

### NAAS eight services (canonical order)

```python
EXPECTED_SERVICES = [
    "api-gateway",
    "event-ingestion",
    "identity-normalization",
    "signal-enrichment",
    "risk-evaluator",
    "policy-management",
    "alert-service",
    "persona-simulator",
]
```

Ports: 8000–8007 in that order.

### .env.example/.env identity assertion

Compare bytes (`read_bytes()`) not text to catch encoding/line-ending differences.

### No conftest.py for scaffold tests

Scaffold tests have no app code to import. Do not create a conftest.py that
imports application code — keep tests self-contained. Module-scope fixtures
inside the test file suffice.

**Why:** No app code exists during TDD phase; importing would cause ImportError.
**How to apply:** For each scaffold chunk test file, inline fixtures instead of
using conftest.py.

### sqlparse availability pattern (established in spec_0/test_chunk_3_postgres_redis.py)

`sqlparse` is NOT installed in the dev venv. For a test that needs it:

```python
def test_init_sql_parses_without_error(self, init_sql_text: str):
    sqlparse = pytest.importorskip(
        "sqlparse",
        reason="sqlparse not installed — SQL parse test skipped",
    )
```

Use `pytest.importorskip` (skip, not error) for the parse-specific test.
All structural/content checks use plain `str`/`re` assertions — no sqlparse needed.

### Module-scope skip guard for content tests on absent files

When all content tests for a file share a module-scoped fixture that reads that
file, a single `pytest.skip()` in the fixture body skips all dependent tests
cleanly and leaves only the existence tests as FAILED. This gives a clean signal:
- Existence tests: FAILED (file missing)
- Content tests: SKIPPED (file missing, not double-failed)
- On implementation: existence tests flip GREEN → skip guard dissolves → content
  tests become live

```python
@pytest.fixture(scope="module")
def init_sql_text() -> str:
    if not INIT_SQL_PATH.exists():
        pytest.skip("file does not exist yet — expected TDD failure")
    return INIT_SQL_PATH.read_text(encoding="utf-8")
```

This is the established pattern for Chunk 3 and should be used for all future
static-artifact tests (SQL files, config files, YAML files, JSON files).

### SQL CHECK constraint regex pattern

For asserting a full inline CHECK constraint exists on a column:

```python
pattern = re.compile(
    r"protocol\s+\w+.*?CHECK\s*\(\s*protocol\s+IN\s*\("
    r"['\"]oidc['\"],\s*['\"]saml['\"],\s*['\"]ldap['\"]\s*\)\s*\)",
    re.IGNORECASE | re.DOTALL,
)
```

Use `re.DOTALL` when the constraint spans multiple lines (common in formatted SQL).

### SQL string doubling guard (critical for embedded YAML in INSERT)

Single quotes inside PostgreSQL string literals must be doubled ('').
Guard with:
1. Positive assertion: `assert "''contractor''" in init_sql_text`
2. Negative assertion using negative lookbehind/lookahead:
   `re.search(r"(?<!')'contractor'(?!')", text)` — must be None

The negative check catches the exact transcription error where doubled was
forgotten and single was used instead.

### LDIF structural parsing (established in spec_0/test_chunk_4_keycloak_ldap.py)

`python-ldap` / `ldif` package is NOT installed in dev venv. Parse LDIF with
plain string/line operations. Key patterns:

1. **No-base-DN guard** (the #1 osixia/openldap pitfall):
   ```python
   pattern = re.compile(r"^\s*dn\s*:\s*dc=corp,dc=com\s*$", re.IGNORECASE)
   matching = [ln for ln in lines if pattern.match(ln)]
   assert matching == []
   ```

2. **OU-before-user ordering** by comparing first-match line indices:
   ```python
   ou_line = next((i for i, ln in enumerate(lines) if ln.strip() == ou_dn), None)
   first_user = next((i for i, ln in enumerate(lines) if user_pattern.match(ln)), None)
   assert ou_line < first_user
   ```

3. **Block parser** (`_parse_ldif_blocks`): iterate lines, partition on `:`,
   accumulate into `{dn: {attr_lower: [value, ...]}}`. Blank lines flush the
   current block. Flush final block after loop (file may not end with blank line).
   Store attr names lowercased for case-insensitive lookup.

4. **`pytest.importorskip("ldif")`** for an optional deep-parse test — keep it
   separate from all structural checks so structural tests are always unconditional.

5. **Fixture-level assert for missing file**: in TDD mode, use
   `assert FILE.exists(), f"File missing: {FILE}"` inside each fixture rather
   than a module-scope skip — the chunk 4 pattern reports FAILED (not SKIPPED)
   for all tests when the file is absent, giving the implementer a full picture.
   (Contrast with chunk 3 pattern using module-scope pytest.skip for cleaner
   signal — both approaches are valid; choose based on test signal preference.)

### JSON realm file: locate client by clientId, not array index

```python
def _find_client(realm, client_id):
    for client in realm.get("clients", []):
        if client.get("clientId") == client_id:
            return client
    raise KeyError(f"No client with clientId={client_id!r}")
```

Use a class-scoped `@pytest.fixture` that calls `_find_client()` so all client
property tests share one lookup without re-parsing the file.
