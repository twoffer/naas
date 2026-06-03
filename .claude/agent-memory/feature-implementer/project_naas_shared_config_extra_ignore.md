---
name: project-naas-shared-config-extra-ignore
description: Settings class in naas_shared/config.py requires extra="ignore" because the repo .env file contains vars not declared in the model
metadata:
  type: project
---

The repo root `.env` file (committed by Chunk 1) contains env vars like `KEYCLOAK_ADMIN`, `LDAP_ORGANISATION`, `LDAP_DOMAIN`, `LDAP_POOL_SIZE`, etc. that are NOT fields in the `Settings` class. pydantic-settings v2 raises `ValidationError: Extra inputs are not permitted` by default when it reads these from `.env`.

**Fix:** Add `extra = "ignore"` to the inner `Config` class in `Settings`. The spec snippet omits this because it was written for a containerized context where only declared vars are present.

**How to apply:** Any time `Settings(BaseSettings)` is added to or modified in config.py, include `extra = "ignore"` in the Config. Without it, `get_settings()` will fail whenever the `.env` file is present.
