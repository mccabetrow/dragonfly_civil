"""
Dragonfly Engine - Configuration

Pydantic Settings for environment-based configuration.
Loads from .env file and environment variables.

================================================================================
SINGLE SOURCE OF TRUTH – PRODUCTION ENVIRONMENT VARIABLE REFERENCE
================================================================================

REQUIRED for application startup:
  SUPABASE_URL             – Supabase project REST URL (https://xxx.supabase.co)
  SUPABASE_SERVICE_ROLE_KEY– Service role JWT (server-side only, 100+ chars)
  SUPABASE_DB_URL          – Postgres connection string (pooler recommended)

REQUIRED for Railway production behavior:
  ENVIRONMENT=prod         – Enables rate limiting, stricter logging
  SUPABASE_MODE=prod       – Used by Python scripts/tools for DSN resolution
  PORT                     – Injected by Railway; default fallback is 8888

REQUIRED for API key authentication (X-API-Key header):
  DRAGONFLY_API_KEY        – Read from os.environ ONLY (not file secrets)
                             If missing in prod, logs warning but does not crash

OPTIONAL – Notification integrations:
  DISCORD_WEBHOOK_URL      – Discord alerts for intake failures, escalations
  SENDGRID_API_KEY         – Email notifications (CEO briefing, alerts)
  SENDGRID_FROM_EMAIL      – Default sender for SendGrid
  TWILIO_ACCOUNT_SID       – SMS notifications
  TWILIO_AUTH_TOKEN        – Twilio auth
  TWILIO_FROM_NUMBER       – E.164 format sender number

OPTIONAL – Recipients:
  CEO_EMAIL                – Executive briefings
  OPS_EMAIL                – Operational alerts
  OPS_PHONE                – SMS alerts (E.164 format)

OPTIONAL – Advanced:
  OPENAI_API_KEY           – Embedding generation for semantic search
  SUPABASE_JWT_SECRET      – JWT token validation (if using Supabase Auth JWTs)
  LOG_LEVEL                – DEBUG/INFO/WARNING/ERROR (default: INFO)

DEPLOYMENT NOTES:
  - Railway injects env vars at runtime; never use file-based /secrets/ paths.
  - Never commit secrets; Railway encrypts env vars at rest.
  - For local dev, copy .env.example to .env and fill in values.
  - Run `python -m tools.doctor --env prod` after any config change.
================================================================================
"""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    See module docstring for the complete production env var reference.
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

    # Email notifications (SendGrid)
    sendgrid_api_key: str | None = Field(
        default=None, description="SendGrid API key for email notifications"
    )
    sendgrid_from_email: str | None = Field(
        default=None, description="Default sender email for SendGrid"
    )

    # SMS notifications (Twilio)
    twilio_account_sid: str | None = Field(
        default=None, description="Twilio Account SID"
    )
    twilio_auth_token: str | None = Field(default=None, description="Twilio Auth Token")
    twilio_from_number: str | None = Field(
        default=None, description="Twilio sender phone number (E.164 format)"
    )

    # Notification recipients
    ceo_email: str | None = Field(
        default=None, description="CEO email for executive briefings"
    )
    ops_email: str | None = Field(
        default=None, description="Ops team email for operational alerts"
    )
    ops_phone: str | None = Field(
        default=None, description="Ops team phone for SMS alerts (E.164 format)"
    )

    # OpenAI (for embeddings)
    openai_api_key: str | None = Field(
        default=None, description="OpenAI API key for embedding generation"
    )

    # Proof.com (process server dispatch)
    proof_api_key: str | None = Field(
        default=None, description="Proof.com API key for process server dispatch"
    )
    proof_api_url: str | None = Field(
        default=None,
        description="Proof.com API URL (sandbox: https://api.sandbox.proof.com, prod: https://api.proof.com)",
    )
    proof_webhook_secret: str | None = Field(
        default=None, description="Proof.com webhook signature verification secret"
    )

    # Environment
    environment: Literal["dev", "staging", "prod"] = Field(
        default="dev", description="Deployment environment"
    )

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )

    # =========================================================================
    # CORS Configuration
    # =========================================================================
    # Comma-separated list of allowed origins for CORS.
    # Railway env var: DRAGONFLY_CORS_ORIGINS
    #
    # Example for production:
    #   DRAGONFLY_CORS_ORIGINS="https://dragonfly-console1.vercel.app,https://dragonfly-console1-git-main-mccabetrow.vercel.app,http://localhost:5173"
    #
    # Note: Wildcards like https://*.vercel.app do NOT work with CORS.
    # You must list each specific origin or Vercel preview URL explicitly.
    #
    # Parsing rules:
    #   - Comma or space-separated
    #   - Strips whitespace and trailing slashes
    #   - Ignores empty entries
    dragonfly_cors_origins: str | None = Field(
        default=None,
        description="Comma-separated CORS origins (Railway: DRAGONFLY_CORS_ORIGINS)",
    )

    @property
    def cors_allowed_origins(self) -> list[str]:
        """
        Parse DRAGONFLY_CORS_ORIGINS into a list.
        Falls back to localhost origins if unset.

        Handles:
          - Comma-separated: "https://a.com,https://b.com"
          - Space-separated: "https://a.com https://b.com"
          - Trailing slashes: "https://a.com/"
          - Whitespace: " https://a.com , https://b.com "
        """
        if self.dragonfly_cors_origins:
            # Support both comma and space as separators
            raw = self.dragonfly_cors_origins.replace(",", " ")
            origins = []
            for o in raw.split():
                o = o.strip().rstrip("/")  # Strip whitespace and trailing slash
                if o and o.startswith("http"):
                    origins.append(o)
            if origins:
                return origins
        # Default fallback for local dev
        return ["http://localhost:3000", "http://localhost:5173"]

    @property
    def cors_origin_regex(self) -> str | None:
        """
        Regex pattern for CORS origin matching.

        Supports Vercel preview deployments like:
          https://dragonfly-console1-<hash>.vercel.app
          https://dragonfly-console1-git-<branch>-<user>.vercel.app

        Returns None if DRAGONFLY_CORS_ORIGIN_REGEX is not set.
        """
        # Default pattern for Vercel preview deployments
        # Matches: https://dragonfly-console1*.vercel.app
        default_pattern = r"https://dragonfly-console1[\w-]*\.vercel\.app"
        return default_pattern if self.environment in ("prod", "staging") else None

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
