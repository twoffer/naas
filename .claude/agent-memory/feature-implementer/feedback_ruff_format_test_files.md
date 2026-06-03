---
name: feedback_ruff_format_test_files
description: ruff format --check can fail even when ruff check passes; must run both and fix both
metadata:
  type: feedback
---

Run `ruff check` AND `ruff format --check` on every Python file in scope. They are independent checks.

**Why:** `ruff check` catches lint errors (unused imports, etc.). `ruff format --check` catches formatting issues (blank lines, spacing around class/function definitions). A file can pass one and fail the other.

**How to apply:** After fixing any lint issues flagged by `ruff check`, always follow with `ruff format <file>` if `ruff format --check` shows the file would be reformatted. Both must be clean before declaring a Python file done.
