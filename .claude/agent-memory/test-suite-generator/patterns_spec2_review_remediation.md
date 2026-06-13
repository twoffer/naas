---
name: patterns-spec2-review-remediation
description: Patterns from Spec 2 test-improvement batch: canonical conftest fakes, exact-equality guards, round-trip invariant tests, sys.path cleanup, E402/F401 remediation
metadata:
  type: project
---

# Spec 2 Review Remediation — Test Patterns

## Canonical Fake Factories in conftest.py

**Pattern:** When 6+ test files duplicate the same fake module helpers, consolidate into the per-service `conftest.py`. Provide named exports: `make_fake_ldap_module()`, `inject_fake_ldap(monkeypatch)`, `FakeRedis`. Individual test files import by alias and may override specific attributes for specialization.

**Key rule:** Keep LOCAL any fake that intentionally omits a feature to expose a bug (e.g., `_make_correct_hierarchy_fake_ldap` omits `TIMEOUT_EXCEEDED` to test the exception-name bug). The canonical factory must not be used for negative tests.

**Alias pattern for backward compat:**
```python
from tests.services.identity_normalization.conftest import inject_fake_ldap as _inject_fake_ldap
```

## sys.path Cleanup Strategy

**When to remove:** If a per-service conftest.py already inserts both SERVICE_DIR and SHARED_DIR at collection time, ALL per-file sys.path blocks in that service's test files are redundant.

**Watch for retained references:** After removing the sys.path block, check for `_REPO`, `SHARED_DIR`, `REPO_ROOT` variables that were defined in the same block and are still used elsewhere in the file. Add `from tests.helpers import REPO_ROOT as _REPO` to imports if needed.

**`naas_shared` in venv:** `shared/` is installed in dev mode via `-e shared/`. No test file ever needs `sys.path.insert` for `naas_shared` imports — they are available everywhere in the venv.

**demo tests:** `tests/demo/test_demo_flow.py` needed `SHARED_DIR` for naas_shared imports (removable) but still needs `REPO_ROOT` for `DEMO_SCRIPT` path. Move `DEMO_SCRIPT = REPO_ROOT / "demo" / "demo_normalization.py"` to module scope after the imports so it is not between import statements (avoids E402).

## pyproject.toml E402 per-file-ignore

**Before removing `"tests/**" = ["E402"]`:** Run `ruff check tests/ --select E402` first. Pre-existing violations in files NOT in your task scope (e.g., `test_health.py` had `from contextlib import contextmanager` after helper functions) will surface — fix them too.

**Fix pattern for `test_health.py`:** Merge the stray `contextmanager` import at line 71 into the top-level `from contextlib import asynccontextmanager` statement.

## Exact-Equality Guards for Spec-Pinned Dicts

**Pattern (security-relevant):** For spec-marked `[TRANSCRIBE EXACTLY]` dicts (DEPARTMENT_CANONICAL, EMPLOYEE_TYPE_CANONICAL), write an exact-equality test class with:
1. Expected dict as a class attribute (makes diff readable in failure output)
2. Assertion reports extra keys, missing keys, and changed values
3. Docstring explains WHY: a rogue added alias could flip unanimous→priority-conflict, or map a canonical to the wrong Literal value causing Pydantic failure

## Round-Trip Invariant Test

**Pattern:** `_was_department_mapped(value)` in service.py works by looking up `DEPARTMENT_CANONICAL.get(value.strip().lower()) == value`. This requires every canonical VALUE in DEPARTMENT_CANONICAL to also be present as a KEY (its own lowercase). Write a parametrized-style loop test:
```python
for alias_key, canonical_value in DEPARTMENT_CANONICAL.items():
    lookup_key = canonical_value.strip().lower()
    round_trip = DEPARTMENT_CANONICAL.get(lookup_key)
    assert round_trip == canonical_value, ...
```
Docstring must explain: violating this invariant silently applies -0.2 penalty to correctly-mapped departments.

## Poison-Message No-ACK Tests

**Pattern for consumer loop:** Use `AsyncMock(side_effect=[first_batch, CancelledError()])` for redis.xreadgroup to get exactly one processing pass then clean exit. Assert `redis.xack` is NOT called for bad-JSON and invalid-schema messages. For batch-continuation: include both a poison message and a good message in `first_batch`; assert the good one IS processed (service.normalize called with good record).

**FakeRedis xack:** The canonical `FakeRedis` class records calls via `self.xack_calls`. For tests using `AsyncMock` for redis (consumer tests), use `redis.xack.called` / `redis.xack.call_count`.

## TestLdapAttrMergeIntoResolution (Task 3)

**Pattern:** These tests use the real `config/normalization.yaml` (loaded via `load_config(_REPO / "config" / "normalization.yaml")`), not a mocked config. This pins actual production behavior. They call `svc.normalize(record)` end-to-end with LDAP enrich mocked to return specific `ldap_attrs` dict + outcome string.

**Key assertions:**
- `result.resolution_details["department"].sources` must contain `"ldap"`
- `result.resolution_details["department"].winner_source` must be `"ldap"` when config priority is `[ldap, oidc, saml]`
- `result.groups` is a list (union semantics)
- `result.normalization_confidence < 0.9` when LDAP department value is unmapped (penalty applied)

## F401 Cleanup Pitfalls

- `FakeRedis` imported from conftest but only mentioned in a docstring comment → unused, remove
- Local `from naas_shared.models import PriorityResolution, ...` inside a test method that doesn't use them → remove
- `sys` import left over from removed sys.path block → remove if no other `sys.` usage in file
- Check `from unittest.mock import AsyncMock` in conftest — only needed if conftest code itself uses it (FakeRedis uses plain async def methods, not AsyncMock)
