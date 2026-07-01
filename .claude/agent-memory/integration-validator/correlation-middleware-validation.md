---
name: correlation-middleware-validation
description: How to live-validate the ASGI CorrelationIdMiddleware + event_id stream propagation, and results for the pre-public branch
metadata:
  type: project
---

# Correlation Middleware + event_id Propagation (chore/pre-public-fixes, validated 2026-07-01)

## What the middleware does (naas_shared/middleware.py)
- Pure ASGI middleware (NOT BaseHTTPMiddleware — contextvars must reach the handler task). Wired via `application.add_middleware(CorrelationIdMiddleware)` in event-ingestion + identity-normalization `create_app()`.
- Reads inbound `x-request-id` (validated against `[A-Za-z0-9._-]{1,128}` fullmatch; anything else → mint uuid4().hex), binds `correlation_id` into structlog contextvars, echoes it on the response header, clears context in `finally`.
- SCOPE BOUNDARY (by design): correlation_id covers HTTP-request scope only. The async Redis-Streams pipeline is correlated by **event_id** (the record `id`), NOT correlation_id. Stream-consumer structlog lines carry `event_id`, not correlation_id — this is correct, not a gap.

## How to PROVE correlation_id lands in real logs (uvicorn access logs are stdlib, NOT structlog — they never carry it)
- The happy ingest path emits ZERO structlog lines; the only request-scoped structlog emission in event-ingestion is `service.py:_safe_publish` on publish failure.
- Image has NO httpx → TestClient unusable. Drive the real ASGI app directly with a hand-built http scope (see run log). Override `get_ingestion_service` with a publisher that raises ConnectionError; POST with `X-Request-ID`. `setup_logging` runs synchronously in `create_app()`, so no lifespan needed. Result line: `{"event_id":..., "event":"login_events publish failed", "correlation_id":"itval-corr-proof-777", "level":"error", ...}` — proves middleware binding + merge_contextvars.
- Cheap proof middleware runs per-request: it echoes `x-request-id` on EVERY response (even 422). Header-less requests get distinct minted uuid4 hex ids.

## event_id chain (verified identical id across all stages)
events table `id` == login_events stream payload `"id"` == normalized_events payload `"id"`. normalization structlog lines (e.g. `ldap_enrichment_skipped_no_correlation`) carry `event_id`.

## Input caps (branch, shared/naas_shared/models.py LoginEventBase) — live boundary-tested
- `user_agent` max_length=2048: 2048→202, 2049→422.
- `raw_attributes` max_length=200 keys: 200→202, 201→422.
- bulk max_length=5000 (pre-existing): 5001→422.

## Compose scope reminder
docker-compose.yml defines ONLY postgres/redis/keycloak/openldap/event-ingestion/identity-normalization. signal-enrichment, risk-evaluator, alert-service, api-gateway, policy-management, persona-simulator are NOT yet in compose — live pipeline validation currently ends at normalized_events. `docker compose` is v5.2.0 here.
