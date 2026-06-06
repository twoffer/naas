---
name: patterns_fastapi_oauth2_redirect
description: FastAPI adds /docs/oauth2-redirect route by default; suppress it with swagger_ui_oauth2_redirect_url=None
metadata:
  type: feedback
---

FastAPI's default configuration adds a `/docs/oauth2-redirect` route automatically as part of the Swagger UI OAuth2 flow. This route is NOT in the standard set of acceptable paths (`/health`, `/docs`, `/redoc`, `/openapi.json`). Tests that assert "only /health is exposed" (chunk 1 scope boundary tests) will fail because of this hidden route.

**Fix:** Pass `swagger_ui_oauth2_redirect_url=None` to the `FastAPI()` constructor:
```python
application = FastAPI(
    title="identity-normalization",
    version="2.0.0",
    lifespan=lifespan,
    swagger_ui_oauth2_redirect_url=None,
)
```

This suppresses the oauth2-redirect route without disabling `/docs` or `/redoc`.

**Why:** The test suite for each service's chunk 1 checks that ONLY /health is registered (plus FastAPI built-ins). The oauth2-redirect route appears even with no OAuth2 flows defined. Setting it to None removes it from the route table.

**How to apply:** Every new service that has a "only /health in chunk 1" test should use this pattern in `create_app()`.
