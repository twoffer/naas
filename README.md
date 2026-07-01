# NAAS — Normalized Adaptive Access System

> ***Normalize once. Secure everywhere.***

**Unified, risk-based access control across the identity protocols a real enterprise actually runs — OIDC, SAML, and the LDAP directory nobody is allowed to unplug.**

`Python` · `FastAPI` · `PostgreSQL` · `Redis Streams` · `Keycloak` · `OpenLDAP` · `Docker`

**Status:** foundation + first two pipeline stages **implemented and integration-validated end-to-end** · remaining stages architecturally specified — see the [roadmap](#whats-designed-but-not-yet-built)

[![CI](https://img.shields.io/github/actions/workflow/status/twoffer/naas/ci.yml?branch=main&label=CI)](https://github.com/twoffer/naas/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

---

## The problem

Picture a company that has been buying and building for twenty years. There is an LDAP directory from the late 1990s that nobody can switch off, because half the back office still authenticates against it. There is a SAML single sign-on stack that arrived with an acquisition and never quite matched anyone else's attribute names. And there are the modern applications, speaking OIDC — but only a fraction of the estate has migrated, and the rest is not moving quickly.

Each of these systems describes the *same employee* differently. The OIDC token from the new HR app says the user's department is "Marketing." The directory, synced nightly from the system of record, says "Engineering." Neither is lying; they simply disagree — in different field names, in different formats, with no shared notion of which one to trust.

Now try to answer a simple security question — *is this login risky?* — consistently, across all three. You can't. The risk engine would have to understand every protocol's quirks, and it would have no principled way to reconcile the contradictions. This is the gap most enterprises live in: modern access control on one slice of the estate, a patchwork everywhere else.

**NAAS is the bridge.** It takes login events from any of these protocols, reconciles them into one schema with explicit rules about which source to trust for which fact, attaches a confidence score, and hands a single, clean, provenance-tracked identity to everything downstream. Normalize once; reason about risk everywhere.

---

## How it fits together

NAAS is an event-driven pipeline of small, stateless services riding a Redis Streams backbone, with PostgreSQL as the durable system of record. Events enter through one of three doors — live OIDC authentication via Keycloak (the only live auth path), the Persona Simulator generating synthetic OIDC/SAML/LDAP events, or direct REST calls — and every event is tagged with its `source`. From ingestion onward, the pipeline neither knows nor cares which door an event came through.

The diagram doubles as a status map: **green-bordered** services are implemented and integration-validated, **solid** boxes are live infrastructure running today, and **dashed** boxes are designed but not yet built. Blue is Redis — the stream segments between stages and the Pub/Sub broadcast bus.

<p align="center">
  <img src="docs/diagrams/naas-architecture.svg" width="860" alt="NAAS architecture and status map. Three event origins converge on Event Ingestion: live OIDC authentication via Keycloak through the dashboard and API Gateway (source=user), the Persona Simulator generating synthetic OIDC, SAML, and LDAP events (source=simulator), and direct REST calls (source=api). A Redis Streams backbone carries events from Ingestion through Identity Normalization (with a live OpenLDAP enrichment lookup), Signal Enrichment, and the Risk Evaluator, whose decisions broadcast over Redis Pub/Sub to the Alert Service and back up to the API Gateway for WebSocket fan-out to the dashboard. A PostgreSQL rail shows each service persisting to the system of record.">
</p>

Every stage publishes the **full event record** onto its outgoing stream, so each service can act on what it receives without a database round-trip — while PostgreSQL remains the single source of truth ([ADR-0011](docs/adr/0011-full-event-record-on-pipeline-streams.md)). Services are stateless and share nothing; consumer groups track pipeline position, so any service can crash and resume without losing or duplicating work.

---

## What's implemented and running

The foundation and the first two pipeline stages are built, tested, integration-validated against live containers, and runnable from a single `docker compose up`.

**Infrastructure.** PostgreSQL (system of record), Redis (stream transport and cache), Keycloak (OIDC provider), and OpenLDAP (the directory), wired together by Docker Compose with health-gated startup ordering and a shared, typed configuration library.

**Event ingestion.** A FastAPI service that accepts login events, validates them, and performs a dual write — a durable row in PostgreSQL, then a message onto the `login_events` stream — returning immediately so ingestion never blocks on downstream work. Single and bulk endpoints; a real readiness probe that reports `degraded` when a dependency is unreachable.

**Identity normalization — the part that matters most.** This is the differentiator, and it is implemented and validated end-to-end. It consumes login events, extracts each protocol's attributes into one unified schema, and — for OIDC and SAML events — performs a **live lookup against the directory** to enrich the identity with authoritative organizational data. Lookup results are cached in Redis with a configurable TTL, so authentication is never gated on LDAP connectivity. When two sources disagree, it resolves the conflict per attribute, attaches a confidence score, and records full provenance.

<p align="center">
  <img src="docs/diagrams/naas-normalization-flow.svg" width="800" alt="Two-panel diagram. Panel 1, the general flow: a login event (OIDC, SAML, or LDAP) passes through the protocol adapter into the unified schema, then branches on protocol. OIDC and SAML events perform a live OpenLDAP lookup — on a match, the directory entry is normalized through the LDAP protocol adapter and enters resolution as a multi-source entity; on a miss or directory outage, enrichment is skipped gracefully and resolution proceeds single-source. Native LDAP events skip the self-lookup. All paths converge on per-attribute authority resolution, producing a unified identity with a confidence score. Panel 2, the worked example from demo Scene 6: the OIDC token claims name Di Prince and department Marketing; the matched directory entry holds cn Diana Prince and department Engineering. Each side is normalized by its own protocol adapter and both unified entities flow into resolution — OIDC wins display_name (Di Prince), the directory wins department (Engineering), all other attributes are unanimous. The conflict penalty multiplies each contested attribute's confidence by 0.8, overall confidence about 0.82, yielding the final unified identity for diana.">
</p>

Three design choices make this hold up under scrutiny:

- **Authority is per attribute, not per protocol.** There is no global "trust LDAP over OIDC" rule, because that would be wrong half the time. The identity provider owns how a person is *presented* (display name); the directory owns *organizational facts* (department, group membership). Each attribute resolves against its own ordered list of authoritative sources.
- **Confidence is a first-class output.** A clean single-source attribute and a hard-won resolution between two disagreeing sources are not the same thing, and downstream risk scoring should be allowed to know the difference. Conflicts lower confidence rather than being silently discarded.
- **Enrichment degrades; it never fails the request.** If the directory is slow, unreachable, or returns no match, normalization records *why* and proceeds with what it has. A directory outage degrades enrichment quality — it does not take the system down.

---

## What's designed but not yet built

The remaining stages are specified in the system architecture and follow a validated dependency order — each pipeline stage consumes its predecessor's stream, and the downstream decisioning stages communicate over Pub/Sub — so there is no large, deferred integration effort waiting at the end. The implementation sequencing is deliberate: the hardest, most differentiating capability (normalization) was built and proven first.

| Stage | What it adds |
|-------|--------------|
| **Signal enrichment** | IP reputation, geolocation, impossible-travel detection, device fingerprinting, failed-login and login-recency signals |
| **Risk evaluator** | Hybrid scoring — rule-based signal weights combined with an ML model in an ensemble — producing an allow / step-up-MFA / deny decision; fails closed on any error |
| **Policy management** | Versioned YAML policies that supply the signal weights and decision thresholds driving the rule-based half of the Risk Evaluator's hybrid score, evaluated by a safe, sandboxed expression evaluator (no arbitrary code execution); **shadow mode** to test a policy against live traffic before it takes effect |
| **Alert service** | Severity-ranked alerts on high-risk decisions, with an acknowledge / investigate / dismiss workflow |
| **API gateway** | JWT authentication against Keycloak, request routing, real-time WebSocket fan-out, rate limiting |
| **Dashboard + persona simulator** | Protocol-flow visualization and a live event stream; a scriptable generator driving realistic multi-protocol login traffic (office worker, traveler, attacker) — it is how SAML and LDAP events enter a stack whose only live IdP speaks OIDC |

Two of these deserve a note, because both are easy to get quietly wrong. **Shadow mode** is how you migrate policy safely: run the candidate policy alongside the active one, see what it *would have* decided, and investigate the differences before anything in production changes. And the **ML model trains on independent data**, not on the rule engine's own output — training a model to imitate the rules it is meant to complement produces an expensive way to agree with yourself.

---

## What you can do with it

A system like this earns its keep in the workflows it enables. The first runs against the implemented stack today; the others arrive with the dashboard stages — they are what the roadmap above is *for*.

**Watch two protocols argue about one person — runnable today.** Submit the same user as an OIDC token claiming one name and department while the directory claims another, then read the verdict straight out of PostgreSQL: which source won each attribute, why, and how much confidence survived the disagreement? This is the [demo script](demo/demo_normalization.py)'s finale — it builds to the split across six scenes, verifies every claim against the persisted data before rendering it, and cleans up after itself.

**Catch the attacker you just invented.** From the dashboard's simulator panel, bulk-generate thirty days of well-behaved Office Worker history for a user, then hand-craft a single hostile login for the same account — impossible-travel geography, a VPN exit, an unfamiliar device — and watch the pipeline price it in real time: risk score, step-up-MFA or deny, and the alert landing over WebSocket.

**Rehearse a policy change against live traffic.** Start continuous background simulation, put a candidate policy in shadow mode beside the active one, and compare what each *would have* decided — too many step-up challenges? An unexpected deny? — before promoting anything. Policy migration with a dress rehearsal instead of a leap of faith.

---

## How it was built

The implemented services were produced by an automated, test-first build pipeline — and the discipline of that pipeline is itself part of the work.

The design is human-led: the architecture, the specifications, and the decision records were drafted with AI assistance, with every architectural decision debated, adjudicated, and owned by a human. The implementation was then executed by agentic tooling against those specifications, under the quality gates below.

Each specification is decomposed into small chunks. For every chunk, a test suite is written **first**, defining what "done" means; an implementer iterates until those tests pass; and a security-and-quality review gates the commit. If the review finds an issue, the work routes back with specific fixes, under a bounded retry budget that escalates to a human rather than looping forever. Cross-service integration is validated against real running containers — real network, real database, real streams — never mocks.

A fair question is why this much machinery, when the current fashion is to hand a frontier model the goal and let it manage its own delegation. The layers are deliberate. They keep the pipeline reliable across models of varying capability — calibrated to the minimum trustworthy behavior, not the best model's good days. They stop a small misreading, an ambiguous spec line, or a flaky test environment before it cascades into confidently wrong output. And the guards rarely fire on a healthy run, which is precisely what makes the pipeline trustworthy enough to leave unattended.

The receipts live in this repository, under [`.claude/pipeline/`](.claude/pipeline/). Every real pipeline run leaves its artifacts behind: the architecture plan, the per-chunk execution log, security review records, the integration report, and a quality report summarizing tests written, review iterations, and every guard that fired. The execution log is the interesting read — it shows the pipeline catching real issues rather than rubber-stamping its own work: security findings auto-fixed in reflection loops, integration failures escalated and resolved by hand.

A separate **pipeline simulator** validates the orchestration machinery itself — its deterministic state transitions and its failure and escalation paths — with worker outputs stubbed by design. It snapshots state after every step and ends with a simulation report covering contract violations and phase-file ambiguities, so problems in the orchestrator can be diagnosed independently of the code it builds.

---

## Running it yourself

You need Docker and Docker Compose. No API keys are required — everything runs against local containers.

```bash
git clone https://github.com/twoffer/naas.git && cd naas
cp .env.example .env            # sensible defaults; works out of the box
docker compose up -d --build    # infrastructure + the two implemented services
```

Submit a login event to ingestion:

```bash
curl -s -X POST http://localhost:8001/events/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "user_id": "alice",
    "protocol": "oidc",
    "client_ip": "203.0.113.42",
    "timestamp": "2026-06-03T14:05:00Z",
    "raw_attributes": { "email": "alice@corp.com", "department": "Product" }
  }'
# → 202 Accepted  {"id": "<uuid>", "status": "accepted"}
```

Then watch normalization do its work — the event is enriched against the seeded directory user and resolved into the unified schema:

```bash
docker exec naas-postgres psql -U naas -d naas -c \
  "SELECT user_id, protocol, normalized_attributes \
   FROM events ORDER BY created_at DESC LIMIT 1;"
```

The `normalized_attributes` column carries the unified identity, the per-attribute resolution detail, and the confidence score. Health checks live at `GET /health` on each service (`:8001`, `:8002`).

### Demo

A scripted, self-verifying demonstration — [`demo/demo_normalization.py`](demo/demo_normalization.py) — walks the normalization story in six scenes against the live stack: clean OIDC, SAML, and native-LDAP events establishing the source-authority baseline; a suspicious event showing unmapped values penalized or discarded; an enriched event where token and directory agree and confidence climbs; and the finale, where two sources disagree about one person and *two different sources win two different attributes*. Every number rendered is read back from PostgreSQL, and the script verifies the narrative against the persisted data before showing it — if the pipeline doesn't produce the story, the demo aborts rather than telling it.

```bash
pip install -r demo/requirements.txt   # rich, httpx, psycopg — all it needs
POSTGRES_PASSWORD=naas_dev_password python demo/demo_normalization.py
```

Connection parameters all default sensibly; the one thing the script won't guess is the PostgreSQL password — the value above is the out-of-the-box development default from `.env.example` (override it, or pass `--db-dsn`, if you've changed yours). `--step` pauses between scenes for live walkthroughs; `--keep` preserves the demo's events for inspection (by default it cleans up after itself). Flags, scene-by-scene expectations, and troubleshooting live in [`demo/README.md`](demo/README.md).

---

## Tech stack

| Layer        | Choice                                                   | Why it's here                                                                 |
| ------------ | -------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Services     | Python · FastAPI · Pydantic v2                           | Typed contracts everywhere — including stream message schemas                 |
| Internals    | Hexagonal (ports & adapters)                             | Domain logic depends on typed interfaces, never concrete infrastructure       |
| Messaging    | Redis Streams + Pub/Sub                                  | Consumer-group pipeline transport; broadcast for decisions and alerts         |
| Storage      | PostgreSQL                                               | Durable system of record; JSONB for normalized attributes and provenance      |
| Identity     | Keycloak (OIDC) · OpenLDAP                               | Real providers, not stubs; synthesized SAML rides the same normalization path |
| Operations   | Docker Compose · structured JSON logs · `/health` probes | Correlation IDs end to end; health-gated startup ordering                     |
| Later stages | scikit-learn · pluggable LLM backend · React             | ML risk model; persona simulator; dashboard                                   |

---

## Going deeper

- **[`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md)** — the full system architecture: services, data flow, database schema, stream topology.
- **[`docs/architecture/`](docs/architecture/)** — the functional specifications for what's built (the project scaffold, event ingestion, identity normalization, and the demo), alongside the full system architecture that defines the remaining stages.
- **[`docs/adr/`](docs/adr/)** — architectural decision records in MADR format, each capturing the context, the alternatives genuinely considered, and the consequences. A few worth starting with:
  - **[0002](docs/adr/0002-why-redis-streams.md)** — Redis Streams as the pipeline transport, PostgreSQL as the system of record
  - **[0005](docs/adr/0005-hybrid-policy-scoring-model.md)** — the hybrid policy scoring model and its safe expression evaluator
  - **[0006](docs/adr/0006-per-attribute-normalization-authority.md)** — per-attribute authority weights with confidence scoring (the heart of normalization)
  - **[0008](docs/adr/0008-cross-protocol-ldap-enrichment.md)** — cross-protocol LDAP enrichment, correlated by a unified-schema key
  - **[0011](docs/adr/0011-full-event-record-on-pipeline-streams.md)** — the full event record as the payload on every pipeline stream, with explicit conditions for revisiting
- **[`CLAUDE.md`](CLAUDE.md)**, **[`docs/AI-AGENT-PRINCIPLES.md`](docs/AI-AGENT-PRINCIPLES.md)**, **[`docs/Agentic_Workflow_Implementation_Guide.md`](docs/Agentic_Workflow_Implementation_Guide.md)** — the build pipeline, its agents, and the conventions they follow.

---

## About

Built by **Tony Offer** — a senior software engineer with over a decade of enterprise IAM and backend systems experience. [LinkedIn](https://linkedin.com/in/tonyoffer) · [Email](mailto:tony.offer@gmail.com)

Open source under the [MIT License](LICENSE).

---

*Normalize once. Secure everywhere.*
