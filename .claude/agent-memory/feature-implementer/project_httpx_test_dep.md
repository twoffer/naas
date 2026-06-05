---
name: project-httpx-test-dep
description: httpx is required by starlette.testclient but not in venv by default; install it when TestClient tests fail with ModuleNotFoundError
metadata:
  type: project
---

`starlette.testclient.TestClient` requires `httpx` (or `httpx2`). The project venv did not have it installed when Chunk 1 was implemented. Running `pip install httpx` in the venv fixed the 5 TestClient-based health endpoint tests.

**Why:** The tests use `from starlette.testclient import TestClient` which imports `httpx` at import time. Without it, all TestClient tests fail with `RuntimeError: The starlette.testclient module requires the httpx2 package`.

**How to apply:** If skeleton or route tests fail with `ModuleNotFoundError: No module named 'httpx'` or `RuntimeError: starlette.testclient requires httpx2`, run `pip install httpx` in the project venv before diagnosing further.
