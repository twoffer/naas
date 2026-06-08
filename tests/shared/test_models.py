"""Pydantic model validation contracts for naas_shared.models.

Verifies LoginEventIngest, LoginEventRecord, RiskDecision, NormalizedAttributes,
AlertMessage, and HealthResponse validation rules.  These contracts are the
gate for the entire NAAS pipeline — wrong values or missing guards here
propagate silently to every downstream service.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


VALID_USER_ID = "alice"
VALID_CLIENT_IP = "192.168.1.1"
VALID_TIMESTAMP = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


# ===========================================================================
# LoginEventIngest
# ===========================================================================


class TestLoginEventIngestValidation:
    """LoginEventIngest is the request body for POST /events/ingest.

    Strict validation here is the first line of defense against malformed events.
    """

    def test_login_event_ingest_accepts_valid_oidc_event(self):
        """LoginEventIngest must accept a well-formed event with protocol='oidc'."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )

        assert event.user_id == VALID_USER_ID
        assert event.protocol == "oidc"
        assert event.client_ip == VALID_CLIENT_IP

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
        """LoginEventIngest must raise ValidationError for client_ip='not-an-ip'."""
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
        """client_ip='example.com' must raise ValidationError."""
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
        """client_ip='256.0.0.1' must raise ValidationError."""
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
        """client_ip='999.999.999.999' must raise ValidationError."""
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
        """client_ip='192.168.001.1' must raise ValidationError."""
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
        """client_ip='255.255.255.255' must be accepted."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id=VALID_USER_ID,
            client_ip="255.255.255.255",
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert event.client_ip == "255.255.255.255"

    def test_login_event_ingest_rejects_unknown_protocol(self):
        """LoginEventIngest must raise ValidationError for protocol='kerberos'."""
        from pydantic import ValidationError
        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id=VALID_USER_ID,
                client_ip=VALID_CLIENT_IP,
                protocol="kerberos",
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
        assert event.source == "user"

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
        """is_historical defaults to False.

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
        """user_id must have min_length=1."""
        from pydantic import ValidationError
        from naas_shared.models import LoginEventIngest

        with pytest.raises(ValidationError):
            LoginEventIngest(
                user_id="",
                client_ip=VALID_CLIENT_IP,
                protocol="oidc",
                timestamp=VALID_TIMESTAMP,
            )


# ===========================================================================
# LoginEventBase timestamp validator
# ===========================================================================


class TestLoginEventTimestampValidator:
    """LoginEventBase.timestamp must always be normalized to an aware UTC instant.

    The field_validator on LoginEventBase runs for both LoginEventIngest and
    LoginEventRecord (via inheritance), so a single class covers the contract
    for all inbound event timestamps before they reach any pipeline stage.
    """

    def test_naive_datetime_becomes_aware_utc(self) -> None:
        """A naive datetime (no tzinfo) must be returned as UTC-aware."""
        from naas_shared.models import LoginEventIngest

        naive_ts = datetime(2026, 6, 3, 14, 5, 0)
        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=naive_ts,
        )
        assert event.timestamp.tzinfo is not None, (
            "Naive timestamp must be given UTC tzinfo by the validator."
        )
        assert event.timestamp.replace(tzinfo=None) == naive_ts

    def test_offset_aware_timestamp_normalized_to_utc(self) -> None:
        """An offset-aware timestamp from a non-UTC zone must be converted to UTC."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T19:05:00+05:00",
        )
        assert event.timestamp.tzinfo is not None
        expected_utc = datetime(2026, 6, 3, 14, 5, 0, tzinfo=timezone.utc)
        assert event.timestamp == expected_utc

    def test_z_suffix_timestamp_stays_utc_aware(self) -> None:
        """A 'Z' suffix timestamp must remain an aware UTC datetime."""
        from naas_shared.models import LoginEventIngest

        event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T14:05:00Z",
        )
        assert event.timestamp.tzinfo is not None
        expected_utc = datetime(2026, 6, 3, 14, 5, 0, tzinfo=timezone.utc)
        assert event.timestamp == expected_utc

    def test_login_event_record_created_at_default_is_aware(self) -> None:
        """LoginEventRecord().created_at must be timezone-aware by default."""
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
        )
        assert record.created_at.tzinfo is not None

    def test_explicit_naive_created_at_is_normalized_to_utc(self) -> None:
        """An explicitly-supplied naive created_at must be normalized to aware UTC."""
        from naas_shared.models import LoginEventRecord

        naive_created = datetime(2026, 6, 3, 14, 5, 0)
        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            created_at=naive_created,
        )
        assert record.created_at.tzinfo is not None
        assert record.created_at.replace(tzinfo=None) == naive_created

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
        assert record.created_at == expected_utc

    def test_json_serialized_timestamp_carries_utc_offset(self) -> None:
        """The JSON-serialized timestamp must carry an explicit UTC offset."""
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=datetime(2026, 6, 3, 14, 5, 0),
        )
        dumped = record.model_dump(mode="json")["timestamp"]
        assert dumped.endswith("+00:00") or dumped.endswith("Z")

    def test_json_serialized_created_at_carries_utc_offset(self) -> None:
        """The JSON-serialized created_at must carry an explicit UTC offset."""
        from naas_shared.models import LoginEventRecord

        record = LoginEventRecord(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp=VALID_TIMESTAMP,
            created_at=datetime(2026, 6, 3, 14, 5, 0),
        )
        dumped = record.model_dump(mode="json")["created_at"]
        assert dumped.endswith("+00:00") or dumped.endswith("Z")

    def test_naive_and_equivalent_offset_yield_same_instant(self) -> None:
        """A naive UTC submission and its equivalent offset form must store the same instant."""
        from naas_shared.models import LoginEventIngest

        naive_event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T14:05:00",
        )
        offset_event = LoginEventIngest(
            user_id="alice",
            client_ip=VALID_CLIENT_IP,
            protocol="oidc",
            timestamp="2026-06-03T19:05:00+05:00",
        )
        assert naive_event.timestamp == offset_event.timestamp


# ===========================================================================
# RiskDecision
# ===========================================================================


class TestRiskDecisionValidation:
    """RiskDecision is published to the decisions Pub/Sub channel.

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
        """decision='challenge' must raise ValidationError.

        Only allow/step_up_mfa/deny are in the Literal — 'challenge' is not a
        valid NAAS decision.
        """
        from pydantic import ValidationError
        from naas_shared.models import RiskDecision

        with pytest.raises(ValidationError):
            RiskDecision(**self._valid_decision_kwargs("challenge"))

    def test_risk_decision_rejects_unknown_decision(self):
        """An arbitrary unknown string like 'block' must raise ValidationError."""
        from pydantic import ValidationError
        from naas_shared.models import RiskDecision

        with pytest.raises(ValidationError):
            RiskDecision(**self._valid_decision_kwargs("block"))

    def test_risk_decision_is_historical_defaults_to_false(self):
        """is_historical defaults to False on RiskDecision.

        Critical: is_historical=True events must never trigger alerts.
        """
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("allow"))
        assert d.is_historical is False

    def test_risk_decision_shadow_fields_are_optional(self):
        """shadow_decision and shadow_score are Optional — may be None."""
        from naas_shared.models import RiskDecision

        d = RiskDecision(**self._valid_decision_kwargs("allow"))
        assert d.shadow_decision is None
        assert d.shadow_score is None

    def test_risk_decision_shadow_decision_present_when_provided(self):
        """shadow_decision survives roundtrip when explicitly set."""
        from naas_shared.models import RiskDecision

        kwargs = self._valid_decision_kwargs("allow")
        kwargs["shadow_decision"] = "deny"
        kwargs["shadow_score"] = 0.85
        d = RiskDecision(**kwargs)
        assert d.shadow_decision == "deny"
        assert d.shadow_score == 0.85


# ===========================================================================
# NormalizedAttributes
# ===========================================================================


class TestNormalizedAttributesValidation:
    """NormalizedAttributes is stored in events.normalized_attributes JSONB.

    The enrichment field is mandatory — its absence means the normalization
    service failed to record its LDAP enrichment decision.
    """

    def test_normalized_attributes_requires_enrichment_field(self):
        """NormalizedAttributes without an enrichment field must raise ValidationError."""
        from pydantic import ValidationError
        from naas_shared.models import NormalizedAttributes

        with pytest.raises(ValidationError):
            NormalizedAttributes(source_protocol="oidc")

    def test_normalized_attributes_requires_source_protocol(self):
        """source_protocol is required (no default)."""
        from pydantic import ValidationError
        from naas_shared.models import NormalizedAttributes, EnrichmentSkipped

        with pytest.raises(ValidationError):
            NormalizedAttributes(
                enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event")
            )

    def test_normalized_attributes_accepts_enrichment_skipped_ldap_event(self):
        """NormalizedAttributes with EnrichmentSkipped(skip_reason='ldap_event') must validate."""
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="ldap",
            enrichment=EnrichmentSkipped(applied=False, skip_reason="ldap_event"),
        )
        assert attrs.enrichment.applied is False
        assert attrs.enrichment.skip_reason == "ldap_event"

    def test_normalized_attributes_accepts_enrichment_applied(self):
        """NormalizedAttributes with EnrichmentApplied(source='ldap', cache_hit=False) must validate."""
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="oidc",
            enrichment=EnrichmentApplied(applied=True, source="ldap", cache_hit=False),
        )
        assert attrs.enrichment.applied is True
        assert attrs.enrichment.source == "ldap"
        assert attrs.enrichment.cache_hit is False

    def test_normalized_attributes_enrichment_applied_cache_hit_true(self):
        """cache_hit=True must be preserved on EnrichmentApplied."""
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        attrs = NormalizedAttributes(
            source_protocol="saml",
            enrichment=EnrichmentApplied(applied=True, source="ldap", cache_hit=True),
        )
        assert attrs.enrichment.cache_hit is True

    def test_normalized_attributes_discriminated_union_applied_true(self):
        """model_validate with {'applied': True, ...} must resolve to EnrichmentApplied."""
        from naas_shared.models import EnrichmentApplied, NormalizedAttributes

        data = {
            "source_protocol": "oidc",
            "enrichment": {"applied": True, "source": "ldap", "cache_hit": False},
        }
        attrs = NormalizedAttributes.model_validate(data)
        assert isinstance(attrs.enrichment, EnrichmentApplied)

    def test_normalized_attributes_discriminated_union_applied_false(self):
        """model_validate with {'applied': False, ...} must resolve to EnrichmentSkipped."""
        from naas_shared.models import EnrichmentSkipped, NormalizedAttributes

        data = {
            "source_protocol": "saml",
            "enrichment": {"applied": False, "skip_reason": "no_ldap_match"},
        }
        attrs = NormalizedAttributes.model_validate(data)
        assert isinstance(attrs.enrichment, EnrichmentSkipped)
        assert attrs.enrichment.skip_reason == "no_ldap_match"

    def test_normalized_attributes_all_enrichment_skip_reasons_valid(self):
        """All seven EnrichmentSkipReason values from §3.4 must be accepted."""
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
            assert attrs.enrichment.skip_reason == reason

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
        assert attrs.groups == []


# ===========================================================================
# AlertMessage
# ===========================================================================


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
                severity="info",
                title="Test",
                decision="deny",
                final_score=0.9,
                timestamp=VALID_TIMESTAMP,
            )


# ===========================================================================
# HealthResponse
# ===========================================================================


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
        """HealthResponse must reject status values outside {healthy, degraded, unhealthy}."""
        from pydantic import ValidationError
        from naas_shared.models import HealthResponse

        with pytest.raises(ValidationError):
            HealthResponse(
                status="ok",
                service="test-service",
                version="2.0.0",
            )

    def test_health_response_version_defaults_to_2_0_0(self):
        """version defaults to '2.0.0' per §3.4."""
        from naas_shared.models import HealthResponse

        h = HealthResponse(status="healthy", service="test-service")
        assert h.version == "2.0.0"
