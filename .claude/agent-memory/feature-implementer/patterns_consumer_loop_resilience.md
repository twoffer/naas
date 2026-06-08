---
name: patterns_consumer_loop_resilience
description: consumer.py xreadgroup outer loop must catch Exception (not CancelledError) for resilience; error string truncated to 200 chars at log site for PII safety
metadata:
  type: feedback
---

`run_consumer_loop` in `consumer.py`:
- The `await redis.xreadgroup(...)` call must be wrapped in `try/except Exception` (which in Python 3.8+ does NOT catch `CancelledError`) so transient network errors don't kill the consumer process.
- On exception: log with truncated error string (`str(exc)[:200]`), `await asyncio.sleep(_EMPTY_BATCH_SLEEP_S)`, `continue`.
- `CancelledError` propagates naturally because `except Exception` in Python 3.8+ does not catch it.
- In `_process_message`, log `str(exc)[:200]` not `str(exc)` — Pydantic ValidationErrors include the full input_value which may contain PII.

**Why:** CancelledError is the task-cancellation signal for clean shutdown. If it were caught, shutdown would hang. Exception not catching it is a Python 3.8+ guarantee. Error truncation prevents PII leakage via SIEM log aggregators.

**How to apply:** Copy this pattern whenever writing any Redis-consumer loop in this project.
