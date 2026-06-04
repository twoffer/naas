---
name: patterns-docker-compose-tests
description: Patterns for writing static docker-compose.yml TDD tests in NAAS spec_0 — PyYAML importorskip, docker compose config subprocess skip guard, bind-mount helper supporting short and long syntax
metadata:
  type: project
---

## PyYAML Availability

PyYAML is NOT installed by default in the NAAS .venv. It was added as a transitive dep
during chunk 5 test authoring (`pip install pyyaml`, now at 6.0.3). Always guard
YAML-parse tests with `pytest.importorskip("yaml")` for portability.

## docker compose config subprocess test pattern

```python
if shutil.which("docker") is None:
    pytest.skip("docker CLI not available — skipping compose config validation")
result = subprocess.run(
    ["docker", "compose", "config", "-q"],
    cwd=str(REPO_ROOT),
    capture_output=True,
    text=True,
)
assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
```

Skip when docker binary absent; FAIL (not skip) when file is absent — this is correct
TDD behavior because the test is gating the compose file's existence.

## _extract_bind_mounts helper

Handle BOTH short syntax (`"./src:/dest"` or `"./src:/dest:ro"`) and long dict syntax
(`{type: bind, source: ..., target: ...}`). Filter out named-volume shorthand by
checking for leading `./` or `/`.

```python
def _extract_bind_mounts(svc):
    mounts = []
    for entry in svc.get("volumes", []):
        if isinstance(entry, str):
            if entry.startswith("./") or entry.startswith("/"):
                parts = entry.split(":")
                if len(parts) >= 2:
                    mounts.append((parts[0], parts[1]))
        elif isinstance(entry, dict) and entry.get("type") == "bind":
            mounts.append((entry.get("source",""), entry.get("target","")))
    return mounts
```

## _get_env_keys helper

Handles both list form `["KEY=value"]` and dict form `{KEY: value}`.
Key insight: list items may or may not have `=` (bare keys are valid in Compose).

## Module-scoped fixture for parsed compose

Using `scope="module"` on the `compose` fixture means `_load_compose()` runs once
per module. If the file is absent, `pytest.fail()` inside the fixture causes all
fixture-dependent tests to show as ERROR (not FAIL). This is correct — they are
blocked by the missing file, not themselves buggy.

## Exact service-set assertion (evolving — IMPLEMENTED_APP_SERVICES)

⚠ The exact-set assertion is a **point-in-time tripwire**. Asserting
`actual == REQUIRED_SERVICES` (infra only) is correct at Spec 0, but every spec
that adds its service to `docker-compose.yml` then breaks it as a false positive.

Resolution chosen for this repo (do NOT re-tighten to infra-only): keep a
maintained set of landed app services and fold it into both the exact-set check
and the forbidden-list derivation.

```python
REQUIRED_SERVICES = {"postgres", "redis", "keycloak", "openldap"}
IMPLEMENTED_APP_SERVICES = {"event-ingestion"}      # Spec 1 — append per landed spec
ALL_APP_SERVICES = {"api-gateway", "event-ingestion", ..., "dashboard"}
FORBIDDEN_SERVICES = ALL_APP_SERVICES - IMPLEMENTED_APP_SERVICES

# exact-set test:
expected = REQUIRED_SERVICES | IMPLEMENTED_APP_SERVICES
assert actual == expected, f"Missing: {expected - actual}\nExtra: {actual - expected}"
```

This still enforces "all infra present" AND "no *un-implemented* app container
overstepped scope", while accepting the ones that legitimately landed. The
parametrized negative test (`@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_SERVICES))`)
automatically stops flagging an implemented service because it derives from
`FORBIDDEN_SERVICES`.

**When generating/refreshing tests after a new spec lands, you MUST add that
spec's service name to `IMPLEMENTED_APP_SERVICES`** in
`test_chunk_5_docker_compose.py` (and the mirror set in
`test_chunk_1_root_scaffold.py`).

**General rule:** never write a forward-looking "services == EXACTLY {…}" guard
without a maintained allow-set escape hatch, or it false-fails on every
legitimate growth.

## KC_DB* absence pattern (security invariant)

```python
env_keys = _get_env_keys(svc)
kc_db_keys = [k for k in env_keys if k.startswith("KC_DB")]
assert kc_db_keys == [], f"Found: {kc_db_keys}"
```

Any `KC_DB*` var causes Keycloak `start-dev` to attempt PostgreSQL connection,
hanging the stack. This is the most important keycloak config invariant.

## Bind-mount source file existence tests

Tests from `TestBindMountSourceFilesExist` assert infrastructure files exist from
PRIOR chunks. These tests PASS before docker-compose.yml exists — this is intentional.
The overall suite still fails because compose-dependent tests fail/error.
Documented inline with a clear NOTE comment.

## Test counts for chunk 5

46 tests total:
- 3 file existence/parseability tests
- 3 top-level structure tests
- 1 + 9 service set tests (1 exact-set + 9 parametrized forbidden)
- 5 postgres tests
- 4 redis tests
- 6 keycloak tests
- 4 openldap tests
- 2 network tests
- 1 + 4 volume tests (1 aggregate + 4 parametrized)
- 4 bind-mount source file existence tests (parametrized)

TDD run result: 3 failed, 4 passed, 39 errors
- 4 PASSED = bind-mount source file existence tests (files from prior chunks exist)
- 3 FAILED = compose file existence, YAML parse, docker compose config tests
- 39 ERRORS = all fixture-dependent tests blocked by missing compose file
