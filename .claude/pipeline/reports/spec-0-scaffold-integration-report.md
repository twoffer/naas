# Integration Validation Report — Spec 0: Project Scaffold & Shared Foundation

Append-only history of integration-validator invocations for this spec (CONTRACTS.md §9).

## Validation Run 1 — FAIL — 2026-06-03T16:50:14Z

Scope: SPEC_0 §6 — infrastructure stack + shared library (Level 1 infrastructure health; no application services exist in Spec 0). Branch: feature/spec-0-scaffold.

**VERDICT: FAIL** — one blocking infrastructure failure (OpenLDAP, check 6.5).

### Results per check
- **Docker daemon/Compose:** PASS — Docker 29.5.2, Compose v5.1.4, daemon available.
- **6.6 Shared library import:** PASS — all imports OK; `DB URL: postgresql+asyncpg://naas:...@postgres:5432/naas`, `Stream: login_events`.
- **6.1 Stack bring-up:** PARTIAL — postgres, redis, keycloak started; openldap exited (1).
- **6.2 PostgreSQL:** PASS — all 5 tables present (alerts, events, policies, risk_assessments, users); seed policy exactly `default-v1 | Default Risk Policy | t`.
- **6.3 Redis:** PASS — `PONG`; `maxmemory = 268435456` (256mb).
- **6.4 Keycloak:** PASS (functional) — OIDC discovery returns valid JSON (authorization_endpoint, token_endpoint, jwks_uri); password grant for alice/password123 returns a valid `access_token`. Realm `naas-demo` imported.
- **6.5 OpenLDAP:** **FAIL** — container exited (1) at startup; ldapsearch cannot run.
- **6.7 Clean shutdown:** PASS — `docker compose down -v` removed all containers, volumes, and the network.

### Blocking issue
**OpenLDAP container fails to start.** Seam: docker-compose volume mount ↔ osixia/openldap entrypoint.
- Observed: `sed: cannot rename /container/service/slapd/assets/config/bootstrap/ldif/custom/sedXXXXXX: Device or resource busy` → `/container/run/startup/slapd failed with status 4` → exit 1.
- Root cause: `docker-compose.yml` bind-mounts the bootstrap LDIF as a **single file** (`./infrastructure/openldap/bootstrap.ldif:/container/service/slapd/assets/config/bootstrap/ldif/custom/bootstrap.ldif`). The osixia entrypoint runs `sed -i` over files in that `custom/` dir to substitute env vars; `sed -i`'s temp-file rename cannot replace an inode pinned by a single-file bind mount. (This mount form was transcribed verbatim from SPEC_0 §5.1 — the spec itself carries the bug.)
- Data is NOT the problem: `infrastructure/openldap/bootstrap.ldif` correctly defines the 5 users (alice, bob, charlie, diana, eve) and the users/groups OUs.
- Suggested fix: mount the LDIF via its parent directory — `./infrastructure/openldap/:/container/service/slapd/assets/config/bootstrap/ldif/custom/` — so `sed -i` can create/rename temp files freely. (Directory must contain only LDIF assets, since the bootstrap loader reads everything in it.)

### Non-blocking issues
1. Keycloak healthcheck never reports "healthy" (stays "starting") despite being fully functional — the documented TCP-healthcheck-vs-functional discrepancy (image lacks curl). Treated as functionally UP per spec guidance. Later specs that gate on `service_healthy` would hang; recommend revisiting the `/dev/tcp` healthcheck expression.
2. Keycloak benign WARNs: deprecated `KEYCLOAK_ADMIN`/`KEYCLOAK_ADMIN_PASSWORD` env vars (newer images prefer `KC_BOOTSTRAP_ADMIN_USERNAME`/`_PASSWORD`) and a JDBC ResultSet leak during import — harmless in dev mode.

### Recommendation
Fix the OpenLDAP volume mount (directory mount, not single-file), then re-run 6.1/6.5/6.7 to confirm OpenLDAP serves the 5 users. Everything else (6.2/6.3/6.4/6.6) already passed.

## Validation Run 2 — PASS — 2026-06-03T19:04:28Z

Re-validation after fix commit `7a3a288` (OpenLDAP LDIF baked into a custom image via `infrastructure/openldap/Dockerfile`; openldap service switched to `build:`). Brought up with `docker compose up -d --build`.

**VERDICT: PASS** — the previously-failing OpenLDAP container now starts and stays running; all re-confirmed checks succeed.

### Results per check
- **6.6 Shared library import:** PASS — `DB URL: postgresql+asyncpg://naas:...@postgres:5432/naas`, `Stream: login_events`, all imports OK.
- **6.1 Bring up `--build`:** PASS — `naas-openldap:local` image built; all 4 containers started.
- **6.1 OpenLDAP stays running (KEY CHECK):** PASS — `running exitcode=0 restarts=0` across the full poll; final `Up (healthy)`. No exit 1.
- **6.2 PostgreSQL:** PASS — 5 tables (alerts, events, policies, risk_assessments, users); seed `default-v1 | Default Risk Policy | t`.
- **6.3 Redis:** PASS — `PONG`; maxmemory `268435456` (256mb).
- **6.4 Keycloak:** PASS — OIDC discovery valid JSON (issuer `http://localhost:8080/realms/naas-demo`); alice password grant returns a Bearer `access_token`.
- **6.5 OpenLDAP (was failing):** PASS — alice's full entry returned (`departmentNumber: Engineering`, `employeeType: FTE`, `mail: alice@corp.com`); user count = **5**.
- **Host file untouched:** PASS — `infrastructure/openldap/bootstrap.ldif` identical before/after (61 lines, 1307 bytes, owner unchanged, not chowned to uid 911, not emptied).
- **6.7 Clean shutdown:** PASS — `docker compose down -v` removed all containers, 4 volumes, and the network.

### Seam status
Host filesystem ↔ openldap bootstrap seam now healthy: baking the LDIF into the image confines the osixia entrypoint's `sed -i`/`chown -R`/`rm -rf` to the container, eliminating the run-1 `Device or resource busy` failure at its root.

### Non-blocking issues
1. Keycloak healthcheck stays "starting" despite being fully functional (image lacks curl for the `/dev/tcp` `/health/ready` check). Functionally UP. Recommend adjusting the healthcheck or documenting as expected dev-mode behavior — later specs gating on `service_healthy` would otherwise hang.

### Operational note
`docker compose up -d` now requires `--build` for OpenLDAP (a plain up may use a stale/absent `naas-openldap:local` image). Worth surfacing in any quickstart/run guide.
