---
name: patterns-osixia-memberof-overlay
description: osixia/openldap:1.5.0 has a built-in default memberof overlay for groupOfUniqueNames/uniqueMember; fix via numbered LDIF in ldif/custom/ that sorts before bootstrap data
metadata:
  type: project
---

osixia/openldap:1.5.0 ships with a built-in default `memberof` overlay at
`olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config` configured for `groupOfUniqueNames`/`uniqueMember`.

**The problem**: if bootstrap data uses `groupOfNames`/`member`, the overlay never fires and `memberOf` is never back-populated on user entries.

**The fix**: Add a LDIF file to `ldif/custom/` (baked into the Dockerfile) that uses `changetype: modify` + `replace:` to reconfigure `olcMemberOfGroupOC` and `olcMemberOfMemberAD`.

**Critical ordering**: Name the file `00-memberof-overlay.ldif` (or any name that sorts BEFORE `bootstrap.ldif` alphabetically). osixia's startup.sh processes `ldif/custom/*.ldif` via `find | sort`. The overlay must be reconfigured BEFORE the group entries are loaded, otherwise `memberOf` back-links are not populated (they only fire when groups are added while the overlay is active).

**Why it works**: The `ldap_add_or_modify()` function in osixia's `startup.sh` detects "changetype" and calls `ldapmodify -Y EXTERNAL -Q -H ldapi:///`. SASL EXTERNAL authenticates as `gidNumber=0+uidNumber=0,cn=peercred,cn=external,cn=auth` which has cn=config write access.

**Do NOT**: Try to use the `.sh` script path (osixia does not auto-execute scripts — only processes `*.ldif` files). Do NOT add a second overlay entry (causes collision). Do NOT forget the `00-` prefix (bootstrap.ldif runs first without it, leaving no memberOf links).

**Verification command**:
```
ldapsearch -x -H ldap://localhost -D "cn=admin,dc=corp,dc=com" -w admin -b "uid=alice,ou=users,dc=corp,dc=com" memberOf
```

Related: [[patterns_ldap_dn_no_native]]
