---
name: patterns-health-patch
description: How to wire /health handlers so test-level module patches on naas_shared.* are effective
metadata:
  type: project
---

When tests patch `naas_shared.database.get_db_session` and `naas_shared.redis_client.get_redis` at the module level (via `unittest.mock.patch`), the `/health` handler MUST access those symbols through the module object at call time — NOT through a locally-bound import name.

**Wrong (patch has no effect on locally-bound name):**
```python
from naas_shared.database import get_db_session  # binds at import time
async def health():
    async for session in get_db_session():  # uses old ref — patch misses this
        ...
```

**Correct (patch replaces module attribute, accessed at call time):**
```python
import naas_shared.database as _db_mod
import naas_shared.redis_client as _redis_mod

async def health():
    async for session in _db_mod.get_db_session():  # sees patched attribute
        ...
    client = await _redis_mod.get_redis()  # sees patched attribute
```

The key is that `_db_mod` IS `naas_shared.database` (same module object), so `_db_mod.get_db_session` reflects any patch applied to `naas_shared.database.get_db_session`.

This pattern also means the health route should NOT use `Depends(get_db_session)` — FastAPI stores the callable reference at `Depends(...)` call time (module import), so module-level patches applied later won't affect it.

**Why:** The NAAS health tests only use module-level patches (not `app.dependency_overrides`) for the health endpoint's DB/Redis checks. The ingest/bulk routes DO use `dependency_overrides[get_ingestion_service]`.
