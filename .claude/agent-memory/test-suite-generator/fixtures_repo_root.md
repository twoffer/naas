---
name: fixtures-repo-root
description: Robust repo-root discovery pattern for filesystem tests — walks up from __file__ looking for docs/architecture/
metadata:
  type: project
---

For filesystem/scaffold tests, never hardcode an absolute path. Use this pattern
to locate the repo root robustly (works in CI and across developer machines):

```python
def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError("Could not locate repo root")

REPO_ROOT = _find_repo_root()
```

The sentinel `docs/architecture/` is reliable because it is checked into the
repo at commit 8a6078a and will persist for all downstream specs.

**Why:** Absolute paths break in CI and on other developer machines.
**How to apply:** Use this in every spec_N test file that makes filesystem assertions.
