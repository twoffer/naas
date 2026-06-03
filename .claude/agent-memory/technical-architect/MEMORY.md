# Technical Architect Agent Memory

## Spec 0 Patterns

- **Keycloak DB strategy:** Use built-in H2 dev database (no KC_DB* vars). Realm imported on every start via `--import-realm`.
- **Keycloak healthcheck:** TCP-based approach is fragile. Fallback: `test: ["CMD-SHELL", "true"]` with `start_period: 90s`. Do not spend >20min debugging.
- **OpenLDAP LDIF:** Do NOT include base DN (`dc=corp,dc=com`) -- image creates it from `LDAP_DOMAIN`. OUs before users (order-sensitive).
- **Shared library mount pattern:** `./shared:/app/shared` in docker-compose volumes, `pip install -e /app/shared/` in Dockerfiles.
- **schemas.py:** Placeholder only in Spec 0. ORM models deferred to Spec 1.
- **ml_features.py / simulation_tools.py:** In §1 file tree but §3 defines no content and §6.6 doesn't import them. Decision: create as importable placeholder modules (deferral comment only), like schemas.py. Real content owned by Spec 3 (ml_features) and persona-simulator track (simulation_tools P0 defs). Surface as a flagged decision, not a silent guess.
- **config.py transcription bug:** Spec §3.8 snippet uses `Field`/`Optional` (LLM fields) but its import block omits them. Implementer MUST add `from pydantic import Field` and `from typing import Optional` or §6.6 import test fails.
- **Pre-existing root files:** `.gitignore`, `README.md`, root `CLAUDE.md` already exist in repo despite §1 listing them as "created." Augment/verify, do NOT overwrite (root CLAUDE.md = the agent reference; gitignore already superset of §5.5).

## Chunking Strategy

- Chunk sizing: ~200-500 lines new code, 30-45 min agent work
- Infrastructure chunks: separate DB/cache (simple) from identity providers (complex startup)
- Shared library: always its own chunk due to import verification complexity
- Last chunk: integration smoke test covering all spec validation criteria
- Service scaffolds: directory + Dockerfile + docker-compose entry + health endpoint = first chunk of any service spec

## Key File Paths

- Spec docs: `docs/architecture/SPEC_*.md`
- Shared library: `shared/naas_shared/` (7 modules + `__init__.py`)
- Infrastructure configs: `infrastructure/{postgres,redis,keycloak,openldap}/`
- Docker compose: `docker-compose.yml` (root)

## Redis Stream/Channel Constants (from naas_shared/constants.py)

- Streams: `login_events`, `normalized_events`, `enriched_events` (maxlen 10000)
- Pub/Sub channels: `decisions`, `alerts`
- Consumer groups: `normalization_workers`, `enrichment_workers`, `evaluator_workers`
- Stream messages wrap data as `{"data": json.dumps(payload)}`

## Cross-Service Import Contract (from Spec 0 Section 4)

Every service imports from `naas_shared`: config, constants, models, database, redis_client, logging.
Volume mount `./shared:/app/shared` + `pip install -e /app/shared/` in every Dockerfile.
