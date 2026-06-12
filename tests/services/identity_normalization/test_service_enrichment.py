"""NormalizationService.normalize(): full enrichment flow with LDAP lookup and result assembly."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID


# ---------------------------------------------------------------------------
# sys.path injection (mirrors conftest.py pattern for this service)
# ---------------------------------------------------------------------------

from tests.helpers import REPO_ROOT as _REPO

_SVC = str(_REPO / "services" / "identity-normalization")
_SHARED = str(_REPO / "shared")
for _p in [_SVC, _SHARED]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# Shared model imports (always present)
# ---------------------------------------------------------------------------
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
