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
COPY memberof-overlay.sh /container/service/slapd/assets/config/bootstrap/memberof-overlay.sh
