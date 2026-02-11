# Chunk 0: Project Skeleton, Environment, Docker Compose (Postgres + Redis)

**Spec Reference:** `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md`
**Prerequisites:** None (this is the first chunk of the first spec)
**Estimated Effort:** ~30 minutes, ~200 lines of new code/config

---

## Scope

This chunk creates the foundational project files and brings up the two simplest infrastructure services (PostgreSQL and Redis). At the end of this chunk, `docker-compose up -d postgres redis` produces healthy containers with the full database schema initialized and Redis configured.

### Files Created

```
naas/
├── .env.example
├── .env                              # Copy of .env.example (gitignored)
├── .gitignore                        # Updated with full project ignores
├── docker-compose.yml                # Postgres + Redis only (Keycloak/OpenLDAP added in chunk 1)
└── infrastructure/
    ├── postgres/
    │   └── init.sql                  # Full DDL: all tables, indexes, extensions, seed data
    └── redis/
        └── redis.conf                # Custom Redis config
```

### Files NOT Touched

- No `shared/` directory (chunk 2)
- No `services/` directories (chunk 3)
- No `infrastructure/keycloak/` or `infrastructure/openldap/` (chunk 1)
- Do NOT modify `CLAUDE.md` or `README.md`

---

## Steps

### Step 1: Create `.env.example`

**File:** `naas/.env.example`

Create the environment variable template with all variables defined in Spec 0, Section 2 (Input Contracts). Copy the content exactly as specified in the spec:

```env
# PostgreSQL
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_USER=naas
POSTGRES_PASSWORD=naas_dev_password
POSTGRES_DB=naas

# Keycloak (also uses PG — separate DB auto-created by Keycloak)
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=admin
KEYCLOAK_DB=keycloak

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# OpenLDAP
LDAP_HOST=openldap
LDAP_PORT=389
LDAP_BASE_DN=dc=corp,dc=com
LDAP_ADMIN_DN=cn=admin,dc=corp,dc=com
LDAP_ADMIN_PASSWORD=admin
LDAP_ORGANISATION=Corp Inc
LDAP_DOMAIN=corp.com

# Service Ports
API_GATEWAY_PORT=8000
EVENT_INGESTION_PORT=8001
IDENTITY_NORMALIZATION_PORT=8002
SIGNAL_ENRICHMENT_PORT=8003
POLICY_MANAGEMENT_PORT=8004
RISK_EVALUATOR_PORT=8005
ALERT_SERVICE_PORT=8006

# Dashboard
DASHBOARD_PORT=3000

# Keycloak OIDC
KEYCLOAK_URL=http://keycloak:8080
KEYCLOAK_REALM=naas-demo
KEYCLOAK_CLIENT_ID=naas-dashboard
```

**Then** copy `.env.example` to `.env` (which will be gitignored).

**Verify:** `cat .env.example` shows all variables. `diff .env.example .env` shows no differences.

---

### Step 2: Update `.gitignore`

**File:** `naas/.gitignore`

Replace the existing `.gitignore` (if any) with the full project gitignore from Spec 0, Section 5.5. The complete content:

```gitignore
# Python
__pycache__/
*.py[cod]
*.egg-info/
dist/
build/
.venv/
venv/

# Environment
.env

# IDE
.vscode/
.idea/
*.swp
*.swo

# Docker
postgres-data/
redis-data/

# OS
.DS_Store
Thumbs.db

# Node (dashboard)
node_modules/
dashboard/dist/

# ML models
*.pkl
*.joblib

# Logs
*.log
```

**Verify:** `cat .gitignore` shows the content. `.env` should NOT appear in `git status` as trackable (it should be ignored).

---

### Step 3: Create PostgreSQL init script

**File:** `naas/infrastructure/postgres/init.sql`

Create the directory `infrastructure/postgres/` and then the `init.sql` file. The DDL is specified exactly in Spec 0, Section 3.1. This includes:

1. `CREATE EXTENSION IF NOT EXISTS "pgcrypto";`
2. `CREATE TABLE IF NOT EXISTS users` -- with columns: `id` (UUID PK), `user_id` (VARCHAR UNIQUE NOT NULL), `email` (VARCHAR NOT NULL), `display_name` (VARCHAR), `created_at` (TIMESTAMP)
3. `CREATE TABLE IF NOT EXISTS events` -- with ALL columns including `user_agent TEXT`, `raw_attributes JSONB`, `normalized_attributes JSONB`, `enriched_signals JSONB`. Includes CHECK constraints on `protocol` (oidc|saml|ldap) and `source` (user|simulator|api).
4. Three indexes on events: `idx_events_user_id`, `idx_events_timestamp` (DESC), `idx_events_protocol`
5. `CREATE TABLE IF NOT EXISTS policies` -- with `policy_yaml TEXT NOT NULL` and `is_shadow BOOLEAN`
6. `CREATE TABLE IF NOT EXISTS risk_assessments` -- with FK to events and policies, includes `shadow_decision` and `shadow_score` columns
7. Two indexes on risk_assessments: `idx_risk_assessments_event_id`, `idx_risk_assessments_decision`
8. `CREATE TABLE IF NOT EXISTS alerts` -- with FK to events and risk_assessments
9. One index on alerts: `idx_alerts_status`
10. Seed data: INSERT the default policy (`policy_id='default-v1'`, `name='Default Risk Policy'`, `version='1.0.0'`, `is_active=TRUE`, `is_shadow=FALSE`) with the full policy YAML from Spec 0, Section 3.1. Use `ON CONFLICT (policy_id) DO NOTHING`.

Copy the SQL exactly from the spec. Do NOT add anything beyond what the spec defines. Do NOT create a separate Keycloak database -- the spec explicitly says to use Option A (H2 dev database for Keycloak).

**Verify:** The file is valid SQL syntax (no verification command needed yet; the docker step will validate).

---

### Step 4: Create Redis configuration

**File:** `naas/infrastructure/redis/redis.conf`

Create the directory `infrastructure/redis/` and then the `redis.conf` file with exactly the content from Spec 0, Section 3.2:

```conf
maxmemory 256mb
maxmemory-policy allkeys-lru
appendonly yes
appendfsync everysec
```

Four lines. No more, no less.

**Verify:** `cat infrastructure/redis/redis.conf` shows exactly 4 lines.

---

### Step 5: Create `docker-compose.yml` with Postgres and Redis

**File:** `naas/docker-compose.yml`

Create the Docker Compose file with ONLY the `postgres` and `redis` services for now (Keycloak and OpenLDAP are added in chunk 1). Include:

- `version: "3.8"`
- `postgres` service: image `postgres:17-alpine`, container_name `naas-postgres`, environment variables (using `${VAR:-default}` syntax), port mapping `${POSTGRES_PORT:-5432}:5432`, volumes for data persistence AND the init.sql mount (`./infrastructure/postgres/init.sql:/docker-entrypoint-initdb.d/01-init.sql`), network `naas-network`, healthcheck using `pg_isready`.
- `redis` service: image `redis:7.4-alpine`, container_name `naas-redis`, port mapping `${REDIS_PORT:-6379}:6379`, volumes for data persistence AND the redis.conf mount, command `["redis-server", "/usr/local/etc/redis/redis.conf"]`, network `naas-network`, healthcheck using `redis-cli ping`.
- `networks` section: `naas-network` with `driver: bridge`
- `volumes` section: `postgres-data` and `redis-data`
- Comment placeholder at the bottom where Keycloak and OpenLDAP will be added: `# Keycloak and OpenLDAP added in chunk 1`
- Comment placeholder for application services: `# Application services added by Specs 1-6`

Use the exact configuration values from Spec 0, Section 5.1 for healthcheck intervals, timeouts, retries, pool sizes, etc.

**Verify:**
```bash
docker-compose config
```
This should print the resolved compose file with no errors.

---

### Step 6: Start containers and validate

**Commands:**
```bash
# Start just Postgres and Redis
docker-compose up -d postgres redis

# Wait for healthy status (up to 30s)
docker-compose ps

# Verify PostgreSQL schema
docker exec -it naas-postgres psql -U naas -d naas -c "\dt"
# Expected: lists users, events, policies, risk_assessments, alerts

# Verify seed data
docker exec -it naas-postgres psql -U naas -d naas -c "SELECT policy_id, name, is_active FROM policies;"
# Expected: default-v1 | Default Risk Policy | t

# Verify Redis
docker exec -it naas-redis redis-cli ping
# Expected: PONG

docker exec -it naas-redis redis-cli CONFIG GET maxmemory
# Expected: includes "256mb" or 268435456 bytes
```

If PostgreSQL tables are missing, check `docker-compose logs postgres` for init.sql errors. Common issue: SQL syntax errors cause the init script to fail silently on some entries.

If Redis maxmemory is not set, verify the redis.conf mount path is correct.

---

## naas_shared Imports Needed

None for this chunk. The shared library does not exist yet.

---

## Done When

All of the following pass:

1. `docker-compose up -d postgres redis` starts both containers without errors
2. `docker-compose ps` shows both as "healthy"
3. `docker exec -it naas-postgres psql -U naas -d naas -c "\dt"` lists 5 tables: `users`, `events`, `policies`, `risk_assessments`, `alerts`
4. `docker exec -it naas-postgres psql -U naas -d naas -c "SELECT policy_id, name, is_active FROM policies;"` returns the default policy row
5. `docker exec -it naas-redis redis-cli ping` returns `PONG`
6. `docker exec -it naas-redis redis-cli CONFIG GET maxmemory` returns `256mb` equivalent
7. `.env` file exists and is gitignored
8. `docker-compose down -v` shuts down cleanly

---

## Next Chunk Preview

Chunk 1 adds Keycloak (OIDC provider) and OpenLDAP (legacy directory) to the Docker Compose stack, including the realm export JSON and bootstrap LDIF files. **Do NOT proceed to chunk 1 until all "Done When" criteria above are verified.**
