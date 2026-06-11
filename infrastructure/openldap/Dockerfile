# Custom OpenLDAP image: bakes the bootstrap LDIF into the osixia custom-bootstrap
# directory at build time instead of bind-mounting it at runtime.
#
# Why bake instead of bind-mount: the osixia entrypoint runs `chown -R` and `sed -i`
# over its assets tree on startup, and (by default) `rm -rf`s the bootstrap config
# after seeding. When the LDIF is bind-mounted, those operations reach back through
# the mount and mutate the host file (ownership flips to uid 911) or fail outright
# (`Device or resource busy`). Copying the file into the image keeps all of that
# confined to the container's own layer — the host file is never touched, and no
# osixia workaround env vars are needed.
#
# Trade-off: editing bootstrap.ldif requires a rebuild (`docker compose build openldap`
# or `docker compose up --build`) to take effect, not just a container restart.
FROM osixia/openldap:1.5.0

COPY bootstrap.ldif /container/service/slapd/assets/config/bootstrap/ldif/custom/bootstrap.ldif
# Reconfigure the built-in memberof overlay for groupOfNames/member via a custom
# bootstrap LDIF.  osixia processes *.ldif files in ldif/custom/ via
# ldap_add_or_modify() (uses "ldapmodify -Y EXTERNAL -H ldapi:///") which runs
# after the image-default overlay entry is created, so this modify lands cleanly.
# Placed as 00-memberof-overlay.ldif so it sorts BEFORE bootstrap.ldif alphabetically.
# osixia processes ldif/custom/ files via `find | sort`, so this modify runs first —
# the overlay is reconfigured for groupOfNames/member before the group entries are
# loaded, ensuring memberOf back-links are populated when groups are added.
COPY 00-memberof-overlay.ldif /container/service/slapd/assets/config/bootstrap/ldif/custom/00-memberof-overlay.ldif
