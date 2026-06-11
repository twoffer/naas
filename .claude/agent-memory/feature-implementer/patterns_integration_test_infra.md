---
name: patterns-integration-test-infra
description: Patterns for integration test infrastructure: compose override, ruff on non-Python files, pytest.fail unbound vars
metadata:
  type: feedback
---

## ruff check/format scope

Run `ruff check tests/integration/` (not `ruff check tests/integration/ scripts/ requirements-dev.txt .gitignore`). ruff treats `.sh`, `.txt`, `.gitignore` as Python and emits cascading SyntaxErrors. Pass only `.py` paths or directories containing only Python files.

**Why:** Discovered during integration test infra task — accidental inclusion of shell scripts and config files caused 50+ false ruff errors.

**How to apply:** When running ruff on a mixed-extension directory, use the directory path only if it contains only Python files; otherwise list individual `.py` files.

## pytest.fail() possibly-unbound variable fix

When `pytest.fail(str(exc))` appears inside `except SomeError:` and a variable assigned in the `try:` block is used after, type checkers flag the variable as possibly-unbound. Fix: add `return  # unreachable — pytest.fail() raises; satisfies type checkers` after `pytest.fail()`. This preserves semantics (pytest.fail always raises Failed).

**How to apply:** Any except block where pytest.fail() is the only statement and the surrounding code uses variables from the try block.

## docker-compose.test.yml for in-container unit tests

Pattern for test-runner service overlay:
- `profiles: ["test"]` prevents accidental start
- Reuse identity-normalization image/build to get python-ldap (the only image with gcc + libldap2-dev)
- `image: naas-identity-normalization:local` must be EXPLICITLY declared on BOTH the identity-normalization service in docker-compose.yml AND the test-runner (without the explicit tag in the base file, compose auto-names the build `naas-identity-normalization:latest` and the override silently builds a divergent second image — was a MAJOR review finding)
- `command` must be the JSON exec-array form `["sh", "-c", "pip install ... && python -m pytest ... <flags>"]`. A YAML `>` folded scalar with deeper-indented continuation lines KEEPS the newlines: `sh -c` runs only line 1 and the flags are executed as separate commands (exit 127). Caught on first live run.
- `rich==13.9.4` must be in requirements-dev.txt: tests/demo/test_demo_flow.py imports demo_normalization.py which lazily imports rich; the container installs only requirements-dev.txt (host gets rich via demo/requirements.txt in run_integration_tests.sh)
- Mount repo read-only with `docs/architecture/` present (satisfies _find_repo_root())
- `PYTHONDONTWRITEBYTECODE: "1"` prevents writes to read-only mount
- `-p no:cacheprovider --rootdir /workspace -o cache_dir=/tmp/.pytest_cache` handles pytest cache on read-only mount

**Why:** identity-normalization is the only service with C build deps (python-ldap). The in-container suite needs them for full LDAP adapter test coverage.

## Integration marker — single source of truth

The `integration` marker is declared ONLY in `pyproject.toml` `[tool.pytest.ini_options].markers`. An earlier dual registration (also via `addinivalue_line` in `tests/conftest.py` `pytest_configure`) was removed by security review to avoid drift — do not reintroduce it. `pytest_addoption` for `--integration` DOES stay in `tests/conftest.py` (initial-conftest requirement).
