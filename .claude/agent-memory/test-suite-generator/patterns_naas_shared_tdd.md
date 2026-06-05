---
name: patterns_naas_shared_tdd
description: TDD patterns and import strategy for naas_shared library tests (Spec 0, Chunk 2)
metadata:
  type: project
---

## Import strategy for naas_shared tests

Use `sys.path.insert(0, str(REPO_ROOT / "shared"))` at module level. This allows tests
to resolve `naas_shared` imports once `shared/naas_shared/` source exists, without
requiring `pip install -e shared/` to be run first. Mirrors the §6.6 shell smoke test
(`cd shared && python3 -c "..."`).

**Why:** The test venv (requirements-dev.txt) contains only pytest tools — pydantic,
structlog, sqlalchemy, etc. are NOT pre-installed. Tests fail with two layered errors
in TDD state: first `ModuleNotFoundError: No module named 'naas_shared'` (no source),
then `ModuleNotFoundError: No module named 'pydantic'` (no runtime deps). Both resolve
when the implementer runs `pip install -e shared/`.

## lru_cache fixture pattern for Settings

`get_settings()` is `lru_cache`'d. Tests that change env vars or test defaults must
clear the cache:

```python
@pytest.fixture(autouse=True)
def clear_settings_cache(self):
    from naas_shared.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

## Placeholder module test pattern

For placeholder modules (ml_features.py, simulation_tools.py — and schemas.py
*until Spec 1*):
- Assert `importlib.import_module(name)` succeeds
- Assert no fabricated content that belongs to a later spec
- For ml_features.py / simulation_tools.py: only assert clean import + absence of
  specific named attributes (FEATURE_COLUMNS, TOOL_DEFINITIONS) with real content

### ⚠ schemas.py is now POPULATED by Spec 1 — do not regenerate placeholder guards

`schemas.py` is no longer a placeholder: Spec 1 added `Base` and `EventORM`. The
spec_0 class is now `TestSchemasModule` and keeps ONLY the clean-import smoke-test.
Its ORM surface is covered positively by `tests/shared/test_chunk1_orm_mapping.py`.

The two retired assertions were **brittle one-way tripwires** that broke
permanently the instant the module was filled:
- exact-text check for `"# ORM table definitions — populated by Spec 1 when first needed"`
- `dir(module)` returns no public names

**Do NOT re-add these for schemas.py, and do not write this style of
"exact placeholder comment" / "no public names" guard for any module that a
later spec is expected to populate** — unlike the docker-compose / scaffold
guards there is no allow-set to evolve here; once populated, the placeholder
assertion is simply obsolete and must be deleted (keep the import smoke-test).

## Test file location
`tests/spec_0/test_chunk_2_shared_library.py` — 102 tests total

## Key discriminated union testing pattern

To exercise Pydantic discriminated unions, use `Model.model_validate(dict)` not
`Model(**kwargs)` — passing a nested dict forces the discriminator path:

```python
data = {"source_protocol": "oidc", "enrichment": {"applied": True, "source": "ldap", "cache_hit": False}}
attrs = NormalizedAttributes.model_validate(data)
assert isinstance(attrs.enrichment, EnrichmentApplied)
```

## Reference values used
- UUID: "12345678-1234-5678-1234-567812345678"
- IPs: "192.168.1.1" (valid dotted-quad), "8.8.8.8"
- Timestamp: datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
