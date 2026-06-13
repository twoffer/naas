"""conftest.py for identity-normalization service tests.

Ensures that `app.*` modules resolve to the identity-normalization service
when tests in this directory run, regardless of which other service test
directories were collected first.

WHY this is needed: Both event-ingestion and identity-normalization services
ship a top-level package literally named `app`. In a full-suite run with
importlib mode, pytest assigns unique module names to test files, but the
test's own `from app.main import app` still resolves via sys.path. Python's
module cache retains the first-imported `app.main` for the remainder of the
session. This conftest clears and re-anchors the `app.*` namespace before
each test in this directory so the correct service module is always loaded.

The root collection shim (previously in conftest.py at repo root) is no longer
needed now that test directories use underscored names — importlib mode
handles same-basename files in sibling directories without collision.

Canonical fake factories (make_fake_ldap_module, inject_fake_ldap,
FakeRedis) are defined here once and imported by all test files in this
directory.  Each file may still locally override individual attributes of
the returned fake for test-specific specialization — the factories only set
up the shared baseline.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from tests.helpers import REPO_ROOT

# Production service dir stays hyphenated — only test dirs use underscores.
SERVICE_DIR = str(REPO_ROOT / "services" / "identity-normalization")
SHARED_DIR = str(REPO_ROOT / "shared")

# Insert at collection time so `from app.main import app` in test files
# resolves during module-level import (before any test runs).
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)
if SHARED_DIR not in sys.path:
    sys.path.insert(0, SHARED_DIR)


def pytest_runtest_setup(item) -> None:
    """Before each test, ensure app.* resolves to identity-normalization.

    Clears any cached `app` modules from a prior service's collection pass
    and ensures this service's directory is at the front of sys.path.
    """
    # Clear all cached `app.*` modules so Python re-imports from the correct path.
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]

    # Ensure this service dir is at the front of sys.path.
    if SERVICE_DIR in sys.path:
        sys.path.remove(SERVICE_DIR)
    sys.path.insert(0, SERVICE_DIR)

    if SHARED_DIR not in sys.path:
        sys.path.insert(0, SHARED_DIR)


# ===========================================================================
# Canonical fake-ldap factory
# ===========================================================================


def make_fake_ldap_module() -> MagicMock:
    """Build a fake 'ldap' MagicMock that mimics the minimal ldap API.

    Includes:
    - ldap.SCOPE_SUBTREE = 2
    - ldap.OPT_NETWORK_TIMEOUT, ldap.OPT_TIMEOUT constants
    - ldap.filter.escape_filter_chars — real RFC-4515 escaping (\\, *, (, ), NUL)
    - ldap.dn.str2dn — functional parser for simple and escaped-comma DNs
    - ldap.initialize(uri) → configurable fake connection
      (set_option, simple_bind_s, search_s, unbind_s)
    - Exception hierarchy: LDAPError, SERVER_DOWN, TIMEOUT, TIMELIMIT_EXCEEDED,
      NO_SUCH_OBJECT, OPERATIONS_ERROR — all real classes so except clauses work

    The connection's search results and raise-behaviour are configurable per test
    by mutating fake_ldap.initialize.return_value (or replacing search_s.side_effect).
    """
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2
    fake_ldap.OPT_NETWORK_TIMEOUT = 20
    fake_ldap.OPT_TIMEOUT = 30

    # Real exception classes so except/isinstance checks work correctly.
    class LDAPError(Exception):
        pass

    class SERVER_DOWN(LDAPError):
        pass

    class TIMEOUT(LDAPError):
        pass

    class TIMELIMIT_EXCEEDED(LDAPError):
        pass

    class NO_SUCH_OBJECT(LDAPError):
        pass

    class OPERATIONS_ERROR(LDAPError):
        pass

    fake_ldap.LDAPError = LDAPError
    fake_ldap.SERVER_DOWN = SERVER_DOWN
    fake_ldap.TIMEOUT = TIMEOUT
    fake_ldap.TIMELIMIT_EXCEEDED = TIMELIMIT_EXCEEDED
    fake_ldap.NO_SUCH_OBJECT = NO_SUCH_OBJECT
    fake_ldap.OPERATIONS_ERROR = OPERATIONS_ERROR

    # ldap.filter sub-module — real RFC-4515 escaping so injection tests are meaningful.
    fake_filter = MagicMock(name="ldap.filter")

    def _real_escape_filter_chars(value: str) -> str:
        """Escape RFC-4515 special characters: \\ * ( ) NUL."""
        result = []
        for ch in value:
            if ch == "\\":
                result.append("\\5c")
            elif ch == "*":
                result.append("\\2a")
            elif ch == "(":
                result.append("\\28")
            elif ch == ")":
                result.append("\\29")
            elif ch == "\x00":
                result.append("\\00")
            else:
                result.append(ch)
        return "".join(result)

    fake_filter.escape_filter_chars = MagicMock(side_effect=_real_escape_filter_chars)
    fake_ldap.filter = fake_filter

    # ldap.dn sub-module — functional str2dn for simple and escaped-comma DNs.
    fake_dn = MagicMock(name="ldap.dn")

    def _fake_str2dn(dn_str: str):
        """Minimal RFC-4514 str2dn that handles simple and escaped-comma DNs.

        Returns list of RDN lists: [[(attr, value, flags), ...], ...]
        Compatible with the format the production code expects.
        """
        rdns = []
        current: list[str] = []
        i = 0
        while i < len(dn_str):
            ch = dn_str[i]
            if ch == "\\" and i + 1 < len(dn_str):
                current.append(dn_str[i + 1])
                i += 2
            elif ch == ",":
                rdns.append("".join(current).strip())
                current = []
                i += 1
            else:
                current.append(ch)
                i += 1
        if current:
            rdns.append("".join(current).strip())

        result = []
        for rdn_str in rdns:
            if "=" in rdn_str:
                attr, _, value = rdn_str.partition("=")
                result.append([(attr.strip(), value.strip(), 1)])
            else:
                result.append([(rdn_str, rdn_str, 1)])
        return result

    fake_dn.str2dn = MagicMock(side_effect=_fake_str2dn)
    fake_ldap.dn = fake_dn

    # Default connection: binds OK, search returns empty (overrideable per test).
    conn_mock = MagicMock(name="ldap_connection")
    conn_mock.simple_bind_s = MagicMock(return_value=None)
    conn_mock.search_s = MagicMock(return_value=[])
    conn_mock.unbind_s = MagicMock(return_value=None)
    conn_mock.set_option = MagicMock(return_value=None)
    fake_ldap.initialize = MagicMock(return_value=conn_mock)

    return fake_ldap


def inject_fake_ldap(monkeypatch) -> MagicMock:
    """Inject the canonical fake ldap into sys.modules and clear cached adapter.

    Must be called before importing app.adapters.ldap (or after clearing it)
    so the adapter module re-imports with the fake in place.

    Returns the top-level fake for per-test customization.
    """
    fake_ldap = make_fake_ldap_module()
    monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap.dn)
    for key in list(sys.modules.keys()):
        if key in ("app.adapters.ldap", "app.adapters"):
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake_ldap


# ===========================================================================
# Canonical fake Redis client
# ===========================================================================


class FakeRedis:
    """Fake async Redis client recording get/setex/set/delete calls and TTLs.

    Attributes:
        get_return:  What redis.get() returns per call (constant value).
        get_calls:   Keys passed to get(), in call order.
        set_calls:   Dicts with "key", "ttl", "value" for each setex/set call.
        delete_calls: Keys passed to delete(), in call order.
        xack_calls:  Positional-arg tuples passed to xack(), in call order.
    """

    def __init__(self, get_return=None):
        self._get_return = get_return
        self.get_calls: list = []
        self.set_calls: list = []
        self.delete_calls: list = []
        self.xack_calls: list = []

    async def get(self, key: str):
        self.get_calls.append(key)
        return self._get_return

    async def setex(self, key: str, ttl: int, value):
        self.set_calls.append({"key": key, "ttl": ttl, "value": value})

    async def set(self, key: str, value, ex=None):
        self.set_calls.append({"key": key, "ttl": ex, "value": value})

    async def delete(self, key: str):
        self.delete_calls.append(key)

    async def xack(self, stream: str, group: str, *msg_ids):
        self.xack_calls.append((stream, group, *msg_ids))
