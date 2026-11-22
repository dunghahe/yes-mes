from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://mes_app:local_dev_only@localhost:5432/mes"
    migration_database_url: str = (
        "postgresql+psycopg://mes_migrator:local_dev_only@localhost:5432/mes"
    )
    timezone: str = "Asia/Ho_Chi_Minh"
    session_idle_timeout_minutes: int = 60
    totp_encryption_keys: str | None = None
    cloudflare_access_required: bool = True
    cloudflare_access_team_domain: str | None = None
    cloudflare_access_audience: str | None = None

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
