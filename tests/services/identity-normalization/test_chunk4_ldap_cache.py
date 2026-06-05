# Component: NAAS Spec 2 — Chunk 4: LdapAdapter.enrich() — Three-state Redis cache
# Mode: TDD — all tests MUST fail until the full enrich() implementation is in place
#
# What these tests validate:
#   9. THREE-STATE Redis cache mechanics (spec §5.3 — ⚠️ headline behavior):
#      - MISS (GET returns None) → queries LDAP
#      - NEGATIVE HIT (GET returns JSON string "null") → skips LDAP query
#      - POSITIVE HIT (GET returns JSON attr object) → returns cached dict, skips LDAP
#      - Cache key format: f"{LDAP_ENRICHMENT_CACHE_PREFIX}{correlation_value}"
#      - Positive AND negative results are cached with the configured TTL
#      - Transient failures (timeout, connection error, search error) are NOT cached
#        (assert no Redis SET is called after a simulated transient failure)
#
# WHY the three-state cache is critical:
#   Without a NEGATIVE cache, every OIDC/SAML login for a user not in LDAP
#   (test/external users) would hammer the directory on every single login.
#   Under burst load (e.g., 1000 concurrent logins by non-directory users),
#   this would DDoS the LDAP server and cause all enrichment to time out,
#   cascading to enrichment failures for real directory users too.
#
#   Caching transient errors would be WRONG: a network blip would permanently
#   mark a real directory user as "no match" for 60 seconds, preventing their
#   attributes from being enriched until the TTL expires. The adapter must
#   only cache stable states (confirmed match / confirmed no-match).
#
# Mock strategy:
#   Same fake-ldap injection and fake-Redis pattern as test_chunk4_ldap_enrich.py.
#   Redis get/set calls are recorded for assertion.

# stdlib
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not locate repo root. Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"
SERVICE_DIR = REPO_ROOT / "services" / "identity-normalization"

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from test_chunk4_ldap_enrich.py for module isolation)
# ---------------------------------------------------------------------------


def _make_fake_ldap_module() -> MagicMock:
    """Build a minimal fake ldap module."""
    fake_ldap = MagicMock(name="ldap")
    fake_ldap.SCOPE_SUBTREE = 2

    class LDAPError(Exception):
        pass

    class TIMEOUT_EXCEEDED(LDAPError):
        pass

    class SERVER_DOWN(LDAPError):
        pass

    class NO_SUCH_OBJECT(LDAPError):
        pass

    class OPERATIONS_ERROR(LDAPError):
        pass

    fake_ldap.LDAPError = LDAPError
    fake_ldap.TIMEOUT_EXCEEDED = TIMEOUT_EXCEEDED
    fake_ldap.SERVER_DOWN = SERVER_DOWN
    fake_ldap.NO_SUCH_OBJECT = NO_SUCH_OBJECT
    fake_ldap.OPERATIONS_ERROR = OPERATIONS_ERROR

    fake_filter = MagicMock(name="ldap.filter")
    fake_filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
    fake_ldap.filter = fake_filter

    fake_dn = MagicMock(name="ldap.dn")
    fake_ldap.dn = fake_dn

    return fake_ldap


def _inject_fake_ldap(monkeypatch) -> MagicMock:
    """Inject fake ldap into sys.modules and clear cached app.adapters.ldap."""
    fake_ldap = _make_fake_ldap_module()
    monkeypatch.setitem(sys.modules, "ldap", fake_ldap)
    monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap.filter)
    monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap.dn)
    for key in list(sys.modules.keys()):
        if key == "app.adapters.ldap" or key == "app.adapters":
            monkeypatch.delitem(sys.modules, key, raising=False)
    return fake_ldap


def _make_ldap_result(
    cn: str = "Alice Smith",
    mail: str = "alice@corp.com",
    dept: str = "Engineering",
    employee_type: str = "FTE",
) -> list:
    """Build a fake LDAP search result with bytes-encoded values."""
    dn = "uid=alice,ou=users,dc=corp,dc=com"
    attrs = {
        "cn": [cn.encode("utf-8")],
        "mail": [mail.encode("utf-8")],
        "departmentNumber": [dept.encode("utf-8")],
        "employeeType": [employee_type.encode("utf-8")],
    }
    return [(dn, attrs)]


class _FakeRedis:
    """Fake async Redis client that records get/set/setex calls."""

    def __init__(self, get_return=None):
        self._get_return = get_return
        self.get_calls: list = []
        self.set_calls: list = []  # records (key, value, ttl) tuples

    async def get(self, key: str):
        self.get_calls.append(key)
        return self._get_return

    async def setex(self, key: str, ttl: int, value):
        self.set_calls.append({"key": key, "ttl": ttl, "value": value})

    async def set(self, key: str, value, ex=None):
        self.set_calls.append({"key": key, "ttl": ex, "value": value})


# ===========================================================================
# CLASS 1 — Cache MISS (key absent) → queries LDAP
# ===========================================================================


class TestCacheMiss:
    """On a cache miss (GET returns None), enrich() must query LDAP.

    WHY: The cache miss is the initial state for every first-time login. Without
    querying LDAP on miss, enrichment would never work for any user until a
    previous cache entry exists — i.e., never.
    """

    def test_cache_miss_triggers_ldap_search(self, monkeypatch) -> None:
        """When Redis GET returns None, enrich() must call LDAP search_s.

        TDD: fails until enrich() checks cache first and falls through on miss.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)  # None = cache miss
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert conn_mock.search_s.called, (
            "On Redis cache miss (GET returns None), enrich() must call LDAP search_s. "
            "The LDAP query was not made."
        )

    def test_cache_miss_queries_redis_before_ldap(self, monkeypatch) -> None:
        """Redis GET must be called before the LDAP search on a cache miss.

        WHY: If LDAP is queried first (before checking cache), the cache is
        pointless — it would be populated but never read before a fresh query.
        The correct order is: GET → (on miss) LDAP → SET.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        call_order: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=lambda *a, **kw: (call_order.append("ldap_search"), [])[-1]
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        class OrderRecordingRedis(_FakeRedis):
            async def get(self, key):
                call_order.append("redis_get")
                return None

        fake_redis = OrderRecordingRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert "redis_get" in call_order, "Redis GET must be called"
        assert "ldap_search" in call_order, "LDAP search must be called on miss"

        redis_idx = call_order.index("redis_get")
        ldap_idx = call_order.index("ldap_search")
        assert redis_idx < ldap_idx, (
            f"Redis GET (index {redis_idx}) must happen BEFORE LDAP search "
            f"(index {ldap_idx}). call_order: {call_order}"
        )


# ===========================================================================
# CLASS 2 — NEGATIVE HIT (sentinel "null") → skips LDAP
# ===========================================================================


class TestCacheNegativeHit:
    """A negative cache entry (sentinel) must suppress the LDAP query.

    The sentinel value is the JSON string "null" stored as bytes in Redis.
    WHY: Repeated logins by a user not in LDAP (e.g., an external test account)
    would hammer the LDAP server on every login without a negative cache.
    The negative cache TTL (same as positive TTL) provides a grace period
    where the directory is queried at most once per TTL window per user.
    """

    NEGATIVE_SENTINEL = b'"null"'  # JSON string "null" stored as bytes

    def test_negative_cache_hit_skips_ldap_search(self, monkeypatch) -> None:
        """When Redis GET returns the negative sentinel, search_s must NOT be called.

        TDD: fails until enrich() recognises b'"null"' as a negative hit.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=self.NEGATIVE_SENTINEL)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "unknown@corp.com")
        )

        assert not conn_mock.search_s.called, (
            "enrich() must NOT call LDAP search_s when the negative sentinel is in cache. "
            f"Redis returned {self.NEGATIVE_SENTINEL!r} (negative hit) but LDAP was queried."
        )

    def test_negative_cache_hit_returns_none(self, monkeypatch) -> None:
        """A negative cache hit must return None (same as a live no-match).

        WHY: The caller (chunk 6) treats None as 'no directory match' and maps it
        to EnrichmentSkipped(skip_reason='no_ldap_match'). Both live no-match and
        negative cache hit must produce the same observable result.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=self.NEGATIVE_SENTINEL)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "unknown@corp.com")
        )

        assert attrs is None, (
            f"Negative cache hit must return attrs=None, got {attrs!r}"
        )
        assert outcome == "cache_hit_negative", (
            f"Negative cache hit must return outcome='cache_hit_negative', got {outcome!r}"
        )

    def test_second_lookup_for_absent_user_does_not_query_ldap_again(
        self, monkeypatch
    ) -> None:
        """Two successive calls for the same absent user must produce only one LDAP query.

        WHY: This is the core value proposition of the negative cache. The first call
        queries LDAP (miss → empty result → stores sentinel). The second call finds
        the sentinel and returns None without querying. This test verifies the property
        by simulating the full miss→store→hit cycle across two enrich() calls.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        # Simulate stateful Redis: first GET→None (miss); after SET, second GET→sentinel
        redis_store: dict = {}

        class StatefulRedis:
            async def get(self, key: str):
                return redis_store.get(key)

            async def setex(self, key: str, ttl: int, value):
                redis_store[key] = value

            async def set(self, key: str, value, ex=None):
                redis_store[key] = value

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])  # no match
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=StatefulRedis()),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()

        # First call — must query LDAP (cache miss) and store sentinel
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "ghost@corp.com")
        )

        # Second call — must use cached sentinel and NOT query LDAP again
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "ghost@corp.com")
        )

        assert conn_mock.search_s.call_count == 1, (
            f"Two successive calls for the same absent user must produce exactly "
            f"1 LDAP search (second uses negative cache). "
            f"Got {conn_mock.search_s.call_count} searches."
        )


# ===========================================================================
# CLASS 3 — POSITIVE HIT (cached attributes) → returns cached dict, skips LDAP
# ===========================================================================


class TestCachePositiveHit:
    """A positive cache entry (JSON attr object) must return the cached dict.

    WHY: Repeated logins for the same real directory user should not require
    a round-trip to LDAP on every login. The 60-second TTL (or configured value)
    provides a window where LDAP is queried at most once per user. This is
    critical for performance under burst load.
    """

    def _make_cached_attrs(self) -> bytes:
        """Build a fake positive cache entry (bytes-encoded JSON unified dict)."""
        cached = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": [],
        }
        return json.dumps(cached).encode("utf-8")

    def test_positive_cache_hit_skips_ldap_search(self, monkeypatch) -> None:
        """When Redis GET returns a JSON attr object, search_s must NOT be called.

        TDD: fails until enrich() recognises a JSON dict as a positive hit.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=self._make_cached_attrs())
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert not conn_mock.search_s.called, (
            "enrich() must NOT call LDAP search_s on a positive cache hit. "
            "The cached JSON dict should be returned directly."
        )

    def test_positive_cache_hit_returns_dict(self, monkeypatch) -> None:
        """A positive cache hit must return a unified-schema dict.

        WHY: The caller expects a dict (same as a live LDAP match). Returning None
        on a positive cache hit would cause all cached users to be processed as
        no-match, silently defeating the cache.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=self._make_cached_attrs())
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is not None, (
            "Positive cache hit must return a dict, got attrs=None"
        )
        assert isinstance(attrs, dict), (
            f"Positive cache hit must return dict, got {type(attrs).__name__!r}"
        )
        assert outcome == "cache_hit_positive", (
            f"Positive cache hit must return outcome='cache_hit_positive', got {outcome!r}"
        )

    def test_positive_cache_hit_preserves_cached_values(self, monkeypatch) -> None:
        """The returned dict must contain the values from the cache entry.

        WHY: If the adapter re-queries LDAP (ignoring cache) or returns a partially
        constructed dict, the cached values are lost. The enriched display_name must
        match what was stored in cache.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        conn_mock = MagicMock()
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        cached_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": [],
        }
        fake_redis = _FakeRedis(get_return=json.dumps(cached_attrs).encode("utf-8"))
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert attrs is not None
        assert attrs.get("display_name") == "Alice Smith", (
            f"Positive cache hit must return cached display_name 'Alice Smith', "
            f"got {attrs.get('display_name')!r}"
        )
        assert attrs.get("department") == "Engineering", (
            f"Positive cache hit must return cached department 'Engineering', "
            f"got {attrs.get('department')!r}"
        )


# ===========================================================================
# CLASS 4 — Cache key format
# ===========================================================================


class TestCacheKeyFormat:
    """The Redis cache key must use the LDAP_ENRICHMENT_CACHE_PREFIX.

    WHY: The cache key format is the contract between enrich() and any tooling
    (cache inspection, invalidation scripts) that reads or writes enrichment
    cache entries. A wrong prefix → cache entries are stored in the wrong
    keyspace and GET calls miss even when data is present (silent miss on every
    lookup for users who have been queried before).
    """

    def test_cache_get_uses_correct_key_prefix(self, monkeypatch) -> None:
        """Redis GET must be called with key starting with 'ldap_enrichment:'.

        TDD: fails until enrich() uses LDAP_ENRICHMENT_CACHE_PREFIX for key construction.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.get_calls) >= 1, (
            "enrich() must call Redis GET at least once"
        )
        key_used = fake_redis.get_calls[0]
        assert key_used.startswith("ldap_enrichment:"), (
            f"Redis GET key must start with 'ldap_enrichment:' "
            f"(LDAP_ENRICHMENT_CACHE_PREFIX). Got: {key_used!r}"
        )

    def test_cache_key_includes_lookup_value(self, monkeypatch) -> None:
        """Redis GET key must include the correlation_value as suffix.

        WHY: Key = prefix + correlation_value (§5.3). Without the value in the
        key, all users would share the same cache entry — the first user's result
        would be returned for every subsequent user. Critical correctness bug.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        lookup_value = "bob@corp.com"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", lookup_value)
        )

        assert len(fake_redis.get_calls) >= 1
        key_used = fake_redis.get_calls[0]
        assert lookup_value in key_used, (
            f"Redis key must contain the lookup value '{lookup_value}'. "
            f"Got key: {key_used!r}. "
            f"Expected: 'ldap_enrichment:{lookup_value}'"
        )

    def test_cache_key_exact_format(self, monkeypatch) -> None:
        """Redis GET key must be exactly 'ldap_enrichment:<lookup_value>'.

        WHY: Any extra characters (e.g., ':email:', double prefix) would cause
        cache misses even when data is present.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        lookup_value = "alice@corp.com"
        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", lookup_value)
        )

        assert len(fake_redis.get_calls) >= 1
        key_used = fake_redis.get_calls[0]
        expected_key = f"ldap_enrichment:{lookup_value}"
        assert key_used == expected_key, (
            f"Redis GET key must be exactly {expected_key!r}, got {key_used!r}"
        )


# ===========================================================================
# CLASS 5 — Cache writes (positive and negative stored with TTL)
# ===========================================================================


class TestCacheWrites:
    """enrich() must write both positive and negative results to Redis with TTL.

    WHY: Without writing, every call is a cache miss → every login queries LDAP
    directly. The TTL ensures stale cache entries expire (users added/removed from
    LDAP are reflected after at most cache_ttl_seconds).
    """

    def test_positive_match_is_written_to_cache_with_ttl(self, monkeypatch) -> None:
        """A successful LDAP match must be stored in Redis with a non-zero TTL.

        TDD: fails until enrich() calls setex/set with ex= after a successful match.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=[
                (
                    "uid=alice,ou=users,dc=corp,dc=com",
                    {
                        "cn": [b"Alice Smith"],
                        "mail": [b"alice@corp.com"],
                        "departmentNumber": [b"Engineering"],
                        "employeeType": [b"FTE"],
                    },
                )
            ]
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)  # cache miss
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.set_calls) >= 1, (
            "A positive LDAP match must write to Redis cache (setex/set with TTL). "
            "No cache write was recorded."
        )

        # The stored value must be a JSON-serializable dict (not raw bytes)
        set_call = fake_redis.set_calls[0]
        assert set_call["ttl"] is not None and set_call["ttl"] > 0, (
            f"Cache write for positive match must have a positive TTL. "
            f"Got TTL: {set_call['ttl']!r}"
        )
        assert "ldap_enrichment:alice@corp.com" == set_call["key"], (
            f"Cache key for positive match must be 'ldap_enrichment:alice@corp.com', "
            f"got {set_call['key']!r}"
        )

    def test_negative_match_sentinel_is_written_to_cache_with_ttl(
        self, monkeypatch
    ) -> None:
        """A no-match LDAP result must store the negative sentinel in Redis.

        WHY: Without writing the sentinel, every subsequent login for this absent
        user would query LDAP (cache miss every time). The sentinel (JSON "null")
        tells the cache layer "this user was confirmed absent — return None fast".
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])  # no match
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)  # cache miss → hits LDAP → no match
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "ghost@corp.com")
        )

        assert len(fake_redis.set_calls) >= 1, (
            "A no-match LDAP result must write the negative sentinel to Redis cache. "
            "No cache write was recorded."
        )

        set_call = fake_redis.set_calls[0]
        assert set_call["ttl"] is not None and set_call["ttl"] > 0, (
            f"Cache write for negative match must have a positive TTL. "
            f"Got TTL: {set_call['ttl']!r}"
        )

        # Sentinel must be "null" (JSON representation of Python None)
        stored_value = set_call["value"]
        if isinstance(stored_value, bytes):
            stored_value = stored_value.decode("utf-8")
        assert stored_value == '"null"' or stored_value == "null", (
            f"Negative cache sentinel must be the JSON string '\"null\"' or 'null'. "
            f"Got: {stored_value!r}"
        )

    def test_positive_write_uses_json_serializable_value(self, monkeypatch) -> None:
        """The cached positive value must be JSON-serializable (not raw bytes).

        WHY: Redis stores string-like values. Storing a Python dict directly would
        fail or produce unusable cache entries. The adapter must json.dumps() the
        unified dict before writing, and json.loads() it on read.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=[
                (
                    "uid=alice,ou=users,dc=corp,dc=com",
                    {
                        "cn": [b"Alice Smith"],
                        "mail": [b"alice@corp.com"],
                        "departmentNumber": [b"Engineering"],
                        "employeeType": [b"FTE"],
                    },
                )
            ]
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.set_calls) >= 1
        stored_value = fake_redis.set_calls[0]["value"]

        # Must be bytes or str (not dict), and must be valid JSON
        if isinstance(stored_value, bytes):
            stored_value = stored_value.decode("utf-8")

        assert isinstance(stored_value, str), (
            f"Cached value must be a JSON string (str or bytes-of-JSON), "
            f"got {type(stored_value).__name__!r}: {stored_value!r}"
        )
        try:
            parsed = json.loads(stored_value)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"Cached value must be valid JSON. Got: {stored_value!r}. Error: {exc}"
            )

        assert isinstance(parsed, dict), (
            f"Parsed cached value must be a dict, got {type(parsed).__name__!r}"
        )


# ===========================================================================
# CLASS 6 — Transient failures are NOT cached
# ===========================================================================


class TestTransientFailureNotCached:
    """Transient LDAP failures must NOT write to the Redis cache.

    WHY (spec §5.3): "Transient failures (timeout / connection error / search error)
    are NOT negative-cached, so the service recovers automatically when LDAP returns."

    If a transient error were cached as a negative sentinel, a brief LDAP outage
    (even 1 second) would cause all users who logged in during that window to be
    treated as absent for the full cache TTL (60 seconds). When LDAP recovers,
    their enrichment would still fail until the cached negative sentinel expires.
    This is unacceptable for a system that claims graceful degradation.
    """

    def test_ldap_connection_error_does_not_write_to_cache(self, monkeypatch) -> None:
        """SERVER_DOWN error must not write any sentinel to Redis.

        TDD: fails until enrich() correctly skips the cache-write on connection errors.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(
            side_effect=fake_ldap.SERVER_DOWN("connection refused")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.set_calls) == 0, (
            f"A SERVER_DOWN (connection error) must NOT write to Redis cache. "
            f"Got {len(fake_redis.set_calls)} write(s): {fake_redis.set_calls}. "
            f"Caching transient errors would prevent recovery when LDAP comes back."
        )

    def test_ldap_timeout_does_not_write_to_cache(self, monkeypatch) -> None:
        """TIMEOUT_EXCEEDED error must not write any sentinel to Redis.

        WHY: A timeout is transient (network congestion, LDAP load spike). Caching
        the timeout result would prevent successful enrichment for 60 seconds after
        the timeout, even if LDAP recovers immediately.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=fake_ldap.TIMEOUT_EXCEEDED("timed out")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.set_calls) == 0, (
            f"A TIMEOUT_EXCEEDED error must NOT write to Redis cache. "
            f"Got {len(fake_redis.set_calls)} write(s): {fake_redis.set_calls}."
        )

    def test_ldap_search_error_does_not_write_to_cache(self, monkeypatch) -> None:
        """OPERATIONS_ERROR (search error) must not write any sentinel to Redis."""
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=fake_ldap.OPERATIONS_ERROR("search error")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "alice@corp.com")
        )

        assert len(fake_redis.set_calls) == 0, (
            f"An OPERATIONS_ERROR (search error) must NOT write to Redis cache. "
            f"Got {len(fake_redis.set_calls)} write(s): {fake_redis.set_calls}."
        )

    def test_no_match_sentinel_is_written_but_not_on_error(self, monkeypatch) -> None:
        """Contrast test: no-match (empty result) IS cached; error is NOT cached.

        WHY: Both return None from enrich(), but they have different caching semantics.
        No-match = stable state (user truly not in directory) → cache it.
        Error = transient state (LDAP unavailable) → do NOT cache it.
        This test verifies the distinction is implemented.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        # First scenario: no-match (empty result) — should write sentinel
        conn_mock_nomatch = MagicMock()
        conn_mock_nomatch.simple_bind_s = MagicMock(return_value=None)
        conn_mock_nomatch.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock_nomatch)

        fake_redis_nomatch = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis_nomatch),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter.enrich("primary_email", "ghost@corp.com")
        )

        # No-match MUST write to cache (negative sentinel)
        assert len(fake_redis_nomatch.set_calls) >= 1, (
            "A live no-match (empty LDAP result) MUST write the negative sentinel "
            "to cache. No write was recorded."
        )

        # Now test error scenario — should NOT write
        # Re-inject fresh ldap mock with error
        for key in list(sys.modules.keys()):
            if key == "app.adapters.ldap" or key == "app.adapters":
                del sys.modules[key]

        fake_ldap2 = _make_fake_ldap_module()
        monkeypatch.setitem(sys.modules, "ldap", fake_ldap2)
        monkeypatch.setitem(sys.modules, "ldap.filter", fake_ldap2.filter)
        monkeypatch.setitem(sys.modules, "ldap.dn", fake_ldap2.dn)
        fake_ldap2.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock_err = MagicMock()
        conn_mock_err.simple_bind_s = MagicMock(return_value=None)
        conn_mock_err.search_s = MagicMock(
            side_effect=fake_ldap2.OPERATIONS_ERROR("error")
        )
        fake_ldap2.initialize = MagicMock(return_value=conn_mock_err)

        fake_redis_err = _FakeRedis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis_err),
        )

        from app.adapters import ldap as ldap_mod
        import importlib

        importlib.reload(ldap_mod)

        adapter2 = ldap_mod.LdapAdapter()
        asyncio.get_event_loop().run_until_complete(
            adapter2.enrich("primary_email", "ghost@corp.com")
        )

        assert len(fake_redis_err.set_calls) == 0, (
            f"A search error must NOT write to cache. "
            f"Got {len(fake_redis_err.set_calls)} write(s)."
        )
