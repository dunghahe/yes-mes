from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://mes_app:local_dev_only@localhost:5432/mes"
    migration_database_url: str = (
        "postgresql+psycopg://mes_migrator:local_dev_only@localhost:5432/mes"
    )
    timezone: str = "Asia/Ho_Chi_Minh"

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
