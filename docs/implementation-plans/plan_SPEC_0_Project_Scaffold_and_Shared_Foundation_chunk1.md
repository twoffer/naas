# Chunk 1: Keycloak and OpenLDAP Infrastructure

**Spec Reference:** `docs/architecture/SPEC_0_Project_Scaffold_and_Shared_Foundation.md`
**Prerequisites:** Chunk 0 completed (docker-compose.yml with postgres + redis working)
**Estimated Effort:** ~30 minutes, ~250 lines of new config

---

## Scope

This chunk adds Keycloak (OIDC identity provider) and OpenLDAP (legacy directory) to the infrastructure stack. It creates the Keycloak realm export JSON and the OpenLDAP bootstrap LDIF, adds both services to `docker-compose.yml`, and verifies that OIDC token issuance and LDAP user queries work.

### Files Created

```
naas/
└── infrastructure/
    ├── keycloak/
    │   └── naas-realm-export.json    # Realm, client, test users, groups
    └── openldap/
        └── bootstrap.ldif            # OU structure + 5 test users
```

### Files Modified

```
naas/
└── docker-compose.yml                # Add keycloak + openldap services, volumes
```

### Files NOT Touched

- No `shared/` directory (chunk 2)
- No `services/` directories (chunk 3)
- Do NOT modify `infrastructure/postgres/init.sql` or `infrastructure/redis/redis.conf`

---

## Steps

### Step 1: Create the Keycloak realm export JSON

**File:** `naas/infrastructure/keycloak/naas-realm-export.json`

Create the directory `infrastructure/keycloak/` and then the realm export file. This JSON is imported by Keycloak on startup via the `--import-realm` flag.

The JSON must conform to Keycloak's realm representation format as specified in Spec 0, Section 5.2. Key requirements:

**Realm-level settings:**
- `"realm": "naas-demo"`
- `"enabled": true`
- `"sslRequired": "none"` (dev mode)
- `"registrationAllowed": false`

**Client configuration (one client):**
- `"clientId": "naas-dashboard"`
- `"enabled": true`
- `"publicClient": true` (no client secret)
- `"standardFlowEnabled": true`
- `"directAccessGrantsEnabled": true` (needed for password grant in testing)
- `"redirectUris": ["http://localhost:3000/*"]`
- `"webOrigins": ["http://localhost:3000"]`
- `"protocol": "openid-connect"`

**Groups (3):**
- `engineering`
- `product`
- `security`

**Test users (3):**

| Username | Email | First Name | Last Name | Password | Groups |
|----------|-------|-----------|-----------|----------|--------|
| alice | alice@corp.com | Alice | Smith | password123 | /engineering |
| bob | bob@corp.com | Bob | Jones | password123 | /product |
| charlie | charlie@corp.com | Charlie | Brown | password123 | /security |

Each user must have:
- `"enabled": true`
- `"emailVerified": true`
- `"credentials": [{"type": "password", "value": "password123", "temporary": false}]`
- `"groups": ["/groupname"]` (note the leading slash -- Keycloak realm import format requires absolute group paths)

**Important Keycloak JSON pitfalls (from Spec 0, Architect's Review Notes):**
- The `--import-realm` flag expects the file at `/opt/keycloak/data/import/`
- If realm import fails silently, the OIDC discovery endpoint will return 404
- After startup, always verify with the curl check in Step 5

**Verify:** The file is valid JSON: `python3 -m json.tool infrastructure/keycloak/naas-realm-export.json > /dev/null`

---

### Step 2: Create the OpenLDAP bootstrap LDIF

**File:** `naas/infrastructure/openldap/bootstrap.ldif`

Create the directory `infrastructure/openldap/` and then the LDIF file. Copy the content exactly from Spec 0, Section 5.3.

**Critical LDIF rules (from Spec 0, Architect's Review Notes, Gap 6):**
- Do NOT include the base DN entry (`dc=corp,dc=com`) -- the `osixia/openldap` image creates it automatically from `LDAP_DOMAIN`
- Parent entries (OUs) MUST appear before child entries (users) -- LDIF is order-sensitive
- Each entry is separated by a blank line

**Entries to create (in this exact order):**

1. `dn: ou=users,dc=corp,dc=com` (organizationalUnit)
2. `dn: ou=groups,dc=corp,dc=com` (organizationalUnit)
3. `dn: uid=alice,ou=users,dc=corp,dc=com` (inetOrgPerson) -- cn: Alice Smith, departmentNumber: Engineering, employeeType: FTE
4. `dn: uid=bob,ou=users,dc=corp,dc=com` (inetOrgPerson) -- cn: Bob Jones, departmentNumber: Product, employeeType: FTE
5. `dn: uid=charlie,ou=users,dc=corp,dc=com` (inetOrgPerson) -- cn: Charlie Brown, departmentNumber: Security, employeeType: contractor
6. `dn: uid=diana,ou=users,dc=corp,dc=com` (inetOrgPerson) -- cn: Diana Prince, departmentNumber: Engineering, employeeType: vendor
7. `dn: uid=eve,ou=users,dc=corp,dc=com` (inetOrgPerson) -- cn: Eve Torres, mail: eve@partner.com, departmentNumber: External, employeeType: contractor

All users have `objectClass: inetOrgPerson` and fields: `cn`, `sn`, `mail`, `uid`, `userPassword`, `departmentNumber`, `employeeType`.

Note: 5 LDAP users (not 3) to demonstrate variety in `employeeType` (FTE, contractor, vendor) for the normalization layer. The same alice/bob/charlie exist in both Keycloak and LDAP -- this is intentional for cross-protocol identity correlation.

**Verify:** The file has no trailing whitespace issues and entries are properly separated by blank lines.

---

### Step 3: Add Keycloak and OpenLDAP to docker-compose.yml

**File:** `naas/docker-compose.yml`

Add two new services to the existing `docker-compose.yml` (which already has `postgres` and `redis` from chunk 0).

**Keycloak service** (from Spec 0, Section 5.1):
- `image: quay.io/keycloak/keycloak:26.0`
- `container_name: naas-keycloak`
- Environment: `KEYCLOAK_ADMIN` and `KEYCLOAK_ADMIN_PASSWORD` only. Do NOT add `KC_DB*` variables (uses built-in H2 dev database per Spec 0, Section 3.1 architect's note).
- `command: start-dev --import-realm`
- Port mapping: `"8080:8080"`
- Volume mount: `./infrastructure/keycloak/naas-realm-export.json:/opt/keycloak/data/import/naas-realm-export.json`
- `depends_on: postgres: condition: service_healthy`
- Network: `naas-network`
- Healthcheck: Use the TCP-based approach from the spec. Per Spec 0, Section 5.1, use `start_period: 60s`, `interval: 30s`, `timeout: 10s`, `retries: 15`. The test command:
  ```yaml
  test: ["CMD-SHELL", "exec 3<>/dev/tcp/localhost/8080 && echo -e 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && cat <&3 | grep -q '200\\|UP'"]
  ```
  **Fallback (per spec):** If this healthcheck causes `docker-compose up` to hang, replace with:
  ```yaml
  test: ["CMD-SHELL", "true"]
  start_period: 90s
  ```
  Do NOT spend more than 20 minutes debugging Keycloak healthchecks.

**OpenLDAP service** (from Spec 0, Section 5.1):
- `image: osixia/openldap:1.5.0`
- `container_name: naas-openldap`
- Environment: `LDAP_ORGANISATION`, `LDAP_DOMAIN`, `LDAP_ADMIN_PASSWORD` (all using `${VAR:-default}` syntax)
- Ports: `"389:389"` and `"636:636"`
- Volumes: `ldap-data:/var/lib/ldap`, `ldap-config:/etc/ldap/slapd.d`, and the bootstrap LDIF mount at `./infrastructure/openldap/bootstrap.ldif:/container/service/slapd/assets/config/bootstrap/ldif/custom/bootstrap.ldif`
- Network: `naas-network`
- Healthcheck: `ldapsearch` command with `interval: 15s`, `timeout: 5s`, `retries: 5`, `start_period: 15s` -- exact test from the spec.

**Also add to the `volumes` section:** `ldap-data:` and `ldap-config:`

**Verify:** `docker-compose config` validates without errors.

---

### Step 4: Start all infrastructure containers

**Commands:**
```bash
# Clean start (remove any stale volumes from chunk 0 testing)
docker-compose down -v

# Start all 4 infrastructure services
docker-compose up -d

# Watch logs to monitor startup (Keycloak takes 60-90s)
docker-compose logs -f keycloak &

# Wait and check health status
# Give Keycloak up to 2 minutes, then check:
docker-compose ps
```

**Expected:** All 4 containers running. Postgres and Redis should be "healthy" quickly. OpenLDAP should be "healthy" within 30s. Keycloak may show as "starting" for up to 90 seconds.

**If Keycloak healthcheck fails:** Check `docker-compose logs keycloak`. Common issues:
- If realm import fails, you will see error messages in the logs. Fix the JSON and rebuild: `docker-compose down -v && docker-compose up -d`
- If the healthcheck keeps failing but Keycloak is running, switch to the fallback healthcheck per Step 3 notes

---

### Step 5: Verify Keycloak OIDC discovery and token issuance

**Commands (from Spec 0, Section 6.4):**
```bash
# Test OIDC discovery endpoint
curl -s http://localhost:8080/realms/naas-demo/.well-known/openid-configuration | python3 -m json.tool

# Expected: JSON with authorization_endpoint, token_endpoint, jwks_uri, etc.
# If this returns 404, the realm import failed. Check docker-compose logs keycloak.
```

```bash
# Test token issuance (direct access grant with alice's credentials)
curl -s -X POST http://localhost:8080/realms/naas-demo/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "client_id=naas-dashboard" \
  -d "username=alice" \
  -d "password=password123" | python3 -m json.tool

# Expected: JSON with access_token, refresh_token, token_type, expires_in
# If this fails with 401, check user credentials in the realm JSON.
```

---

### Step 6: Verify OpenLDAP returns test users

**Commands (from Spec 0, Section 6.5):**
```bash
# Query alice specifically
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(uid=alice)"

# Expected: dn, cn, sn, mail, uid, departmentNumber, employeeType for alice
```

```bash
# Count all users
docker exec -it naas-openldap ldapsearch -x -H ldap://localhost \
  -b "ou=users,dc=corp,dc=com" \
  -D "cn=admin,dc=corp,dc=com" \
  -w admin \
  "(objectClass=inetOrgPerson)" dn | grep "numEntries"

# Expected: 5 entries
```

**If LDAP returns 0 entries:** The bootstrap LDIF likely failed. Common causes:
- Including the base DN entry (dc=corp,dc=com) which already exists
- Trailing whitespace in the LDIF file
- Wrong LDIF mount path

To debug: `docker-compose logs openldap` and look for "already exists" or "invalid syntax" errors. Fix the LDIF, then `docker-compose down -v && docker-compose up -d` (volumes must be removed to re-bootstrap).

---

## naas_shared Imports Needed

None for this chunk. The shared library does not exist yet.

---

## Done When

All of the following pass:

1. `docker-compose ps` shows all 4 containers running (postgres, redis, keycloak, openldap -- all "healthy" or "running")
2. PostgreSQL still works from chunk 0: `docker exec -it naas-postgres psql -U naas -d naas -c "\dt"` lists 5 tables
3. Redis still works from chunk 0: `docker exec -it naas-redis redis-cli ping` returns `PONG`
4. `curl -s http://localhost:8080/realms/naas-demo/.well-known/openid-configuration | python3 -m json.tool` returns valid OIDC discovery JSON
5. `curl -s -X POST http://localhost:8080/realms/naas-demo/protocol/openid-connect/token -d "grant_type=password" -d "client_id=naas-dashboard" -d "username=alice" -d "password=password123" | python3 -m json.tool` returns an access token
6. `docker exec -it naas-openldap ldapsearch -x -H ldap://localhost -b "dc=corp,dc=com" -D "cn=admin,dc=corp,dc=com" -w admin "(uid=alice)"` returns alice's entry with all attributes
7. LDAP user count query returns 5 entries
8. `docker-compose down -v` shuts down cleanly

---

## Next Chunk Preview

Chunk 2 creates the shared Python library (`shared/naas_shared/`) with all foundation modules: config, constants, models, database, redis_client, logging, and schemas placeholder. **Do NOT proceed to chunk 2 until all "Done When" criteria above are verified.**
