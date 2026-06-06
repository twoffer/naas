---
name: patterns_get_redis_mock_seam
description: Tests patch naas_shared.redis_client.get_redis with MagicMock(return_value=fake_redis); use inspect.isawaitable() to handle both real async and mock sync returns
metadata:
  type: feedback
---

When code calls `await _redis_module.get_redis()`, the chunk-4 LDAP adapter tests patch it with `MagicMock(return_value=fake_redis)` — a plain callable that returns `fake_redis` directly (not a coroutine).

**Why:** The health tests use a proper `async def _fake_get_redis()` function. The adapter unit tests use `MagicMock(return_value=fake_redis)` instead. Calling `MagicMock(return_value=fake_redis)()` returns `fake_redis` directly; awaiting `fake_redis` raises `TypeError: object AsyncMock can't be used in 'await' expression` (or similar for plain class instances).

**How to apply:** Use this pattern to obtain Redis in any adapter-level code that needs to be unit-testable with the MagicMock seam:

```python
redis_result = _redis_module.get_redis()
redis = await redis_result if inspect.isawaitable(redis_result) else redis_result
```

This handles both the real async `get_redis()` (returns a coroutine → awaitable) and the mock (returns `fake_redis` directly → not awaitable).

Import `inspect` at the top of the module (not lazily).

Related: [[patterns_health_patch]]
