---
name: patterns-health-session-factory
description: /health tests must patch get_session_factory (not get_db_session) when the handler uses factory()-as-async-CM pattern
metadata:
  type: feedback
---

After switching the /health handler from the async-generator `get_db_session` pattern to `get_session_factory()` + `async with factory() as session`, all test fixtures that patch the DB seam must be updated to patch `naas_shared.database.get_session_factory` instead of `naas_shared.database.get_db_session`.

The correct fake factory pattern:

```python
from contextlib import asynccontextmanager
from unittest.mock import patch

@asynccontextmanager
async def _fake_session_cm():
    yield mock_session

def _fake_get_session_factory():
    return _fake_session_cm

with patch("naas_shared.database.get_session_factory", new=_fake_get_session_factory):
    ...
```

**Why:** The health handler does `factory = _db_mod.get_session_factory(); async with factory() as session: await session.execute(...)`. Patching `get_db_session` at the module level no longer has any effect because the handler never calls it.

**How to apply:** Any test file that patches `naas_shared.database.get_db_session` for the /health endpoint must be migrated to patch `get_session_factory` with a callable returning an async context manager. Affected files at migration time: test_health.py, test_app_skeleton.py. [[patterns_health_patch]]
