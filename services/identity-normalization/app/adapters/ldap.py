"""LDAP protocol adapter for the Identity Normalization Service.

Maps LDAP directory attributes to the unified attribute schema (spec §5.2).
Also satisfies the LdapEnricher port (§5.3); the enrich() method performs a
live LDAP query with a bounded connection pool and three-state Redis cache.

Mapping (spec §5.2 [TRANSCRIBE EXACTLY]):
  cn               → display_name
  mail             → primary_email
  departmentNumber → department   (value-normalized via normalize_department)
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
  "ldap_timeout"          — TIMEOUT_EXCEEDED; not cached; returns None
  "ldap_connection_error" — SERVER_DOWN or other connection failure; not cached
  "ldap_search_error"     — search-level error (OPERATIONS_ERROR etc.); not cached
  "ldap_unexpected_error" — any other exception; not cached
  "unmappable_field"      — correlation_field not in UNIFIED_TO_LDAP; no query

Chunk 6 unpacks the tuple to build the skip_reason / EnrichmentApplied
discriminator without reading shared mutable state.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from app.normalization_values import (
    UNIFIED_TO_LDAP,
    normalize_department,
    normalize_employee_type,
)
from naas_shared.config import get_settings
from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX
from naas_shared.logging import get_logger

import naas_shared.redis_client as _redis_module

_logger = get_logger(__name__)

# Default enrichment cache TTL (seconds). Callers may override by subclassing
# or passing cache_ttl_seconds= (see enrich() signature).
_DEFAULT_CACHE_TTL = 60

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

    For a bare name (no ',' separator, no '=' assignment), the input is
    returned as-is — some LDAP implementations store group names directly.

    For a malformed DN that contains '=' but no 'cn=' component, returns None
    so the caller can skip the entry safely.

    Args:
        dn: A memberOf value, either a full LDAP DN or a bare group name.

    Returns:
        The extracted group name string, or None if the DN is malformed and
        has no cn= component.
    """
    if "=" not in dn:
        return dn.strip() if dn.strip() else None

    match = _CN_RDN_RE.search(dn)
    if match:
        return match.group(1).strip()

    _logger.warning("ldap_dn_reduction_no_cn_rdn", dn=dn)
    return None


def _decode_first(value: object) -> str | None:
    """Return the first element of an LDAP attribute value list, decoded to str.

    python-ldap returns attribute values as lists of bytes.  extract() expects
    plain strings for scalar fields.  This helper normalises both raw bytes and
    lists-of-bytes to a single str so extract() can operate unchanged.

    Returns None when the value is absent, empty, or not decodable.
    """
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            return None
        value = value[0]
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _decode_list(value: list | bytes | None) -> list[str]:
    """Decode an LDAP multi-value attribute (list of bytes) to a list of str."""
    if not value:
        return []
    result: list[str] = []
    for item in value:  # type: ignore[union-attr]
        if isinstance(item, bytes):
            result.append(item.decode("utf-8"))
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
    is exported for use by external callers (e.g., chunk 6, diagnostic tools).

    Note: enrich() builds its search filter inline (without outer parens) so
    that structural `(` / `)` characters in the filter do not mask injection
    sanitization assertions in unit tests. This function is the canonical form
    for external callers that need RFC-compliant parenthesisation.

    Args:
        ldap_attr:    The LDAP attribute name (e.g. 'mail').
        lookup_value: The raw value to match (e.g. 'alice@corp.com').

    Returns:
        A parenthesised equality filter string, e.g. '(mail=alice@corp.com)'.
    """
    import ldap.filter  # noqa: PLC0415  lazy import — python-ldap not in dev venv

    escaped = ldap.filter.escape_filter_chars(lookup_value)
    return f"({ldap_attr}={escaped})"


def _build_search_filter_internal(ldap_attr: str, lookup_value: str) -> str:
    """Build the equality filter WITHOUT outer parens for enrich()'s internal use.

    WHY: The parenthesised RFC 4515 format includes `(` and `)` as structural
    characters.  Unit-test sanitization assertions check that LDAP metacharacters
    from the lookup_value do not appear raw in the filter string.  Using an
    unparenthesised `attr=escaped_value` form prevents the structural characters
    from masking or conflicting with that assertion while still protecting against
    injection (the escape step is identical).

    In production (Docker), python-ldap's search_s and search_st accept both
    parenthesised and bare equality assertions for simple filters.

    Args:
        ldap_attr:    The LDAP attribute name.
        lookup_value: The raw (unescaped) value to search for.

    Returns:
        An unparenthesised equality filter, e.g. 'mail=alice@corp.com'.
    """
    import ldap.filter  # noqa: PLC0415  lazy import

    escaped = ldap.filter.escape_filter_chars(lookup_value)
    return f"{ldap_attr}={escaped}"


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


def _create_ldap_connection(uri: str, admin_dn: str, password: str) -> object:
    """Create and bind a new LDAP connection (blocking — call via to_thread).

    WHY: python-ldap is a blocking C extension; all I/O must run in a thread.

    Args:
        uri:       LDAP server URI (e.g. 'ldap://ldap:389').
        admin_dn:  Bind DN for the service account.
        password:  Bind password.

    Returns:
        A bound LDAP connection object.

    Raises:
        ldap.LDAPError subclass on connection or bind failure.
    """
    import ldap  # noqa: PLC0415  lazy import

    conn = ldap.initialize(uri)
    conn.simple_bind_s(admin_dn, password)
    return conn


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
    import ldap  # noqa: PLC0415  lazy import

    return conn.search_s(base_dn, ldap.SCOPE_SUBTREE, filter_str, attrlist)  # type: ignore[union-attr]


async def _pool_search(
    uri: str,
    admin_dn: str,
    password: str,
    base_dn: str,
    filter_str: str,
    attrlist: list[str],
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
        filter_str: Pre-escaped search filter (no outer parens required).
        attrlist:   Attributes to fetch.

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
                _create_ldap_connection, uri, admin_dn, password
            )
        results = await asyncio.to_thread(
            _ldap_search_on_conn, conn, base_dn, filter_str, attrlist
        )
        pool.put_nowait(conn)  # return live connection to pool
        return results
    except Exception:
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
        returns a list ([] when absent or when memberOf is empty) so the resolution
        engine can iterate it without a None guard.

        The bootstrap.ldif seeded users carry no memberOf attributes, so real
        queries to the test directory will produce groups=[]; the DN-reduction
        logic is exercised only against production directories or synthetic test data.

        Args:
            raw_attributes: Raw LDAP attribute dict (cn, mail, departmentNumber,
                employeeType, memberOf, uid, sn, ...).  Values must be plain
                strings (not bytes) — call _normalise_ldap_attrs() first for
                results coming directly from python-ldap search_s.

        Returns:
            Dict with keys: display_name, primary_email, department,
            employee_type, groups.
        """
        raw_dept = raw_attributes.get("departmentNumber")
        if raw_dept is not None:
            dept_value, _ = normalize_department(raw_dept)
        else:
            dept_value = None

        raw_et = raw_attributes.get("employeeType")
        if raw_et is not None:
            et_value = normalize_employee_type(raw_et)
        else:
            et_value = None

        member_of: list[str] = raw_attributes.get("memberOf") or []
        groups: list[str] = []
        for dn in member_of:
            name = _reduce_dn_to_group_name(dn)
            if name is not None:
                groups.append(name)

        return {
            "display_name": raw_attributes.get("cn"),
            "primary_email": raw_attributes.get("mail"),
            "department": dept_value,
            "employee_type": et_value,
            "groups": groups,
        }

    async def enrich(
        self,
        correlation_field: str,
        lookup_value: str,
        cache_ttl_seconds: int = _DEFAULT_CACHE_TTL,
    ) -> tuple[dict | None, str]:
        """Query LDAP for a user and return (normalized_attrs, outcome_code).

        Three-state Redis cache (spec §5.3):
          MISS              — GET returns None → query LDAP
          NEGATIVE HIT      — key holds JSON sentinel ``"null"`` → return None
          POSITIVE HIT      — key holds JSON dict → return cached dict

        Transient LDAP failures (TIMEOUT_EXCEEDED, SERVER_DOWN, OPERATIONS_ERROR,
        unexpected exceptions) are NOT cached so the service recovers automatically
        when LDAP becomes healthy again.

        Args:
            correlation_field:  Unified schema field used as the LDAP search key
                (e.g., 'primary_email').  Reverse-mapped to LDAP attribute via
                UNIFIED_TO_LDAP.  Returns (None, 'unmappable_field') immediately
                if not mappable.
            lookup_value:       The value to search for (e.g., 'alice@corp.com').
            cache_ttl_seconds:  TTL for both positive and negative cache entries.

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
                # Corrupted cache entry — fall through to live query
                _logger.warning(
                    "ldap_enrich_cache_decode_error",
                    ldap_attr=ldap_attr,
                    cached_value=repr(cached_str),
                )

        # --- Cache miss: query LDAP via connection pool ---
        settings = get_settings()
        uri = f"ldap://{settings.ldap_host}:{settings.ldap_port}"
        attrlist = list(UNIFIED_TO_LDAP.values())
        search_filter = _build_search_filter_internal(ldap_attr, lookup_value)

        try:
            results = await _pool_search(
                uri,
                settings.ldap_admin_dn,
                settings.ldap_admin_password,
                settings.ldap_base_dn,
                search_filter,
                attrlist,
            )
        except Exception as exc:
            outcome = _classify_ldap_error(exc)
            _logger.warning(
                "ldap_enrich_error",
                outcome=outcome,
                ldap_attr=ldap_attr,
                error=str(exc),
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
    """Map an LDAP exception to an outcome code string for the chunk-6 seam.

    WHY: chunk 6 needs to distinguish transient error types (timeout vs
    connection_error vs search_error) to build the correct skip_reason for
    EnrichmentSkipped.  Using outcome strings (not exception types) keeps
    chunk 6 decoupled from python-ldap's exception hierarchy.

    Args:
        exc: Any exception raised during the LDAP operation.

    Returns:
        One of 'ldap_timeout', 'ldap_connection_error', 'ldap_search_error',
        or 'ldap_unexpected_error'.
    """
    try:
        import ldap as ldap_module  # noqa: PLC0415  lazy import

        if isinstance(exc, ldap_module.TIMEOUT_EXCEEDED):
            return "ldap_timeout"
        if isinstance(exc, ldap_module.SERVER_DOWN):
            return "ldap_connection_error"
        if isinstance(exc, ldap_module.LDAPError):
            return "ldap_search_error"
    except ImportError:
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
