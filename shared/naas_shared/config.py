from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Environment-driven configuration for all NAAS services.

    Defaults match docker-compose service names so containers work out of the
    box.  Override via environment variables or a .env file for local dev.
    """

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "naas"
    postgres_password: str = "naas_dev_password"
    postgres_db: str = "naas"

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379

    # LDAP
    ldap_host: str = "openldap"
    ldap_port: int = 389
    ldap_base_dn: str = "dc=corp,dc=com"
    ldap_admin_dn: str = "cn=admin,dc=corp,dc=com"
    ldap_admin_password: str = "admin"

    # Keycloak
    keycloak_url: str = "http://keycloak:8080"
    keycloak_realm: str = "naas-demo"
    keycloak_client_id: str = "naas-dashboard"

    # LLM Provider Configuration
    llm_provider: str = Field(default="mock", pattern="^(claude|ollama|mock)$")
    llm_model: str = Field(default="claude-sonnet-4-20250514")
    anthropic_api_key: Optional[str] = None
    ollama_url: str = Field(default="http://host.docker.internal:11434")
    ollama_model: str = Field(default="llama3.1")
    simulation_batch_size: int = Field(default=10, ge=1, le=50)
    simulation_max_rate: int = Field(default=30, ge=1, le=60)

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL using asyncpg driver."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """For Alembic or sync contexts."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    lru_cache ensures settings are read once per process, not on every request.
    Call get_settings.cache_clear() in tests to reset between test cases.
    """
    return Settings()
