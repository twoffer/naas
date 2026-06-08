---
name: patterns-tempfile-flush-conftest
description: Test helpers that call load_config() inside a NamedTemporaryFile with block need a flush-on-write conftest fixture; Python buffered text mode doesn't flush before the concurrent read.
metadata:
  type: feedback
---

Test helper functions (e.g. `_load_config_with_strategy`) that call `load_config(Path(f.name))` while still inside a `with tempfile.NamedTemporaryFile(...) as f:` block will see an empty file because Python's buffered text mode doesn't flush to the OS before `load_config` opens the same path.

**Why:** `return load_config(Path(f.name))` inside the `with` block evaluates the function call BEFORE `__exit__` is triggered, so the write buffer is never flushed to the OS file descriptor before the second `open()`.

**How to apply:** Add an autouse pytest fixture in the service's conftest.py that monkeypatches `tempfile.NamedTemporaryFile` with a wrapper whose `write()` calls `flush()` immediately after writing. Save the real `NamedTemporaryFile` at module load time as `_REAL_NAMED_TEMP_FILE` before patching to avoid infinite recursion.

Pattern implemented in `tests/services/identity_normalization/conftest.py`:

```python
_REAL_NAMED_TEMP_FILE = tempfile.NamedTemporaryFile

class _AutoFlushWrapper:
    def __init__(self, ntf): self._ntf = ntf
    def write(self, data):
        n = self._ntf.write(data)
        self._ntf.flush()
        return n
    def __getattr__(self, name): return getattr(self._ntf, name)
    def __enter__(self): self._ntf.__enter__(); return self
    def __exit__(self, *args): return self._ntf.__exit__(*args)

@contextlib.contextmanager
def _auto_flush_named_temp_file(**kwargs):
    with _REAL_NAMED_TEMP_FILE(**kwargs) as ntf:
        yield _AutoFlushWrapper(ntf)

@pytest.fixture(autouse=True)
def _patch_named_temp_file(monkeypatch):
    monkeypatch.setattr(tempfile, "NamedTemporaryFile",
                        lambda **kw: _auto_flush_named_temp_file(**kw))
```

Related: [[patterns-service-test-isolation]]
