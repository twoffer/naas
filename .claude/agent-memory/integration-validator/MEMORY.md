# Integration Validator Memory — NAAS

## Infrastructure Notes
- [infra-notes.md](infra-notes.md) — Keycloak healthcheck stays "starting" but is functionally UP; container names; startup timings
- Compose CLI: use `docker compose` (plugin v5.1.4); `docker-compose` binary is NOT on PATH in this env.

## Failure Modes
- [failure-modes.md](failure-modes.md) — Spec 1: tz-aware timestamp 500s — RESOLVED via TIMESTAMPTZ fix (fresh-volume re-validation caveat); plus what-works verification list
- [ldap-memberof-overlay.md](ldap-memberof-overlay.md) — normalization-demo memberOf back-population: RESOLVED via 00-memberof-overlay.ldif (the .sh hook never ran); Scene-6 0.80 is by design post-b6d7a81; verify now fails token-only merges; --keep prints ids; LDAP creds + demo DB host gotchas (POSTGRES_PASSWORD now required)

## Validation Recipes / Results
- [normalization-validation.md](normalization-validation.md) — live inject+trace recipe (redis host="redis" gotcha) + adapter rule-table refactor regression PASS (2026-06-07)
