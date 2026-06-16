---
name: dependency-pinning-posture
description: ADR-0012 lockfile posture — floors (*.in / shared/pyproject.toml) vs compiled *.txt locks, install path, CI drift job, Dependabot semantics; what's in/out of scope for review
metadata:
  type: reference
---

ADR-0012 (`docs/adr/0012-dependency-pinning-reproducible-builds.md`) + `DEPENDENCIES.md` define the repo dependency posture. Verified at PR #22 (`fix/dependency-drift-hardening`).

## Layout
- **Floors (compile inputs):** `requirements-dev.in`, `demo/requirements.in`, `services/*/requirements.in`, and `shared/pyproject.toml` (shared runtime deps). Human-authored `>=` minimums. Edit these to add/re-floor.
- **Locks (install artifacts):** the generated `*.txt`. Never hand-edit. Each SERVICE lock is compiled with `shared/pyproject.toml` as a 2nd input so it subsumes shared's full transitive closure. `demo/requirements.txt` compiled from `demo/requirements.in` alone (no shared).
- Dev lock = superset of demo lock (demo deps floored in `requirements-dev.in` too), so CI installs only the dev lock for both unit + integration.

## Install path (every env)
`pip install -r <lock>` THEN `pip install -e shared/ --no-deps`. `--no-deps` is CORRECT: lock already pins shared's closure, so it keeps locked versions authoritative and prevents re-resolution. Verified shared's deps (fastapi/pydantic/pydantic-settings/sqlalchemy/asyncpg/redis/structlog) all appear in each service lock annotated `via naas-shared`.
- Both service Dockerfiles: build context `.` (repo root), `COPY services/<svc>/requirements.txt` → install → `COPY shared/` → `pip install -e ... --no-deps` → `COPY app/` last (layer order = slow→fast changing). Non-root `USER appuser` (uid 10001). identity-normalization installs gcc/build-essential/libldap2-dev/libsasl2-dev for python-ldap sdist build.

## CI (`.github/workflows/ci.yml`)
- Actions SHA-pinned (supply-chain). `permissions: contents: read`. concurrency cancel-in-progress.
- `lockfiles` drift job: recompiles all 4 locks (installs libldap2-dev/libsasl2-dev + `pip==26.1.2 setuptools==82.0.1 pip-tools==7.5.3`), `git diff --exit-code` on `requirements-dev.txt 'services/*/requirements.txt' demo/requirements.txt`. No `--upgrade`, so routine upstream releases don't trip it — only a stale lock does. All 3 resolver tools (pip/setuptools/pip-tools) are pinned so a runner default-pip bump can't re-resolve the closure and false-trip the job (was a LOW finding; fixed d4235f4).

## Dependabot (`.github/dependabot.yml`)
- pip ecosystem across all manifest dirs (`/`, `/shared`, `/demo`, `/services/*`) + github-actions, monthly, grouped (minor+patch collapsed, majors separate), `versioning-strategy: lockfile-only` (moves lock, leaves floors as declared minimums). SECURITY updates are a SEPARATE channel enabled in repo UI (Settings→Code security), not in this file.

## Supply-chain gap (known, accepted)
Locks pin by VERSION only — no `--generate-hashes`/`--require-hashes`. Pinning by artifact hash is not in place; a hijacked-but-same-version artifact would still install. Worth flagging as informational, not a blocker, in any future lockfile review.

## iter_routes helper (`tests/helpers.py`)
FastAPI >=0.137 inserts a single `_IncludedRouter` wrapper (attr `original_router`) into `app.routes` per `include_router()` instead of flattening child `APIRoute`s. `iter_routes()` recurses on `original_router.routes`, yields everything else as-is. Correctly preserves "exactly N routes" / "no auth endpoints" assertions — does NOT mask route-registration regressions (a missing route still won't appear). Confirmed against installed fastapi 0.137.1 in `.venv`.
