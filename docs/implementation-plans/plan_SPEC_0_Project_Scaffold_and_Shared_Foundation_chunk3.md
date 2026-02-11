# Chunk 3: Service Placeholders + Integration Smoke Test

**Spec Reference:** `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md`
**Prerequisites:** Chunks 0, 1, and 2 completed (infrastructure running, shared library installable)
**Estimated Effort:** ~20 minutes, ~100 lines of new files + verification

---

## Scope

This is the final chunk of Spec 0. It creates the 8 service directory placeholders (so `git` tracks them and subsequent specs have directories to work in) and runs the complete integration smoke test covering all validation criteria from Spec 0, Section 6.

### Files Created

```
naas/
└── services/
    ├── api-gateway/
    │   └── README.md
    ├── event-ingestion/
    │   └── README.md
    ├── identity-normalization/
    │   └── README.md
    ├── signal-enrichment/
    │   └── README.md
    ├── risk-evaluator/
    │   └── README.md
    ├── policy-management/
    │   └── README.md
    ├── alert-service/
    │   └── README.md
    └── persona-simulator/
        └── README.md
```

### Files NOT Touched

- No modifications to `docker-compose.yml`, infrastructure configs, or shared library
- No `Dockerfile`, `app/`, `requirements.txt`, or Python code inside any `services/*/` directory (Spec 0, Section 7 explicitly forbids this)
- No `dashboard/` directory (Spec 6)

---

## Steps

### Step 1: Create service directory placeholders

Create 8 directories under `services/`, each containing a single `README.md` placeholder file.

The README template from Spec 0, Section 5.6:

```markdown
# {Service Name}

Part of the NAAS system. Implementation defined in Spec {N}.

See `docs/architecture/SYSTEM_ARCHITECTURE.md` for architectural context.
```

Create the following files with the appropriate service name and spec number:

| Directory | Service Name | Spec |
|-----------|-------------|------|
| `services/api-gateway/README.md` | API Gateway | Spec 5 |
| `services/event-ingestion/README.md` | Event Ingestion Service | Spec 1 |
| `services/identity-normalization/README.md` | Identity Normalization Service | Spec 2 |
| `services/signal-enrichment/README.md` | Signal Enrichment Service | Spec 3 |
| `services/risk-evaluator/README.md` | Risk Evaluator Service | Spec 4 |
| `services/policy-management/README.md` | Policy Management Service | Spec 5 |
| `services/alert-service/README.md` | Alert Service | Spec 5 |
| `services/persona-simulator/README.md` | Persona Simulator | Spec 5 |

**Verify:** `ls services/*/README.md` lists all 8 files.

---

### Step 2: Full integration smoke test -- Docker infrastructure

Bring up the full infrastructure stack and verify every Spec 0 validation criterion. Run all checks from Spec 0, Section 6.

**2a: Clean start**
```bash
# Remove stale state from previous chunks
docker-compose down -v

# Start all infrastructure
docker-compose up -d

# Wait for services to stabilize (Keycloak needs ~90s)
sleep 90

# Check all containers
docker-compose ps
```

**Expected:** 4 containers running: `naas-postgres`, `naas-redis`, `naas-keycloak`, `naas-openldap`. Postgres and Redis should be "healthy". OpenLDAP should be "healthy". Keycloak should be "healthy" or at least "running".

---

**2b: PostgreSQL schema exists (Spec 0, Section 6.2)**
```bash
docker exec -it naas-postgres psql -U naas -d naas -c "\dt"
```
**Expected:** Lists 5 tables: `users`, `events`, `policies`, `risk_assessments`, `alerts`

```bash
docker exec -it naas-postgres psql -U naas -d naas -c "SELECT policy_id, name, is_active FROM policies;"
```
**Expected:** `default-v1 | Default Risk Policy | t`

---

**2c: Redis responds (Spec 0, Section 6.3)**
```bash
docker exec -it naas-redis redis-cli ping
```
**Expected:** `PONG`

```bash
docker exec -it naas-redis redis-cli CONFIG GET maxmemory
```
**Expected:** `256mb` or `268435456` (bytes equivalent)

---

**2d: Keycloak OIDC discovery works (Spec 0, Section 6.4)**
```bash
curl -s http://localhost:8080/realms/naas-demo/.well-known/openid-configuration | python3 -m json.tool
```
**Expected:** JSON containing `authorization_endpoint`, `token_endpoint`, `jwks_uri`, etc.

```bash
curl -s -X POST http://localhost:8080/realms/naas-demo/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=naas-dashboard" \
  -d "username=alice" \
  -d "password=password123" | python3 -m json.tool
```
**Expected:** JSON with `access_token`, `refresh_token`, `token_type`, `expires_in`

---

**2e: OpenLDAP returns test users (Spec 0, Section 6.5)**
```bash
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(uid=alice)"
```
**Expected:** Full entry for alice with `cn`, `sn`, `mail`, `uid`, `departmentNumber`, `employeeType`

```bash
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "ou=users,dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(objectClass=inetOrgPerson)" dn | grep "numEntries"
```
**Expected:** `# numEntries: 5`

---

**2f: Shared library importable (Spec 0, Section 6.6)**
```bash
cd shared && python3 -c "
from naas_shared.config import get_settings
from naas_shared.models import LoginEventIngest, RiskDecision, AlertMessage
from naas_shared.constants import STREAM_LOGIN_EVENTS, CHANNEL_DECISIONS
from naas_shared.logging import setup_logging

setup_logging('test')
s = get_settings()
print(f'DB URL: {s.database_url}')
print(f'Stream: {STREAM_LOGIN_EVENTS}')
print('All imports OK')
"
```
**Expected:** Prints DB URL, stream name, and `All imports OK`

---

**2g: Clean shutdown (Spec 0, Section 6.7)**
```bash
docker-compose down -v
```
**Expected:** All containers stopped, volumes removed, no errors

---

### Step 3: Verify project file tree completeness

Verify the entire Spec 0 file tree matches what was specified. Run from the project root:

```bash
# Check all expected files exist
ls .env.example
ls .env
ls .gitignore
ls docker-compose.yml
ls infrastructure/postgres/init.sql
ls infrastructure/redis/redis.conf
ls infrastructure/keycloak/naas-realm-export.json
ls infrastructure/openldap/bootstrap.ldif
ls shared/pyproject.toml
ls shared/naas_shared/__init__.py
ls shared/naas_shared/config.py
ls shared/naas_shared/constants.py
ls shared/naas_shared/models.py
ls shared/naas_shared/database.py
ls shared/naas_shared/redis_client.py
ls shared/naas_shared/logging.py
ls shared/naas_shared/schemas.py
ls services/api-gateway/README.md
ls services/event-ingestion/README.md
ls services/identity-normalization/README.md
ls services/signal-enrichment/README.md
ls services/risk-evaluator/README.md
ls services/policy-management/README.md
ls services/alert-service/README.md
ls services/persona-simulator/README.md
```

**All 24 files must exist.** If any are missing, go back to the relevant chunk.

---

### Step 4: Final verification -- nothing extra was built

Verify that the "What NOT to Build" constraints from Spec 0, Section 7 were honored:

```bash
# No service application code should exist
ls services/*/app/ 2>/dev/null && echo "FAIL: service app dirs found" || echo "PASS: no service app dirs"
ls services/*/Dockerfile 2>/dev/null && echo "FAIL: service Dockerfiles found" || echo "PASS: no service Dockerfiles"
ls services/*/requirements.txt 2>/dev/null && echo "FAIL: service requirements.txt found" || echo "PASS: no service requirements.txt"

# No dashboard directory should exist
ls dashboard/ 2>/dev/null && echo "FAIL: dashboard dir found" || echo "PASS: no dashboard dir"

# No monitoring stack
ls infrastructure/monitoring/ 2>/dev/null && echo "FAIL: monitoring dir found" || echo "PASS: no monitoring dir"

# No CI/CD
ls .github/ 2>/dev/null && echo "FAIL: .github dir found" || echo "PASS: no .github dir"

# No test directories
ls tests/ 2>/dev/null && echo "FAIL: tests dir found" || echo "PASS: no tests dir"
ls shared/tests/ 2>/dev/null && echo "FAIL: shared tests dir found" || echo "PASS: no shared tests dir"

# No Makefile
ls Makefile 2>/dev/null && echo "FAIL: Makefile found" || echo "PASS: no Makefile"
```

**Expected:** All lines print `PASS`.

---

## naas_shared Imports Needed

None for this chunk (only creates placeholder READMEs and runs verification).

---

## Done When

All of the following pass:

1. All 8 service directories exist with `README.md` files: `ls services/*/README.md` lists exactly 8 files
2. Full Docker infrastructure starts cleanly: `docker-compose up -d` brings up 4 healthy containers
3. **PostgreSQL:** 5 tables exist, default policy seeded
4. **Redis:** Responds to ping, maxmemory set to 256mb
5. **Keycloak:** OIDC discovery returns valid JSON, token endpoint issues access tokens for alice
6. **OpenLDAP:** Returns alice's entry with all attributes, user count is 5
7. **Shared library:** All imports from Spec 0, Section 4 work without errors
8. **Clean shutdown:** `docker-compose down -v` completes without errors
9. **No forbidden files:** No service Dockerfiles, no app/ dirs, no dashboard/, no monitoring, no CI/CD, no tests, no Makefile
10. All 24 project files from Spec 0 exist in the correct locations

**Spec 0 is now COMPLETE.** The project skeleton, infrastructure stack, and shared foundation are ready. Subsequent specs (1-6) can begin implementing application services on this foundation.

---

## Next Chunk Preview

This is the final chunk of Spec 0. The next work item is Spec 1 (Event Ingestion Service), which builds the first application service on top of this foundation. **Do NOT proceed to Spec 1 implementation until all "Done When" criteria above are verified and the implementer has confirmed that Spec 0 is fully passing.**
