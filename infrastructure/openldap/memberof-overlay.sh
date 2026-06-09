#!/bin/sh
# memberof-overlay.sh
#
# Loads the memberof and refint modules into cn=config and configures the
# memberof overlay on the mdb (data) database so that LDAP user entries
# receive a reverse memberOf attribute for every group they belong to.
#
# This script runs during osixia/openldap container first-seed via the custom
# bootstrap directory. It targets cn=config over ldapi:// (the Unix socket)
# using SASL EXTERNAL, which is required because cn=config is not accessible
# via the main data DIT credentials.
#
# Idempotency: "already exists" errors on module load are suppressed with
# || true so the script succeeds on repeated runs. Exact olcOverlay ordinals
# ({0}memberof, {1}refint, etc.) vary by osixia build and are verified live
# by the integration validator — the ordinals below are the typical defaults.
#
# Picking up changes to this script requires an image rebuild and a fresh
# ldap-data volume: docker compose build openldap && docker compose down -v openldap && docker compose up -d openldap

set -e

# Wait briefly for slapd to be ready on the ldapi socket
sleep 2

# ---------------------------------------------------------------------------
# Step 1: Load the memberof and refint modules (tolerate "already exists")
# ---------------------------------------------------------------------------
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF || true
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: memberof
EOF

ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF || true
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: refint
EOF

# ---------------------------------------------------------------------------
# Step 2: Add the memberof overlay to the mdb database
# The olcOverlay DN ordinal ({0}memberof) is the typical first-overlay slot;
# the integration validator confirms the live ordinal on each deployment.
# ---------------------------------------------------------------------------
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF || true
dn: olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config
changetype: add
objectClass: olcOverlayConfig
objectClass: olcMemberOf
olcOverlay: memberof
olcMemberOfDangling: ignore
olcMemberOfRefInt: TRUE
olcMemberOfGroupOC: groupOfNames
olcMemberOfMemberAD: member
olcMemberOfMemberOfAD: memberOf
EOF

# ---------------------------------------------------------------------------
# Step 3: Add the refint overlay for referential integrity on member attribute
# ---------------------------------------------------------------------------
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF || true
dn: olcOverlay={1}refint,olcDatabase={1}mdb,cn=config
changetype: add
objectClass: olcOverlayConfig
objectClass: olcRefintConfig
olcOverlay: refint
olcRefintAttribute: member
EOF
