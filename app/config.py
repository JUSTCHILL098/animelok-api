"""Application settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Animelok Multi Scraper API"
    version: str = "1.0.0"
    base_url: str = Field(default="https://animelok.online", alias="BASE_URL")
    request_timeout: float = 20.0
    request_retries: int = 3
    cache_ttl_seconds: int = 300
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60

    @property
    def normalized_base_url(self) -> str:
        """Return BASE_URL without a trailing slash."""

        return self.base_url.rstrip("/")


settings = Settings()

