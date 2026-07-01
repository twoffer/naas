# Identity Normalization Service

The NAAS differentiator. Consumes login events from the Redis `login_events` stream, extracts each protocol's attributes into one unified schema, performs a **live cross-protocol LDAP lookup** to enrich OIDC/SAML identities with authoritative directory data, resolves any conflicts **per attribute**, attaches a confidence score with full provenance, and republishes the enriched record for the downstream pipeline.

**Status:** implemented and integration-validated end-to-end. Implements [`SPEC_2_Identity_Normalization_Service`](../../docs/architecture/SPEC_2_Identity_Normalization_Service.md); see [`docs/architecture/SYSTEM_ARCHITECTURE.md`](../../docs/architecture/SYSTEM_ARCHITECTURE.md) for the surrounding system.

## What it does

This is a **stream consumer**, not a request/response API — its only HTTP surface is `GET /health`. For each event read from `login_events` it runs a four-step pipeline, then ACKs:

1. **Extract** — the protocol adapter (OIDC / SAML / LDAP) maps protocol-native attribute names (`name`/`displayName`/`cn`, `email`/`mail`, `department`/`dept`/`departmentNumber`, …) into the unified schema, normalizing values (e.g. `employeeType` → `FTE`/`contractor`/`vendor`, `memberOf` DNs → bare group names).
2. **Enrich** — for OIDC and SAML events, a **live OpenLDAP query** (correlated by a configurable unified-schema key, default `primary_email`) merges authoritative directory attributes with the token/assertion claims. Native LDAP events skip this step. Results use a three-state Redis cache (positive / negative / miss) with a configurable TTL, a bounded connection pool, and injection-safe filters. Enrichment **degrades, never fails**: a directory miss, timeout, or outage is recorded and normalization proceeds single-source ([ADR-0008](../../docs/adr/0008-cross-protocol-ldap-enrichment.md)).
3. **Resolve** — conflicts are settled **per attribute** against an ordered authority list, not by a global "trust LDAP over OIDC" rule: the IdP owns how a person is *presented* (display name), the directory owns *organizational facts* (department, groups). Each resolution records the winner, the conflicting values, and a confidence score; disagreements and unmapped values lower confidence rather than being silently dropped ([ADR-0006](../../docs/adr/0006-per-attribute-normalization-authority.md)).
4. **Persist & publish** — `UPDATE events.normalized_attributes` (JSONB: unified identity + per-attribute `resolution_details` + `normalization_confidence`), then `XADD` the full record to the `normalized_events` stream for Signal Enrichment.

**Port `8002`.** Consumer group: `normalization_workers` on `login_events`.

**Health decision table** (HTTP status is always `200`; the operational status is in the body):

| PostgreSQL | Redis | Reported status |
|---|---|---|
| reachable | reachable | `healthy` |
| reachable | unreachable | `degraded` — events can persist; the stream publish fails |
| unreachable | — | `unhealthy` — cannot persist normalized attributes |

## Configuration

Per-attribute authority (priority + weights), the `groups` merge strategy, and the LDAP enrichment source live in [`config/normalization.yaml`](../../config/normalization.yaml), loaded and validated once at startup. The service refuses to start on an invalid config rather than silently producing wrong enrichment decisions. (Path resolution: `NORMALIZATION_CONFIG_PATH` env → the compose mount `/app/config/normalization.yaml` → a repo-relative fallback for host/dev runs.)

## Internals (hexagonal — ports & adapters)

The domain depends only on typed `Protocol` ports; concrete adapters supply the I/O (see [ADR-0009](../../docs/adr/0009-hexagonal-service-architecture.md)). The resolution core is **pure** — no I/O, fully deterministic, safe to call from any thread.

- `app/consumer.py` — the `XREADGROUP` loop (ACK only after success; a poison message is logged and skipped without stalling the pipeline).
- `app/service.py` — `NormalizationService`: orchestration and the enrich/skip decision.
- `app/resolution.py` — pure per-attribute resolution + confidence scoring.
- `app/adapters/` — `oidc.py`, `saml.py`, `ldap.py` (the LDAP adapter is dual-role: passive `extract()` plus the active `enrich()` query, pool, and cache).
- `app/normalization_values.py` — value-normalization tables (department, employee-type, DN reduction).
- `app/repository.py` / `app/normalization_config.py` — persistence port impl and config model/loader.
- `app/ports.py` — `ProtocolAdapter`, `LdapEnricher`, `Normalizer`, `NormalizationRepository`, `EventPublisher`.
- `app/main.py` — composition root (`uvicorn app.main:app`); wires the pipeline and runs the consumer as a background task within the FastAPI lifespan.

**Tests:** [`tests/services/identity_normalization/`](../../tests/services/identity_normalization/) (unit) and [`tests/integration/test_identity_normalization_live.py`](../../tests/integration/test_identity_normalization_live.py) (live, against the running stack).

## Run

Starts with the rest of the stack via `docker compose up -d --build` from the repo root. The [`demo/`](../../demo/) script walks this service's behavior end-to-end across six scenes (clean single-source events, an unmapped-value penalty, an enriched agreement, and a two-source conflict finale); see the root [`README.md`](../../README.md).
