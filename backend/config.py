"""
Dragonfly Engine - Configuration

Pydantic Settings for environment-based configuration.
Loads from .env file and environment variables.
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    Required env vars:
        SUPABASE_URL: Supabase project URL
        SUPABASE_SERVICE_ROLE_KEY: Service role key for admin operations
        SUPABASE_DB_URL: Direct Postgres connection string (pooler or direct)

    Optional:
        DISCORD_WEBHOOK_URL: Discord webhook for notifications
        ENVIRONMENT: dev/staging/prod
        LOG_LEVEL: DEBUG/INFO/WARNING/ERROR
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Supabase configuration
    supabase_url: HttpUrl = Field(
        ..., description="Supabase project URL (e.g., https://xxx.supabase.co)"
    )
    supabase_service_role_key: str = Field(
        ..., min_length=100, description="Supabase service role JWT key"
    )
    supabase_db_url: str = Field(
        ..., description="Postgres connection string (pooler or direct)"
    )

    # Discord notifications
    discord_webhook_url: HttpUrl | None = Field(
        default=None, description="Discord webhook URL for notifications"
    )

    # OpenAI (for embeddings)
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for embedding generation"
    )

    # Environment
    environment: Literal["dev", "staging", "prod"] = Field(
        default="dev", description="Deployment environment"
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")

    # Document Assembly Engine
    legal_packet_bucket: str = Field(
        default="legal_packets",
        description="Supabase Storage bucket for generated legal packets",
    )
    # NOTE: Confirm NY post-judgment interest rate with counsel before production.
    # As of 2024, NY CPLR 5004 prescribes 9% per annum, but this can change.
    ny_interest_rate_percent: float = Field(
        default=9.0,
        description="NY post-judgment interest rate (CPLR 5004). Confirm with counsel.",
    )

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment == "prod"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.environment == "dev"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()


def configure_logging(settings: Settings | None = None) -> None:
    """
    Configure application logging based on settings.
    """
    if settings is None:
        settings = get_settings()

    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
        if settings.is_development
        else "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format=log_format,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


# Export settings instance for convenience
settings = get_settings()
