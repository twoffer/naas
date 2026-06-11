---
name: patterns-integration-tests
description: Live-docker integration test harness patterns for NAAS — skip gate, compose lifecycle, app health polling, psycopg3 fixtures, subprocess timeouts
metadata:
  type: project
---

## Integration test suite location

`tests/integration/` — four files plus conftest.

## Skip gate: critical placement rule

`pytest_addoption` (for `--integration`) MUST live in `tests/conftest.py`, NOT in
`tests/integration/conftest.py`. When pytest is invoked from the repo root the
subdirectory conftest's `pytest_addoption` is ignored — only the initial conftest
(the one in the rootdir) processes addoption hooks.

The skip logic itself (`pytest_collection_modifyitems`) lives in
`tests/integration/conftest.py` and reads `config.getoption("--integration",
default=False)` (with `default=False` so it works even when the option was not
registered in this conftest's scope).

## Skip is runtime, not collection-time

`pytest_collection_modifyitems` adds a skip marker at runtime. `--collect-only`
always shows the 26 integration tests regardless of the flag — that is correct and
intentional. The SKIP appears in the run phase.

Opt-in paths:
  - CLI: `--integration`
  - Env: `NAAS_RUN_INTEGRATION=1`

## compose_stack fixture contract

Session-scoped. Lives in `tests/integration/conftest.py`. Yields:

```python
{
    "pg_dsn": "host=localhost port=5432 dbname=naas user=naas password=naas_dev_password",
    "pg_conninfo": {"host": ..., "port": 5432, "dbname": "naas", "user": "naas", "password": "naas_dev_password"},
    "event_ingestion_url": "http://localhost:8001",
    "identity_normalization_url": "http://localhost:8002",
    "services": [...],
}
```

App health polling: after `docker compose up --wait` (container healthchecks),
separately polls HTTP `/health` endpoints and checks body `status == "healthy"`.
Event-ingestion reports HTTP 200 even when degraded — so we must check the body.

Teardown: `docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
--remove-orphans` (volume wipe; both -f flags so a lingering test-runner is also
removed). NAAS_IT_KEEP_STACK=1 suppresses.
Log capture on failure to `tests/integration/.logs/<service>.log`.

## psycopg3 fixture pattern

```python
@pytest.fixture(scope="module")
def pg_connection(compose_stack: dict):
    import psycopg
    info = compose_stack["pg_conninfo"]
    conn = psycopg.connect(**info)
    conn.autocommit = True
    yield conn
    conn.close()
```

psycopg3 returns JSONB columns as Python dicts directly (no `json.loads` needed,
but handle the str case defensively).

## Subprocess timeout discipline

pytest-timeout's thread mode cannot interrupt `subprocess.run`. Every subprocess
call needs its own `timeout=` argument. Set the inner timeout 10s less than the
outer `@pytest.mark.timeout(...)` to avoid race conditions:

```
pytest.mark.timeout(600)  →  subprocess.run(..., timeout=590)
pytest.mark.timeout(300)  →  subprocess.run(..., timeout=290)
```

## cleanup_event_ids fixture pattern

```python
@pytest.fixture
def cleanup_event_ids(pg_connection):
    ids: list[str] = []
    yield ids
    if ids:
        with pg_connection.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = ANY(%s::uuid[])", (ids,))
```

Register the event ID BEFORE asserting so partial test failures still clean up.

## Normalization polling pattern

```python
def _poll_normalized_attributes(pg_conn, event_id, timeout_s=60.0, interval_s=2.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        with pg_conn.cursor() as cur:
            cur.execute("SELECT normalized_attributes FROM events WHERE id = %s::uuid", (event_id,))
            row = cur.fetchone()
        if row and row[0] is not None:
            attrs = row[0]
            if isinstance(attrs, str):
                attrs = json.loads(attrs)
            return attrs
        time.sleep(interval_s)
    raise TimeoutError(...)
```

## Mark registration

The `integration` marker is registered ONLY in root `pyproject.toml`
`[tool.pytest.ini_options].markers`. An initial belt-and-suspenders
`pytest_configure`/`addinivalue_line` in `tests/conftest.py` was removed by
security review (single source of truth) — don't reintroduce it.

## Service subset

Default: postgres, redis, openldap, event-ingestion, identity-normalization
(keycloak excluded — 60s start_period dominates cold startup).
Override: NAAS_IT_SERVICES env var (space-separated, or "all" for full stack).

## In-container test-runner

The test-runner compose service (profile: test, docker-compose.test.yml overlay)
runs the host unit suite inside the identity-normalization image where python-ldap
is importable. The inner pytest invocation ignores:
  - tests/integration (would recurse)
  - tests/infrastructure/test_docker_compose.py (shells out to docker CLI absent in container)
