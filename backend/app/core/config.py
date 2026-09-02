"""Конфигурация приложения. Все значения — из переменных окружения (.env)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Общее ---
    app_env: Literal["development", "production"] = "development"
    public_url: str = "http://localhost"

    # --- База данных ---
    postgres_user: str = "lawyer"
    postgres_password: str = "lawyer"
    postgres_db: str = "lawyer"
    postgres_host: str = "db"
    postgres_port: int = 5432

    # --- Аутентификация ---
    admin_login: str = "admin"
    admin_password: str = "admin"
    session_secret: str = "dev-secret-change-me"
    session_ttl_minutes: int = 720

    # --- Источник данных ---
    data_source: Literal["mock", "real"] = "mock"

    # --- Интеграции (Этап E) ---
    bitrix24_webhook_url: str = ""
    bitrix24_inbound_token: str = ""
    yandex_oauth_token: str = ""
    yandex_direct_login: str = ""
    yandex_metrika_counter_id: str = ""
    calltouch_site_id: str = ""
    calltouch_client_api_id: str = ""
    moysklad_token: str = ""
    # DSN Postgres-реплики МойСклад (`mpdb`) — первичный источник данных МойСклад,
    # API МойСклад используется как резерв. Формат:
    # postgresql://user:pass@host:5432/mpdb[?sslmode=require]
    moysklad_pg_dsn: str = ""

    # --- AI-слой ---
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""

    @property
    def database_url(self) -> str:
        """Асинхронный DSN для SQLAlchemy (asyncpg)."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    cors_origins: list[str] = Field(default_factory=list)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
