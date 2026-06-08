---
name: patterns-adapter-refactor-tests
description: Patterns for testing the identity-normalization adapter refactor — _mapping.py engine, normalize_department_value wrapper, and bare-string groups behavior change
metadata:
  type: feedback
---

## Adapter Refactor Test Patterns (Spec 2 post-refactor)

### coerce_str_list bare-string security invariant

The single most important test is `coerce_str_list('admin') == []`. A naive
`[v for v in value if isinstance(v, str)]` applied to a non-list iterates the string
character-by-character — each char IS a str, so you get `['a','d','m','i','n']`.
The spec requires `isinstance(value, list)` check first. Always write two assertions:
1. `result == []` (primary)
2. `result != list("admin")` (explicit belt-and-suspenders)

### Intentional behavior change test pattern for bare-string groups

The adapter refactor changes ONE behavior: `extract({'groups': 'admin'})` now returns
`groups=[]` instead of iterating the string. Pattern for testing this:

```python
class TestOidcAdapterBareStringGroups:
    def test_bare_string_groups_yields_empty_list(self):
        result = OidcAdapter().extract({"groups": "admin"})
        groups = result.get("groups", "ABSENT_SENTINEL")
        assert groups == []
        assert groups != list("admin")  # belt-and-suspenders

    def test_list_groups_still_passes_through(self):  # regression guard
        result = OidcAdapter().extract({"groups": ["admin", "vpn"]})
        assert result.get("groups") == ["admin", "vpn"]
```

The regression guard (`test_list_groups_still_passes_through`) passes before the
refactor because the list path already works. Only the bare-string tests fail.
This is correct — the regression guard being green pre-refactor confirms the normal
path is not broken.

### normalize_department_value — tuple return is the critical bug to test

`normalize_department(value)` returns `(str, bool)`. The wrapper `normalize_department_value`
must return only the string. The critical test is `test_return_value_is_never_a_tuple`:

```python
def test_return_value_is_never_a_tuple(self):
    result = normalize_department_value("eng")
    assert not isinstance(result, tuple)
```

If the implementer writes `return normalize_department(value)` instead of
`return normalize_department(value)[0]`, this test catches it.

### FieldRule multi-key test pattern

```python
rules = {"combined": FieldRule(("a", "b"), lambda x, y: f"{x}-{y}")}
raw = {"a": "1", "b": "2"}
result = apply_field_rules(raw, rules)
assert result == {"combined": "1-2"}
```

Absent second key passes None:
```python
raw = {"a": "1"}  # 'b' absent
result = apply_field_rules(raw, rules)
assert result == {"combined": "1-None"}
```

### Appending tests to existing test files vs creating new ones

- New surface area (`_mapping.py`): new file `test_mapping_engine.py`
- New wrapper in existing module (`normalize_department_value`): append CLASS 8 to
  `test_normalization_values.py` (keeps normalization_values tests together)
- Behavior change in existing adapters: append CLASS 7 to each adapter test file
  (`test_adapters_oidc.py`, `test_adapters_saml.py`,
  `test_adapters_ldap.py`) so the behavior change is co-located with the
  existing adapter test suite

### Running from the service directory

Always run pytest from `services/identity-normalization/` with:
```bash
python -m pytest ../../tests/services/identity_normalization/test_*.py -v
```

The pyproject.toml configures the test root correctly when CWD is the service dir.
