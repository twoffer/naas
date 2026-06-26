"""LDAP protocol adapter for the Identity Normalization Service.

Maps LDAP directory attributes to the unified attribute schema (spec §5.2).
Also satisfies the LdapEnricher port (§5.3); the enrich() method performs a
live LDAP query with a bounded connection pool and three-state Redis cache.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  cn               → display_name
  mail             → primary_email
  departmentNumber → department   (value-normalized via normalize_department_value)
  employeeType     → employee_type (value-normalized via normalize_employee_type)
  memberOf         → groups        (DN-reduced to cn RDN values; default [])

DN reduction: memberOf values are full DNs in production LDAP directories
(e.g., 'cn=engineering,ou=groups,dc=corp,dc=com'). The unified groups field
stores only the group name (the cn RDN value). Bare names pass through as-is.

Connection pool
---------------
A bounded pool of up to ``settings.ldap_pool_size`` (default 3) connections is
maintained as an ``asyncio.Queue``.  Connections are created lazily on first use
and returned to the queue after each search.  On a connection error the broken
connection is discarded rather than returned so that a fresh one is created next
time.  Bind happens at connection creation time (inside asyncio.to_thread).

enrich() return contract
------------------------
enrich() returns a 2-tuple ``(attrs, outcome)`` where:
  attrs    — unified dict on a successful match; None on no-match or error
  outcome  — one of the outcome code strings below

Outcome codes:
  "cache_hit_positive"    — returned cached positive result
  "cache_hit_negative"    — returned None from negative sentinel
  "ldap_match"            — live LDAP returned a match (result written to cache)
  "ldap_no_match"         — live LDAP returned empty (negative sentinel cached)
  "ldap_timeout"          — LDAP client/server timeout; not cached; returns None
  "ldap_connection_error" — SERVER_DOWN or other connection failure; not cached
  "ldap_search_error"     — search-level error (OPERATIONS_ERROR etc.); not cached
  "ldap_unexpected_error" — any other exception; not cached
  "unmappable_field"      — correlation_field not in UNIFIED_TO_LDAP; no query

The consumer layer unpacks the tuple to build the skip_reason / EnrichmentApplied
discriminator without reading shared mutable state.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import re

import naas_shared.redis_client as _redis_module
from naas_shared.config import get_settings
from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX
from naas_shared.logging import get_logger

from app.adapters._mapping import (
    FieldRule,
    apply_field_rules,
    coerce_str,
    coerce_str_list,
)
from app.normalization_values import (
    UNIFIED_TO_LDAP,
    normalize_department_value,
    normalize_employee_type,
)

_logger = get_logger(__name__)

# Default enrichment cache TTL (seconds). Service passes the YAML-configured
# value per-call; this constant is the fallback when called without kwargs.
_DEFAULT_CACHE_TTL = 60

# Default LDAP network/operation timeout (milliseconds). Service passes the
# YAML-configured value per-call; this constant is the adapter fallback.
_DEFAULT_TIMEOUT_MS = 2000

# Matches the cn= RDN at the start or after a comma in an LDAP DN.
# Captures the attribute value verbatim (case-preserving, per spec §5.2 note).
_CN_RDN_RE = re.compile(r"(?:^|,)\s*cn=([^,]+)", re.IGNORECASE)

# Module-level connection pool state.  Initialised on first use by
# _get_pool(); one pool per process lifetime is sufficient.
_pool_queue: asyncio.Queue | None = None
_pool_size: int = 0


def _reduce_dn_to_group_name(dn: str) -> str | None:
    """Extract the cn RDN value from an LDAP DN string.

    WHY: The unified groups field stores group names (plain strings), not full
    DNs. If full DNs were stored, cross-protocol comparison with OIDC groups
    would always fail and group-based policy conditions would be broken for
    all LDAP users.

    Primary strategy: ldap.dn.str2dn (RFC 4514 parser). This correctly handles
    escaped commas in cn values (e.g. 'cn=Smith\\, John,...'), which the regex
    approach truncates to 'Smith\\'.  ldap.dn is available at runtime (Docker)
    via python-ldap, or injected via sys.modules in tests.

    Fallback strategy: _CN_RDN_RE regex, used only when ldap.dn is not importable
    (e.g., dev-venv where python-ldap cannot be installed without gcc). The fallback
    preserves all existing behaviour for simple DNs; only escaped-comma handling
    requires str2dn.

    For a bare name (no '=' assignment in the string), the input is returned as-is —
    some LDAP implementations store group names directly in memberOf.

    For a malformed DN that str2dn raises on or that contains no 'cn=' RDN,
    returns None so the caller can skip the entry safely.

    Args:
        dn: A memberOf value, either a full LDAP DN or a bare group name.

    Returns:
        The extracted group name string, or None if the DN is malformed or
        has no cn= component.
    """
    dn_stripped = dn.strip()
    if not dn_stripped:
        return None

    if "=" not in dn_stripped:
        # Bare group name — return as-is
        return dn_stripped

    # Primary: use ldap.dn.str2dn for correct RFC-4514 escaped-character handling.
    try:
        import ldap.dn

        parsed = ldap.dn.str2dn(dn_stripped)
        # parsed is list[list[(attr, value, flags)]] — one list per RDN component.
        # Walk all RDNs to find the first with attr=="cn" (case-insensitive).
        for rdn_list in parsed:
            for attr, value, _flags in rdn_list:
                if attr.lower() == "cn":
                    return value
        _logger.warning("ldap_dn_reduction_no_cn_rdn", dn_length=len(dn_stripped))
        return None
    except ImportError:
        pass  # python-ldap not available; fall through to regex fallback
    except Exception:  # noqa: BLE001 — defense-in-depth; any DN-reduction failure falls through to the regex fallback
        _logger.warning("ldap_dn_reduction_failed", dn_length=len(dn_stripped))
        return None

    # Fallback: regex-based extraction (python-ldap not installed, e.g., dev venv).
    # Handles simple DNs correctly; escaped-comma DNs will be partially wrong,
    # but that is acceptable in a dev context without python-ldap.
    match = _CN_RDN_RE.search(dn_stripped)
    if match:
        return match.group(1).strip()

    _logger.warning("ldap_dn_reduction_no_cn_rdn", dn_length=len(dn_stripped))
    return None


def reduce_member_of(value: object) -> list[str]:
    """Reduce a raw memberOf attribute to a list of group name strings.

    Applies coerce_str_list (strict list-only semantics) first so that a bare
    string memberOf value produces [] rather than iterating the string
    character-by-character.  Each DN string in the resulting list is then passed
    to _reduce_dn_to_group_name; entries that cannot be reduced (malformed DN with
    no cn= component) are silently dropped so the caller always receives a clean
    list of group name strings.

    WHY: This is the FieldRule transform for LDAP's 'memberOf' → 'groups' mapping.
    Consolidating the coercion + DN-reduction pipeline here keeps extract() as a
    one-liner while preserving the existing _reduce_dn_to_group_name logic intact.

    Args:
        value: Raw memberOf value from the login event attributes. Expected to be
            a list[str] of LDAP DNs; a non-list produces [] immediately.

    Returns:
        List of extracted group name strings (cn RDN values or bare names).
    """
    names: list[str] = []
    for dn in coerce_str_list(value):
        name = _reduce_dn_to_group_name(dn)
        if name is not None:
            names.append(name)
    return names


LDAP_FIELD_RULES: dict[str, FieldRule] = {
    "display_name": FieldRule(("cn",), coerce_str),
    "primary_email": FieldRule(("mail",), coerce_str),
    "department": FieldRule(("departmentNumber",), normalize_department_value),
    "employee_type": FieldRule(("employeeType",), normalize_employee_type),
    "groups": FieldRule(("memberOf",), reduce_member_of),
}


def _decode_first(value: object) -> str | None:
    """Return the first element of an LDAP attribute value list, decoded to str.

    python-ldap returns attribute values as lists of bytes.  extract() expects
    plain strings for scalar fields.  This helper normalises both raw bytes and
    lists-of-bytes to a single str so extract() can operate unchanged.

    Returns None when the value is absent, empty, or not decodable as UTF-8.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return str(value)


def _decode_list(value: list | bytes | None) -> list[str]:
    """Decode an LDAP multi-value attribute (list of bytes) to a list of str.

    Items that cannot be decoded as UTF-8 are silently skipped so the caller
    always receives a clean list of string values.
    """
    if not value:
        return []
    result: list[str] = []
    for item in value:  # type: ignore[union-attr]
        if isinstance(item, bytes):
            try:
                result.append(item.decode("utf-8"))
            except UnicodeDecodeError:
                continue
        else:
            result.append(str(item))
    return result


def _normalise_ldap_attrs(raw: dict) -> dict:
    """Convert raw python-ldap attribute dict (lists of bytes) to plain strings.

    WHY: python-ldap search_s returns ``{attr_name: [bytes, ...]}`` dicts.
    LdapAdapter.extract() was designed for single-string values (the format
    used when constructing synthetic dicts in tests and in the LDAP adapter's
    own integration path).  Decoding here keeps extract() simple and ensures
    a single decoding path for both unit and integration contexts.
    """
    return {
        "cn": _decode_first(raw.get("cn")),
        "mail": _decode_first(raw.get("mail")),
        "departmentNumber": _decode_first(raw.get("departmentNumber")),
        "employeeType": _decode_first(raw.get("employeeType")),
        "memberOf": _decode_list(raw.get("memberOf") or []),
    }


def build_search_filter(ldap_attr: str, lookup_value: str) -> str:
    """Build a safe, RFC 4515-compliant LDAP search filter for equality assertion.

    LDAP injection sanitization (spec §5.3 ⚠️ REQUIRED): the lookup_value is
    escaped via ldap.filter.escape_filter_chars before interpolation so that
    LDAP metacharacters cannot alter the filter semantics.

    The returned filter is parenthesised as required by RFC 4515. This function
    is used by enrich() internally and exported for external callers (diagnostic
    tools, etc.).

    Args:
        ldap_attr:    The LDAP attribute name (e.g. 'mail').
        lookup_value: The raw value to match (e.g. 'alice@corp.com').

    Returns:
        A parenthesised equality filter string, e.g. '(mail=alice@corp.com)'.
    """
    import ldap.filter

    escaped = ldap.filter.escape_filter_chars(lookup_value)
    return f"({ldap_attr}={escaped})"


def _get_pool(uri: str, admin_dn: str, password: str) -> asyncio.Queue:
    """Return (and lazily initialise) the module-level connection pool queue.

    WHY: The queue acts as a bounded semaphore that also holds live connection
    objects.  Each slot starts as None (meaning 'no connection yet'); the worker
    replaces None with a real connection on first use and returns the live
    connection after each search so it can be reused.

    The pool is initialised once per process.  If ldap_pool_size changes between
    calls (only possible in tests), a fresh pool is created.
    """
    global _pool_queue, _pool_size

    settings = get_settings()
    desired_size = settings.ldap_pool_size

    if _pool_queue is None or _pool_size != desired_size:
        _pool_queue = asyncio.Queue(maxsize=desired_size)
        for _ in range(desired_size):
            _pool_queue.put_nowait(None)  # None = slot available, no live conn yet
        _pool_size = desired_size

    return _pool_queue


def _create_ldap_connection(
    uri: str,
    admin_dn: str,
    password: str,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> object:
    """Create and bind a new LDAP connection (blocking — call via to_thread).

    WHY: python-ldap is a blocking C extension; all I/O must run in a thread.
    OPT_NETWORK_TIMEOUT bounds the TCP connect + initial data wait; OPT_TIMEOUT
    bounds synchronous operations (search_s, bind_s) client-side and raises
    ldap.TIMEOUT on expiry — already classified by _classify_ldap_error.

    Pooled connections are created once and reused; config is fixed per process,
    so setting timeout options at connection creation time is correct.

    Args:
        uri:        LDAP server URI (e.g. 'ldap://ldap:389').
        admin_dn:   Bind DN for the service account.
        password:   Bind password.
        timeout_ms: Network and operation timeout in milliseconds.

    Returns:
        A bound LDAP connection object.

    Raises:
        ldap.LDAPError subclass on connection or bind failure.
    """
    import ldap

    timeout_s = timeout_ms / 1000.0
    conn = ldap.initialize(uri)
    conn.set_option(ldap.OPT_NETWORK_TIMEOUT, timeout_s)
    conn.set_option(ldap.OPT_TIMEOUT, timeout_s)
    conn.simple_bind_s(admin_dn, password)
    return conn


def _do_unbind_s(conn: object) -> None:
    """Call unbind_s() on an LDAP connection (blocking — call via to_thread).

    WHY: python-ldap is a blocking C extension; unbind_s() must run in a thread.
    Signalling the server that the session is closed prevents server-side session
    leaks which, under heavy error load, can exhaust the directory's connection
    limit and block all future clients. Any exception from unbind_s() is swallowed
    by the caller — the point is best-effort cleanup, not error propagation.
    """
    conn.unbind_s()  # type: ignore[union-attr]


def _ldap_search_on_conn(
    conn: object,
    base_dn: str,
    filter_str: str,
    attrlist: list[str],
) -> list:
    """Run a synchronous LDAP search on an existing connection (call via to_thread).

    WHY: python-ldap is a blocking C extension.  Running it on the event loop
    would stall all concurrent pipeline events.

    Raises any ldap.LDAPError subclass so the caller can classify the error.
    """
    import ldap

    return conn.search_s(base_dn, ldap.SCOPE_SUBTREE, filter_str, attrlist)  # type: ignore[union-attr]


async def _pool_search(
    uri: str,
    admin_dn: str,
    password: str,
    base_dn: str,
    filter_str: str,
    attrlist: list[str],
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> list:
    """Acquire a connection from the pool, search, then return it to the pool.

    WHY: Reusing bound connections avoids the TCP + TLS + LDAP bind overhead on
    every enrich() call.  The pool is bounded by ldap_pool_size so we never
    open more connections than the directory server is configured to accept from
    a single client.

    On a connection error the slot is returned as None (not the broken object)
    so the next caller transparently creates a fresh connection.

    Args:
        uri:        LDAP server URI.
        admin_dn:   Service-account bind DN.
        password:   Bind password.
        base_dn:    LDAP search base.
        filter_str: Pre-escaped search filter.
        attrlist:   Attributes to fetch.
        timeout_ms: Timeout passed to _create_ldap_connection for new connections.

    Returns:
        List of (dn, attrs) tuples from search_s.

    Raises:
        Any ldap.LDAPError subclass on connection or search failure.
    """
    pool = _get_pool(uri, admin_dn, password)
    conn = await pool.get()  # blocks if pool is exhausted (bounded concurrency)

    try:
        if conn is None:
            # Slot was empty — create and bind a new connection in a thread
            conn = await asyncio.to_thread(
                _create_ldap_connection, uri, admin_dn, password, timeout_ms
            )
        results = await asyncio.to_thread(
            _ldap_search_on_conn, conn, base_dn, filter_str, attrlist
        )
        pool.put_nowait(conn)  # return live connection to pool
        return results
    except Exception:
        # Best-effort unbind: tell the server the session is done before
        # discarding the connection object so server-side sessions are not
        # leaked under error conditions. Any exception from unbind_s() is
        # swallowed — the slot must be freed regardless.
        if conn is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(_do_unbind_s, conn)
        pool.put_nowait(None)  # discard broken connection; free the slot
        raise


class LdapAdapter:
    """Extracts and normalizes LDAP directory attributes to the unified schema.

    Satisfies both ProtocolAdapter (§5.2) via extract() and LdapEnricher (§5.3)
    via extract() + enrich().  The enrich() method performs a live LDAP query
    using a bounded connection pool (sized by settings.ldap_pool_size) and a
    three-state Redis cache (miss / negative sentinel / positive hit).

    enrich() returns a (attrs, outcome) 2-tuple so callers receive the outcome
    code without reading shared mutable state (safe for concurrent use).
    """

    def extract(self, raw_attributes: dict) -> dict:
        """Map LDAP attribute names to unified field names with value normalization.

        Absent scalar keys produce None in the result. The 'groups' field always
        returns a list ([] when absent or when memberOf is empty or non-list) so
        the resolution engine can iterate it without a None guard.

        Seeded users in bootstrap.ldif DO have memberOf back-links (via the
        memberOf overlay); live enrichment returns real groups for those entries.

        Args:
            raw_attributes: Raw LDAP attribute dict (cn, mail, departmentNumber,
                employeeType, memberOf, uid, sn, ...).  Values must be plain
                strings (not bytes) — call _normalise_ldap_attrs() first for
                results coming directly from python-ldap search_s.

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        return apply_field_rules(raw_attributes, LDAP_FIELD_RULES)

    async def enrich(
        self,
        correlation_field: str,
        lookup_value: str,
        *,
        cache_ttl_seconds: int = _DEFAULT_CACHE_TTL,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        enrich_attributes: list[str] | None = None,
    ) -> tuple[dict | None, str]:
        """Query LDAP for a user and return (normalized_attrs, outcome_code).

        Three-state Redis cache (spec §5.3):
          MISS              — GET returns None → query LDAP
          NEGATIVE HIT      — key holds JSON sentinel ``"null"`` → return None
          POSITIVE HIT      — key holds JSON dict → return cached dict

        Transient LDAP failures (TIMEOUT, TIMELIMIT_EXCEEDED, SERVER_DOWN,
        OPERATIONS_ERROR, unexpected exceptions) are NOT cached so the service
        recovers automatically when LDAP becomes healthy again.

        Args:
            correlation_field:  Unified schema field used as the LDAP search key
                (e.g., 'primary_email').  Reverse-mapped to LDAP attribute via
                UNIFIED_TO_LDAP.  Returns (None, 'unmappable_field') immediately
                if not mappable.
            lookup_value:       The value to search for (e.g., 'alice@corp.com').
            cache_ttl_seconds:  TTL for both positive and negative cache entries.
            timeout_ms:         Network and operation timeout in milliseconds,
                applied when creating a new connection from the pool.
            enrich_attributes:  When not None, restricts the LDAP fetch to only
                the specified unified field names (reverse-mapped to LDAP attrs).
                When None, all five unified fields are fetched (sorted for
                deterministic attrlist ordering).

        Returns:
            (attrs, outcome) where attrs is the unified dict on match (else None)
            and outcome is one of the outcome code strings defined in the module
            docstring.
        """
        # --- Reverse-map unified field → LDAP attribute name ---
        ldap_attr = UNIFIED_TO_LDAP.get(correlation_field)
        if ldap_attr is None:
            _logger.debug(
                "ldap_enrich_unmappable_field",
                correlation_field=correlation_field,
            )
            return None, "unmappable_field"

        cache_key = f"{LDAP_ENRICHMENT_CACHE_PREFIX}{lookup_value}"

        # --- Check Redis cache (three-state) ---
        # Use inspect.isawaitable so both the real async get_redis() and
        # test-injected MagicMock(return_value=fake_redis) work correctly.
        redis_result = _redis_module.get_redis()
        redis = (
            await redis_result if inspect.isawaitable(redis_result) else redis_result
        )
        cached = await redis.get(cache_key)

        if cached is not None:
            # Decode bytes → str for comparison
            cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else cached
            if cached_str == '"null"' or cached_str == "null":
                _logger.debug("ldap_enrich_negative_cache_hit", ldap_attr=ldap_attr)
                return None, "cache_hit_negative"
            # Positive hit — deserialize JSON
            try:
                attrs = json.loads(cached_str)
                _logger.debug("ldap_enrich_positive_cache_hit", ldap_attr=ldap_attr)
                return attrs, "cache_hit_positive"
            except (json.JSONDecodeError, TypeError):
                # Corrupted cache entry — best-effort delete so the next call
                # is a clean miss rather than hitting the corrupt value again.
                # Log the length only (not the raw content) to prevent PII leakage:
                # the cached string may contain the user's email address, display name,
                # or other directory attributes collected during a prior successful query.
                with contextlib.suppress(Exception):
                    await redis.delete(cache_key)
                _logger.warning(
                    "ldap_enrich_cache_decode_error",
                    ldap_attr=ldap_attr,
                    cached_value_length=len(cached_str),
                )

        # --- Cache miss: query LDAP via connection pool ---
        settings = get_settings()
        uri = f"ldap://{settings.ldap_host}:{settings.ldap_port}"

        # Build attrlist: restrict to requested fields (sorted for determinism),
        # or fetch all five unified fields when enrich_attributes is not set.
        if enrich_attributes is not None:
            attrlist = sorted(UNIFIED_TO_LDAP[f] for f in enrich_attributes)
        else:
            attrlist = sorted(UNIFIED_TO_LDAP.values())

        search_filter = build_search_filter(ldap_attr, lookup_value)

        try:
            results = await _pool_search(
                uri,
                settings.ldap_admin_dn,
                settings.ldap_admin_password,
                settings.ldap_base_dn,
                search_filter,
                attrlist,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001 — graceful degradation: classify any LDAP error, never drop the event (ADR-0008)
            outcome = _classify_ldap_error(exc)
            # For connection errors the service owns operator-facing logging;
            # log at DEBUG here to avoid duplicate ERRORs per event.
            if outcome == "ldap_connection_error":
                _logger.debug(
                    "ldap_enrich_error",
                    outcome=outcome,
                    ldap_attr=ldap_attr,
                    error=str(exc)[:200],
                )
            else:
                _logger.warning(
                    "ldap_enrich_error",
                    outcome=outcome,
                    ldap_attr=ldap_attr,
                    error=str(exc)[:200],
                )
            # Transient errors are NOT cached
            return None, outcome

        # --- Process results ---
        if not results:
            # Confirmed no-match: cache negative sentinel
            await _cache_write(redis, cache_key, '"null"', cache_ttl_seconds)
            _logger.debug("ldap_enrich_no_match", ldap_attr=ldap_attr)
            return None, "ldap_no_match"

        # Successful match: decode bytes, normalise, cache positive result
        _dn, raw_attrs = results[0]
        normalised_attrs = _normalise_ldap_attrs(raw_attrs)
        unified = self.extract(normalised_attrs)

        serialized = json.dumps(unified)
        await _cache_write(redis, cache_key, serialized, cache_ttl_seconds)

        _logger.info("ldap_enrich_match", ldap_attr=ldap_attr)
        return unified, "ldap_match"


def _classify_ldap_error(exc: Exception) -> str:
    """Map an LDAP exception to an outcome code string for the consumer layer.

    WHY: The consumer layer needs to distinguish transient error types (timeout
    vs connection_error vs search_error) to build the correct skip_reason for
    EnrichmentSkipped.  Using outcome strings (not exception types) keeps it
    decoupled from python-ldap's exception hierarchy.

    python-ldap timeout names:
      ldap.TIMEOUT            — client / network timeout
      ldap.TIMELIMIT_EXCEEDED — server time-limit exceeded
    Both map to 'ldap_timeout'.

    Args:
        exc: Any exception raised during the LDAP operation.

    Returns:
        One of 'ldap_timeout', 'ldap_connection_error', 'ldap_search_error',
        or 'ldap_unexpected_error'.
    """
    try:
        import ldap as ldap_module

        # Collect timeout exception types from the canonical attribute names.
        # ldap.TIMEOUT = client/network timeout; ldap.TIMELIMIT_EXCEEDED = server
        # time-limit.  Both are guarded with getattr + isinstance(t, type) to
        # tolerate stub modules that may be missing either attribute.
        _timeout_types = tuple(
            t
            for t in (
                getattr(ldap_module, "TIMEOUT", None),
                getattr(ldap_module, "TIMELIMIT_EXCEEDED", None),
            )
            if isinstance(t, type)
        )
        if _timeout_types and isinstance(exc, _timeout_types):
            return "ldap_timeout"
        if isinstance(exc, ldap_module.SERVER_DOWN):
            return "ldap_connection_error"
        if isinstance(exc, ldap_module.LDAPError):
            return "ldap_search_error"
    except (ImportError, AttributeError):
        pass

    return "ldap_unexpected_error"


async def _cache_write(redis: object, key: str, value: str, ttl: int) -> None:
    """Write a value to Redis with TTL, using setex when available.

    WHY: Supports both real aioredis clients (which have setex) and the fake
    Redis clients used in tests (which implement setex and/or set(ex=...)).
    Prefers setex for atomic TTL setting; falls back to set(ex=ttl).
    """
    if hasattr(redis, "setex"):
        await redis.setex(key, ttl, value)
    else:
        await redis.set(key, value, ex=ttl)
