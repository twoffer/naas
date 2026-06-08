"""Constant value contract for naas_shared.constants.

Verifies exact string and integer values for every constant in §3.3.
Any drift causes consumers to publish to the wrong stream or consumer group.
"""

from __future__ import annotations



class TestConstants:
    """Exact constant values from §3.3.

    Any drift causes consumers to publish to the wrong stream or read from
    the wrong consumer group.
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
        """STREAM_MAXLEN must equal 10000 (int).

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
        """All three consumer group names must be distinct.

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
