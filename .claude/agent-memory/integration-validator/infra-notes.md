---
name: infra-notes
description: NAAS infrastructure stack startup behavior, container names, and the known Keycloak healthcheck discrepancy
metadata:
  type: project
---

# NAAS Infrastructure Notes (Spec 0)

## Container names
- naas-postgres (5432), naas-redis (6379), naas-keycloak (8080), naas-openldap (389/636)

## Keycloak healthcheck (FIXED — now reports healthy)
- Compose uses a bash /dev/tcp probe of /health/ready (no curl needed). It now
  correctly targets the **management port 9000** with `KC_HEALTH_ENABLED: "true"`
  set in the keycloak environment. With both in place the container transitions
  starting → healthy within ~60–120s of `up`.
- **Prior bug (history):** the probe targeted port 8080 and health was not
  enabled, so /health/ready 404'd and the container sat in "starting" forever
  while being fully functional. Misdiagnosed at the time as a missing-curl
  issue; the real cause was the missing flag + wrong port. Fixed in SPEC_0 §5.1.
- **How to apply:** the Keycloak healthcheck is now a valid readiness signal —
  it may be used for `service_healthy` gating. Still cross-check functionally
  via OIDC discovery + alice/password123 password grant as a secondary signal.
- Runs in dev mode (start-dev) with built-in H2 DB, no KC_DB vars. Logs a
  JDBC ResultSet leak WARN on import — benign in dev.

## Startup timings (first run, incl. image pulls)
- Postgres/Redis healthy in ~12s. Keycloak listening ~21s after its JVM start
  (~90s wall from compose up incl. import). OpenLDAP currently broken — see
  [[openldap-single-file-mount]].

## Realm/clients
- Realm: naas-demo. Public client: naas-dashboard (password grant works for
  user alice / password123).
