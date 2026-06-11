---
name: integration-tests-e2e
description: Patterns for NAAS live docker-compose integration tests + GitHub Actions CI (gating, in-container unit runner, compose lifecycle)
metadata:
  type: project
---

End-to-end integration test design for NAAS (live compose stack, not mocks).

**Why this exists:** Tony wanted live integration tests that exercise containerized
product code + a CI workflow (no `.github/` existed before this work).

**How to apply** when extending integration tests or CI:

- **Gating (3 layers):** integration tests live under `tests/integration/`, carry
  `pytestmark = [pytest.mark.integration, pytest.mark.timeout(N)]`, and a
  `pytest_collection_modifyitems` hook in `tests/integration/conftest.py` skips them
  unless `NAAS_RUN_INTEGRATION=1` (env) or `--integration` (CLI flag via
  `pytest_addoption`). Plain host `pytest tests/` must stay fast + skip them.
- **Global pytest timeout is 60s** (`pyproject.toml`, `timeout_method="thread"`). Do
  NOT raise it — protects the unit suite. Integration tests override per-module with
  `@pytest.mark.timeout(120-600)`. Crucially: pytest-timeout `thread` mode does NOT
  cancel `subprocess.run`, so every compose subprocess call needs its own `timeout=`.
- **In-container unit runner:** a profile-gated `test-runner` service in
  `docker-compose.test.yml` built from the identity-normalization Dockerfile (only image
  with python-ldap system+pip deps — that's the whole motivation, see
  [[spec2_identity_normalization]] and project memory python_ldap_dev_venv_gap). Mount
  whole repo read-only at a path containing `docs/architecture/` (repo-root marker used
  by `tests/conftest.py` + infra tests). Drive via `docker compose ... run --rm test-runner`
  with `pip install -r requirements-dev.txt && pytest tests/ --ignore=tests/integration
  --ignore=tests/infrastructure/test_docker_compose.py`. That one file shells out to the
  docker CLI (absent in-container); everything else only reads mounted files.
- **App readiness > container health:** `docker compose up -d --wait` blocks on
  healthchecks, but ALSO poll `:8001/health` and `:8002/health` for JSON
  `status=="healthy"` (event-ingestion returns degraded/unhealthy if PG/Redis down).
- **Teardown:** `down -v` (volume wipe) between runs so postgres init.sql re-applies
  (init.sql only runs on empty volume — CLAUDE.md). `NAAS_IT_KEEP_STACK=1` escape hatch.
- **Keycloak (start_period 60s) dominates startup** though no tested service uses it.
  Offer a `NAAS_IT_SERVICES` override to bring up only postgres/redis/openldap/the 2 apps.
- **Demo deps** (rich/httpx/psycopg in demo/requirements.txt): pinned copies of all
  three now live in requirements-dev.txt (self-contained harness, don't couple to
  demo). rich is required because tests/demo/test_demo_flow.py imports
  demo_normalization.py, and the in-container runner installs only requirements-dev.txt.
- **Compose override gotchas (both bit on first live run):** the test-runner needs
  `image: naas-identity-normalization:local` explicitly declared in BOTH
  docker-compose.yml and docker-compose.test.yml (base service had no `image:`, so
  compose default-tags `:latest` and the override silently builds a divergent image);
  and `command` must be the JSON exec-array `["sh","-c","..."]` form — a `>` folded
  scalar with deeper-indented continuation lines preserves newlines and `sh -c` drops
  every flag (exit 127).
- **CI:** two jobs in `.github/workflows/ci.yml` on `pull_request` + push to main. Fast
  `unit` job (no docker) gates slow `integration` job via `needs:`. `cp .env.example .env`
  (gitignored). ubuntu-latest ships docker + compose v2. Log dump on `if: failure()`,
  teardown `down -v` on `if: always()`. No docker layer caching initially (boring).

**Live contracts asserted (verified from source, not memory):**
- POST `:8001/events/ingest` → 202 `{"id":<uuid>,"status":"accepted"}` (app/schemas.py
  IngestAccepted). Bulk: bare JSON array → `{"accepted":N,"event_ids":[...],"status":"accepted"}`.
- `/health` → 200 `{"status":"healthy","service":"event-ingestion"}` (always HTTP 200,
  status in body).
- events table (init.sql): id, user_id, protocol CHECK in (oidc,saml,ldap),
  raw_attributes JSONB, normalized_attributes JSONB (NULL until normalized).
- normalized_attributes parses into naas_shared.models.NormalizedAttributes; LDAP-native
  event → enrichment.applied=False, skip_reason="ldap_event".
