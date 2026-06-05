# Component: NAAS Spec 2 — Chunk 4: shared additions (constants.py + config.py)
# Mode: TDD — all tests MUST fail until the implementer modifies:
#   shared/naas_shared/constants.py  (ADD LDAP_ENRICHMENT_CACHE_PREFIX)
#   shared/naas_shared/config.py     (ADD ldap_pool_size field)
#
# What these tests validate:
#   A. LDAP_ENRICHMENT_CACHE_PREFIX constant:
#      - importable from naas_shared.constants
#      - exact value "ldap_enrichment:"
#      - is a str
#   B. ldap_pool_size Settings field:
#      - default is 3 (LDAP_POOL_SIZE unset)
#      - reads env var LDAP_POOL_SIZE correctly (e.g. 5)
#      - rejects LDAP_POOL_SIZE=0 (ge=1 constraint)
#      - rejects LDAP_POOL_SIZE=11 (le=10 constraint)
#
# Why this matters:
#   LDAP_ENRICHMENT_CACHE_PREFIX is the shared key namespace for the three-state
#   Redis cache (§5.3). Any typo causes cache misses for every enrichment lookup.
#   ldap_pool_size controls LDAP connection pool sizing; an unconstrained value
#   (e.g. 0) would cause the pool to open zero connections at startup, silently
#   breaking all LDAP enrichment for every OIDC/SAML event.
#
# TDD state:
#   LDAP_ENRICHMENT_CACHE_PREFIX does NOT exist in constants.py yet.
#   ldap_pool_size does NOT exist in config.py yet.
#   All tests in this file MUST fail (ImportError / AttributeError / ValidationError
#   in the wrong direction) until the implementer adds the two fields.

# stdlib
import sys
from pathlib import Path

# third-party
import pytest


# ---------------------------------------------------------------------------
# Repo-root discovery and sys.path injection
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path:
    """Walk up from this file until we find docs/architecture/ — repo root marker."""
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

if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))


# ===========================================================================
# CLASS 1 — LDAP_ENRICHMENT_CACHE_PREFIX constant
# ===========================================================================


class TestLdapEnrichmentCachePrefix:
    """The LDAP_ENRICHMENT_CACHE_PREFIX constant must be present in naas_shared.constants.

    WHY: Every enrichment cache READ and WRITE uses this prefix to build the key.
    The key format is f"{LDAP_ENRICHMENT_CACHE_PREFIX}{correlation_value}" (§5.3).
    A missing constant → NameError at adapter import time, breaking the whole service.
    A wrong value → cache keys point to the wrong Redis keyspace, causing all
    enrichment lookups to miss, hammering LDAP on every OIDC/SAML event.
    """

    def test_ldap_enrichment_cache_prefix_is_importable(self) -> None:
        """from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX must not raise.

        TDD: fails with ImportError until the constant is added.
        """
        from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX  # noqa: F401

    def test_ldap_enrichment_cache_prefix_exact_value(self) -> None:
        """LDAP_ENRICHMENT_CACHE_PREFIX must equal exactly 'ldap_enrichment:'.

        WHY: The spec §5.3 mandates the exact key format.
        A trailing colon is the project convention: CACHE_IP_REP_PREFIX='ip_rep:',
        CACHE_GEO_PREFIX='geo:'. The enrichment prefix MUST follow the same pattern.
        """
        from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX

        assert LDAP_ENRICHMENT_CACHE_PREFIX == "ldap_enrichment:", (
            f"Expected LDAP_ENRICHMENT_CACHE_PREFIX == 'ldap_enrichment:', "
            f"got {LDAP_ENRICHMENT_CACHE_PREFIX!r}"
        )

    def test_ldap_enrichment_cache_prefix_is_str(self) -> None:
        """LDAP_ENRICHMENT_CACHE_PREFIX must be a str, not bytes or None.

        WHY: Redis key construction uses f-string interpolation; a non-str value
        would either raise TypeError or silently produce a malformed key like
        "b'ldap_enrichment:'alice@corp.com".
        """
        from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX

        assert isinstance(LDAP_ENRICHMENT_CACHE_PREFIX, str), (
            f"LDAP_ENRICHMENT_CACHE_PREFIX must be str, "
            f"got {type(LDAP_ENRICHMENT_CACHE_PREFIX)}"
        )

    def test_ldap_enrichment_cache_prefix_key_construction(self) -> None:
        """Key construction pattern f'{prefix}{value}' produces expected composite key.

        WHY: Documents and locks in the exact key format so that the adapter and
        any future cache inspection tooling use the identical namespace.
        """
        from naas_shared.constants import LDAP_ENRICHMENT_CACHE_PREFIX

        lookup_value = "alice@corp.com"
        key = f"{LDAP_ENRICHMENT_CACHE_PREFIX}{lookup_value}"

        assert key == "ldap_enrichment:alice@corp.com", (
            f"Expected 'ldap_enrichment:alice@corp.com', got {key!r}"
        )

    def test_ldap_enrichment_cache_prefix_sits_in_cache_prefix_block(self) -> None:
        """The constant can be imported alongside the existing cache prefixes.

        WHY: Validates that the addition did not disturb the module-level names
        already used by the signal-enrichment and api-gateway services. A failed
        import here would break those services indirectly.
        """
        from naas_shared.constants import (  # noqa: F401
            CACHE_GEO_PREFIX,
            CACHE_IP_REP_PREFIX,
            CACHE_JWKS,
            CACHE_POLICY_ACTIVE,
            LDAP_ENRICHMENT_CACHE_PREFIX,
        )

        # All should be non-empty strings following the prefix convention
        for name, value in [
            ("CACHE_IP_REP_PREFIX", CACHE_IP_REP_PREFIX),
            ("CACHE_GEO_PREFIX", CACHE_GEO_PREFIX),
            ("LDAP_ENRICHMENT_CACHE_PREFIX", LDAP_ENRICHMENT_CACHE_PREFIX),
        ]:
            assert isinstance(value, str) and len(value) > 0, (
                f"{name} must be a non-empty str"
            )
            assert value.endswith(":"), (
                f"{name} must end with ':' to follow project prefix convention, "
                f"got {value!r}"
            )


# ===========================================================================
# CLASS 2 — ldap_pool_size Settings field (default)
# ===========================================================================


class TestLdapPoolSizeDefault:
    """ldap_pool_size must be present on Settings with a default of 3.

    WHY: The connection pool is initialized at adapter startup using this value.
    A missing field → AttributeError at LdapAdapter.__init__ call time.
    A wrong default → the demo environment opens the wrong number of connections
    without any indication that the value was not set.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self) -> None:
        """Clear lru_cache before and after each test so env changes take effect."""
        from naas_shared.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_ldap_pool_size_attribute_exists(self) -> None:
        """Settings must have a ldap_pool_size attribute.

        TDD: fails with AttributeError until the field is added.
        """
        from naas_shared.config import get_settings

        settings = get_settings()
        assert hasattr(settings, "ldap_pool_size"), (
            "Settings is missing ldap_pool_size attribute — add it per spec §1"
        )

    def test_ldap_pool_size_default_is_3(self, monkeypatch) -> None:
        """Default value of ldap_pool_size must be 3 (LDAP_POOL_SIZE env unset).

        WHY: The spec §4 / §5.3 states 'default 3'. This is the conservative pool
        size for the demo environment. Tests that override with LDAP_POOL_SIZE
        appear in the next class.
        """
        from naas_shared.config import get_settings

        monkeypatch.delenv("LDAP_POOL_SIZE", raising=False)

        settings = get_settings()

        assert settings.ldap_pool_size == 3, (
            f"Expected ldap_pool_size default == 3, got {settings.ldap_pool_size!r}"
        )

    def test_ldap_pool_size_is_int(self, monkeypatch) -> None:
        """ldap_pool_size must be an int, not a float or str.

        WHY: The pool implementation calls range(ldap_pool_size) to create
        connections; a non-int causes TypeError at adapter init.
        """
        from naas_shared.config import get_settings

        monkeypatch.delenv("LDAP_POOL_SIZE", raising=False)

        settings = get_settings()

        assert isinstance(settings.ldap_pool_size, int), (
            f"ldap_pool_size must be int, got {type(settings.ldap_pool_size)}"
        )

    def test_ldap_pool_size_sits_in_ldap_block(self, monkeypatch) -> None:
        """ldap_pool_size must be readable alongside the existing LDAP fields.

        WHY: Validates that the new field did not shadow or overwrite ldap_host,
        ldap_port, ldap_base_dn, ldap_admin_dn, or ldap_admin_password.
        """
        from naas_shared.config import get_settings

        monkeypatch.delenv("LDAP_POOL_SIZE", raising=False)

        settings = get_settings()

        # Verify all existing LDAP fields are intact
        assert settings.ldap_host == "openldap", "ldap_host default disturbed"
        assert settings.ldap_port == 389, "ldap_port default disturbed"
        assert settings.ldap_base_dn == "dc=corp,dc=com", "ldap_base_dn default disturbed"
        assert settings.ldap_admin_dn == "cn=admin,dc=corp,dc=com", (
            "ldap_admin_dn default disturbed"
        )
        assert settings.ldap_admin_password == "admin", (
            "ldap_admin_password default disturbed"
        )
        # New field must also be present
        assert settings.ldap_pool_size == 3, "ldap_pool_size missing or wrong"


# ===========================================================================
# CLASS 3 — ldap_pool_size env var override
# ===========================================================================


class TestLdapPoolSizeEnvOverride:
    """LDAP_POOL_SIZE env var must be read by Settings.ldap_pool_size.

    WHY: Production deployments tune the pool size per environment via env var.
    If the env var is ignored, every environment uses the default (3), preventing
    performance tuning without a code change.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self) -> None:
        from naas_shared.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_ldap_pool_size_reads_env_var_5(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=5 must produce ldap_pool_size == 5."""
        from naas_shared.config import get_settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "5")

        settings = get_settings()

        assert settings.ldap_pool_size == 5, (
            f"Expected ldap_pool_size == 5 with LDAP_POOL_SIZE=5, "
            f"got {settings.ldap_pool_size!r}"
        )

    def test_ldap_pool_size_reads_env_var_1(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=1 (minimum valid) must produce ldap_pool_size == 1."""
        from naas_shared.config import get_settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "1")

        settings = get_settings()

        assert settings.ldap_pool_size == 1, (
            f"Expected ldap_pool_size == 1 with LDAP_POOL_SIZE=1, "
            f"got {settings.ldap_pool_size!r}"
        )

    def test_ldap_pool_size_reads_env_var_10(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=10 (maximum valid) must produce ldap_pool_size == 10."""
        from naas_shared.config import get_settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "10")

        settings = get_settings()

        assert settings.ldap_pool_size == 10, (
            f"Expected ldap_pool_size == 10 with LDAP_POOL_SIZE=10, "
            f"got {settings.ldap_pool_size!r}"
        )


# ===========================================================================
# CLASS 4 — ldap_pool_size constraint violations
# ===========================================================================


class TestLdapPoolSizeConstraints:
    """ldap_pool_size must enforce ge=1 le=10 via Pydantic Field constraints.

    WHY (security / reliability):
    - pool_size=0 → adapter creates 0 connections → every enrich() call gets None
      immediately, silently degrading all OIDC/SAML events to no-enrichment without
      any error message. This is a silent misconfiguration hazard.
    - pool_size=11 → the upper bound prevents runaway connection growth against an
      LDAP server that may have connection limits. Without the cap, a misconfigured
      deployment could exhaust LDAP server connections.
    - Both must be caught at Settings construction time, not silently clamped.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self) -> None:
        from naas_shared.config import get_settings
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_ldap_pool_size_zero_raises_validation_error(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=0 must raise pydantic ValidationError (ge=1 constraint).

        WHY: Zero connections would silently disable all LDAP enrichment without any
        indication that a misconfiguration occurred. The service must refuse to start.
        """
        from pydantic import ValidationError

        from naas_shared.config import Settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "0")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        # The error must mention ldap_pool_size so operators know what to fix
        errors = exc_info.value.errors()
        field_names = [e.get("loc", ()) for e in errors]
        assert any("ldap_pool_size" in str(loc) for loc in field_names), (
            f"ValidationError must reference ldap_pool_size, got errors: {errors}"
        )

    def test_ldap_pool_size_eleven_raises_validation_error(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=11 must raise pydantic ValidationError (le=10 constraint).

        WHY: More than 10 connections may exhaust the LDAP server's connection limit.
        The upper cap prevents runaway resource usage from a misconfigured deployment.
        """
        from pydantic import ValidationError

        from naas_shared.config import Settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "11")

        with pytest.raises(ValidationError) as exc_info:
            Settings()

        errors = exc_info.value.errors()
        field_names = [e.get("loc", ()) for e in errors]
        assert any("ldap_pool_size" in str(loc) for loc in field_names), (
            f"ValidationError must reference ldap_pool_size, got errors: {errors}"
        )

    def test_ldap_pool_size_negative_raises_validation_error(self, monkeypatch) -> None:
        """LDAP_POOL_SIZE=-1 must raise pydantic ValidationError (ge=1 constraint).

        WHY: Negative pool size is nonsensical. The ge=1 constraint must cover
        negative values, not just zero.
        """
        from pydantic import ValidationError

        from naas_shared.config import Settings

        monkeypatch.setenv("LDAP_POOL_SIZE", "-1")

        with pytest.raises(ValidationError):
            Settings()

    @pytest.mark.parametrize("valid_size", [1, 2, 3, 5, 10])
    def test_ldap_pool_size_valid_range_does_not_raise(
        self, monkeypatch, valid_size: int
    ) -> None:
        """Valid LDAP_POOL_SIZE values (1–10) must not raise ValidationError.

        WHY: Boundary tests in both directions. Confirms ge=1 and le=10 are
        inclusive bounds, not exclusive.
        """
        from naas_shared.config import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("LDAP_POOL_SIZE", str(valid_size))

        settings = get_settings()

        assert settings.ldap_pool_size == valid_size, (
            f"Expected {valid_size}, got {settings.ldap_pool_size!r}"
        )
