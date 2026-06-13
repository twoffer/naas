"""NormalizationService.normalize(): full enrichment flow with LDAP lookup and result assembly."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

from tests.helpers import REPO_ROOT as _REPO
from naas_shared.models import (
    EnrichmentSkipped,
    LoginEventRecord,
    NormalizedAttributes,
)

# ---------------------------------------------------------------------------
# Helpers — deterministic test fixtures
# ---------------------------------------------------------------------------

_UUID = UUID("12345678-1234-5678-1234-567812345678")
_NOW = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def _oidc_record(
    email: str = "alice@corp.com",
    is_synthetic: bool = False,
    extra_raw: dict | None = None,
) -> LoginEventRecord:
    raw: dict[str, Any] = {
        "name": "Alice Smith",
        "email": email,
        "department": "eng",
        "employee_type": "fte",
        "groups": ["admin", "vpn-users"],
    }
    if extra_raw:
        raw.update(extra_raw)
    return LoginEventRecord(
        id=_UUID,
        user_id="alice",
        client_ip="192.168.1.1",
        protocol="oidc",
        timestamp=_NOW,
        source="user",
        is_synthetic=is_synthetic,
        is_historical=False,
        raw_attributes=raw,
    )


def _saml_record(email: str = "bob@corp.com") -> LoginEventRecord:
    return LoginEventRecord(
        id=_UUID,
        user_id="bob",
        client_ip="192.168.1.2",
        protocol="saml",
        timestamp=_NOW,
        source="user",
        is_synthetic=False,
        is_historical=False,
        raw_attributes={
            "displayName": "Bob Jones",
            "email": email,
            "dept": "Finance",
            "employeeType": "contractor",
            "groups": ["finance-users"],
        },
    )


def _ldap_record() -> LoginEventRecord:
    return LoginEventRecord(
        id=_UUID,
        user_id="charlie",
        client_ip="192.168.1.3",
        protocol="ldap",
        timestamp=_NOW,
        source="user",
        is_synthetic=False,
        is_historical=False,
        raw_attributes={
            "cn": "Charlie Brown",
            "mail": "charlie@corp.com",
            "departmentNumber": "engineering",
            "employeeType": "fte",
            "memberOf": [],
        },
    )


def _load_real_config():
    """Load the real normalization.yaml from config/."""
    from app.normalization_config import load_config

    cfg_path = _REPO / "config" / "normalization.yaml"
    return load_config(cfg_path)


def _make_service(
    enrich_return: tuple = (None, "ldap_no_match"), ldap_enabled: bool = True
):
    """Build a NormalizationService with mocked ldap adapter enrich().

    The ldap_adapter.enrich is replaced with an AsyncMock that returns enrich_return.
    Adapter extract() methods call the real implementations.
    """
    from app.service import NormalizationService
    from app.adapters.oidc import OidcAdapter
    from app.adapters.saml import SamlAdapter
    from app.adapters.ldap import LdapAdapter
    from app.normalization_config import load_config

    cfg_path = _REPO / "config" / "normalization.yaml"
    config = load_config(cfg_path)

    # Override enabled flag if needed
    config.enrichment.sources.ldap.enabled = ldap_enabled

    oidc = OidcAdapter()
    saml = SamlAdapter()
    ldap = LdapAdapter()

    # Mock the enrich method — never calls real LDAP
    ldap.enrich = AsyncMock(return_value=enrich_return)

    return NormalizationService(
        config=config, oidc_adapter=oidc, saml_adapter=saml, ldap_adapter=ldap
    )


# ===========================================================================
# A. Adapter selection by protocol
# ===========================================================================


class TestAdapterSelectionByProtocol:
    """NormalizationService selects the correct adapter per record.protocol."""

    async def test_oidc_record_uses_oidc_adapter(self):
        """OIDC record → OidcAdapter.extract is called; display_name comes from 'name' key."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"))
        record = _oidc_record()

        result = await svc.normalize(record)

        assert isinstance(result, NormalizedAttributes), (
            "normalize() must return NormalizedAttributes"
        )
        assert result.display_name == "Alice Smith", (
            f"OIDC 'name' key must map to display_name, got {result.display_name!r}"
        )
        assert result.primary_email == "alice@corp.com", (
            f"OIDC 'email' key must map to primary_email, got {result.primary_email!r}"
        )

    async def test_saml_record_uses_saml_adapter(self):
        """SAML record → SamlAdapter.extract is called; display_name comes from 'displayName' key."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"))
        record = _saml_record()

        result = await svc.normalize(record)

        assert result.display_name == "Bob Jones", (
            f"SAML 'displayName' must map to display_name, got {result.display_name!r}"
        )
        assert result.primary_email == "bob@corp.com"

    async def test_ldap_record_uses_ldap_adapter(self):
        """LDAP record → LdapAdapter.extract is called; display_name comes from 'cn' key."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"))
        record = _ldap_record()

        result = await svc.normalize(record)

        assert result.display_name == "Charlie Brown", (
            f"LDAP 'cn' must map to display_name, got {result.display_name!r}"
        )
        assert result.source_protocol == "ldap", (
            f"source_protocol must equal record.protocol, got {result.source_protocol!r}"
        )

    async def test_source_protocol_equals_record_protocol_oidc(self):
        """source_protocol on output == record.protocol even when enrichment contributes."""
        svc = _make_service(
            enrich_return=(
                {
                    "display_name": "Alice Smith",
                    "primary_email": "alice@corp.com",
                    "department": "Engineering",
                    "employee_type": "FTE",
                    "groups": [],
                },
                "ldap_match",
            )
        )
        record = _oidc_record()

        result = await svc.normalize(record)

        assert result.source_protocol == "oidc", (
            f"source_protocol must be the primary event protocol 'oidc', got {result.source_protocol!r}"
        )

    async def test_source_protocol_equals_record_protocol_saml(self):
        """source_protocol on output == 'saml' for SAML records."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"))
        record = _saml_record()

        result = await svc.normalize(record)

        assert result.source_protocol == "saml", (
            f"source_protocol must be 'saml', got {result.source_protocol!r}"
        )


# ===========================================================================
# B. Enrichment decision — source-agnostic (never branch on is_synthetic)
# ===========================================================================


class TestEnrichmentSourceAgnostic:
    """§5.4: enrichment depends only on protocol and config, never on is_synthetic."""

    async def test_real_oidc_and_synthetic_oidc_get_identical_enrichment_treatment(
        self,
    ):
        """is_synthetic=True and is_synthetic=False OIDC events both attempt enrichment.

        This is the critical invariant: enrichment must never branch on is_synthetic.
        Both records get the same enrich() call path. We verify enrich() call count
        is identical for both.
        """
        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter

        cfg = _load_real_config()

        # Build two services with separate ldap mocks
        def _build_svc():
            oidc = OidcAdapter()
            saml = SamlAdapter()
            ldap = LdapAdapter()
            ldap.enrich = AsyncMock(return_value=(None, "ldap_no_match"))
            return NormalizationService(
                config=cfg, oidc_adapter=oidc, saml_adapter=saml, ldap_adapter=ldap
            )

        real_svc = _build_svc()
        synth_svc = _build_svc()

        real_record = _oidc_record(is_synthetic=False)
        synth_record = _oidc_record(is_synthetic=True)

        real_result = await real_svc.normalize(real_record)
        synth_result = await synth_svc.normalize(synth_record)

        # Both should have attempted enrichment (enrich() called once each)
        assert real_svc._ldap_adapter.enrich.call_count == 1, (
            "enrich() must be called for real OIDC event"
        )
        assert synth_svc._ldap_adapter.enrich.call_count == 1, (
            "enrich() must be called for synthetic OIDC event — never branch on is_synthetic"
        )
        # Both should produce the same enrichment skip reason
        assert isinstance(real_result.enrichment, EnrichmentSkipped)
        assert isinstance(synth_result.enrichment, EnrichmentSkipped)
        assert (
            real_result.enrichment.skip_reason == synth_result.enrichment.skip_reason
        ), "is_synthetic must not affect enrichment outcome"

    async def test_ldap_protocol_never_attempts_enrichment_regardless_of_is_synthetic(
        self,
    ):
        """LDAP protocol events skip enrichment regardless of is_synthetic value."""
        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter

        cfg = _load_real_config()
        ldap = LdapAdapter()
        ldap.enrich = AsyncMock(return_value=(None, "ldap_no_match"))
        svc = NormalizationService(
            config=cfg,
            oidc_adapter=OidcAdapter(),
            saml_adapter=SamlAdapter(),
            ldap_adapter=ldap,
        )

        record = LoginEventRecord(
            id=_UUID,
            user_id="u",
            client_ip="192.168.1.1",
            protocol="ldap",
            timestamp=_NOW,
            source="simulator",
            is_synthetic=True,
            is_historical=False,
            raw_attributes={"cn": "Test User", "mail": "t@t.com"},
        )

        await svc.normalize(record)

        assert ldap.enrich.call_count == 0, (
            "enrich() must never be called for ldap protocol events, even when is_synthetic=True"
        )


# ===========================================================================
# C. Enrichment decision — attempt iff enabled and oidc/saml
# ===========================================================================


class TestEnrichmentDecision:
    """Service decides whether to attempt enrichment based on config + protocol."""

    async def test_oidc_with_ldap_enabled_calls_enrich(self):
        """OIDC + ldap.enabled=True → enrich() is called once."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _oidc_record()

        await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 1, (
            "enrich() must be called for OIDC when ldap enrichment is enabled"
        )

    async def test_saml_with_ldap_enabled_calls_enrich(self):
        """SAML + ldap.enabled=True → enrich() is called once."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _saml_record()

        await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 1, (
            "enrich() must be called for SAML when ldap enrichment is enabled"
        )

    async def test_ldap_protocol_skips_enrich_call(self):
        """LDAP protocol → enrich() is NOT called (directory data already in payload)."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _ldap_record()

        await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 0, (
            "enrich() must not be called for ldap protocol events"
        )

    async def test_ldap_disabled_in_config_skips_enrich_call(self):
        """ldap.enabled=False → enrich() is NOT called even for OIDC."""
        svc = _make_service(ldap_enabled=False)
        record = _oidc_record()

        await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 0, (
            "enrich() must not be called when ldap enrichment is disabled in config"
        )

    async def test_missing_correlation_value_skips_enrich_call(self):
        """OIDC with no email in raw_attributes → enrich() NOT called, invalid_correlation_key skip."""
        svc = _make_service(ldap_enabled=True)
        record = LoginEventRecord(
            id=_UUID,
            user_id="anon",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=_NOW,
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={"name": "Anon User"},  # no email
        )

        result = await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 0, (
            "enrich() must not be called when correlation_value is absent"
        )
        assert isinstance(result.enrichment, EnrichmentSkipped), (
            f"Expected EnrichmentSkipped, got {type(result.enrichment)}"
        )
        assert result.enrichment.skip_reason == "invalid_correlation_key", (
            f"Expected skip_reason='invalid_correlation_key', got {result.enrichment.skip_reason!r}"
        )

    async def test_empty_string_correlation_value_skips_enrich(self):
        """OIDC with empty email string → enrich() NOT called, invalid_correlation_key skip."""
        svc = _make_service(ldap_enabled=True)
        record = LoginEventRecord(
            id=_UUID,
            user_id="anon",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=_NOW,
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={"name": "Anon", "email": ""},
        )

        result = await svc.normalize(record)

        assert svc._ldap_adapter.enrich.call_count == 0, (
            "enrich() must not be called when correlation_value is an empty string"
        )
        assert isinstance(result.enrichment, EnrichmentSkipped)
        assert result.enrichment.skip_reason == "invalid_correlation_key"

    async def test_enrich_called_with_correct_correlation_field_and_value(self):
        """enrich() receives the configured correlation_key and the primary-attrs value for it."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        # Default correlation_key is "primary_email", so enrich gets ("primary_email", email_value)
        record = _oidc_record(email="alice@corp.com")

        await svc.normalize(record)

        call_args = svc._ldap_adapter.enrich.call_args
        assert call_args is not None, "enrich() was not called"
        pos_args = call_args.args if call_args.args else call_args[0]
        # First positional arg is correlation_field, second is lookup_value
        assert pos_args[0] == "primary_email", (
            f"enrich() correlation_field must be 'primary_email', got {pos_args[0]!r}"
        )
        assert pos_args[1] == "alice@corp.com", (
            f"enrich() lookup_value must be 'alice@corp.com', got {pos_args[1]!r}"
        )


# ===========================================================================
# D. Config kwargs are passed from service to enrich() (Change 1)
# ===========================================================================


class TestEnrichConfigKwargs:
    """Service must pass YAML-loaded config values as kwargs into enrich().

    WHY: If the service ignores the config values, timeout_ms / cache_ttl_seconds /
    enrich_attributes are effectively dead knobs — always the adapter defaults.
    Wiring the config per-call allows YAML changes to take effect without code
    changes (op hygiene).
    """

    async def test_service_passes_yaml_cache_ttl_to_enrich(self):
        """cache_ttl_seconds kwarg == config/normalization.yaml value (60)."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _oidc_record()

        await svc.normalize(record)

        call_kwargs = svc._ldap_adapter.enrich.call_args.kwargs
        assert "cache_ttl_seconds" in call_kwargs, (
            "enrich() must be called with cache_ttl_seconds kwarg"
        )
        assert call_kwargs["cache_ttl_seconds"] == 60, (
            f"cache_ttl_seconds must be 60 (from config/normalization.yaml), "
            f"got {call_kwargs['cache_ttl_seconds']!r}"
        )

    async def test_service_passes_yaml_timeout_ms_to_enrich(self):
        """timeout_ms kwarg == config/normalization.yaml value (2000)."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _oidc_record()

        await svc.normalize(record)

        call_kwargs = svc._ldap_adapter.enrich.call_args.kwargs
        assert "timeout_ms" in call_kwargs, (
            "enrich() must be called with timeout_ms kwarg"
        )
        assert call_kwargs["timeout_ms"] == 2000, (
            f"timeout_ms must be 2000 (from config/normalization.yaml), "
            f"got {call_kwargs['timeout_ms']!r}"
        )

    async def test_service_passes_enrich_attributes_none_when_not_configured(self):
        """enrich_attributes kwarg is None when not set in config (default)."""
        svc = _make_service(enrich_return=(None, "ldap_no_match"), ldap_enabled=True)
        record = _oidc_record()

        await svc.normalize(record)

        call_kwargs = svc._ldap_adapter.enrich.call_args.kwargs
        assert "enrich_attributes" in call_kwargs, (
            "enrich() must be called with enrich_attributes kwarg"
        )
        assert call_kwargs["enrich_attributes"] is None, (
            f"enrich_attributes must be None when not configured, "
            f"got {call_kwargs['enrich_attributes']!r}"
        )


# ===========================================================================
# E. Connection-error state-change logging (Change 6)
# ===========================================================================


class TestConnectionErrorStatefulLogging:
    """Service logs ERROR only on the first connection error; subsequent errors log DEBUG.

    WHY: With LDAP down, every OIDC/SAML event would otherwise emit an ERROR log,
    flooding the log stream with identical messages. State-change logging emits
    ERROR once (state change: healthy → degraded) and DEBUG thereafter (repeated
    known condition). On recovery, an INFO log signals the state change back.
    """

    def _make_service_with_ldap_outcome(self, outcome: str):
        """Build NormalizationService with ldap.enrich always returning (None, outcome)."""
        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter

        cfg = _load_real_config()
        oidc = OidcAdapter()
        saml = SamlAdapter()
        ldap = LdapAdapter()
        ldap.enrich = AsyncMock(return_value=(None, outcome))
        return NormalizationService(
            config=cfg, oidc_adapter=oidc, saml_adapter=saml, ldap_adapter=ldap
        )

    async def test_first_connection_error_logs_error(self):
        """First ldap_connection_error outcome → service logs at ERROR level."""
        import app.service as svc_mod

        logged_events: list[dict] = []

        class CapturingLogger:
            def error(self, event, **kwargs):
                logged_events.append({"level": "error", "event": event, **kwargs})

            def debug(self, event, **kwargs):
                logged_events.append({"level": "debug", "event": event, **kwargs})

            def bind(self, **kwargs):
                return self

            def __getattr__(self, name):
                return lambda *a, **kw: None

        svc = self._make_service_with_ldap_outcome("ldap_connection_error")
        record = _oidc_record()

        orig_logger = svc_mod._logger
        svc_mod._logger = CapturingLogger()
        try:
            await svc.normalize(record)
        finally:
            svc_mod._logger = orig_logger

        error_events = [e for e in logged_events if e["level"] == "error"]
        assert len(error_events) >= 1, "First connection error must log at ERROR level"
        assert any("connection_error" in e["event"] for e in error_events), (
            f"ERROR event must be 'ldap_enrichment_connection_error'. Got: {error_events}"
        )

    async def test_second_connection_error_does_not_log_error(self):
        """Second consecutive ldap_connection_error → ERROR count remains 1 (debug only)."""
        import app.service as svc_mod

        logged_events: list[dict] = []

        class CapturingLogger:
            def error(self, event, **kwargs):
                logged_events.append({"level": "error", "event": event, **kwargs})

            def debug(self, event, **kwargs):
                logged_events.append({"level": "debug", "event": event, **kwargs})

            def bind(self, **kwargs):
                return self

            def __getattr__(self, name):
                return lambda *a, **kw: None

        svc = self._make_service_with_ldap_outcome("ldap_connection_error")
        record = _oidc_record()

        orig_logger = svc_mod._logger
        svc_mod._logger = CapturingLogger()
        try:
            await svc.normalize(record)  # first — sets degraded flag
            logged_events.clear()
            await svc.normalize(record)  # second — should be DEBUG only
        finally:
            svc_mod._logger = orig_logger

        error_events = [e for e in logged_events if e["level"] == "error"]
        assert len(error_events) == 0, (
            f"Second connection error must NOT emit ERROR log. Got: {error_events}"
        )

    async def test_recovery_after_degradation_logs_info(self):
        """After a connection error, a successful ldap_no_match logs INFO recovered."""
        import app.service as svc_mod

        logged_events: list[dict] = []

        class CapturingLogger:
            def error(self, event, **kwargs):
                logged_events.append({"level": "error", "event": event, **kwargs})

            def info(self, event, **kwargs):
                logged_events.append({"level": "info", "event": event, **kwargs})

            def debug(self, event, **kwargs):
                logged_events.append({"level": "debug", "event": event, **kwargs})

            def bind(self, **kwargs):
                return self

            def warning(self, event, **kwargs):
                logged_events.append({"level": "warning", "event": event, **kwargs})

            def __getattr__(self, name):
                return lambda *a, **kw: None

        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter

        cfg = _load_real_config()
        oidc = OidcAdapter()
        saml = SamlAdapter()
        ldap = LdapAdapter()

        # First call: connection error; second call: no_match (recovery evidence)
        ldap.enrich = AsyncMock(
            side_effect=[
                (None, "ldap_connection_error"),
                (None, "ldap_no_match"),
            ]
        )
        svc = NormalizationService(
            config=cfg, oidc_adapter=oidc, saml_adapter=saml, ldap_adapter=ldap
        )

        record = _oidc_record()

        orig_logger = svc_mod._logger
        svc_mod._logger = CapturingLogger()
        try:
            await svc.normalize(record)  # sets degraded flag
            logged_events.clear()
            await svc.normalize(record)  # recovery
        finally:
            svc_mod._logger = orig_logger

        recovery_events = [
            e
            for e in logged_events
            if e["level"] == "info" and "recovered" in e["event"]
        ]
        assert len(recovery_events) >= 1, (
            f"Recovery after degradation must log INFO 'ldap_enrichment_recovered'. "
            f"Got logged events: {logged_events}"
        )


# ===========================================================================
# F. LDAP attribute merge into resolution (Task 3)
# ===========================================================================


class TestLdapAttrMergeIntoResolution:
    """_merge_ldap_attrs wires LDAP-sourced attributes into the resolution layer.

    Spec §5.5: when enrichment returns ldap_match or cache_hit_positive, the LDAP
    unified attrs are added as the "ldap" source in attribute_sources before
    resolution.resolve() is called.  These tests pin that the merge is actually
    visible in NormalizedAttributes.resolution_details, so that adding an LDAP
    source produces observable output differences rather than silently being ignored.

    Uses the real config/normalization.yaml for all weight/priority assertions so
    the tests pin actual production behaviour.
    """

    def _make_service_with_ldap_attrs(
        self,
        ldap_attrs: dict,
        outcome: str = "ldap_match",
    ):
        """Build NormalizationService whose ldap.enrich() returns the given attrs."""
        from app.service import NormalizationService
        from app.adapters.oidc import OidcAdapter
        from app.adapters.saml import SamlAdapter
        from app.adapters.ldap import LdapAdapter
        from app.normalization_config import load_config

        cfg = load_config(_REPO / "config" / "normalization.yaml")
        oidc = OidcAdapter()
        saml = SamlAdapter()
        ldap = LdapAdapter()
        ldap.enrich = AsyncMock(return_value=(ldap_attrs, outcome))
        return NormalizationService(
            config=cfg, oidc_adapter=oidc, saml_adapter=saml, ldap_adapter=ldap
        )

    async def test_ldap_match_ldap_appears_in_resolution_details_sources(self):
        """When LDAP returns a department, 'ldap' must appear in resolution_details['department'].sources.

        Spec §5.5: resolution_details records all sources that contributed to the
        winning value.  If _merge_ldap_attrs silently drops LDAP data, sources will
        contain only 'oidc' and the test will fail — confirming the merge happened.
        """
        # OIDC record has department='eng' (→ 'Engineering'); LDAP also sends 'Engineering'.
        # With the real config, priority for department is [ldap, oidc, saml].
        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": ["engineering"],
        }
        svc = self._make_service_with_ldap_attrs(ldap_attrs, outcome="ldap_match")
        record = _oidc_record()

        result = await svc.normalize(record)

        dept_detail = result.resolution_details.get("department")
        assert dept_detail is not None, (
            "resolution_details must contain 'department' when both OIDC and LDAP provide it"
        )
        sources = dept_detail.sources
        assert "ldap" in sources, (
            f"'ldap' must appear in resolution_details['department'].sources when "
            f"ldap_match returns a department. Got sources={sources!r}. "
            "If ldap is absent, _merge_ldap_attrs is not wiring LDAP into attribute_sources."
        )

    async def test_cache_hit_positive_ldap_appears_in_resolution_details_sources(self):
        """cache_hit_positive: LDAP data arrives from cache, must still appear in resolution.

        WHY: The merge path for cache_hit_positive is identical to ldap_match but
        sets cache_hit=True on EnrichmentApplied.  Both branches call _merge_ldap_attrs.
        """
        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": ["ldap-group"],
        }
        svc = self._make_service_with_ldap_attrs(
            ldap_attrs, outcome="cache_hit_positive"
        )
        record = _oidc_record()

        result = await svc.normalize(record)

        dept_detail = result.resolution_details.get("department")
        assert dept_detail is not None, (
            "resolution_details must contain 'department' for cache_hit_positive outcome"
        )
        sources = dept_detail.sources
        assert "ldap" in sources, (
            f"'ldap' must appear in resolution_details['department'].sources for "
            f"cache_hit_positive.  Got sources={sources!r}."
        )
        # Also confirm cache_hit is True
        from naas_shared.models import EnrichmentApplied

        assert isinstance(result.enrichment, EnrichmentApplied)
        assert result.enrichment.cache_hit is True

    async def test_ldap_wins_department_when_config_priority_favors_ldap(self):
        """When OIDC and LDAP disagree on department, LDAP wins per config priority [ldap, oidc, saml].

        Real config: department priority = [ldap, oidc, saml].
        OIDC has 'Finance'; LDAP has 'Engineering'.
        Resolution must pick 'Engineering' (LDAP wins) and record conflicting_values.

        Spec §5.5: priority resolution — winner_source matches config priority ordering.
        """
        from naas_shared.models import PriorityResolution

        # OIDC raw: department='fin' → 'Finance'
        # LDAP: department='Engineering'
        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": [],
        }
        # Build a record with a different department so there IS a conflict.
        record = LoginEventRecord(
            id=_UUID,
            user_id="alice",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=_NOW,
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={
                "name": "Alice Smith",
                "email": "alice@corp.com",
                "department": "fin",   # → 'Finance' after normalization
                "employee_type": "fte",
                "groups": [],
            },
        )
        svc = self._make_service_with_ldap_attrs(ldap_attrs, outcome="ldap_match")
        result = await svc.normalize(record)

        dept_detail = result.resolution_details.get("department")
        assert dept_detail is not None, "department must be in resolution_details"
        assert isinstance(dept_detail, PriorityResolution), (
            f"Conflicting OIDC/LDAP departments must produce PriorityResolution, "
            f"got {type(dept_detail).__name__!r}"
        )
        assert dept_detail.winner_source == "ldap", (
            f"LDAP must win the department conflict per config priority [ldap, oidc, saml]. "
            f"Got winner_source={dept_detail.winner_source!r}"
        )
        assert result.department == "Engineering", (
            f"Resolved department must be 'Engineering' (LDAP winner). "
            f"Got {result.department!r}"
        )
        assert "oidc" in dept_detail.conflicting_values, (
            f"conflicting_values must include 'oidc' (the losing source). "
            f"Got {dept_detail.conflicting_values!r}"
        )
        assert dept_detail.conflicting_values["oidc"] == "Finance", (
            f"OIDC conflicting value must be 'Finance' (from 'fin'). "
            f"Got {dept_detail.conflicting_values['oidc']!r}"
        )

    async def test_ldap_groups_are_unioned_into_resolved_groups(self):
        """OIDC and LDAP groups are unioned (default strategy) in the resolved output.

        Spec §5.5: groups merge_strategy defaults to 'union'. Both OIDC and LDAP
        groups must appear in the resolved groups list.
        """
        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "Engineering",
            "employee_type": "FTE",
            "groups": ["engineering", "ldap-all-users"],
        }
        # OIDC record has groups=['admin', 'vpn-users']
        svc = self._make_service_with_ldap_attrs(ldap_attrs, outcome="ldap_match")
        record = _oidc_record()  # groups=["admin", "vpn-users"]

        result = await svc.normalize(record)

        resolved_groups = set(result.groups)
        assert "admin" in resolved_groups, (
            f"OIDC group 'admin' must appear in resolved groups. Got {result.groups!r}"
        )
        assert "engineering" in resolved_groups, (
            f"LDAP group 'engineering' must appear in resolved groups. Got {result.groups!r}"
        )
        assert "ldap-all-users" in resolved_groups, (
            f"LDAP group 'ldap-all-users' must appear in resolved groups. Got {result.groups!r}"
        )

    async def test_ldap_department_unmapped_triggers_penalty_in_resolution(self):
        """LDAP returning an unmapped department value applies the -0.2 confidence penalty.

        Spec §5.5: was_mapped=False on the winning department value → confidence reduced
        by 0.2.  When LDAP provides the only source ('ldap_match', no OIDC department
        in raw_attrs), _was_department_mapped('WidgetCorp') returns False, so
        SingleSourceResolution.confidence = 0.90 - 0.20 = 0.70 (ldap weight 0.90).
        """
        import pytest
        from naas_shared.models import SingleSourceResolution

        ldap_attrs = {
            "display_name": "Alice Smith",
            "primary_email": "alice@corp.com",
            "department": "WidgetCorp",   # unmapped — not in DEPARTMENT_CANONICAL
            "employee_type": "FTE",
            "groups": [],
        }
        # Build a record without any OIDC department so LDAP is the single source.
        record = LoginEventRecord(
            id=_UUID,
            user_id="alice",
            client_ip="192.168.1.1",
            protocol="oidc",
            timestamp=_NOW,
            source="user",
            is_synthetic=False,
            is_historical=False,
            raw_attributes={
                "name": "Alice Smith",
                "email": "alice@corp.com",
                # no department key — LDAP is the single source
                "employee_type": "fte",
                "groups": [],
            },
        )
        svc = self._make_service_with_ldap_attrs(ldap_attrs, outcome="ldap_match")
        result = await svc.normalize(record)

        dept_detail = result.resolution_details.get("department")
        assert dept_detail is not None, (
            "department must appear in resolution_details when LDAP provides it"
        )
        assert isinstance(dept_detail, SingleSourceResolution), (
            f"Single LDAP source must produce SingleSourceResolution. "
            f"Got {type(dept_detail).__name__!r}"
        )
        assert dept_detail.resolved_value == "WidgetCorp", (
            f"Unmapped LDAP department 'WidgetCorp' must be retained. "
            f"Got {dept_detail.resolved_value!r}"
        )
        # ldap weight for department = 0.90; penalty for unmapped = -0.20 → 0.70
        assert dept_detail.confidence == pytest.approx(0.70), (
            f"Confidence must be 0.90 (ldap weight) - 0.20 (unmapped penalty) = 0.70. "
            f"Got {dept_detail.confidence!r}"
        )
