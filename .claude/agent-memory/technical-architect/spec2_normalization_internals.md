---
name: spec2-normalization-internals
description: Non-obvious internal couplings in identity-normalization (was_mapped re-derivation, dept non-str miss contract, pyproject location)
metadata:
  type: project
---

Internal couplings in `services/identity-normalization/` that are NOT obvious from the spec and bit a remediation plan.

**Adapters discard `was_mapped`; the service re-derives it from the string.**
`OidcAdapter/SamlAdapter/LdapAdapter.extract()` all do `dept_value, _ = normalize_department(...)` — the bool is thrown away. `service.py::_was_department_mapped(normalized_value)` reconstructs it by lowercasing the *normalized string* and checking `DEPARTMENT_CANONICAL.get(key) == normalized_value`. So whatever STRING `normalize_department` returns is what drives the 0.2 penalty downstream, not the bool it returns.
**How to apply:** any change to `normalize_department`'s return must reason about the string, not just the bool. For a non-str input the helper must short-circuit to `(None, False)` (string=None), NOT a stringified/title-cased value — `service.py::_build_attribute_sources`/`_merge_ldap_attrs` guard `is not None`, so a None dept is cleanly dropped as a non-source (no penalty, no poison). Returning a non-None garbage string would make it a live source and apply the penalty to garbage. Return type widens to `tuple[str | None, bool]`. `normalize_employee_type` non-str → `None` (its existing miss return), no signature change.

**`shared/pyproject.toml` already exists** (naas-shared build config; no `[tool.pytest.ini_options]`). pytest config lives in the *root* `pyproject.toml` `[tool.pytest.ini_options]` (now sets `--import-mode=importlib` + `consider_namespace_packages` + timeout), never in `shared/` — putting an inifile in `shared/` could drag pytest rootdir into `shared/` and break the per-service `conftest.py` `pytest_runtest_setup` `app`-isolation and the `tests/conftest.py` `shared/`-path insertion. A `[tool.pytest.ini_options]` table at repo root pins rootdir to repo root, which is where it already resolves.

**Async tests use a manual `_run(coro)` helper** (`asyncio.get_event_loop().run_until_complete`), NOT `@pytest.mark.asyncio`. Zero markers, zero `async def` test fns, no `asyncio_mode` set anywhere. `pytest-asyncio` is installed but inert. Do NOT add `asyncio_mode` to a new pytest ini block — it could change collection silently. See [[spec2_identity_normalization]].
