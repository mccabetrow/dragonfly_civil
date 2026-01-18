"""
Dragonfly Engine - Backend Core Config

STRICT CONFIGURATION LOADER
============================

This module provides the Settings class with strict environment loading.
Auto-loading of .env files is DISABLED. All environment variables must be
pre-loaded via backend.core.loader.load_environment() before importing.

CRITICAL: Import Order Matters
------------------------------
    # CORRECT:
    from backend.core.loader import load_environment
    env = load_environment()  # Loads env vars into os.environ

    from backend.core.config import get_settings
    settings = get_settings()  # Now reads from os.environ

    # WRONG - will use stale/dev credentials:
    from backend.core.config import get_settings
    settings = get_settings()  # DANGER: May load wrong .env

PROD SAFETY:
    If DRAGONFLY_ENV is 'prod' but DB_HOST contains dev project ID,
    a RuntimeError is raised immediately to prevent data corruption.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Dev and prod project IDs for cross-contamination detection
_DEV_PROJECT_ID = "ejiddanxtqcleyswqvkc"
_PROD_PROJECT_ID = "iaketsyhmqbwaabgykux"


class Settings(BaseSettings):
    """
    Application settings with strict environment isolation.

    CRITICAL: Does NOT auto-load any .env file.
    All variables must be present in os.environ before instantiation.
    Use backend.core.loader.load_environment() to populate os.environ.
    """

    # DISABLE auto-loading of .env files
    # Variables must come from os.environ (pre-loaded by loader.py)
    model_config = SettingsConfigDict(
        env_file=None,  # DISABLED - no auto-load
        env_file_encoding="utf-8",
        case_sensitive=False,
        populate_by_name=True,
        extra="ignore",
    )

    # =========================================================================
    # CORE SUPABASE CONFIGURATION
    # Indestructible Boot: DB URL can be missing/malformed - API enters degraded mode
    #
    # SINGLE DSN CONTRACT:
    #   PRIMARY:  DATABASE_URL (industry standard)
    #   FALLBACK: SUPABASE_DB_URL (legacy, emits warning)
    #   MISSING:  Soft-fail (degraded mode), never crash
    # =========================================================================

    # Primary DSN (industry standard)
    DATABASE_URL: str = Field(
        default="",
        description="Primary Postgres connection string (preferred)",
    )

    SUPABASE_URL: str = Field(
        default="",
        description="Supabase project REST URL",
    )
    SUPABASE_SERVICE_ROLE_KEY: str = Field(
        default="",
        description="Supabase service role JWT key",
    )

    # Legacy DSN (fallback only - emits deprecation warning)
    SUPABASE_DB_URL: str = Field(
        default="",
        description="Legacy Postgres connection string (use DATABASE_URL instead)",
    )

    # Migration-only (scripts, not runtime)
    SUPABASE_MIGRATE_DB_URL: str | None = Field(default=None)

    # =========================================================================
    # ENVIRONMENT CONTROL
    # =========================================================================

    DRAGONFLY_ENV: Literal["dev", "prod"] = Field(
        default="dev",
        description="Environment marker set by loader.py",
    )
    ENVIRONMENT: Literal["dev", "staging", "prod"] = Field(
        default="dev",
        description="Deployment environment",
    )
    SUPABASE_MODE: str = Field(
        default="dev",
        description="Supabase mode (dev/prod)",
    )
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO",
        description="Logging level",
    )

    # =========================================================================
    # API AUTHENTICATION
    # =========================================================================

    DRAGONFLY_API_KEY: str | None = Field(default=None)

    # =========================================================================
    # OPTIONAL INTEGRATIONS
    # =========================================================================

    OPENAI_API_KEY: str | None = Field(default=None)
    DISCORD_WEBHOOK_URL: str | None = Field(default=None)
    SENDGRID_API_KEY: str | None = Field(default=None)
    SENDGRID_FROM_EMAIL: str | None = Field(default=None)
    TWILIO_ACCOUNT_SID: str | None = Field(default=None)
    TWILIO_AUTH_TOKEN: str | None = Field(default=None)
    TWILIO_FROM_NUMBER: str | None = Field(default=None)
    CEO_EMAIL: str | None = Field(default=None)
    OPS_EMAIL: str | None = Field(default=None)
    OPS_PHONE: str | None = Field(default=None)
    N8N_API_KEY: str | None = Field(default=None)
    PROOF_API_KEY: str | None = Field(default=None)
    PROOF_API_URL: str | None = Field(default=None)
    PROOF_WEBHOOK_SECRET: str | None = Field(default=None)

    # =========================================================================
    # CORS CONFIGURATION
    # =========================================================================

    DRAGONFLY_CORS_ORIGINS: str | None = Field(default=None)

    # =========================================================================
    # SERVER CONFIGURATION
    # =========================================================================

    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8888)

    # =========================================================================
    # VALIDATION - INDESTRUCTIBLE BOOT PATTERN
    # =========================================================================

    @model_validator(mode="after")
    def _validate_and_set_degraded_mode(self) -> "Settings":
        """
        Post-init validation with Indestructible Boot pattern.

        DSN Resolution Order:
        1. DATABASE_URL (primary, industry standard)
        2. SUPABASE_DB_URL (legacy fallback, emits warning)
        3. None (soft-fail, degraded mode)

        If DATABASE_URL is missing or malformed:
        - Log a warning
        - Set db_state.is_db_connected = False
        - Continue booting in "Degraded Mode"
        - DO NOT raise Fatal Error

        For production: Still validate env/credential mismatch as fatal.
        """
        import backend.core.db_state as db_state_module

        from .db_state import db_state

        # =====================================================================
        # SINGLE DSN CONTRACT: DATABASE_URL is primary, SUPABASE_DB_URL fallback
        # =====================================================================
        effective_db_url = self._resolve_database_url()

        # Check if critical DB config is missing
        if not effective_db_url:
            logger.critical(
                "⚠️ DATABASE_URL not configured - entering DEGRADED MODE\n"
                "   Neither DATABASE_URL nor SUPABASE_DB_URL is set.\n"
                "   /health will return 200, /readyz will return 503\n"
                "   Database operations will fail until configured."
            )
            db_state_module.is_db_connected = False
            db_state.mark_no_config()
            return self

        # Validate DB URL format
        if not effective_db_url.startswith(("postgresql://", "postgres://")):
            logger.warning(
                f"⚠️ DATABASE_URL has invalid format - entering DEGRADED MODE\n"
                f"   Expected: postgresql://... or postgres://...\n"
                f"   Got: {effective_db_url[:30]}...\n"
                f"   Database operations will fail until fixed."
            )
            db_state_module.is_db_connected = False
            db_state.mark_no_config()
            return self

        # Production-specific validation (credential mismatch is still fatal)
        if self.DRAGONFLY_ENV != "prod":
            return self

        # Extract host from effective DB URL
        db_host = self._extract_db_host(effective_db_url)

        # Check for dev project ID in prod environment
        if db_host and _DEV_PROJECT_ID in db_host:
            raise RuntimeError(
                f"CRITICAL: PROD CONFIG LOADED DEV CREDENTIALS\n"
                f"  DRAGONFLY_ENV: {self.DRAGONFLY_ENV}\n"
                f"  DB Host: {db_host}\n"
                f"  Expected: {_PROD_PROJECT_ID}\n\n"
                f"This is a FATAL configuration error.\n"
                f"Ensure DATABASE_URL points to production."
            )

        # Check SUPABASE_URL too
        if _DEV_PROJECT_ID in self.SUPABASE_URL:
            raise RuntimeError(
                f"CRITICAL: PROD CONFIG LOADED DEV SUPABASE_URL\n"
                f"  DRAGONFLY_ENV: {self.DRAGONFLY_ENV}\n"
                f"  SUPABASE_URL: {self.SUPABASE_URL}\n"
                f"  Expected project: {_PROD_PROJECT_ID}\n\n"
                f"This is a FATAL configuration error.\n"
                f"Ensure .env.prod contains production credentials."
            )

        return self

    def _resolve_database_url(self) -> str | None:
        """
        Resolve the effective database URL using Single DSN Contract.

        Resolution Order:
        1. DATABASE_URL (primary, industry standard)
        2. SUPABASE_DB_URL (legacy fallback, emits deprecation warning)
        3. None (triggers degraded mode)

        Returns:
            Effective database URL or None if not configured.
        """
        # Primary: DATABASE_URL
        if self.DATABASE_URL and self.DATABASE_URL.strip():
            return self.DATABASE_URL.strip()

        # Fallback: SUPABASE_DB_URL (legacy, emit warning)
        if self.SUPABASE_DB_URL and self.SUPABASE_DB_URL.strip():
            logger.warning(
                "⚠️ Using legacy SUPABASE_DB_URL - migrate to DATABASE_URL\n"
                "   Set DATABASE_URL in your environment and remove SUPABASE_DB_URL."
            )
            return self.SUPABASE_DB_URL.strip()

        # Neither configured
        return None

    @staticmethod
    def _extract_db_host(db_url: str) -> str | None:
        """Extract hostname from database URL."""
        try:
            parsed = urlparse(db_url)
            return parsed.hostname
        except Exception:
            return None

    # =========================================================================
    # PROPERTY ALIASES (backward compatibility)
    # =========================================================================

    @property
    def supabase_url(self) -> str:
        return self.SUPABASE_URL

    @property
    def supabase_service_role_key(self) -> str:
        return self.SUPABASE_SERVICE_ROLE_KEY

    @property
    def supabase_db_url(self) -> str:
        """Get effective database URL (prefers DATABASE_URL over SUPABASE_DB_URL)."""
        return self._resolve_database_url() or ""

    @property
    def database_url(self) -> str:
        """Canonical database URL accessor (same as supabase_db_url)."""
        return self._resolve_database_url() or ""

    @property
    def supabase_mode(self) -> Literal["dev", "prod"]:
        mode = (self.SUPABASE_MODE or "dev").strip().lower()
        return "prod" if mode in ("prod", "production") else "dev"

    @property
    def environment(self) -> Literal["dev", "staging", "prod"]:
        return self.ENVIRONMENT

    @property
    def log_level(self) -> str:
        return self.LOG_LEVEL

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "prod" or self.DRAGONFLY_ENV == "prod"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "dev"

    @property
    def dragonfly_cors_origins(self) -> str | None:
        return self.DRAGONFLY_CORS_ORIGINS

    @property
    def cors_allowed_origins(self) -> list[str]:
        """
        Parse DRAGONFLY_CORS_ORIGINS into a list.

        SECURITY: If DRAGONFLY_CORS_ORIGINS is missing or empty,
        defaults to [] (Deny All) to prevent accidental open CORS.
        """
        if self.DRAGONFLY_CORS_ORIGINS:
            raw = self.DRAGONFLY_CORS_ORIGINS.replace(",", " ")
            origins = [o.strip().rstrip("/") for o in raw.split() if o.strip().startswith("http")]
            if origins:
                return origins
        # DENY ALL if not configured - fail secure
        return []

    @property
    def cors_origin_regex(self) -> str | None:
        """Regex pattern for CORS origin matching (Vercel previews)."""
        if self.is_production:
            return r"https://dragonfly-console1.*\.vercel\.app"
        return None

    # =========================================================================
    # CREDENTIAL RESOLUTION
    # =========================================================================

    def get_supabase_credentials(self, mode: str | None = None) -> tuple[str, str]:
        """Get Supabase URL and service role key."""
        return self.SUPABASE_URL, self.SUPABASE_SERVICE_ROLE_KEY

    def get_db_url(self, mode: str | None = None) -> str:
        """Get the database URL."""
        return self.SUPABASE_DB_URL


# =========================================================================
# SINGLETON PATTERN
# =========================================================================

_settings_instance: Settings | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get cached settings instance.

    CRITICAL: Call load_environment() before first access to ensure
    correct environment variables are in os.environ.

    Returns:
        Singleton Settings instance

    Raises:
        RuntimeError: If environment hasn't been initialized
    """
    # Warn if loader hasn't been called
    if not os.environ.get("DRAGONFLY_ENV"):
        logger.warning(
            "DRAGONFLY_ENV not set. Call load_environment() before get_settings(). "
            "Defaulting to 'dev' mode."
        )
        os.environ["DRAGONFLY_ENV"] = "dev"

    return Settings()  # type: ignore[call-arg]


def reset_settings() -> None:
    """Clear the cached settings (for testing or environment switch)."""
    global _settings_instance
    _settings_instance = None
    get_settings.cache_clear()


# =========================================================================
# STARTUP HELPERS
# =========================================================================


def log_startup_diagnostics(service_name: str = "Dragonfly") -> None:
    """
    Log startup diagnostics for audit trail.

    Args:
        service_name: Name of the service for log prefix
    """
    settings = get_settings()

    # Use resolved database URL
    effective_db_url = settings.database_url
    db_host = Settings._extract_db_host(effective_db_url) if effective_db_url else "not_configured"
    db_source = (
        "DATABASE_URL"
        if settings.DATABASE_URL
        else ("SUPABASE_DB_URL" if settings.SUPABASE_DB_URL else "none")
    )

    logger.info("╔══════════════════════════════════════════════════════════════════╗")
    logger.info(f"║  {service_name} Startup Diagnostics")
    logger.info("╠══════════════════════════════════════════════════════════════════╣")
    logger.info(f"║  DRAGONFLY_ENV:  {settings.DRAGONFLY_ENV}")
    logger.info(f"║  ENVIRONMENT:    {settings.ENVIRONMENT}")
    logger.info(f"║  SUPABASE_MODE:  {settings.SUPABASE_MODE}")
    logger.info(f"║  DB Host:        {db_host}")
    logger.info(f"║  DSN Source:     {db_source}")
    logger.info(f"║  LOG_LEVEL:      {settings.LOG_LEVEL}")
    logger.info("╚══════════════════════════════════════════════════════════════════╝")


def validate_required_env(fail_fast: bool = True) -> dict[str, Any]:
    """
    Validate required environment variables.

    Args:
        fail_fast: If True, raise on missing required vars

    Returns:
        Validation result dict

    Raises:
        RuntimeError: If fail_fast and required vars missing
    """
    # Single DSN Contract: DATABASE_URL is primary, SUPABASE_DB_URL is fallback
    required_core = ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]

    # Check for database URL (either primary or fallback)
    has_database_url = bool(os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL"))

    missing = [var for var in required_core if not os.environ.get(var)]

    # Add database URL to missing if neither is set
    if not has_database_url:
        missing.append("DATABASE_URL")

    # Build present list
    present = [var for var in required_core if os.environ.get(var)]
    if os.environ.get("DATABASE_URL"):
        present.append("DATABASE_URL")
    elif os.environ.get("SUPABASE_DB_URL"):
        present.append("SUPABASE_DB_URL (legacy)")

    # Check for legacy usage
    warnings = []
    if os.environ.get("SUPABASE_DB_URL") and not os.environ.get("DATABASE_URL"):
        warnings.append("Using legacy SUPABASE_DB_URL - migrate to DATABASE_URL")

    result = {
        "valid": len(missing) == 0,
        "present": present,
        "missing": missing,
        "warnings": warnings,
    }

    if missing and fail_fast:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Set DATABASE_URL (preferred) or SUPABASE_DB_URL (legacy)."
        )

    return result


# =========================================================================
# EXPORTS
# =========================================================================

__all__ = [
    "Settings",
    "get_settings",
    "reset_settings",
    "log_startup_diagnostics",
    "validate_required_env",
]
