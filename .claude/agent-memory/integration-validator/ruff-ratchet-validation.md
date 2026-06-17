---
name: ruff-ratchet-validation
description: chore/ruff-rule-set-ratchet (e2ada32) full live integration validation — PASS/safe to merge; harness refuses to run while default stack occupies naas-* names
metadata:
  type: project
---

# ruff rule-set ratchet (e2ada32) — live integration validation PASS (2026-06-17)

- Change = enterprise ruff rule-set; production-code edits are behavior-preserving:
  event-ingestion main/routes/service.py = ONLY `# noqa: BLE001` comments added to
  existing `except Exception`; consumer.py/service.py = isort reorder + noqa; ldap.py =
  isort reorder, removed stale PLC0415 comments on lazy imports, two `try/except: pass`
  → `contextlib.suppress(Exception)` (exact equivalents); main.py = extracted three-tier
  config-path logic into sync `_resolve_config_path()` (env NORMALIZATION_CONFIG_PATH →
  /app/config/normalization.yaml → 4-parent repo fallback) — order preserved, ASYNC240 fix.
- LIVE startup/config verification (the at-risk lifespan refactor): default-project stack
  rebuilt `up -d --build` at e2ada32, all 6 healthy. In live container
  `_resolve_config_path()` → `/app/config/normalization.yaml` (tier 2 compose mount), exists=True,
  load_config parses, ldap enrichment block intact. consumer_loop_started +
  identity_normalization_startup_complete, /health 200, ZERO tracebacks. Critical shared import
  `from naas_shared.config import get_settings` works in both app containers.
- Integration suite `python -m pytest tests/integration --integration -v` = 30 passed / 73.85s.
- HARNESS GOTCHA (cost one run): conftest spins up its OWN `naas-it` compose project but REFUSES
  to run while the default-project stack holds the `naas-*` container names — errors with
  "Conflict. The container name /naas-openldap is already in use ... a dev stack is already running
  ... stop it first". So to run the suite you MUST `docker compose down` the default stack first.
  Sequence that works: rebuild default stack for manual startup/config checks → `docker compose down`
  → run integration suite (harness builds+manages+tears down naas-it). Default `naas_*` volumes
  untouched by harness.
- TEARDOWN: harness removes naas-it containers/volumes/app-network but LEAVES a stray
  `naas-it_default` network — remove manually with `docker network rm naas-it_default`.
- VERDICT: PASS, safe to merge. No regression in the refactored areas.
