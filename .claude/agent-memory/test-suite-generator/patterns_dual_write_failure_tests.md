---
name: patterns-dual-write-failure-tests
description: Patterns for testing spec §5.5 dual-write failure semantics: persist-fail-propagates vs publish-fail-swallowed, route-level 5xx, self-contained fakes per file
metadata:
  type: project
---

## Dual-Write Failure Test Patterns (Spec 1 §5.5)

### FailingRepo idiom
`FailingRepo` records the call in call_log *before* raising RuntimeError. This lets
tests assert both that persist was attempted AND that nothing was published after the
failure. Appending to call_log before raise is load-bearing — a fake that raises
without recording would make the "persist was called" check impossible.

### Fake isolation between test files
`test_routes.py` and `test_service.py` are independent pytest modules under importlib
mode. Cross-file imports between test modules are fragile (the importer's path is not
guaranteed). Define a local `_FailingRepo` and `_CapturingPublisher` in `test_routes.py`
rather than importing from `test_service.py`. Prefix with `_` to suppress pytest
collection.

### Route-level 5xx pattern
Override `get_ingestion_service` with a real `IngestionService(FailingRepo, publisher)`
(not a FakeIngestionService that absorbs the exception). The real service propagates
the RuntimeError; FastAPI's unhandled exception handler returns 500.
Use `TestClient(app, raise_server_exceptions=False)` — consistent with the rest of the
routes file — so the 5xx appears as a normal response object rather than re-raising.

### Guard intent docstrings
For fail-closed tests, the docstring must include a "Guard intent:" line explaining
exactly which future refactor these tests are designed to catch. Example:
  "Guard intent: a future refactor wrapping persist in try/except (mimicking _safe_publish)
  must fail these tests."
This makes the security invariant self-documenting in CI failure messages.

### call_log ordering assertion
Use a shared `call_log: list` passed to both repo and publisher fakes. Assert:
- `[entry[0] for entry in call_log if entry[0] == "persist"]` has expected count
- `[entry[0] for entry in call_log if entry[0] == "publish"]` is empty on persist failure
Both checks together prove the ordering invariant.

### Redis Stream integration fixture pattern
The `compose_stack` dict does not expose a Redis URL. Add an inline `_resolve_redis_port()`
helper that mirrors compose's precedence: `os.environ["REDIS_PORT"]` → `.env` file →
default 6379. Add a module-scoped `redis_client` fixture with deferred `import redis`
to avoid collection-time ImportError in non-integration environments.

### Stream message search pattern
The `login_events` stream is shared; never assume position. Use `XREVRANGE login_events
count=200` to search recent entries newest-first. Parse each entry's `data` field as
JSON, match on `payload["id"] == event_id`. The `decode_responses=True` client option
makes all Redis return values str, simplifying JSON parsing.

### Bulk ingest integration pattern
Add a `bulk_url` module-scoped fixture mirroring `ingest_url`. Use a separate
`_http_post_json_bulk` helper that accepts `list` not `dict` to make call-site intent
clear. Register returned `event_ids` in `cleanup_event_ids` before asserting to ensure
cleanup even on partial failures.
