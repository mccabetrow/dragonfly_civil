"""
Dragonfly Engine - Unified Configuration

CANONICAL ENVIRONMENT VARIABLE CONTRACT
========================================

This module is the SINGLE SOURCE OF TRUTH for all Dragonfly configuration.
Both API (backend/) and workers (backend/workers/, workers/) use this loader.

CANONICAL ENV VARS (uppercase, no suffix):
------------------------------------------
Required:
  SUPABASE_URL                  - Supabase project REST URL (https://xxx.supabase.co)
  SUPABASE_SERVICE_ROLE_KEY     - Service role JWT (server-side only, 100+ chars)
  SUPABASE_DB_URL               - Postgres connection string (pooler recommended)

Environment control:
  ENVIRONMENT                   - dev | staging | prod (default: dev)
  SUPABASE_MODE                 - dev | prod (for DSN resolution, default: dev)
  LOG_LEVEL                     - DEBUG | INFO | WARNING | ERROR (default: INFO)

Optional integrations:
  DRAGONFLY_API_KEY             - API key for X-API-Key header auth
  OPENAI_API_KEY                - Embedding generation for semantic search
  DISCORD_WEBHOOK_URL           - Alerts for intake failures, escalations
  SENDGRID_API_KEY              - Email notifications
  TWILIO_ACCOUNT_SID            - SMS notifications
  DRAGONFLY_CORS_ORIGINS        - Comma-separated CORS origins

PROD OVERRIDES (legacy, deprecated):
------------------------------------
These are accepted for backward compatibility but emit warnings:
  SUPABASE_URL_PROD             -> use SUPABASE_URL with SUPABASE_MODE=prod
  SUPABASE_SERVICE_ROLE_KEY_PROD
  SUPABASE_DB_URL_PROD
  SUPABASE_DB_URL_DIRECT_PROD

LOWERCASE ALIASES (legacy, deprecated):
---------------------------------------
These are accepted for backward compatibility but emit warnings:
  supabase_url                  -> SUPABASE_URL
  supabase_service_role_key     -> SUPABASE_SERVICE_ROLE_KEY
  supabase_db_url               -> SUPABASE_DB_URL

Usage:
------
    from src.core_config import get_settings, Settings

    settings = get_settings()
    print(settings.supabase_url)
    print(settings.supabase_db_url)
"""

from __future__ import annotations

import logging
import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Track which deprecated keys are used (for diagnostic output)
_DEPRECATED_KEYS_USED: set[str] = set()

# Mapping of deprecated keys to canonical keys
_DEPRECATED_TO_CANONICAL = {
    # Lowercase variants
    "supabase_url": "SUPABASE_URL",
    "supabase_service_role_key": "SUPABASE_SERVICE_ROLE_KEY",
    "supabase_db_url": "SUPABASE_DB_URL",
    "supabase_mode": "SUPABASE_MODE",
    "environment": "ENVIRONMENT",
    "log_level": "LOG_LEVEL",
    # _PROD suffix variants (only needed when SUPABASE_MODE != prod)
    "SUPABASE_URL_PROD": "SUPABASE_URL (with SUPABASE_MODE=prod)",
    "SUPABASE_SERVICE_ROLE_KEY_PROD": "SUPABASE_SERVICE_ROLE_KEY (with SUPABASE_MODE=prod)",
    "SUPABASE_DB_URL_PROD": "SUPABASE_DB_URL (with SUPABASE_MODE=prod)",
    "SUPABASE_DB_URL_DIRECT_PROD": "SUPABASE_DB_URL (with SUPABASE_MODE=prod)",
}


def _check_deprecated_env_vars() -> None:
    """Check for deprecated env var usage and emit warnings."""
    for deprecated, canonical in _DEPRECATED_TO_CANONICAL.items():
        if deprecated in os.environ:
            _DEPRECATED_KEYS_USED.add(deprecated)
            if deprecated.islower():
                # Lowercase variant - definitely deprecated
                warnings.warn(
                    f"Environment variable '{deprecated}' is deprecated. "
                    f"Use uppercase '{canonical}' instead.",
                    DeprecationWarning,
                    stacklevel=3,
                )
            elif deprecated.endswith("_PROD"):
                # _PROD suffix - only warn if not in prod mode
                mode = os.environ.get("SUPABASE_MODE", "").lower()
                if mode not in ("prod", "production"):
                    logger.info(
                        f"Using {deprecated} for prod credentials. "
                        f"Consider setting SUPABASE_MODE=prod and using {canonical}."
                    )


def get_deprecated_keys_used() -> set[str]:
    """Get the set of deprecated keys that were used during config load."""
    return _DEPRECATED_KEYS_USED.copy()


class Settings(BaseSettings):
    """
    Unified application settings for API and workers.

    Loads from environment variables with fallback to .env file.
    Supports both canonical uppercase and legacy lowercase/suffix keys.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,  # Accept both SUPABASE_URL and supabase_url
        populate_by_name=True,
        extra="ignore",
    )

    # =========================================================================
    # CORE SUPABASE CONFIGURATION
    # =========================================================================

    # Primary credentials (for dev or when SUPABASE_MODE=prod)
    SUPABASE_URL: str = Field(
        ...,
        description="Supabase project REST URL",
        json_schema_extra={"env": ["SUPABASE_URL", "supabase_url"]},
    )
    SUPABASE_SERVICE_ROLE_KEY: str = Field(
        ...,
        min_length=100,
        description="Supabase service role JWT key",
        json_schema_extra={"env": ["SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"]},
    )
    SUPABASE_DB_URL: str | None = Field(
        default=None,
        description="Postgres connection string (pooler recommended)",
        json_schema_extra={"env": ["SUPABASE_DB_URL", "supabase_db_url"]},
    )

    # Legacy _PROD suffixed credentials (backward compatibility)
    SUPABASE_URL_PROD: str | None = Field(default=None, description="[DEPRECATED] Prod URL")
    SUPABASE_SERVICE_ROLE_KEY_PROD: str | None = Field(
        default=None, description="[DEPRECATED] Prod key"
    )
    SUPABASE_DB_URL_PROD: str | None = Field(default=None, description="[DEPRECATED] Prod DB URL")
    SUPABASE_DB_URL_DIRECT_PROD: str | None = Field(
        default=None, description="[DEPRECATED] Direct prod DB URL"
    )
    SUPABASE_DB_PASSWORD: str | None = Field(
        default=None, description="DB password for URL construction"
    )
    SUPABASE_DB_PASSWORD_PROD: str | None = Field(
        default=None, description="[DEPRECATED] Prod DB password"
    )

    # =========================================================================
    # ENVIRONMENT CONTROL
    # =========================================================================

    ENVIRONMENT: Literal["dev", "staging", "prod"] = Field(
        default="dev",
        description="Deployment environment",
        json_schema_extra={"env": ["ENVIRONMENT", "environment"]},
    )
    SUPABASE_MODE: str = Field(
        default="dev",
        description="Supabase mode (dev/prod) for credential selection",
        json_schema_extra={"env": ["SUPABASE_MODE", "supabase_mode"]},
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
        json_schema_extra={"env": ["LOG_LEVEL", "log_level"]},
    )

    # =========================================================================
    # API AUTHENTICATION
    # =========================================================================

    DRAGONFLY_API_KEY: str | None = Field(
        default=None,
        description="API key for X-API-Key header authentication",
    )

    # =========================================================================
    # OPTIONAL INTEGRATIONS
    # =========================================================================

    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key")
    DISCORD_WEBHOOK_URL: str | None = Field(default=None, description="Discord webhook URL")
    SENDGRID_API_KEY: str | None = Field(default=None, description="SendGrid API key")
    SENDGRID_FROM_EMAIL: str | None = Field(default=None, description="SendGrid sender email")
    TWILIO_ACCOUNT_SID: str | None = Field(default=None, description="Twilio Account SID")
    TWILIO_AUTH_TOKEN: str | None = Field(default=None, description="Twilio Auth Token")
    TWILIO_FROM_NUMBER: str | None = Field(default=None, description="Twilio sender number")
    CEO_EMAIL: str | None = Field(default=None, description="CEO email for briefings")
    OPS_EMAIL: str | None = Field(default=None, description="Ops team email")
    OPS_PHONE: str | None = Field(default=None, description="Ops team phone (E.164)")
    N8N_API_KEY: str | None = Field(default=None, description="n8n API key")

    # =========================================================================
    # PROOF.COM INTEGRATION
    # =========================================================================

    PROOF_API_KEY: str | None = Field(default=None, description="Proof.com API key")
    PROOF_API_URL: str | None = Field(default=None, description="Proof.com API URL")
    PROOF_WEBHOOK_SECRET: str | None = Field(default=None, description="Proof webhook secret")

    # =========================================================================
    # CORS CONFIGURATION
    # =========================================================================

    DRAGONFLY_CORS_ORIGINS: str | None = Field(
        default=None,
        description="Comma-separated CORS origins",
    )

    # =========================================================================
    # SERVER CONFIGURATION
    # =========================================================================

    HOST: str = Field(default="0.0.0.0", description="Server host")
    PORT: int = Field(default=8888, description="Server port")

    # =========================================================================
    # SESSION & ENCRYPTION
    # =========================================================================

    SESSION_PATH: str = Field(
        default=str(Path("state") / "session.json"),
        description="Path to session file",
    )
    ENCRYPT_SESSIONS: bool = Field(default=True, description="Encrypt session data")
    SESSION_KMS_KEY: str | None = Field(default=None, description="KMS key for session encryption")

    # =========================================================================
    # DOCUMENT ASSEMBLY
    # =========================================================================

    LEGAL_PACKET_BUCKET: str = Field(
        default="legal_packets",
        description="Supabase Storage bucket for legal packets",
    )
    NY_INTEREST_RATE_PERCENT: float = Field(
        default=9.0,
        description="NY post-judgment interest rate (CPLR 5004)",
    )

    # =========================================================================
    # VALIDATION & NORMALIZATION
    # =========================================================================

    @model_validator(mode="before")
    @classmethod
    def _normalize_values(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Normalize string values (strip whitespace, quotes)."""
        for key, value in list(values.items()):
            if isinstance(value, str):
                # Strip whitespace and quotes
                cleaned = value.strip().strip('"').strip("'").strip()
                values[key] = cleaned
        return values

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization: check for deprecated keys."""
        _check_deprecated_env_vars()

    # =========================================================================
    # PROPERTY ALIASES (backward compatibility)
    # =========================================================================

    @property
    def supabase_url(self) -> str:
        """Lowercase alias for SUPABASE_URL."""
        return self.SUPABASE_URL

    @property
    def supabase_service_role_key(self) -> str:
        """Lowercase alias for SUPABASE_SERVICE_ROLE_KEY."""
        return self.SUPABASE_SERVICE_ROLE_KEY

    @property
    def supabase_db_url(self) -> str:
        """Get the effective database URL based on mode."""
        return self.get_db_url()

    @property
    def supabase_mode(self) -> Literal["dev", "prod"]:
        """Normalized Supabase mode."""
        mode = (self.SUPABASE_MODE or "dev").strip().lower()
        if mode in ("prod", "production"):
            return "prod"
        return "dev"

    @property
    def environment(self) -> Literal["dev", "staging", "prod"]:
        """Lowercase alias for ENVIRONMENT."""
        return self.ENVIRONMENT

    @property
    def log_level(self) -> str:
        """Lowercase alias for LOG_LEVEL."""
        return self.LOG_LEVEL

    @property
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.ENVIRONMENT == "prod"

    @property
    def is_development(self) -> bool:
        """Check if running in development."""
        return self.ENVIRONMENT == "dev"

    @property
    def legal_packet_bucket(self) -> str:
        """Lowercase alias for LEGAL_PACKET_BUCKET."""
        return self.LEGAL_PACKET_BUCKET

    @property
    def ny_interest_rate_percent(self) -> float:
        """Lowercase alias for NY_INTEREST_RATE_PERCENT."""
        return self.NY_INTEREST_RATE_PERCENT

    # =========================================================================
    # CORS HELPERS
    # =========================================================================

    @property
    def dragonfly_cors_origins(self) -> str | None:
        """Lowercase alias for DRAGONFLY_CORS_ORIGINS."""
        return self.DRAGONFLY_CORS_ORIGINS

    @property
    def cors_allowed_origins(self) -> list[str]:
        """Parse DRAGONFLY_CORS_ORIGINS into a list."""
        if self.DRAGONFLY_CORS_ORIGINS:
            raw = self.DRAGONFLY_CORS_ORIGINS.replace(",", " ")
            origins = []
            for o in raw.split():
                o = o.strip().rstrip("/")
                if o and o.startswith("http"):
                    origins.append(o)
            if origins:
                return origins
        return ["http://localhost:3000", "http://localhost:5173"]

    @property
    def cors_origin_regex(self) -> str | None:
        """Regex pattern for CORS origin matching."""
        default_pattern = r"https://dragonfly-console1.*\.vercel\.app"
        return default_pattern if self.ENVIRONMENT in ("prod", "staging") else None

    # =========================================================================
    # CREDENTIAL RESOLUTION
    # =========================================================================

    def get_supabase_credentials(self, mode: str | None = None) -> tuple[str, str]:
        """
        Get Supabase URL and service role key for the specified mode.

        Args:
            mode: 'dev' or 'prod'. Defaults to self.supabase_mode.

        Returns:
            Tuple of (url, service_role_key)
        """
        effective_mode = mode or self.supabase_mode

        if effective_mode == "prod":
            # Try _PROD suffixed first for backward compatibility
            url = self.SUPABASE_URL_PROD or self.SUPABASE_URL
            key = self.SUPABASE_SERVICE_ROLE_KEY_PROD or self.SUPABASE_SERVICE_ROLE_KEY
        else:
            url = self.SUPABASE_URL
            key = self.SUPABASE_SERVICE_ROLE_KEY

        if not url or not key:
            raise RuntimeError(
                f"Missing Supabase credentials for mode '{effective_mode}'. "
                f"Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
            )
        return url, key

    def get_db_url(self, mode: str | None = None) -> str:
        """
        Get the database URL for the specified mode.

        Args:
            mode: 'dev' or 'prod'. Defaults to self.supabase_mode.

        Returns:
            PostgreSQL connection string
        """
        effective_mode = mode or self.supabase_mode

        if effective_mode == "prod":
            # Try direct URL first (best for prod)
            if self.SUPABASE_DB_URL_DIRECT_PROD:
                return self.SUPABASE_DB_URL_DIRECT_PROD
            if self.SUPABASE_DB_URL_PROD:
                return self.SUPABASE_DB_URL_PROD

        # Fall back to primary DB URL
        if self.SUPABASE_DB_URL:
            return self.SUPABASE_DB_URL

        raise RuntimeError(
            f"Missing database URL for mode '{effective_mode}'. " f"Set SUPABASE_DB_URL."
        )


# =========================================================================
# SINGLETON & FACTORY
# =========================================================================

_settings_instance: Settings | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Uses lru_cache to ensure settings are only loaded once.
    """
    return Settings()  # type: ignore[call-arg]


def reset_settings() -> None:
    """Clear the cached settings (for testing)."""
    get_settings.cache_clear()


# =========================================================================
# LOGGING CONFIGURATION
# =========================================================================


def configure_logging(settings: Settings | None = None) -> None:
    """
    Configure application logging based on settings.

    In production, uses structured JSON logging for observability.
    In development, uses colored console output.
    """
    if settings is None:
        settings = get_settings()

    # Try to use structured logging if available
    try:
        from backend.core.logging import configure_structured_logging

        configure_structured_logging(
            level=settings.LOG_LEVEL,
            json_output=settings.is_production,
            service_name="dragonfly",
        )
    except ImportError:
        # Fallback to basic logging
        logging.basicConfig(
            level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
            format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # Quiet noisy loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)


# =========================================================================
# DIAGNOSTIC HELPERS
# =========================================================================


def print_effective_config(redact_secrets: bool = True) -> dict[str, Any]:
    """
    Print the effective configuration (for diagnostics).

    Args:
        redact_secrets: If True, redact sensitive values

    Returns:
        Dict of effective configuration values
    """
    settings = get_settings()

    secret_fields = {
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY_PROD",
        "SUPABASE_DB_URL",
        "SUPABASE_DB_URL_PROD",
        "SUPABASE_DB_URL_DIRECT_PROD",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_DB_PASSWORD_PROD",
        "DRAGONFLY_API_KEY",
        "OPENAI_API_KEY",
        "SENDGRID_API_KEY",
        "TWILIO_AUTH_TOKEN",
        "PROOF_API_KEY",
        "PROOF_WEBHOOK_SECRET",
        "SESSION_KMS_KEY",
        "N8N_API_KEY",
    }

    config = {}
    for field_name in settings.model_fields:
        value = getattr(settings, field_name, None)
        if redact_secrets and field_name.upper() in secret_fields:
            if value:
                config[field_name] = f"***SET*** (len={len(str(value))})"
            else:
                config[field_name] = None
        else:
            config[field_name] = value

    # Add computed properties
    config["_computed"] = {
        "supabase_mode": settings.supabase_mode,
        "is_production": settings.is_production,
        "cors_allowed_origins": settings.cors_allowed_origins,
    }

    # Add deprecated keys info
    config["_deprecated_keys_used"] = list(get_deprecated_keys_used())

    return config


# =========================================================================
# BACKWARD COMPATIBILITY HELPERS
# =========================================================================


def is_demo_env() -> bool:
    """Check if running in demo/local environment."""
    value = os.getenv("DEMO_ENV", "local")
    return value.lower() in {"local", "demo"}


def ensure_parent_dir(path_str: str) -> None:
    """Ensure parent directory exists for a file path."""
    path = Path(path_str).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
