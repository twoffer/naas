"""LdapAdapter.enrich(): LDAP search, attribute extraction, and cache write mechanics."""

from unittest.mock import AsyncMock, MagicMock

# third-party
import pytest

from tests.services.identity_normalization.conftest import inject_fake_ldap


def _make_fake_redis(get_return=None, set_calls=None) -> MagicMock:
    """Build a fake async Redis client (legacy helper — new tests use FakeRedis).

    Kept for tests that assert on a shared list passed in via set_calls.
    """
    fake_redis = AsyncMock(name="redis")

    recorded_sets = set_calls if set_calls is not None else []

    async def fake_get(key: str):
        return get_return

    async def fake_setex(key: str, ttl: int, value):
        recorded_sets.append({"key": key, "ttl": ttl, "value": value})

    async def fake_set(key: str, value, ex=None):
        recorded_sets.append({"key": key, "ttl": ex, "value": value})

    fake_redis.get = AsyncMock(side_effect=fake_get)
    fake_redis.setex = AsyncMock(side_effect=fake_setex)
    fake_redis.set = AsyncMock(side_effect=fake_set)

    return fake_redis


# Alias so test bodies that call _inject_fake_ldap continue to work unchanged.
_inject_fake_ldap = inject_fake_ldap


# ---------------------------------------------------------------------------
# LDAP search result factory
# ---------------------------------------------------------------------------


def _make_ldap_result(
    cn: str = "Alice Smith",
    mail: str = "alice@corp.com",
    dept: str = "engineering",
    employee_type: str = "FTE",
    member_of: list | None = None,
) -> list:
    """Build a fake LDAP search result in python-ldap tuple format.

    python-ldap search_s returns a list of (dn, attr_dict) tuples where all
    attribute values are lists of bytes.

    The adapter must decode bytes to str — test the decode contract here.
    """
    if member_of is None:
        member_of = []

    dn = "uid=alice,ou=users,dc=corp,dc=com"
    attrs = {
        "cn": [cn.encode("utf-8")],
        "mail": [mail.encode("utf-8")],
        "departmentNumber": [dept.encode("utf-8")],
        "employeeType": [employee_type.encode("utf-8")],
    }
    if member_of:
        attrs["memberOf"] = [v.encode("utf-8") for v in member_of]

    return [(dn, attrs)]


# ===========================================================================
# CLASS 1 — enrich() is awaitable (async coroutine)
# ===========================================================================


class TestEnrichIsAwaitable:
    """enrich() must be an async coroutine that can be awaited.

    WHY: The identity-normalization service is fully async (FastAPI + asyncio).
    A synchronous enrich() would block the event loop during every LDAP call,
    starving all other concurrent pipeline events. The spec §5.3 explicitly
    requires wrapping blocking LDAP calls in asyncio.to_thread().
    """

    async def test_enrich_returns_coroutine_on_call(self, monkeypatch) -> None:
        """LdapAdapter().enrich(...) must return a coroutine, not a plain value.

        Spec §5.3 requires asyncio.to_thread wrapping; a non-coroutine return
        indicates a synchronous implementation.
        """
        import inspect

        _inject_fake_ldap(monkeypatch)
        fake_redis = _make_fake_redis(
            get_return=b'"null"'
        )  # negative cache → no LDAP call
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        result = adapter.enrich("primary_email", "alice@corp.com")

        assert inspect.iscoroutine(result), (
            f"LdapAdapter().enrich() must return a coroutine (async def), "
            f"got {type(result).__name__!r}. Spec §5.3 requires asyncio.to_thread wrapping."
        )
        # Close the coroutine to avoid ResourceWarning
        result.close()

    async def test_enrich_can_be_awaited(self, monkeypatch) -> None:
        """await LdapAdapter().enrich(...) must complete without RuntimeError."""
        _inject_fake_ldap(monkeypatch)
        fake_redis = _make_fake_redis(get_return=b'"null"')
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()

        # Must not raise RuntimeError("cannot reuse already awaited coroutine") etc.
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        # Negative cache hit → attrs is None (no LDAP search); outcome is a str
        assert attrs is None or isinstance(attrs, dict), (
            f"enrich() attrs must be None or dict, got {type(attrs).__name__!r}"
        )
        assert isinstance(outcome, str), (
            f"enrich() outcome must be a str, got {type(outcome).__name__!r}"
        )


# ===========================================================================
# CLASS 2 — Reverse mapping (correlation_field → LDAP attr)
# ===========================================================================


class TestEnrichReverseMapping:
    """enrich() must reverse-map unified field names to LDAP attribute names.

    WHY: The enrichment config (§5.6) names unified fields (e.g., 'primary_email'),
    NOT LDAP attribute names. The adapter is the single source of truth for the
    unified↔LDAP translation (§5.3). If enrich() builds its filter using the raw
    unified field name as the LDAP attribute ('primary_email=alice'), the LDAP
    search will always return zero results — a silent misconfiguration.
    """

    async def test_known_correlation_field_does_not_return_immediately_as_none(
        self, monkeypatch
    ) -> None:
        """A correlation_field in UNIFIED_TO_LDAP must attempt an LDAP query.

        Verify by injecting a fake LDAP connection that records search calls and
        confirming at least one search was attempted (i.e., the adapter did NOT
        short-circuit to None before querying).
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        # Configure LDAP: connection binds OK, search returns a match
        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=_make_ldap_result())
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        # Cache miss → must query LDAP
        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        await adapter.enrich("primary_email", "alice@corp.com")

        assert conn_mock.search_s.called, (
            "LdapAdapter.enrich('primary_email', ...) must call search_s at least once. "
            "The correlation_field 'primary_email' is in UNIFIED_TO_LDAP and must be queried."
        )

    async def test_unknown_correlation_field_returns_none_without_ldap_query(
        self, monkeypatch
    ) -> None:
        """A correlation_field NOT in UNIFIED_TO_LDAP must return None immediately.

        WHY: 'favorite_color' is not a mappable unified field. Building a search
        filter for it would be meaningless. The adapter must detect this and return
        None (the 'un-reverse-mappable' path from spec §5.3). No LDAP search,
        no Redis cache write. This avoids confusing results and guards against
        misconfigured enrichment config.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        set_calls: list = []
        fake_redis = _make_fake_redis(get_return=None, set_calls=set_calls)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("favorite_color", "blue")

        assert attrs is None, (
            f"enrich('favorite_color', ...) must return attrs=None for an unmappable "
            f"correlation_field, got {attrs!r}"
        )
        assert outcome == "unmappable_field", (
            f"enrich('favorite_color', ...) must return outcome='unmappable_field', "
            f"got {outcome!r}"
        )
        assert not conn_mock.search_s.called, (
            "enrich() must NOT call search_s for an unmappable correlation_field. "
            "Querying LDAP with an unmapped attribute would always return empty results."
        )

    @pytest.mark.parametrize(
        "unified_field,expected_ldap_attr",
        [
            ("primary_email", "mail"),
            ("display_name", "cn"),
            ("department", "departmentNumber"),
            ("employee_type", "employeeType"),
            ("groups", "memberOf"),
        ],
    )
    async def test_correlation_field_reverse_maps_to_correct_ldap_attr(
        self,
        monkeypatch,
        unified_field: str,
        expected_ldap_attr: str,
    ) -> None:
        """Each unified field must map to the correct LDAP attribute in the filter.

        WHY: The mapping table is 'TRANSCRIBE EXACTLY' in spec §5.2. A wrong
        mapping (e.g., primary_email→uid instead of primary_email→mail) means the
        search filter never matches real LDAP entries.

        This test records the actual filter string passed to search_s and asserts
        it contains the correct LDAP attribute name.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        # escape_filter_chars passes through unchanged for simple values
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append(
                {
                    "base_dn": base_dn,
                    "scope": scope,
                    "filter_str": filter_str,
                    "attrlist": attrlist,
                }
            )
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        await adapter.enrich(unified_field, "test_value")

        assert len(search_calls) >= 1, (
            f"enrich('{unified_field}', ...) must call search_s — no search was recorded."
        )

        filter_str = search_calls[0]["filter_str"]
        assert expected_ldap_attr in filter_str, (
            f"enrich('{unified_field}', ...) must build a filter containing "
            f"'{expected_ldap_attr}' (the LDAP attribute for this unified field). "
            f"Got filter: {filter_str!r}"
        )


# ===========================================================================
# CLASS 3 — Search + match: LDAP result through extract() → unified dict
# ===========================================================================


class TestEnrichSearchAndMatch:
    """On a successful LDAP match, enrich() must run the result through extract()
    and return the unified-schema dict.

    WHY: The adapter must not return raw LDAP attribute dicts (with bytes values
    and LDAP attribute names). The caller (NormalizationService) expects a unified
    dict with string values using unified field names. Using extract() internally
    ensures the same normalization path as direct LDAP events.
    """

    async def test_enrich_match_returns_dict_with_unified_keys(
        self, monkeypatch
    ) -> None:
        """A successful LDAP match must return a dict with unified schema keys.

        WHY: The unified dict is merged with primary-source attributes during
        conflict resolution (§5.5). Wrong key names (e.g., 'cn' instead of
        'display_name') would cause the resolution engine to ignore the LDAP data,
        silently producing single-source results for all enriched events.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="engineering",
                employee_type="FTE",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is not None, (
            "enrich() returned attrs=None on a successful LDAP match — expected a dict. "
            "When search_s returns a non-empty result, enrich() must return the "
            "unified dict, not None."
        )
        assert isinstance(attrs, dict), (
            f"enrich() must return a dict on match, got {type(attrs).__name__!r}"
        )
        assert outcome == "ldap_match", (
            f"enrich() outcome must be 'ldap_match' on a successful LDAP match, "
            f"got {outcome!r}"
        )

        expected_keys = {
            "display_name",
            "primary_email",
            "department",
            "employee_type",
            "groups",
        }
        actual_keys = set(attrs.keys())
        assert expected_keys.issubset(actual_keys), (
            f"enrich() result must contain all unified schema keys. "
            f"Missing: {expected_keys - actual_keys}. Got keys: {actual_keys}"
        )

    async def test_enrich_match_decodes_bytes_to_str(self, monkeypatch) -> None:
        """LDAP attribute values are bytes; enrich() must decode them to str.

        WHY: python-ldap returns attribute values as lists of bytes
        (e.g., b"Alice Smith"). Storing bytes in the unified dict would cause
        JSON serialization to fail with TypeError, breaking the stream publish.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="engineering",
                employee_type="FTE",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, _outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is not None, "Expected a match result, got attrs=None"

        # Scalar string fields must be str, not bytes
        for field in ("display_name", "primary_email"):
            val = attrs.get(field)
            if val is not None:
                assert isinstance(val, str), (
                    f"attrs['{field}'] must be str after bytes decoding, "
                    f"got {type(val).__name__!r}: {val!r}"
                )

    async def test_enrich_match_applies_value_normalization(self, monkeypatch) -> None:
        """enrich() must apply value normalization (via extract()) to LDAP results.

        WHY: The caller (NormalizationService) runs conflict resolution expecting
        canonical values (e.g., 'Engineering', not 'engineering'). Skipping
        normalization in the enrichment path would cause canonical-value mismatches
        in unanimous resolution, silently flipping unanimous results to priority
        resolution with incorrect winner selection.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        # LDAP stores 'eng' — must normalize to 'Engineering'
        conn_mock.search_s = MagicMock(
            return_value=_make_ldap_result(
                cn="Alice Smith",
                mail="alice@corp.com",
                dept="eng",
                employee_type="fte",
            )
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, _outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is not None, "Expected a match result, got attrs=None"
        assert attrs.get("department") == "Engineering", (
            f"enrich() must normalize department 'eng' → 'Engineering' via extract(). "
            f"Got: {attrs.get('department')!r}"
        )
        assert attrs.get("employee_type") == "FTE", (
            f"enrich() must normalize employee_type 'fte' → 'FTE' via extract(). "
            f"Got: {attrs.get('employee_type')!r}"
        )


# ===========================================================================
# CLASS 4 — No match / errors → None (graceful, no uncaught exceptions)
# ===========================================================================


class TestEnrichNoMatchAndErrors:
    """enrich() must return None on no-match and absorb LDAP errors gracefully.

    WHY (spec §5.3, §5.4 — graceful degradation, ADR-0008):
    Enrichment failure must NEVER propagate as an exception to the consumer
    loop. A raised exception would cause the consumer to skip XACK, leaving
    the event stuck in the pending-entries list (PEL). Redis Streams do not
    auto-redeliver, so the event would never be reprocessed — its enrichment
    is silently lost instead of degrading gracefully — and repeated failures
    would accumulate unACKed entries in the PEL with no retry path. All LDAP
    error conditions must be absorbed.
    """

    async def test_enrich_empty_search_result_returns_none(self, monkeypatch) -> None:
        """An empty LDAP search result (no directory entry) must return None.

        WHY: This is the 'no_ldap_match' path. The consumer maps None to
        EnrichmentSkipped(skip_reason='no_ldap_match'). enrich() must not raise
        KeyError or IndexError when the result list is empty.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])  # empty result
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("primary_email", "unknown@corp.com")

        assert attrs is None, (
            f"enrich() must return attrs=None when LDAP search returns no results, "
            f"got {attrs!r}"
        )
        assert outcome == "ldap_no_match", (
            f"enrich() outcome must be 'ldap_no_match' on empty result, got {outcome!r}"
        )

    async def test_enrich_ldap_connection_error_returns_none(self, monkeypatch) -> None:
        """An LDAP connection error (SERVER_DOWN) must not propagate out of enrich().

        WHY: If LDAP is down, the event must still be processed using primary-
        source-only data. Propagating the exception would break the consumer loop.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(
            side_effect=fake_ldap.SERVER_DOWN("connection refused")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        # Must NOT raise — graceful degradation
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is None, (
            f"enrich() must return attrs=None on connection error, not propagate SERVER_DOWN. "
            f"Got: {attrs!r}"
        )
        assert outcome == "ldap_connection_error", (
            f"enrich() outcome must be 'ldap_connection_error' on SERVER_DOWN, "
            f"got {outcome!r}"
        )

    async def test_enrich_ldap_search_error_returns_none(self, monkeypatch) -> None:
        """An LDAP search error (OPERATIONS_ERROR) must not propagate out of enrich().

        WHY: Search errors can occur due to LDAP server load, ACL issues, or
        malformed filters that pass sanitization. In all cases, the event must be
        processed with primary-source-only data.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=fake_ldap.OPERATIONS_ERROR("search failed")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is None, (
            f"enrich() must return attrs=None on LDAP search error, "
            f"not propagate OPERATIONS_ERROR. Got: {attrs!r}"
        )
        assert outcome == "ldap_search_error", (
            f"enrich() outcome must be 'ldap_search_error' on OPERATIONS_ERROR, "
            f"got {outcome!r}"
        )

    async def test_enrich_ldap_timeout_returns_none(self, monkeypatch) -> None:
        """An LDAP client timeout (ldap.TIMEOUT) must not propagate out of enrich().

        WHY: The config specifies timeout_ms (§5.6). A timeout is a transient
        condition. The event must still be published downstream with primary-
        source-only data.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(side_effect=fake_ldap.TIMEOUT("query timed out"))
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is None, (
            f"enrich() must return attrs=None on LDAP timeout, "
            f"not propagate ldap.TIMEOUT. Got: {attrs!r}"
        )
        assert outcome == "ldap_timeout", (
            f"enrich() outcome must be 'ldap_timeout' on ldap.TIMEOUT, got {outcome!r}"
        )

    async def test_enrich_unexpected_exception_returns_none(self, monkeypatch) -> None:
        """Unexpected exceptions during LDAP query must not propagate out of enrich().

        WHY: Belt-and-suspenders test. Even an unexpected exception (RuntimeError,
        ValueError from malformed LDAP response) must be absorbed gracefully.
        The event pipeline must not stall due to any single LDAP failure.
        """
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(
            side_effect=RuntimeError("unexpected LDAP response format")
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        attrs, outcome = await adapter.enrich("primary_email", "alice@corp.com")

        assert attrs is None, (
            f"enrich() must return attrs=None on unexpected exceptions, got {attrs!r}"
        )
        assert outcome == "ldap_unexpected_error", (
            f"enrich() outcome must be 'ldap_unexpected_error' on unexpected exception, "
            f"got {outcome!r}"
        )


# ===========================================================================
# CLASS 5 — timeout_ms is applied to new connections
# ===========================================================================


class TestTimeoutOption:
    """When a new connection is created, set_option must be called with the timeout.

    WHY (Change 1): timeout_ms is a config knob that was always validated but never
    applied. The connection must call conn.set_option(OPT_NETWORK_TIMEOUT, ...) and
    conn.set_option(OPT_TIMEOUT, ...) derived from timeout_ms before simple_bind_s.
    """

    async def test_set_option_called_with_opt_network_timeout(
        self, monkeypatch
    ) -> None:
        """OPT_NETWORK_TIMEOUT must be set on the connection using timeout_ms."""
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)
        fake_ldap.OPT_NETWORK_TIMEOUT = 20  # fake constant value
        fake_ldap.OPT_TIMEOUT = 30

        set_option_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)
        conn_mock.search_s = MagicMock(return_value=[])
        conn_mock.set_option = MagicMock(
            side_effect=lambda opt, val: set_option_calls.append((opt, val))
        )
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        await adapter.enrich("primary_email", "alice@corp.com", timeout_ms=3000)

        opt_keys = [opt for opt, _ in set_option_calls]
        assert fake_ldap.OPT_NETWORK_TIMEOUT in opt_keys, (
            "set_option must be called with OPT_NETWORK_TIMEOUT when creating a connection"
        )
        assert fake_ldap.OPT_TIMEOUT in opt_keys, (
            "set_option must be called with OPT_TIMEOUT when creating a connection"
        )

        # Verify the timeout value is timeout_ms / 1000.0
        net_timeout_val = next(
            val for opt, val in set_option_calls if opt == fake_ldap.OPT_NETWORK_TIMEOUT
        )
        assert net_timeout_val == pytest.approx(3.0), (
            f"OPT_NETWORK_TIMEOUT must be timeout_ms/1000.0 = 3.0, got {net_timeout_val!r}"
        )


# ===========================================================================
# CLASS 6 — enrich_attributes restricts the attrlist
# ===========================================================================


class TestEnrichAttributes:
    """enrich_attributes restricts the LDAP attrlist to the specified unified fields.

    WHY (Change 1): enrich_attributes is a config knob that was validated but never
    applied. When set, only the specified unified fields (reverse-mapped to LDAP
    attrs) should be fetched. When None, all five LDAP attrs are fetched (sorted).
    """

    async def test_enrich_attributes_none_fetches_all_five_sorted(
        self, monkeypatch
    ) -> None:
        """When enrich_attributes is None, all five LDAP attrs are fetched, sorted."""
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append({"attrlist": attrlist})
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter
        from app.normalization_values import UNIFIED_TO_LDAP

        adapter = LdapAdapter()
        await adapter.enrich("primary_email", "alice@corp.com", enrich_attributes=None)

        assert len(search_calls) == 1, "search_s must be called once"
        attrlist = search_calls[0]["attrlist"]
        expected = sorted(UNIFIED_TO_LDAP.values())
        assert attrlist == expected, (
            f"enrich_attributes=None must fetch all five attrs sorted: {expected!r}. "
            f"Got: {attrlist!r}"
        )

    async def test_enrich_attributes_subset_restricts_attrlist(
        self, monkeypatch
    ) -> None:
        """enrich_attributes=['primary_email','department'] → attrlist=['departmentNumber','mail']."""
        fake_ldap = _inject_fake_ldap(monkeypatch)
        fake_ldap.filter.escape_filter_chars = MagicMock(side_effect=lambda v: v)

        search_calls: list = []

        conn_mock = MagicMock()
        conn_mock.simple_bind_s = MagicMock(return_value=None)

        def recording_search(base_dn, scope, filter_str, attrlist=None):
            search_calls.append({"attrlist": attrlist})
            return []

        conn_mock.search_s = MagicMock(side_effect=recording_search)
        fake_ldap.initialize = MagicMock(return_value=conn_mock)

        fake_redis = _make_fake_redis(get_return=None)
        monkeypatch.setattr(
            "naas_shared.redis_client.get_redis",
            MagicMock(return_value=fake_redis),
        )

        from app.adapters.ldap import LdapAdapter

        adapter = LdapAdapter()
        await adapter.enrich(
            "primary_email",
            "alice@corp.com",
            enrich_attributes=["primary_email", "department"],
        )

        assert len(search_calls) == 1
        attrlist = search_calls[0]["attrlist"]
        # primary_email → mail, department → departmentNumber; sorted alphabetically
        expected = sorted(["mail", "departmentNumber"])
        assert attrlist == expected, (
            f"enrich_attributes=['primary_email','department'] must produce "
            f"attrlist={expected!r}. Got: {attrlist!r}"
        )


# ===========================================================================
# CLASS 7 — _decode_first and _decode_list helpers
# ===========================================================================


class TestDecodeHelpers:
    """Unit tests for _decode_first and _decode_list byte-decoding helpers.

    WHY (Change 4b): These helpers must gracefully handle invalid UTF-8 bytes
    rather than raising UnicodeDecodeError.
    """

    def test_decode_first_bytes(self) -> None:
        """_decode_first with plain bytes returns decoded str."""
        from app.adapters.ldap import _decode_first

        assert _decode_first(b"Alice Smith") == "Alice Smith"

    def test_decode_first_list_of_bytes(self) -> None:
        """_decode_first with [bytes, ...] returns first element decoded."""
        from app.adapters.ldap import _decode_first

        assert _decode_first([b"alice@corp.com", b"other"]) == "alice@corp.com"

    def test_decode_first_empty_list(self) -> None:
        """_decode_first with empty list returns None."""
        from app.adapters.ldap import _decode_first

        assert _decode_first([]) is None

    def test_decode_first_none(self) -> None:
        """_decode_first with None returns None."""
        from app.adapters.ldap import _decode_first

        assert _decode_first(None) is None

    def test_decode_first_non_bytes_non_list(self) -> None:
        """_decode_first with a plain string returns str(value)."""
        from app.adapters.ldap import _decode_first

        assert _decode_first("Alice") == "Alice"

    def test_decode_first_invalid_utf8(self) -> None:
        """_decode_first with invalid UTF-8 bytes returns None (not UnicodeDecodeError)."""
        from app.adapters.ldap import _decode_first

        result = _decode_first(b"\xff\xfe")
        assert result is None, (
            f"_decode_first must return None for invalid UTF-8, got {result!r}"
        )

    def test_decode_list_bytes_items(self) -> None:
        """_decode_list with list of bytes returns decoded strings."""
        from app.adapters.ldap import _decode_list

        assert _decode_list([b"engineering", b"admin"]) == ["engineering", "admin"]

    def test_decode_list_empty(self) -> None:
        """_decode_list with empty list returns []."""
        from app.adapters.ldap import _decode_list

        assert _decode_list([]) == []

    def test_decode_list_none(self) -> None:
        """_decode_list with None returns []."""
        from app.adapters.ldap import _decode_list

        assert _decode_list(None) == []

    def test_decode_list_non_bytes_items(self) -> None:
        """_decode_list with non-bytes items converts via str()."""
        from app.adapters.ldap import _decode_list

        assert _decode_list(["admin", "eng"]) == ["admin", "eng"]

    def test_decode_list_invalid_utf8_skipped(self) -> None:
        """_decode_list skips items with invalid UTF-8 bytes."""
        from app.adapters.ldap import _decode_list

        result = _decode_list([b"valid", b"\xff\xfe", b"also_valid"])
        assert result == ["valid", "also_valid"], (
            f"_decode_list must skip invalid UTF-8 items, got {result!r}"
        )
