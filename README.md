# naas
Normalized Adaptive Access System — Enterprise IAM modernization platform bridging legacy LDAP, SAML, and modern OIDC with unified risk-based access control. Normalize once. Secure everywhere. Shadow mode testing + real-time protocol visualization.

## Quick start

```bash
docker compose up -d --build
docker compose ps
```

> The `--build` flag is required the first time, and after any change to
> `infrastructure/openldap/` (the `openldap` service runs a locally-built image that
> bakes in `bootstrap.ldif`). A plain `docker compose up -d` is fine otherwise.

For full architectural context, see [docs/architecture/SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md).
