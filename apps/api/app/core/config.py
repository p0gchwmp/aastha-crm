from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Aastha CRM API"
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://aastha:change-me@localhost:5432/aastha"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 720
    api_cors_origins: str = "http://localhost:3000"
    trusted_hosts: str = "localhost,127.0.0.1"
    api_docs_enabled: bool = True
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 30
    db_pool_recycle_seconds: int = 1800

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.api_cors_origins.split(",") if x.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [x.strip() for x in self.trusted_hosts.split(",") if x.strip()]

    @model_validator(mode="after")
    def validate_production_security(self):
        if not self.is_production:
            return self
        weak_secrets = {"dev-only-change-me", "replace-with-a-long-random-secret", "change-me", ""}
        if self.jwt_secret in weak_secrets or len(self.jwt_secret) < 32:
            raise ValueError("Production JWT_SECRET must be a non-default secret of at least 32 characters")
        if "*" in self.cors_origins:
            raise ValueError("Wildcard CORS is prohibited in production")
        if "change-me" in self.database_url:
            raise ValueError("Production DATABASE_URL must not use the default password")
        if not self.trusted_host_list or "*" in self.trusted_host_list:
            raise ValueError("Production TRUSTED_HOSTS must explicitly list allowed hosts")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
