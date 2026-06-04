---
name: event-ingestion-orm-matches-init-sql
description: The events-table DDL is owned by infra init.sql; EventORM is a mapping over it, never a migration
metadata:
  type: project
---

The PostgreSQL `events` table DDL lives in `infrastructure/postgres/init.sql` (§EVENTS TABLE) and is created by the Postgres Docker entrypoint on first start. Spec 1's `EventORM` (appended to `shared/naas_shared/schemas.py`) is a read/write MAPPING over that pre-existing table — verified to match the DDL column-by-column (id UUID PK, client_ip INET, raw/normalized/enriched JSONB, timestamp + created_at TIMESTAMPTZ default CURRENT_TIMESTAMP).

**Why:** Schema ownership is split — infra owns DDL, services own ORM mappings. Calling `Base.metadata.create_all` or adding Alembic would create a competing source of truth and drift.

**How to apply:** When a spec says "ORM columns must mirror the existing DDL," read `infrastructure/postgres/init.sql` and diff it against the spec's exemplary mapping before planning. NEVER plan `create_all` or migrations for tables init.sql already defines. Later specs append their own table mappings to `naas_shared.schemas.py` the same way (one Base, many ORM classes). Cross-ref [[spec1-dual-write-patterns]].
