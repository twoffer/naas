"""Settings class defaults and database URL properties for naas_shared.config.

Verifies that Settings has correct defaults for docker-compose out-of-the-box
operation and that database_url / database_url_sync properties produce URLs
with the right schemes.
"""

from __future__ import annotations

import pytest


class TestSettingsDefaults:
    """Settings must have defaults matching the .env.example values so that
    `docker-compose up` works out of the box.

    These tests instantiate ``Settings(_env_file=None)`` so they assert the
    in-code defaults, not whatever a developer's local (gitignored) .env
    happens to set.  The local .env is expected to drift — e.g.
    POSTGRES_HOST=localhost for bare-metal runs — so reading it here would
    make the defaults untestable.
    """

    @pytest.fixture(autouse=True)
    def clear_settings_cache(self):
        """get_settings() is lru_cache'd. Clear before each test so env-var
        overrides in individual tests take effect.
        """
        from naas_shared.config import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_settings_instantiates_without_env_file(self):
        """Settings() must not raise even without a .env file."""
        from naas_shared.config import Settings

        s = Settings(_env_file=None)
        assert s is not None

    def test_postgres_host_default_is_postgres(self):
        """postgres_host defaults to 'postgres' (Docker service name)."""
        from naas_shared.config import Settings

        s = Settings(_env_file=None)
        assert s.postgres_host == "postgres", (
            f"Expected postgres_host='postgres', got {s.postgres_host!r}"
        )

    def test_redis_port_default_is_6379(self):
        """redis_port defaults to 6379 (standard Redis port)."""
        from naas_shared.config import Settings

        s = Settings(_env_file=None)
        assert s.redis_port == 6379, f"Expected redis_port=6379, got {s.redis_port!r}"

    def test_keycloak_realm_default_is_naas_demo(self):
        """keycloak_realm defaults to 'naas-demo'.

        Must match the realm name in infrastructure/keycloak/naas-realm-export.json.
        Wrong realm → 404 on OIDC discovery.
        """
        from naas_shared.config import Settings

        s = Settings(_env_file=None)
        assert s.keycloak_realm == "naas-demo", (
            f"Expected keycloak_realm='naas-demo', got {s.keycloak_realm!r}"
        )

    def test_llm_provider_default_is_mock(self):
        """llm_provider defaults to 'mock'.

        Ensures the persona-simulator starts without requiring external API keys.
        """
        from naas_shared.config import Settings

        s = Settings(_env_file=None)
        assert s.llm_provider == "mock", (
            f"Expected llm_provider='mock', got {s.llm_provider!r}"
        )

    def test_database_url_property_returns_asyncpg_url(self):
        """Settings.database_url must return a postgresql+asyncpg:// URL."""
        from naas_shared.config import Settings

        s = Settings(
            postgres_host="postgres",
            postgres_port=5432,
            postgres_user="naas",
            postgres_password="naas_dev_password",
            postgres_db="naas",
        )
        url = s.database_url
        assert url.startswith("postgresql+asyncpg://")
        assert "naas" in url

    def test_database_url_sync_property_returns_sync_url(self):
        """Settings.database_url_sync must return a plain postgresql:// URL."""
        from naas_shared.config import Settings

        s = Settings(
            postgres_host="postgres",
            postgres_port=5432,
            postgres_user="naas",
            postgres_password="naas_dev_password",
            postgres_db="naas",
        )
        url_sync = s.database_url_sync
        assert url_sync.startswith("postgresql://")
        assert "+asyncpg" not in url_sync

    def test_database_url_uses_configured_host(self):
        """database_url must embed the configured postgres_host."""
        from naas_shared.config import Settings

        s = Settings(postgres_host="my-custom-host")
        assert "my-custom-host" in s.database_url

    def test_database_url_sync_uses_configured_host(self):
        """database_url_sync must embed the configured postgres_host."""
        from naas_shared.config import Settings

        s = Settings(postgres_host="my-custom-host")
        assert "my-custom-host" in s.database_url_sync

    def test_get_settings_is_cached(self):
        """get_settings() must return the same instance on repeated calls (lru_cache)."""
        from naas_shared.config import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2, "get_settings() must return the same cached instance"
