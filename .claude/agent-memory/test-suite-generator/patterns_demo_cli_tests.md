---
name: patterns-demo-cli-tests
description: Patterns for testing the demo/ CLI scaffold — absent-directory guards, subprocess --help verification, module-level SCENES constant, soft-import AST walk, banned-token grep
metadata:
  type: feedback
---

## Key patterns for demo/demo_normalization.py tests

### Absent-directory guard: use pytest.fail(), not pytest.skip()
For TDD tests where the entire demo/ directory is missing, all tests should FAIL
(not skip). Fixtures that read demo files must call `pytest.fail(...)` rather than
`pytest.skip(...)` so the test run counts as failed, not as inconclusive.

For parametrized "banned token absent" tests, the test body must assert the directory
exists before iterating files — otherwise the loop silently skips nothing and the test
passes vacuously.

**Why:** pytest.skip() produces false-green in a TDD run where absence of the
implementation IS the failure condition.

### Module import via importlib.util
Use `importlib.util.spec_from_file_location` / `module_from_spec` / `exec_module` to
import demo_normalization.py by absolute path. This avoids sys.path pollution and works
correctly from any cwd.

### SCENES constant — canonical symbol name
The module-level event list is named `SCENES` (a list of six dicts). Tests assert
`hasattr(module, "SCENES")` before any structural checks. Each dict must have keys:
`user_id`, `protocol`, `client_ip`, `source`, `is_synthetic`, `raw_attributes`
(and optionally `caption`).

### Soft naas_shared import — AST walk approach
Build a parent_map by walking the AST and calling `ast.iter_child_nodes`. Then walk
again for `ImportFrom` nodes whose module starts with "naas_shared". For each, call
`_is_inside_try_except(node)` which traverses parent_map upward looking for a `Try`
node. Also assert the except branch has at least one non-`Pass` statement.

### CLI --help subprocess test
Use `subprocess.run([sys.executable, str(DEMO_SCRIPT), "--help"], ...)` with
`cwd=str(REPO_ROOT)`. Check `result.returncode == 0` and search
`result.stdout + result.stderr` for each flag string. One test checks all 7 flags at
once; 7 parametrized tests check each individually.

### requirements.txt version-pin regex
`re.search(r"^rich[>=<!\[]", text, re.MULTILINE)` — matches `rich==`, `rich>=`,
`rich[...]`, etc. Same pattern for httpx and `psycopg\[binary\]`.

### README honesty note check
Two separate regex checks: `re.search(r"[Pp]ostgres", text)` and
`re.search(r"direct(ly)?|reads?\s+[Pp]ostgres|...", text, re.IGNORECASE)`. Both
must be True.

### ERRORs vs FAILs in TDD run
Tests that depend on a module-scope fixture that calls `pytest.fail()` show as ERROR
(not FAILED). This is correct TDD behavior — both FAILED and ERROR count as
"not passing". The 88-test suite produces 19 FAILED + 69 ERRORS = 0 PASSED before
implementation exists.
