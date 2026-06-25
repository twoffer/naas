---
name: lockfile-drift-validation
description: How to faithfully replicate the CI pip-compile drift job locally without false drift
metadata:
  type: project
---

Dependency pinning landed in PR #22 (commit c06ba80, ADR-0012). Floors in `*.in`,
pinned closures in `*.txt`, compiled with `pip-compile --strip-extras`. CI has a
`lockfiles` drift-check job (`.github/workflows/ci.yml`) that recompiles in place
and `git diff --exit-code`s.

**Why:** Verifying drift requires replicating CI exactly, and the naive way gives
false positives.

**How to apply — to check the drift job would be green:**
- pip-compile only PRESERVES existing pins when the OUTPUT FILE ALREADY EXISTS and
  `--upgrade` is NOT passed. Recompiling to a fresh temp path re-resolves EVERYTHING
  to latest (e.g. mypy 2.1, pytest 9, ruff 0.15) → looks like massive drift. This is
  WRONG and not what CI does.
- Correct: recompile IN PLACE (output = the committed lock), then `git diff`. This is
  exactly the CI sequence. On PR #22 this produced ZERO drift (clean working tree).
- The four compile commands (dev and demo run from repo root; the service locks run from the service directory — see next bullet; `.venv` active; pin all 3 resolver tools to match CI: `pip==26.1.2 setuptools==82.0.1 pip-tools==7.5.3`):
  - shared is folded into each `.in` as a path dep (single input, so Dependabot can't drop it on regen); suppress it + build backends with `--unsafe-package`. Let `U="--unsafe-package=naas-shared --unsafe-package=pip --unsafe-package=setuptools"`. The service `.in` files point to `../../shared` (relative to the manifest dir, the way Dependabot resolves path deps), so their lock MUST be compiled from the service directory or the path won't resolve:
  - `pip-compile --strip-extras $U -o requirements-dev.txt requirements-dev.in -q`
  - `( cd services/event-ingestion && pip-compile --strip-extras $U -o requirements.txt requirements.in -q )`
  - `( cd services/identity-normalization && pip-compile --strip-extras $U -o requirements.txt requirements.in -q )`
  - `pip-compile --strip-extras -o demo/requirements.txt demo/requirements.in -q`
  - identity-normalization needs python-ldap metadata; on a bare system install its build headers first (`sudo apt-get install -y libldap2-dev libsasl2-dev`, as the CI `lockfiles` job does).
- Restore after: `git checkout -- <the four .txt files>` (in-place recompile may touch them).

**Env facts confirmed (2026-06-16):** pip-tools 7.5.3 present in `.venv`; fastapi
pinned 0.137.1 across all locks; shared runtime closure (fastapi/pydantic/
pydantic-settings/sqlalchemy/asyncpg/redis/structlog) pinned at IDENTICAL versions in
all three service/dev locks; `pip check` clean with dev-lock + `naas-shared --no-deps`.
Full unit suite: 1572 passed, 2 skipped, 30 deselected; ruff clean.

`tests/helpers.py::iter_routes` flattens FastAPI >=0.137 `original_router` wrappers
(app.include_router now inserts an opaque wrapper into app.routes). Verified it
surfaces leaf routes; note leaf `APIRoute.path` does NOT include the include prefix.
