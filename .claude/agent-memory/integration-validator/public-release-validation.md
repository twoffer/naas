---
name: public-release-validation
description: Pre-public-flip end-to-end validation of NAAS (Spec-2 freeze) — full PASS 2026-06-30; confirms README headline claim holds
metadata:
  type: project
---

# Public-release validation (private→public flip) — PASS, 2026-06-30

Scope: confirm README headline ("foundation + first two pipeline stages implemented
and integration-validated end-to-end · runnable from a single docker compose up") is
TRUE for the frozen Spec-2 repo. Only event-ingestion + identity-normalization are
implemented; other 6 services are README-only stubs (NOT in compose, do not run).

**Why:** repo about to be made public; needed independent
fresh-clone-fidelity confirmation before the flip.

**How to apply:** this is the canonical "does the project still work for a stranger"
check. Re-run the 5 checks below if anything in compose / the two services / the demo
changes before any future public push.

## Results (all PASS)
1. ENV: `.env` is gitignored (`.gitignore:11`, NOT tracked) — fresh cloner only gets
   `.env.example` then `cp`. The working-tree `.env` had benign LOCAL drift from
   `.env.example` (extra `KEYCLOAK_DB`, quoted `LDAP_ORGANISATION`, stale KC comment) —
   does NOT ship, pure local artifact. Overwrote `.env` from `.env.example` for fidelity;
   git stays clean (ignored).
2. Integration suite `python -m pytest tests/integration --integration -v` = **30 passed,
   0 fail/skip in 115.28s** (first run, includes image build). Scenario split: demo-script-live 4,
   event-ingestion-live 15, identity-normalization-live 10, in-container-unit-suite 1.
   Harness self-manages `naas-it` project, tore down clean (no containers/volumes); left the
   usual stray `naas-it_default` network → removed manually.
3. Health: default stack `up -d --build` → all 6 healthy ~45-54s (keycloak ~46s).
   `:8001/health` + `:8002/health` both `{"status":"healthy"}` HTTP 200 (v2.0.0).
4. Demo `POSTGRES_PASSWORD=naas_dev_password python demo/demo_normalization.py --pace 0` =
   exit 0, all 6 scenes rendered, internal verify passed (no "Verification failed" abort),
   summary table printed, "Cleanup: removed 6 event(s)". Scene-5 alice 0.917, Scene-6 diana
   0.823 (priority split: display_name→oidc, department→ldap), matches design.
5. README verbatim curl→202 + psql read works: token `department:"Product"` →
   resolved `"Engineering"` (ldap priority win, penalty_applied), enrichment.applied=true
   cache_hit=true, normalization_confidence=0.8515.

**VERDICT: headline claim HOLDS. Safe to flip public.** No repo source modified.

## Fresh-clone friction (non-blocking, all already documented in README/demo README)
- First `docker compose up -d --build` / first integration run builds images (~2 min) — slow
  but expected; no hang.
- Demo host-run needs `POSTGRES_PASSWORD` exported (no default) and relies on the demo's OWN
  `localhost` default for POSTGRES_HOST (NOT `.env`'s `postgres` alias) — README + demo/README
  both call this out explicitly. See [[ldap-memberof-overlay]] env note.
- `pip install -r demo/requirements.txt` assumes the cloner has a venv/pip ready — README shows
  it but doesn't spell out venv creation. Minor.
