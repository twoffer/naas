# Component: NAAS Spec 0 — Chunk 2: Shared Python library (naas_shared)
# Mode: TDD — all tests MUST fail until the chunk is implemented
#
# What these tests validate:
#   - Package import surface (§4, §6.6): smoke-test imports and runtime calls succeed
#   - constants.py (§3.3): exact string/int values for every constant
#   - models.py (§3.4): Pydantic validation contracts for all pipeline message schemas
#   - config.py (§3.8): Settings defaults and database_url / database_url_sync properties
#   - Placeholder modules: schemas.py (Gap-5 comment, no ORM tables),
#     ml_features.py, simulation_tools.py (import without error, no fabricated content)
#
# Why this matters:
#   naas_shared is the keystone package for the entire NAAS pipeline.  Every
#   downstream service (Specs 1-6) imports from it.  Wrong constant values →
#   consumers publish to the wrong streams.  Wrong Pydantic contracts → silent
#   data corruption across service boundaries.  Wrong database_url scheme →
#   asyncpg connection failures at runtime.  These tests are the gate for all
#   subsequent implementation work.
#
# Import strategy:
#   sys.path.insert(0, str(REPO_ROOT / "shared")) is used so that once the
#   implementer creates shared/naas_shared/ the tests resolve imports directly
#   from source, without requiring a `pip install -e shared/` reinstall step.
#   This mirrors the §6.6 shell snippet (`cd shared && python3 -c "..."`).
#   Currently the tests fail with ModuleNotFoundError because shared/ does not
#   exist yet.  After the implementer creates the package and `pip install -e
#   shared/` runs (which brings in pydantic, structlog, etc.), all tests here
#   should turn green.

# stdlib
import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find the directory containing
    docs/architecture/ — that is the repo root."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "docs" / "architecture").is_dir():
            return candidate
        candidate = candidate.parent
    raise RuntimeError(
        "Could not locate repo root (expected directory containing docs/architecture/). "
        f"Started from: {Path(__file__).resolve()}"
    )


REPO_ROOT = _find_repo_root()
SHARED_DIR = REPO_ROOT / "shared"

# Inject shared/ onto sys.path so imports resolve once source exists.
# This is the pragmatic approach that matches the spec's §6.6 shell test.
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


# ---------------------------------------------------------------------------
# Test data — deterministic, from the system prompt reference set
# ---------------------------------------------------------------------------

VALID_USER_ID = "alice"
VALID_CLIENT_IP = "192.168.1.1"
VALID_TIMESTAMP = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
REFERENCE_UUID = "12345678-1234-5678-1234-567812345678"


# ---------------------------------------------------------------------------
# 1. Package import surface (§4, §6.6)
# ---------------------------------------------------------------------------


class TestPackageImportSurface:
    """
    Verify that the smoke-test import set from §6.6 all resolve without error.
    These are the imports every downstream service will execute at startup.
    A ModuleNotFoundError here is a total service failure.
    """

    def test_import_get_settings_from_config(self):
        """
        from naas_shared.config import get_settings must succeed.
        get_settings() is used by every service to read environment configuration.
        """
        from naas_shared.config import get_settings  # noqa: F401

    def test_import_login_event_ingest_from_models(self):
        """
        from naas_shared.models import LoginEventIngest must succeed.
        Used by event-ingestion service for request body validation.
        """
        from naas_shared.models import LoginEventIngest  # noqa: F401

    def test_import_risk_decision_from_models(self):
        """
        from naas_shared.models import RiskDecision must succeed.
        Published to the decisions Pub/Sub channel by risk-evaluator.
        """
        from naas_shared.models import RiskDecision  # noqa: F401

    def test_import_alert_message_from_models(self):
        """
        from naas_shared.models import AlertMessage must succeed.
        Published to the alerts Pub/Sub channel by alert-service.
        """
        from naas_shared.models import AlertMessage  # noqa: F401

    def test_import_stream_login_events_from_constants(self):
        """
        from naas_shared.constants import STREAM_LOGIN_EVENTS must succeed.
        Consumers reference this constant — wrong name → silent pipeline break.
        """
        from naas_shared.constants import STREAM_LOGIN_EVENTS  # noqa: F401

    def test_import_channel_decisions_from_constants(self):
        """
        from naas_shared.constants import CHANNEL_DECISIONS must succeed.
        Risk evaluator publishes to this channel for dashboard / alert-service.
        """
        from naas_shared.constants import CHANNEL_DECISIONS  # noqa: F401

    def test_import_setup_logging_from_logging(self):
        """
        from naas_shared.logging import setup_logging must succeed.
        Called at service startup to configure structlog JSON output.
        """
        from naas_shared.logging import setup_logging  # noqa: F401

    def test_setup_logging_call_does_not_raise(self):
        """
        setup_logging('test') must complete without raising.
        The §6.6 smoke test calls this directly.
        """
        from naas_shared.logging import setup_logging

        setup_logging("test")  # must not raise

    def test_get_settings_returns_settings_instance(self):
        """
        get_settings() must return a Settings object (not None, not raise).
        Called at startup by every service that needs DB/Redis/LDAP config.
        """
        from naas_shared.config import get_settings

        settings = get_settings()
        assert settings is not None, "get_settings() returned None"

    def test_database_url_starts_with_asyncpg_scheme(self):
        """
        settings.database_url must start with 'postgresql+asyncpg://'.
        asyncpg is the async driver required by SQLAlchemy create_async_engine.
        A wrong scheme causes an engine creation error at service startup.
        """
        from naas_shared.config import get_settings

        url = get_settings().database_url
        assert url.startswith("postgresql+asyncpg://"), (
            f"Expected database_url to start with 'postgresql+asyncpg://', got: {url!r}"
        )

    def test_database_url_sync_starts_with_sync_scheme(self):
        """
        settings.database_url_sync must start with 'postgresql://' (no +asyncpg).
        Used by Alembic and any sync context.  asyncpg in the sync URL would
        cause a driver-not-found error.
        """
        from naas_shared.config import get_settings

        url_sync = get_settings().database_url_sync
        assert url_sync.startswith("postgresql://"), (
            f"Expected database_url_sync to start with 'postgresql://', got: {url_sync!r}"
        )
        assert "+asyncpg" not in url_sync, (
            f"database_url_sync must NOT contain '+asyncpg', got: {url_sync!r}"
        )

    def test_full_import_set_from_spec_section_4(self):
        """
        The complete canonical import block from §4 must succeed in one pass.
        This test mirrors exactly what each service does at the top of its module.
        """
        from naas_shared.constants import (  # noqa: F401
            CHANNEL_ALERTS,
            CHANNEL_DECISIONS,
            GROUP_ENRICHMENT,
            GROUP_EVALUATOR,
            GROUP_NORMALIZATION,
            STREAM_ENRICHED_EVENTS,
            STREAM_LOGIN_EVENTS,
            STREAM_NORMALIZED_EVENTS,
        )
        from naas_shared.database import get_db_session, get_engine  # noqa: F401
        from naas_shared.logging import get_logger, setup_logging  # noqa: F401
        from naas_shared.models import (  # noqa: F401
            AlertMessage,
            HealthResponse,
            LoginEventBase,
            LoginEventIngest,
            LoginEventRecord,
            NormalizedAttributes,
            RiskDecision,
        )
        from naas_shared.redis_client import (  # noqa: F401
            ensure_consumer_group,
            get_redis,
            publish_to_channel,
            publish_to_stream,
        )


# ---------------------------------------------------------------------------
# 2. constants.py (§3.3)
# ---------------------------------------------------------------------------


class TestConstants:
    """
    Exact constant values from §3.3.  Any drift causes consumers to publish
    to the wrong stream or read from the wrong consumer group.
    """

    # --- Stream names ---

    def test_stream_login_events_exact_value(self):
        """STREAM_LOGIN_EVENTS must equal 'login_events' (exact string)."""
        from naas_shared.constants import STREAM_LOGIN_EVENTS

        assert STREAM_LOGIN_EVENTS == "login_events", (
            f"Expected 'login_events', got {STREAM_LOGIN_EVENTS!r}"
        )

    def test_stream_normalized_events_exact_value(self):
        """STREAM_NORMALIZED_EVENTS must equal 'normalized_events'."""
        from naas_shared.constants import STREAM_NORMALIZED_EVENTS

        assert STREAM_NORMALIZED_EVENTS == "normalized_events", (
            f"Expected 'normalized_events', got {STREAM_NORMALIZED_EVENTS!r}"
        )

    def test_stream_enriched_events_exact_value(self):
        """STREAM_ENRICHED_EVENTS must equal 'enriched_events'."""
        from naas_shared.constants import STREAM_ENRICHED_EVENTS

        assert STREAM_ENRICHED_EVENTS == "enriched_events", (
            f"Expected 'enriched_events', got {STREAM_ENRICHED_EVENTS!r}"
        )

    def test_stream_maxlen_is_10000(self):
        """
        STREAM_MAXLEN must equal 10000 (int).
        This caps each Redis Stream to prevent unbounded memory growth.
        Wrong value → either OOM (too high) or lost events (too low).
        """
        from naas_shared.constants import STREAM_MAXLEN

        assert STREAM_MAXLEN == 10000, (
            f"Expected STREAM_MAXLEN == 10000, got {STREAM_MAXLEN!r}"
        )
        assert isinstance(STREAM_MAXLEN, int), (
            f"STREAM_MAXLEN must be int, got {type(STREAM_MAXLEN)}"
        )

    # --- Pub/Sub channel names ---

    def test_channel_decisions_exact_value(self):
        """CHANNEL_DECISIONS must equal 'decisions'."""
        from naas_shared.constants import CHANNEL_DECISIONS

        assert CHANNEL_DECISIONS == "decisions", (
            f"Expected 'decisions', got {CHANNEL_DECISIONS!r}"
        )

    def test_channel_alerts_exact_value(self):
        """CHANNEL_ALERTS must equal 'alerts'."""
        from naas_shared.constants import CHANNEL_ALERTS

        assert CHANNEL_ALERTS == "alerts", f"Expected 'alerts', got {CHANNEL_ALERTS!r}"

    # --- Consumer group names ---

    def test_group_normalization_exists(self):
        """GROUP_NORMALIZATION must be defined and be a non-empty string."""
        from naas_shared.constants import GROUP_NORMALIZATION

        assert isinstance(GROUP_NORMALIZATION, str), (
            f"GROUP_NORMALIZATION must be str, got {type(GROUP_NORMALIZATION)}"
        )
        assert GROUP_NORMALIZATION, "GROUP_NORMALIZATION must not be empty"

    def test_group_enrichment_exists(self):
        """GROUP_ENRICHMENT must be defined and be a non-empty string."""
        from naas_shared.constants import GROUP_ENRICHMENT

        assert isinstance(GROUP_ENRICHMENT, str), (
            f"GROUP_ENRICHMENT must be str, got {type(GROUP_ENRICHMENT)}"
        )
        assert GROUP_ENRICHMENT, "GROUP_ENRICHMENT must not be empty"

    def test_group_evaluator_exists(self):
        """GROUP_EVALUATOR must be defined and be a non-empty string."""
        from naas_shared.constants import GROUP_EVALUATOR

        assert isinstance(GROUP_EVALUATOR, str), (
            f"GROUP_EVALUATOR must be str, got {type(GROUP_EVALUATOR)}"
        )
        assert GROUP_EVALUATOR, "GROUP_EVALUATOR must not be empty"

    def test_group_names_are_distinct(self):
        """
        All three consumer group names must be distinct.
        Sharing a group name between services would cause each service to
        receive only a fraction of the messages (round-robin delivery).
        """
        from naas_shared.constants import (
            GROUP_ENRICHMENT,
            GROUP_EVALUATOR,
            GROUP_NORMALIZATION,
        )

        groups = [GROUP_NORMALIZATION, GROUP_ENRICHMENT, GROUP_EVALUATOR]
        assert len(set(groups)) == 3, (
            f"Consumer group names must all be distinct, got: {groups}"
        )

    # --- Cache TTLs ---

    def test_cache_policy_ttl_is_60(self):
        """CACHE_POLICY_TTL must equal 60 (seconds)."""
        from naas_shared.constants import CACHE_POLICY_TTL

        assert CACHE_POLICY_TTL == 60, (
            f"Expected CACHE_POLICY_TTL == 60, got {CACHE_POLICY_TTL!r}"
        )

    def test_cache_ip_rep_ttl_is_86400(self):
        """CACHE_IP_REP_TTL must equal 86400 (24 hours in seconds)."""
        from naas_shared.constants import CACHE_IP_REP_TTL

        assert CACHE_IP_REP_TTL == 86400, (
            f"Expected CACHE_IP_REP_TTL == 86400 (24h), got {CACHE_IP_REP_TTL!r}"
        )

    def test_cache_geo_ttl_is_604800(self):
        """CACHE_GEO_TTL must equal 604800 (7 days in seconds)."""
        from naas_shared.constants import CACHE_GEO_TTL

        assert CACHE_GEO_TTL == 604800, (
            f"Expected CACHE_GEO_TTL == 604800 (7d), got {CACHE_GEO_TTL!r}"
        )

    def test_cache_jwks_ttl_is_300(self):
        """CACHE_JWKS_TTL must equal 300 (5 minutes in seconds)."""
        from naas_shared.constants import CACHE_JWKS_TTL

        assert CACHE_JWKS_TTL == 300, (
            f"Expected CACHE_JWKS_TTL == 300 (5min), got {CACHE_JWKS_TTL!r}"
        )

    def test_cache_feature_flags_ttl_is_60(self):
        """CACHE_FEATURE_FLAGS_TTL must equal 60 (seconds)."""
        from naas_shared.constants import CACHE_FEATURE_FLAGS_TTL

        assert CACHE_FEATURE_FLAGS_TTL == 60, (
            f"Expected CACHE_FEATURE_FLAGS_TTL == 60, got {CACHE_FEATURE_FLAGS_TTL!r}"
        )


# ---------------------------------------------------------------------------
# 3. models.py (§3.4)
# ---------------------------------------------------------------------------


class TestLoginEventIngestValidation:
    """
    LoginEventIngest is the request body for POST /events/ingest.
    Strict validation here is the first line of defense against malformed events.
    """

    def test_login_event_ingest_accepts_valid_oidc_event(self):
        """
        LoginEventIngest must accept a well-formed event with protocol='oidc',
        a valid dotted-quad IP, a user_id, and a timestamp.
        This is the happy path that the entire pipeline depends on.
        """
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )

        assert event.user_id == VALID_USER_ID, (
            f"Expected user_id={VALID_USER_ID!r}, got {event.user_id!r}"
        )
        assert event.protocol == "oidc", (
            f"Expected protocol='oidc', got {event.protocol!r}"
        )
        assert event.client_ip == VALID_CLIENT_IP, (
            f"Expected client_ip={VALID_CLIENT_IP!r}, got {event.client_ip!r}"
        )

    def test_login_event_ingest_accepts_saml_protocol(self):
        """LoginEventIngest must accept protocol='saml'."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="saml",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.protocol == "saml"

    def test_login_event_ingest_accepts_ldap_protocol(self):
        """LoginEventIngest must accept protocol='ldap'."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="ldap",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.protocol == "ldap"

    def test_login_event_ingest_rejects_invalid_ip_not_dotted_quad(self):
        """
        LoginEventIngest must raise ValidationError for client_ip='not-an-ip'.
        The client_ip field has a regex pattern requiring a dotted-quad format.
        Accepting invalid IPs would break signal-enrichment's IP reputation lookup.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError, match="client_ip"):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="not-an-ip",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_rejects_hostname_as_ip(self):
        """
        client_ip='example.com' must raise ValidationError.
        Only dotted-quad format is accepted — hostnames are not valid.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="example.com",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_rejects_out_of_range_octet(self):
        """
        client_ip='256.0.0.1' must raise ValidationError.
        The tightened pattern accepts only octets in 0-255; a value that is
        well-shaped (four dot-separated groups) but numerically invalid must be
        rejected at the ingestion boundary so malformed IPs never reach the
        geolocation, IP-reputation, or impossible-travel enrichers.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="256.0.0.1",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_rejects_all_octets_out_of_range(self):
        """
        client_ip='999.999.999.999' must raise ValidationError.
        The prior shape-only pattern accepted this value (four groups of one-to-
        three digits); the tightened octet-bounded pattern rejects it. This test
        locks in the regression so the old shape-only behavior cannot return.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="999.999.999.999",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_rejects_leading_zero_octet(self):
        """
        client_ip='192.168.001.1' must raise ValidationError.
        The tightened pattern disallows leading-zero octet forms, which are
        ambiguous (octal-looking) and not a canonical dotted-quad representation.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip="192.168.001.1",
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_accepts_max_octet_boundary(self):
        """
        client_ip='255.255.255.255' must be accepted.
        255 is the upper boundary of a valid octet; the tightened pattern must
        still admit well-formed addresses at the boundary, not just reject the
        out-of-range ones.
        """
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip="255.255.255.255",
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.client_ip == "255.255.255.255"

    def test_login_event_ingest_rejects_unknown_protocol(self):
        """
        LoginEventIngest must raise ValidationError for protocol='kerberos'.
        Only oidc/saml/ldap are valid per the Literal constraint in §3.4.
        An unknown protocol reaching the pipeline would break normalization routing.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip=VALID_CLIENT_IP,
                protocol="kerberos",  # not in Literal["oidc", "saml", "ldap"]
                timestamp=VALID_TIMESTAMP,
            )

    def test_login_event_ingest_default_source_is_user(self):
        """source defaults to 'user' when not specified."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.source == "user", (
            f"Expected default source='user', got {event.source!r}"
        )

    def test_login_event_ingest_default_is_synthetic_false(self):
        """is_synthetic defaults to False when not specified."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.is_synthetic is False

    def test_login_event_ingest_default_is_historical_false(self):
        """
        is_historical defaults to False.
        is_historical=True events must never trigger alerts — this default
        ensures normal events are treated as live unless explicitly marked.
        """
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.is_historical is False

    def test_login_event_ingest_accepts_simulator_source(self):
        """source='simulator' is a valid value (used by persona-simulator)."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            source="simulator",
            is_synthetic=True,
        )
        assert event.source == "simulator"
        assert event.is_synthetic is True

    def test_login_event_ingest_rejects_empty_user_id(self):
        """
        user_id must have min_length=1.
        An empty user_id cannot be correlated with any identity record.
        """
        from pydantic import ValidationError

        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id="",
                client_ip=VALID_CLIENT_IP,
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )


class TestLoginEventTimestampValidator:
    """LoginEventBase.timestamp must always be normalized to an aware UTC instant.

    The field_validator on LoginEventBase runs for both LoginEventIngest and
    LoginEventRecord (via inheritance), so a single class covers the contract
    for all inbound event timestamps before they reach any pipeline stage.
    """

    def test_naive_datetime_becomes_aware_utc(self) -> None:
        """A naive datetime (no tzinfo) must be returned as UTC-aware.

        WHY: Naive timestamps submitted without a timezone offset would otherwise
        be interpreted according to the PostgreSQL session timezone, which could
        silently shift the stored instant.  The validator pins naive inputs to UTC.
        """
        from naas_shared.models import LoginEventIngest

        naive_ts = datetime(2026, 6, 3, 14, 5, 0)  # no tzinfo
        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=naive_ts,
        )
        assert event.timestamp.tzinfo is not None, (
            "Naive timestamp must be given UTC tzinfo by the validator."
        )
        # Wall-clock must be unchanged (not shifted)
        assert event.timestamp.replace(tzinfo=None) == naive_ts, (
            "Validator must not shift the wall-clock value of a naive timestamp."
        )

    def test_offset_aware_timestamp_normalized_to_utc(self) -> None:
        """An offset-aware timestamp from a non-UTC zone must be converted to UTC.

        WHY: A +05:00 timestamp at 19:05 represents UTC 14:05. The pipeline must
        store the UTC instant so that impossible-travel and recency calculations
        are deterministic across all submitting clients.
        """
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T19:05:00+05:00",
        )
        assert event.timestamp.tzinfo is not None, (
            "Offset-aware timestamp must remain aware after normalization."
        )
        expected_utc = datetime(2026, 6, 3, 14, 5, 0, tzinfo=timezone.utc)
        assert event.timestamp == expected_utc, (
            f"Expected UTC equivalent {expected_utc!r}, got {event.timestamp!r}."
        )

    def test_z_suffix_timestamp_stays_utc_aware(self) -> None:
        """A 'Z' suffix timestamp must remain an aware UTC datetime.

        WHY: The Z suffix is the most common form submitted by API clients and the
        persona simulator.  The validator must accept it without error and leave the
        UTC value unchanged.
        """
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T14:05:00Z",
        )
        assert event.timestamp.tzinfo is not None, (
            "'Z' timestamp must be UTC-aware after validation."
        )
        expected_utc = datetime(2026, 6, 3, 14, 5, 0, tzinfo=timezone.utc)
        assert event.timestamp == expected_utc, (
            f"Expected {expected_utc!r}, got {event.timestamp!r}."
        )

    def test_login_event_record_created_at_default_is_aware(self) -> None:
        """LoginEventRecord().created_at must be timezone-aware by default.

        WHY: The aware default (datetime.now(timezone.utc)) replaces the legacy
        datetime.utcnow() which returned a naive datetime.  A naive created_at
        could be misinterpreted by downstream consumers that compare it against
        aware timestamps from the DB (TIMESTAMPTZ columns return aware datetimes
        via asyncpg), causing comparison errors or silent offsets.
        """
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert record.created_at.tzinfo is not None, (
            "LoginEventRecord.created_at default must be timezone-aware (UTC)."
        )

    def test_explicit_naive_created_at_is_normalized_to_utc(self) -> None:
        """An explicitly-supplied naive created_at must be normalized to aware UTC.

        WHY: Pydantic lets callers override the aware default by passing created_at
        explicitly (e.g. reconstructing a record from a serialized stream payload).
        Without a validator on the field, a naive value would be stored unnormalized
        — the same ambiguity the timestamp validator eliminates.  This locks
        created_at to be safe-by-construction, not just by the default factory.
        """
        from naas_shared.models import LoginEventRecord

        naive_created = datetime(2026, 6, 3, 14, 5, 0)  # no tzinfo
        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            created_at=naive_created,
        )
        assert record.created_at.tzinfo is not None, (
            "Explicit naive created_at must be given UTC tzinfo by the validator."
        )
        assert record.created_at.replace(tzinfo=None) == naive_created, (
            "Validator must not shift the wall-clock value of a naive created_at."
        )

    def test_explicit_offset_created_at_normalized_to_utc_instant(self) -> None:
        """An explicit offset-aware created_at must be converted to the UTC instant."""
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            created_at="2026-06-03T19:05:00+05:00",
        )
        expected_utc = datetime(2026, 6, 3, 14, 5, 0, tzinfo=timezone.utc)
        assert record.created_at == expected_utc, (
            f"Expected UTC equivalent {expected_utc!r}, got {record.created_at!r}."
        )

    def test_json_serialized_timestamp_carries_utc_offset(self) -> None:
        """The JSON-serialized timestamp must carry an explicit UTC offset.

        WHY: The login event is dual-written to PostgreSQL and the Redis stream.
        The Redis payload is record.model_dump(mode="json").  If the serialized
        timestamp dropped its offset, the stream and the DB could disagree about
        the instant.  This locks the textual representation at the serialization
        boundary even for a naive submission.
        """
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=datetime(2026, 6, 3, 14, 5, 0),  # naive submission
        )
        dumped = record.model_dump(mode="json")["timestamp"]
        assert dumped.endswith("+00:00") or dumped.endswith("Z"), (
            f"Serialized timestamp must carry an explicit UTC offset, got {dumped!r}."
        )

    def test_json_serialized_created_at_carries_utc_offset(self) -> None:
        """The JSON-serialized created_at must carry an explicit UTC offset.

        WHY: created_at is part of the Redis stream payload too
        (record.model_dump(mode="json")).  Even when supplied explicitly as a
        naive value, the serialized form must carry an offset so the stream and
        any consumer agree on the instant — symmetric with the timestamp guarantee.
        """
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            created_at=datetime(2026, 6, 3, 14, 5, 0),  # explicit naive
        )
        dumped = record.model_dump(mode="json")["created_at"]
        assert dumped.endswith("+00:00") or dumped.endswith("Z"), (
            f"Serialized created_at must carry an explicit UTC offset, got {dumped!r}."
        )

    def test_naive_and_equivalent_offset_yield_same_instant(self) -> None:
        """A naive UTC submission and its equivalent offset form must store the same instant.

        WHY: End-to-end guarantee that there is no ambiguity in how timestamps are
        normalized — submitting "14:05" (treated as UTC) and "19:05+05:00" must
        produce the identical stored UTC instant in both sinks.
        """
        from naas_shared.models import LoginEventIngest

        naive_event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T14:05:00",  # naive -> treated as UTC
        )
        offset_event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T19:05:00+05:00",  # same instant as 14:05 UTC
        )
        assert naive_event.timestamp == offset_event.timestamp, (
            "Naive-as-UTC and equivalent offset submissions must normalize to the "
            "same UTC instant."
        )


class TestRiskDecisionValidation:
    """
    RiskDecision is published to the decisions Pub/Sub channel.
    The decision field is the authoritative access control outcome — wrong values
    are a security vulnerability.
    """

    def _valid_decision_kwargs(self, decision: str) -> dict:
        return {
            "event_id": "evt-001",
            "user_id": VALID_USER_ID,
            "rule_based_score": 0.3,
            "final_score": 0.3,
            "decision": decision,
            "timestamp": VALID_TIMESTAMP,
        }

    def test_risk_decision_accepts_allow(self):
        """decision='allow' is a valid access control outcome."""
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("allow"))
        assert d.decision == "allow"

    def test_risk_decision_accepts_step_up_mfa(self):
        """decision='step_up_mfa' is a valid access control outcome."""
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("step_up_mfa"))
        assert d.decision == "step_up_mfa"

    def test_risk_decision_accepts_deny(self):
        """decision='deny' is a valid access control outcome."""
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("deny"))
        assert d.decision == "deny"

    def test_risk_decision_rejects_challenge(self):
        """
        decision='challenge' must raise ValidationError.
        Only allow/step_up_mfa/deny are in the Literal — 'challenge' is not a
        valid NAAS decision and must never reach the pipeline as a silent default.
        """
        from pydantic import ValidationError

        from naas_shared.models import RiskDecision

        with pytest.raises(ValidationError):
            RiskDecision(**self._valid_decision_kwargs("challenge"))

    def test_risk_decision_rejects_unknown_decision(self):
        """
        An arbitrary unknown string like 'block' must raise ValidationError.
        Unknown decisions are a fail-open security risk.
        """
        from pydantic import ValidationError

        from naas_shared.models import RiskDecision

        with pytest.raises(ValidationError):
            RiskDecision(**self._valid_decision_kwargs("block"))

    def test_risk_decision_is_historical_defaults_to_false(self):
        """
        is_historical defaults to False on RiskDecision.
        Critical: is_historical=True events must never trigger alerts.
        The default must be False so live events are correctly identified.
        """
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("allow"))
        assert d.is_historical is False

    def test_risk_decision_shadow_fields_are_optional(self):
        """
        shadow_decision and shadow_score are Optional — may be None.
        Shadow mode means a parallel policy is evaluated without affecting
        the real decision; its fields are absent in non-shadow flows.
        """
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("allow"))
        assert d.shadow_decision is None
        assert d.shadow_score is None

    def test_risk_decision_shadow_decision_present_when_provided(self):
        """
        shadow_decision survives roundtrip when explicitly set.
        Shadow mode: shadow_decision reflects the shadow policy outcome,
        decision reflects the real policy outcome — they are independent.
        """
        from naas_shared.models import RiskDecision

        kwargs = self._valid_decision_kwargs("allow")
        kwargs["shadow_decision"] = "deny"
        kwargs["shadow_score"] = 0.85
        d = RiskDecision(**kwargs)
        assert d.shadow_decision == "deny", (
            f"Expected shadow_decision='deny', got {d.shadow_decision!r}"
        )
        assert d.shadow_score == 0.85


class TestNormalizedAttributesValidation:
    """
    NormalizedAttributes is stored in events.normalized_attributes JSONB and
    read by both the Risk Evaluator and the Dashboard.  The enrichment field
    is mandatory — its absence means the normalization service failed to record
    its LDAP enrichment decision, which is a pipeline integrity violation.
    """

    def test_normalized_attributes_requires_enrichment_field(self):
        """
        NormalizedAttributes without an enrichment field must raise ValidationError.
        enrichment is mandatory per §3.4: 'always populated; even LDAP events
        get EnrichmentSkipped(applied=False, skip_reason="ldap_event")'.
        Absence means the normalization service produced an incomplete record.
        """
        from pydantic import ValidationError

        from naas_shared.models import NormalizedAttributes

        with pytest.raises(ValidationError):
            NormalizedAttributes(source_protocol="oidc")  # missing enrichment

    def test_normalized_attributes_requires_source_protocol(self):
        """
        source_protocol is required (no default).  Without it we cannot
        determine which adapter produced the record or route enrichment.
        """
        from pydantic import ValidationError

        from naas_shared.models import NormalizedAttributes, EnrichmentSkipped

        with pytest.raises(ValidationError):
            NormalizedAttributes(
                enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event")
                # missing source_protocol
            )

    def test_normalized_attributes_accepts_enrichment_skipped_ldap_event(self):
        """
        NormalizedAttributes with EnrichmentSkipped(skip_reason='ldap_event')
        must validate.  LDAP events always skip enrichment — this is the most
        common skip_reason in the pipeline.
        """
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="ldap",
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event"),
        )
        assert attrs.enrichment.applied is False
        assert attrs.enrichment.skip_reason == "ldap_event"

    def test_normalized_attributes_accepts_enrichment_applied(self):
        """
        NormalizedAttributes with EnrichmentApplied(source='ldap', cache_hit=False)
        must validate.  This is the success path for OIDC/SAML LDAP enrichment.
        """
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="oidc",
            enrichment=EnrichmentApplied(applied=True, source="ldap", cache_hit=False),
        )
        assert attrs.enrichment.applied is True
        assert attrs.enrichment.source == "ldap"
        assert attrs.enrichment.cache_hit is False

    def test_normalized_attributes_enrichment_applied_cache_hit_true(self):
        """
        cache_hit=True must be preserved on EnrichmentApplied.
        The Dashboard uses cache_hit to show LDAP enrichment performance metrics.
        """
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="saml",
            enrichment=EnrichmentApplied(applied=True, source="ldap", cache_hit=True),
        )
        assert attrs.enrichment.cache_hit is True

    def test_normalized_attributes_discriminated_union_applied_true(self):
        """
        model_validate with {'applied': True, 'source': 'ldap', 'cache_hit': False}
        must resolve to EnrichmentApplied variant via the discriminator.
        The discriminator 'applied' is how the Risk Evaluator and Dashboard
        distinguish enrichment outcomes when deserializing JSONB.
        """
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        data = {
            "source_protocol": "oidc",
            "enrichment": {"applied": True, "source": "ldap", "cache_hit": False},
        }
        attrs = NormalizedAttributes.model_validate(data)
        assert isinstance(attrs.enrichment, EnrichmentApplied), (
            f"Expected EnrichmentApplied, got {type(attrs.enrichment)}"
        )

    def test_normalized_attributes_discriminated_union_applied_false(self):
        """
        model_validate with {'applied': False, 'skip_reason': 'no_ldap_match'}
        must resolve to EnrichmentSkipped variant.
        """
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        data = {
            "source_protocol": "saml",
            "enrichment": {"applied": False, "skip_reason": "no_ldap_match"},
        }
        attrs = NormalizedAttributes.model_validate(data)
        assert isinstance(attrs.enrichment, EnrichmentSkipped), (
            f"Expected EnrichmentSkipped, got {type(attrs.enrichment)}"
        )
        assert attrs.enrichment.skip_reason == "no_ldap_match"

    def test_normalized_attributes_all_enrichment_skip_reasons_valid(self):
        """
        All seven EnrichmentSkipReason values from §3.4 must be accepted.
        Each corresponds to a distinct failure mode in the LDAP enrichment path.
        An unknown skip_reason would indicate a bug in the normalization service.
        """
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        skip_reasons = [
            "ldap_disabled",
            "ldap_event",
            "no_ldap_match",
            "ldap_timeout",
            "ldap_connection_error",
            "ldap_search_error",
            "invalid_correlation_key",
        ]
        for reason in skip_reasons:
            attrs = NormalizedAttributes(
                source_protocol="oidc",
                enrichment=EnrichmentSkipped(applied=False, skip_reason=reason),
            )
            assert attrs.enrichment.skip_reason == reason, (
                f"skip_reason {reason!r} was not preserved"
            )

    def test_normalized_attributes_normalization_confidence_defaults_to_1(self):
        """normalization_confidence defaults to 1.0 (no conflict, full confidence)."""
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="oidc",
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_disabled"),
        )
        assert attrs.normalization_confidence == 1.0

    def test_normalized_attributes_groups_defaults_to_empty_list(self):
        """groups defaults to an empty list when not provided."""
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="oidc",
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_disabled"),
        )
        assert attrs.groups == [], f"Expected groups=[], got {attrs.groups!r}"


class TestAlertMessageValidation:
    """AlertMessage is published to the alerts Pub/Sub channel."""

    def test_alert_message_accepts_valid_data(self):
        """AlertMessage must instantiate with all required fields."""
        from naas_shared.models import AlertMessage

        msg = AlertMessage(
            alert_id="alert-001",
            event_id="evt-001",
            user_id=VALID_USER_ID,
            severity="high",
            title="Suspicious login detected",
            decision="deny",
            final_score=0.9,
            timestamp=VALID_TIMESTAMP,
        )
        assert msg.alert_id == "alert-001"
        assert msg.severity == "high"

    @pytest.mark.parametrize("severity", ["critical", "high", "medium", "low"])
    def test_alert_message_accepts_all_valid_severities(self, severity):
        """AlertMessage must accept all four valid severity levels."""
        from naas_shared.models import AlertMessage

        msg = AlertMessage(
            alert_id=f"alert-{severity}",
            event_id="evt-001",
            user_id=VALID_USER_ID,
            severity=severity,
            title="Test alert",
            decision="deny",
            final_score=0.9,
            timestamp=VALID_TIMESTAMP,
        )
        assert msg.severity == severity

    def test_alert_message_rejects_unknown_severity(self):
        """AlertMessage must reject an unknown severity like 'info'."""
        from pydantic import ValidationError

        from naas_shared.models import AlertMessage

        with pytest.raises(ValidationError):
            AlertMessage(
                alert_id="alert-001",
                event_id="evt-001",
                user_id=VALID_USER_ID,
                severity="info",  # not in Literal["critical", "high", "medium", "low"]
                title="Test",
                decision="deny",
                final_score=0.9,
                timestamp=VALID_TIMESTAMP,
            )


class TestHealthResponseValidation:
    """HealthResponse is the standard health check response for all services."""

    def test_health_response_accepts_healthy(self):
        """status='healthy' must be accepted."""
        from naas_shared.models import HealthResponse

        h = HealthResponse(status="healthy", service="test-service", version="2.0.0")
        assert h.status == "healthy"

    def test_health_response_accepts_degraded(self):
        """status='degraded' must be accepted."""
        from naas_shared.models import HealthResponse

        h = HealthResponse(status="degraded", service="test-service", version="2.0.0")
        assert h.status == "degraded"

    def test_health_response_accepts_unhealthy(self):
        """status='unhealthy' must be accepted."""
        from naas_shared.models import HealthResponse

        h = HealthResponse(status="unhealthy", service="test-service", version="2.0.0")
        assert h.status == "unhealthy"

    def test_health_response_rejects_unknown_status(self):
        """
        HealthResponse must reject status values outside {healthy, degraded, unhealthy}.
        An unknown status would prevent operators from reliably parsing health endpoints.
        """
        from pydantic import ValidationError

        from naas_shared.models import HealthResponse

        with pytest.raises(ValidationError):
            HealthResponse(
                status="ok",  # not in Literal["healthy", "degraded", "unhealthy"]
                service="test-service",
                version="2.0.0",
            )

    def test_health_response_version_defaults_to_2_0_0(self):
        """version defaults to '2.0.0' per §3.4."""
        from naas_shared.models import HealthResponse

        h = HealthResponse(status="healthy", service="test-service")
        assert h.version == "2.0.0", f"Expected version='2.0.0', got {h.version!r}"


# ---------------------------------------------------------------------------
# 4. Placeholder modules
# ---------------------------------------------------------------------------


class TestSchemasModule:
    """
    schemas.py was a Gap-5 placeholder in Spec 0 and is now populated by Spec 1
    (Base, EventORM).  Its ORM surface is covered positively by
    tests/shared/test_chunk1_orm_mapping.py; here we only smoke-test that the
    module still imports cleanly so services importing it at load time don't crash.

    (The former placeholder assertions — exact Gap-5 comment text and "no public
    names" — were retired when Spec 1 populated the module.)
    """

    def test_schemas_module_imports_without_error(self):
        """schemas.py must be importable without raising any exception."""
        import naas_shared.schemas  # noqa: F401


class TestMlFeaturesPyPlaceholder:
    """
    ml_features.py is a placeholder in Spec 0 — real content (16-feature column
    ordering) is owned by Spec 3.  We assert only that it imports cleanly.
    Asserting specific feature names here would couple the test to Spec 3 content
    that hasn't been defined yet.
    """

    def test_ml_features_module_imports_without_error(self):
        """
        ml_features.py must be importable without raising any exception.
        Services that import it at module load time must not crash on startup.
        """
        import naas_shared.ml_features  # noqa: F401

    def test_ml_features_does_not_define_feature_columns(self):
        """
        ml_features.py must NOT define a FEATURE_COLUMNS or ML_FEATURES constant
        with actual column names — that content belongs to Spec 3.
        If a placeholder accidentally defines a wrong 16-feature ordering, it
        would silently propagate an incorrect contract to training and inference.
        """
        import naas_shared.ml_features

        # Lenient: assert no ML_FEATURES or FEATURE_COLUMNS list with content
        for attr_name in ("FEATURE_COLUMNS", "ML_FEATURES", "FEATURE_NAMES"):
            if hasattr(naas_shared.ml_features, attr_name):
                value = getattr(naas_shared.ml_features, attr_name)
                assert value == [] or value is None, (
                    f"ml_features.{attr_name} must be empty or None in the placeholder "
                    f"(Spec 3 owns the real content), got: {value!r}"
                )


class TestSimulationToolsPyPlaceholder:
    """
    simulation_tools.py is a placeholder in Spec 0 — real content (tool definitions
    and ToolExecutor) is owned by a later spec.  We assert only clean import.
    """

    def test_simulation_tools_module_imports_without_error(self):
        """
        simulation_tools.py must be importable without raising any exception.
        Persona-simulator imports this at startup — a crash here stops the
        simulator from ever starting.
        """
        import naas_shared.simulation_tools  # noqa: F401

    def test_simulation_tools_does_not_define_tool_definitions(self):
        """
        simulation_tools.py must NOT define TOOL_DEFINITIONS or ToolExecutor
        with actual content — that belongs to the later spec.
        Premature definition risks an incorrect tool schema reaching the simulator.
        """
        import naas_shared.simulation_tools

        for attr_name in ("TOOL_DEFINITIONS", "ToolExecutor"):
            if hasattr(naas_shared.simulation_tools, attr_name):
                value = getattr(naas_shared.simulation_tools, attr_name)
                # Allow None or empty list/dict as placeholder
                assert value is None or value == [] or value == {}, (
                    f"simulation_tools.{attr_name} must be None/empty in the placeholder "
                    f"(later spec owns the real content), got: {value!r}"
                )


class TestAllModulesImportCleanly:
    """
    Regression guard: every module under naas_shared must import without raising.
    This catches circular imports, missing dependencies, and syntax errors that
    only surface at import time.
    """

    @pytest.mark.parametrize(
        "module_name",
        [
            "naas_shared",
            "naas_shared.constants",
            "naas_shared.config",
            "naas_shared.models",
            "naas_shared.database",
            "naas_shared.redis_client",
            "naas_shared.logging",
            "naas_shared.schemas",
            "naas_shared.ml_features",
            "naas_shared.simulation_tools",
        ],
    )
    def test_module_imports_without_error(self, module_name):
        """
        Each naas_shared module must import without raising any exception.
        A crash on import is a hard service startup failure.
        """
        module = importlib.import_module(module_name)
        assert module is not None, f"{module_name} imported as None"


# ---------------------------------------------------------------------------
# 5. config.py (§3.8)
# ---------------------------------------------------------------------------


class TestSettingsDefaults:
    """
    Settings must have defaults matching the .env.example values so that
    `docker-compose up` works out of the box.  Wrong defaults mean services
    connect to the wrong host at startup, causing failures that are hard to
    diagnose because they manifest as connection errors, not config errors.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self):
        """
        get_settings() is lru_cache'd.  Clear the cache before each test
        so env-var overrides in individual tests take effect.
        """
        from naas_shared.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_settings_instantiates_without_env_file(self):
        """
        Settings() must not raise even without a .env file.
        Tests run in environments where .env may not exist; defaults must be
        sufficient to construct the object.
        """
        from naas_shared.config import Settings

        s = Settings()
        assert s is not None

    def test_postgres_host_default_is_postgres(self):
        """
        postgres_host defaults to 'postgres' (Docker service name).
        Using 'localhost' here would break all containerized service connections.
        """
        from naas_shared.config import Settings

        s = Settings()
        assert s.postgres_host == "postgres", (
            f"Expected postgres_host='postgres', got {s.postgres_host!r}"
        )

    def test_redis_port_default_is_6379(self):
        """redis_port defaults to 6379 (standard Redis port)."""
        from naas_shared.config import Settings

        s = Settings()
        assert s.redis_port == 6379, f"Expected redis_port=6379, got {s.redis_port!r}"

    def test_keycloak_realm_default_is_naas_demo(self):
        """
        keycloak_realm defaults to 'naas-demo'.
        Must match the realm name in infrastructure/keycloak/naas-realm-export.json.
        Wrong realm → 404 on OIDC discovery, breaking the entire auth flow.
        """
        from naas_shared.config import Settings

        s = Settings()
        assert s.keycloak_realm == "naas-demo", (
            f"Expected keycloak_realm='naas-demo', got {s.keycloak_realm!r}"
        )

    def test_llm_provider_default_is_mock(self):
        """
        llm_provider defaults to 'mock'.
        This ensures the persona-simulator starts without requiring any external
        API keys in development — the most important dev-experience default.
        """
        from naas_shared.config import Settings

        s = Settings()
        assert s.llm_provider == "mock", (
            f"Expected llm_provider='mock', got {s.llm_provider!r}"
        )

    def test_database_url_property_returns_asyncpg_url(self):
        """
        Settings.database_url must return a postgresql+asyncpg:// URL using
        the configured postgres_* fields.
        """
        from naas_shared.config import Settings

        s = Settings(
            postgres_host="postgres",
            postgres_port=5432,
            postgres_user="naas",
            postgres_password="naas_dev_password",
            postgres_db="naas",
        )
        url = s.database_url
        assert url.startswith("postgresql+asyncpg://"), (
            f"Expected postgresql+asyncpg://, got {url!r}"
        )
        assert "naas" in url, f"Expected 'naas' in database_url, got {url!r}"

    def test_database_url_sync_property_returns_sync_url(self):
        """
        Settings.database_url_sync must return a plain postgresql:// URL
        without +asyncpg for Alembic / sync contexts.
        """
        from naas_shared.config import Settings

        s = Settings(
            postgres_host="postgres",
            postgres_port=5432,
            postgres_user="naas",
            postgres_password="naas_dev_password",
            postgres_db="naas",
        )
        url_sync = s.database_url_sync
        assert url_sync.startswith("postgresql://"), (
            f"Expected postgresql://, got {url_sync!r}"
        )
        assert "+asyncpg" not in url_sync, (
            f"database_url_sync must not contain '+asyncpg', got {url_sync!r}"
        )

    def test_database_url_uses_configured_host(self):
        """
        database_url must embed the configured postgres_host.
        This verifies the property assembles the URL from live field values,
        not a hardcoded string.
        """
        from naas_shared.config import Settings

        s = Settings(postgres_host="my-custom-host")
        assert "my-custom-host" in s.database_url, (
            f"Expected 'my-custom-host' in database_url, got {s.database_url!r}"
        )

    def test_database_url_sync_uses_configured_host(self):
        """database_url_sync must embed the configured postgres_host."""
        from naas_shared.config import Settings

        s = Settings(postgres_host="my-custom-host")
        assert "my-custom-host" in s.database_url_sync, (
            f"Expected 'my-custom-host' in database_url_sync, got {s.database_url_sync!r}"
        )

    def test_get_settings_is_cached(self):
        """
        get_settings() must return the same instance on repeated calls (lru_cache).
        Without caching, each call to get_settings() creates a new Settings object,
        potentially re-reading env vars on every request — a performance and
        consistency issue.
        """
        from naas_shared.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2, "get_settings() must return the same cached instance"


# ---------------------------------------------------------------------------
# 6. Package structure — pyproject.toml
# ---------------------------------------------------------------------------


class TestPyprojectToml:
    """
    shared/pyproject.toml must be present and correctly structured so that
    `pip install -e shared/` works.  Without this, every service container
    fails at build time with a 'No module named naas_shared' error.
    """

    @pytest.fixture(scope="class")
    def pyproject_path(self) -> Path:
        return SHARED_DIR / "pyproject.toml"

    @pytest.fixture(scope="class")
    def pyproject_content(self, pyproject_path) -> str:
        if not pyproject_path.exists():
            pytest.fail(
                f"shared/pyproject.toml not found at {pyproject_path} — "
                "the package cannot be installed without it"
            )
        return pyproject_path.read_text(encoding="utf-8")

    def test_pyproject_toml_exists(self, pyproject_path):
        """shared/pyproject.toml must exist for pip install -e to work."""
        assert pyproject_path.exists(), (
            f"shared/pyproject.toml not found at {pyproject_path}"
        )

    def test_pyproject_toml_declares_package_name(self, pyproject_content):
        """
        pyproject.toml must declare the package name 'naas-shared'.
        This is what appears in `pip list` and what other packages depend on.
        """
        assert 'name = "naas-shared"' in pyproject_content, (
            "pyproject.toml must contain 'name = \"naas-shared\"'"
        )

    def test_pyproject_toml_requires_python_312(self, pyproject_content):
        """requires-python must specify >=3.12 per the project tech stack."""
        assert ">=3.12" in pyproject_content, (
            "pyproject.toml must contain 'requires-python = \">=3.12\"'"
        )

    def test_pyproject_toml_declares_pydantic_dependency(self, pyproject_content):
        """pydantic is a hard runtime dependency — must be in [project].dependencies."""
        assert "pydantic>=" in pyproject_content, (
            "pyproject.toml must declare 'pydantic>=' in dependencies"
        )

    def test_pyproject_toml_declares_pydantic_settings_dependency(
        self, pyproject_content
    ):
        """pydantic-settings is required for Settings class — must be declared."""
        assert "pydantic-settings>=" in pyproject_content, (
            "pyproject.toml must declare 'pydantic-settings>=' in dependencies"
        )

    def test_pyproject_toml_declares_structlog_dependency(self, pyproject_content):
        """structlog is required for setup_logging — must be declared."""
        assert "structlog>=" in pyproject_content, (
            "pyproject.toml must declare 'structlog>=' in dependencies"
        )

    def test_pyproject_toml_declares_sqlalchemy_dependency(self, pyproject_content):
        """sqlalchemy[asyncio] is required for database.py — must be declared."""
        assert "sqlalchemy" in pyproject_content.lower(), (
            "pyproject.toml must declare sqlalchemy in dependencies"
        )

    def test_pyproject_toml_has_build_system(self, pyproject_content):
        """[build-system] section must be present for pip install -e to work."""
        assert "[build-system]" in pyproject_content, (
            "pyproject.toml must contain a [build-system] section"
        )
