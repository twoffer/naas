---
name: integration-harness-invariants
description: NAAS live-docker integration harness (tests/integration/conftest.py) invariants — compose project isolation, .env precedence pitfalls, module-scoped cleanup ordering
metadata:
  type: project
---

# Live-docker integration harness invariants (PR #17 remediation, branch feature/e2e-integration-tests)

Verified-correct patterns in `tests/integration/conftest.py` and siblings. Use as a fast checklist for future integration-harness reviews.

**Compose project isolation.** All compose invocations must go through `_COMPOSE_CMD` (= `docker compose -p naas-it -f docker-compose.yml -f docker-compose.test.yml`). Sites: `up`, `logs`, `down -v --remove-orphans` (conftest) + in-container `run` (test_in_container_unit_suite via `compose_stack["compose_cmd"]`). The demo subprocess runs the Python script, not compose. `down -v` is safe only because `-p naas-it` scopes it away from the default `naas` dev project.
**Why:** a stray default-project compose call could `down -v`-wipe the dev stack's postgres/redis/ldap volumes.
**How to apply:** flag any `subprocess.run([... "docker", "compose" ...])` that does not carry `-p naas-it` and both `-f` files. CI logs/teardown steps must mirror this too.

**Concurrency-conflict-by-design.** docker-compose.yml pins `container_name` on every service (naas-postgres, etc.) and binds openldap host ports `389`/`636` unconditionally (no `${VAR:-}`). So a concurrent default-project stack fails loudly at `up`; the harness refuses to share/replace it. The `up_result.returncode != 0` branch must emit a hint naming the name/port-conflict cause.

**.env resolution precedence (latent pitfalls).**
- `_read_dot_env` does NOT strip inline ` # comment` from values — diverges from docker compose's dotenv parser. `.env.example` uses inline comments, but none on the resolved keys (POSTGRES_*, EVENT_INGESTION_PORT, IDENTITY_NORMALIZATION_PORT). Latent, not active.
- `_resolve_settings` uses `os.environ.get(k) or dot_env.get(k) or default` — `or` short-circuits on empty string. Matches compose ONLY because all resolved keys use `${VAR:-default}` (colon-dash → empty falls to default). Would diverge if any key switches to `${VAR-default}` (no colon → empty kept).

**Module-scoped cleanup ordering.** `module_cleanup_ids` fixture depends on `pg_connection`, so setup order is pg_connection → module_cleanup_ids → result fixtures; teardown reverses → DELETE runs before `conn.close()`. Correct. Event IDs are appended to `module_cleanup_ids` BEFORE polling so a poll timeout still cleans up.

**Failure-log capture.** Uses `request.session.testsfailed` delta around `yield` (not try/except — test failures never propagate through a fixture yield). Captures genuine failures incl. fixture-setup `pytest.fail`. No xfail markers in this suite.
