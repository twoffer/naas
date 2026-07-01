# Integration Validator Memory — NAAS

## Infrastructure Notes
- [infra-notes.md](infra-notes.md) — Keycloak healthcheck stays "starting" but is functionally UP; container names; startup timings
- Compose CLI: use `docker compose` (plugin v5.1.4); `docker-compose` binary is NOT on PATH in this env.

## Failure Modes
- [failure-modes.md](failure-modes.md) — Spec 1 tz-aware 500s RESOLVED; what-works list; live E2E suite first run 2026-06-11: in-container scenario failed (test-runner `command` YAML-fold bug + rich missing from image) — both RESOLVED same day, full suite 26/26; teardown+gating clean
- [ldap-memberof-overlay.md](ldap-memberof-overlay.md) — normalization-demo memberOf back-population: RESOLVED via 00-memberof-overlay.ldif (the .sh hook never ran); Scene-6 0.80 is by design post-b6d7a81; verify now fails token-only merges; --keep prints ids; LDAP creds + demo DB host gotchas (POSTGRES_PASSWORD now required)

## Validation Recipes / Results
- [correlation-middleware-validation.md](correlation-middleware-validation.md) — chore/pre-public-fixes (2026-07-01) full PASS: how to prove correlation_id in real logs (no httpx→drive raw ASGI, only publish-fail path logs via structlog); event_id chain across streams; input-cap boundaries; compose scope ends at normalized_events
- [public-release-validation.md](public-release-validation.md) — pre-public-flip E2E (2026-06-30): full PASS, README headline holds; 30/30 integration, demo exit 0 all 6 scenes, both /health healthy; .env is gitignored (drift is local-only)
- [normalization-validation.md](normalization-validation.md) — live inject+trace recipe (redis host="redis" gotcha) + adapter rule-table refactor regression PASS (2026-06-07)
- [lockfile-drift-validation.md](lockfile-drift-validation.md) — PR #22 dep-pinning: faithfully replicate CI drift job by recompiling IN PLACE (fresh-output gives false drift); GO verdict, 1572 unit tests green
- [ruff-ratchet-validation.md](ruff-ratchet-validation.md) — e2ada32 ruff ratchet: 30/30 integration PASS, live config-path refactor verified, safe to merge. GOTCHA: integration harness refuses to run while default naas-* stack is up — `docker compose down` first; remove stray naas-it_default net after
