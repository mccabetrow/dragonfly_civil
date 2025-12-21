"""
Dragonfly Engine - Unified Configuration

CANONICAL ENVIRONMENT VARIABLE CONTRACT v2.0
=============================================

This module is the SINGLE SOURCE OF TRUTH for all Dragonfly configuration.
Both API (backend/) and workers (backend/workers/, workers/) use this loader.

CANONICAL ENV VARS (no suffixes, mode-based):
---------------------------------------------
Required:
  SUPABASE_URL                  - Supabase project REST URL (https://xxx.supabase.co)
  SUPABASE_SERVICE_ROLE_KEY     - Service role JWT (server-side only, 100+ chars)
  SUPABASE_DB_URL               - Postgres connection string (pooler recommended)

Environment control:
  SUPABASE_MODE                 - dev | prod (determines which project, default: dev)
  ENVIRONMENT                   - dev | staging | prod (affects logging/rate limits, default: dev)
  LOG_LEVEL                     - DEBUG | INFO | WARNING | ERROR (default: INFO)

Optional integrations:
  DRAGONFLY_API_KEY             - API key for X-API-Key header auth
  OPENAI_API_KEY                - Embedding generation for semantic search
  DISCORD_WEBHOOK_URL           - Alerts for intake failures, escalations
  SENDGRID_API_KEY              - Email notifications
  TWILIO_ACCOUNT_SID            - SMS notifications
  DRAGONFLY_CORS_ORIGINS        - Comma-separated CORS origins

REMOVED (v2.0 - fail if present):
---------------------------------
The following variables are NO LONGER SUPPORTED:
  SUPABASE_URL_PROD             - Use SUPABASE_URL with SUPABASE_MODE=prod
  SUPABASE_SERVICE_ROLE_KEY_PROD
  SUPABASE_DB_URL_PROD
  SUPABASE_DB_URL_DEV
  SUPABASE_DB_URL_DIRECT_PROD
  supabase_url (lowercase)      - Use SUPABASE_URL

FAIL-FAST BEHAVIOR:
-------------------
If required variables are missing, the app exits immediately with a clear message:

  FATAL: Missing required environment variable: SUPABASE_DB_URL

  Required for database connectivity:
    SUPABASE_URL              ✓ set
    SUPABASE_SERVICE_ROLE_KEY ✓ set
    SUPABASE_DB_URL           ✗ MISSING

  Current SUPABASE_MODE: dev

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

# Deprecated keys that are NO LONGER SUPPORTED (v2.0)
# If any of these are set, fail fast with a migration message
_REMOVED_KEYS = {
    "SUPABASE_URL_PROD",
    "SUPABASE_SERVICE_ROLE_KEY_PROD",
    "SUPABASE_DB_URL_DIRECT_PROD",
    "SUPABASE_DB_PASSWORD",
    "SUPABASE_DB_PASSWORD_PROD",
}

# Migration-only vars: warn but don't crash (used by scripts/tooling, not runtime app)
# These are deprecated for RUNTIME but still allowed for MIGRATION SCRIPTS
_MIGRATION_ONLY_KEYS = {
    "SUPABASE_DB_URL_PROD",
    "SUPABASE_DB_URL_DEV",
    "SUPABASE_MIGRATE_DB_URL",  # Canonical migration-only credential
}

# Lowercase aliases that are deprecated but accepted (with warning)
_LOWERCASE_ALIASES = {
    "supabase_url": "SUPABASE_URL",
    "supabase_service_role_key": "SUPABASE_SERVICE_ROLE_KEY",
    "supabase_db_url": "SUPABASE_DB_URL",
    "supabase_mode": "SUPABASE_MODE",
    "environment": "ENVIRONMENT",
    "log_level": "LOG_LEVEL",
}


def _check_removed_env_vars() -> None:
    """Check for removed env vars and warn/fail with migration guidance.

    In dev mode (SUPABASE_MODE=dev or unset): logs a warning
    In prod mode (SUPABASE_MODE=prod): raises RuntimeError
    """
    found_removed = []
    for key in _REMOVED_KEYS:
        if os.environ.get(key):
            found_removed.append(key)

    # Check for migration-only keys (warn but never crash)
    found_migration_only = []
    for key in _MIGRATION_ONLY_KEYS:
        if os.environ.get(key):
            found_migration_only.append(key)
            _DEPRECATED_KEYS_USED.add(key)

    if found_migration_only:
        logger.info(
            "Migration-only environment variables detected (OK for scripts, not for runtime): %s",
            ", ".join(found_migration_only),
        )

    if not found_removed:
        return

    migration_msg = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                    CONFIGURATION MIGRATION REQUIRED                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║ The following environment variables are NO LONGER SUPPORTED:                 ║
║                                                                              ║
"""
    for key in found_removed:
        migration_msg += f"║   ✗ {key:<68} ║\n"

    migration_msg += """║                                                                              ║
║ MIGRATION: Use a single set of canonical variables per environment:         ║
║                                                                              ║
║   Production (Railway):                                                      ║
║     SUPABASE_MODE=prod                                                       ║
║     SUPABASE_URL=https://your-prod-project.supabase.co                       ║
║     SUPABASE_SERVICE_ROLE_KEY=eyJ...                                         ║
║     SUPABASE_DB_URL=postgresql://dragonfly_app:pass@host:5432/postgres       ║
║                                                                              ║
║   Development (local .env):                                                  ║
║     SUPABASE_MODE=dev                                                        ║
║     SUPABASE_URL=https://your-dev-project.supabase.co                        ║
║     SUPABASE_SERVICE_ROLE_KEY=eyJ...                                         ║
║     SUPABASE_DB_URL=postgresql://postgres:pass@host:5432/postgres            ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
    # In production mode, fail fast. In dev mode, warn but continue.
    mode = os.environ.get("SUPABASE_MODE", "dev").lower().strip()
    if mode in ("prod", "production"):
        raise RuntimeError(migration_msg)
    else:
        logger.warning(
            "Deprecated environment variables detected (will fail in prod):\n%s",
            ", ".join(found_removed),
        )
        for key in found_removed:
            warnings.warn(
                f"Environment variable '{key}' is deprecated. Remove it and use canonical variables.",
                DeprecationWarning,
                stacklevel=4,
            )


def _check_deprecated_env_vars() -> None:
    """Check for deprecated lowercase env var usage and emit warnings."""
    for deprecated, canonical in _LOWERCASE_ALIASES.items():
        if deprecated in os.environ:
            _DEPRECATED_KEYS_USED.add(deprecated)
            warnings.warn(
                f"Environment variable '{deprecated}' is deprecated. "
                f"Use uppercase '{canonical}' instead.",
                DeprecationWarning,
                stacklevel=3,
            )


def get_deprecated_keys_used() -> set[str]:
    """Get the set of deprecated keys that were used during config load."""
    return _DEPRECATED_KEYS_USED.copy()


class Settings(BaseSettings):
    """
    Unified application settings for API and workers.

    Loads from environment variables with fallback to env file.

    ONE FILE, ONE ENVIRONMENT PATTERN:
        Set ENV_FILE to point to the correct file:
        - ENV_FILE=.env.dev  → loads development credentials
        - ENV_FILE=.env.prod → loads production credentials
        - Defaults to .env.dev if ENV_FILE is not set

    Supports both canonical uppercase and legacy lowercase keys.
    """

    model_config = SettingsConfigDict(
        env_file=os.environ.get("ENV_FILE", ".env.dev"),
        env_file_encoding="utf-8",
        case_sensitive=False,  # Accept both SUPABASE_URL and supabase_url
        populate_by_name=True,
        extra="ignore",
    )

    # =========================================================================
    # CORE SUPABASE CONFIGURATION (Canonical - no suffixes)
    # =========================================================================

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
    SUPABASE_DB_URL: str = Field(
        ...,
        description="Postgres connection string (pooler recommended)",
        json_schema_extra={"env": ["SUPABASE_DB_URL", "supabase_db_url"]},
    )

    # Migration-only credential (used by scripts/db_push.ps1, not runtime app)
    SUPABASE_MIGRATE_DB_URL: str | None = Field(
        default=None,
        description="Postgres connection string for migrations only (direct port 5432)",
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
        """Normalize string values and check for removed/deprecated keys."""
        # FAIL FAST: Check for removed env vars before anything else
        _check_removed_env_vars()

        # Collision guard: check for canonical + lowercase alias conflicts
        _COLLISION_PAIRS = [
            ("SUPABASE_URL", "supabase_url"),
            ("SUPABASE_SERVICE_ROLE_KEY", "supabase_service_role_key"),
            ("SUPABASE_DB_URL", "supabase_db_url"),
            ("SUPABASE_MODE", "supabase_mode"),
            ("ENVIRONMENT", "environment"),
            ("LOG_LEVEL", "log_level"),
        ]
        collisions = []
        for canonical, deprecated in _COLLISION_PAIRS:
            canonical_val = os.environ.get(canonical)
            deprecated_val = os.environ.get(deprecated)
            if canonical_val and deprecated_val and canonical_val != deprecated_val:
                collisions.append(
                    f"  • {canonical}={canonical_val!r} vs {deprecated}={deprecated_val!r}"
                )
        if collisions:
            raise ValueError(
                "Configuration collision detected! Both canonical and deprecated env vars "
                "are set with DIFFERENT values:\n"
                + "\n".join(collisions)
                + "\n\nFix: Remove the deprecated lowercase variant(s) and use only the "
                "canonical UPPERCASE key."
            )

        # Critical DB vars that need aggressive sanitization
        DB_CRITICAL_KEYS = {
            "SUPABASE_DB_URL",
            "supabase_db_url",
            "SUPABASE_URL",
            "supabase_url",
            "SUPABASE_SERVICE_ROLE_KEY",
            "supabase_service_role_key",
            "DATABASE_URL",
        }

        for key, value in list(values.items()):
            if isinstance(value, str):
                # Strip whitespace and quotes
                cleaned = value.strip().strip('"').strip("'").strip()

                # For critical DB vars, also remove internal newlines/carriage returns
                if key in DB_CRITICAL_KEYS:
                    original = cleaned
                    cleaned = cleaned.replace("\n", "").replace("\r", "").replace("\t", "")
                    if cleaned != original:
                        logger.warning(
                            f"Sanitized {key}: removed internal whitespace/newlines "
                            f"(original length={len(original)}, cleaned={len(cleaned)})"
                        )

                values[key] = cleaned

        # Normalize ENVIRONMENT: accept 'production'→'prod', 'development'→'dev'
        env_key = None
        for k in ("ENVIRONMENT", "environment"):
            if k in values:
                env_key = k
                break
        if env_key:
            raw = str(values[env_key]).lower().strip()
            if raw == "production":
                logger.warning("ENVIRONMENT='production' is deprecated; use 'prod'. Normalizing.")
                values[env_key] = "prod"
            elif raw == "development":
                logger.warning("ENVIRONMENT='development' is deprecated; use 'dev'. Normalizing.")
                values[env_key] = "dev"
            elif raw not in ("dev", "staging", "prod"):
                raise ValueError(
                    f"ENVIRONMENT='{raw}' is invalid. Must be one of: dev, staging, prod"
                )

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
        """Get the database URL (canonical, no fallbacks)."""
        return self.SUPABASE_DB_URL

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
    # CREDENTIAL RESOLUTION (Simplified - no fallbacks)
    # =========================================================================

    def get_supabase_credentials(self, mode: str | None = None) -> tuple[str, str]:
        """
        Get Supabase URL and service role key.

        Args:
            mode: Ignored (kept for backward compatibility). Uses canonical vars.

        Returns:
            Tuple of (url, service_role_key)
        """
        return self.SUPABASE_URL, self.SUPABASE_SERVICE_ROLE_KEY

    def get_db_url(self, mode: str | None = None) -> str:
        """
        Get the database URL.

        Args:
            mode: Ignored (kept for backward compatibility). Uses canonical SUPABASE_DB_URL.

        Returns:
            PostgreSQL connection string
        """
        return self.SUPABASE_DB_URL


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
        "SUPABASE_DB_URL",
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


# =========================================================================
# STARTUP VALIDATION
# =========================================================================

# Required environment variables for API startup
REQUIRED_ENV_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
]

# Required for database operations (can be missing if only using REST)
REQUIRED_FOR_DB = [
    "SUPABASE_DB_URL",
]

# Recommended for production
RECOMMENDED_PROD_VARS = [
    "DRAGONFLY_API_KEY",
    "DRAGONFLY_CORS_ORIGINS",
]


def validate_required_env(fail_fast: bool = True) -> dict[str, Any]:
    """
    Validate required environment variables and log a startup report.

    Args:
        fail_fast: If True, raise an exception if required vars are missing

    Returns:
        Dict with validation results:
        {
            "valid": bool,
            "present": ["VAR1", "VAR2"],
            "missing": ["VAR3"],
            "warnings": ["message1", "message2"],
        }

    Raises:
        RuntimeError: If fail_fast=True and required vars are missing
    """
    result: dict[str, Any] = {
        "valid": True,
        "present": [],
        "missing": [],
        "warnings": [],
    }

    # Check required vars
    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if value and value.strip():
            result["present"].append(var)
        else:
            result["missing"].append(var)

    # Check DB vars (warn but don't fail)
    for var in REQUIRED_FOR_DB:
        value = os.environ.get(var)
        if not value or not value.strip():
            result["warnings"].append(f"{var} not set - database operations will fail")

    # Check production recommendations
    env = os.environ.get("ENVIRONMENT", "dev").lower()
    if env == "prod":
        for var in RECOMMENDED_PROD_VARS:
            value = os.environ.get(var)
            if not value or not value.strip():
                result["warnings"].append(f"{var} not set (recommended for production)")

    # Set overall validity
    if result["missing"]:
        result["valid"] = False

    # Log the report
    logger.info("=" * 60)
    logger.info("DRAGONFLY STARTUP CONFIGURATION REPORT")
    logger.info("=" * 60)
    logger.info(f"Environment: {env.upper()}")
    logger.info(f"Supabase Mode: {os.environ.get('SUPABASE_MODE', 'dev')}")

    if result["present"]:
        logger.info(f"✓ Present: {', '.join(result['present'])}")

    if result["missing"]:
        logger.error(f"✗ MISSING: {', '.join(result['missing'])}")

    for warning in result["warnings"]:
        logger.warning(f"⚠ {warning}")

    # Check for deprecated keys
    deprecated = get_deprecated_keys_used()
    if deprecated:
        logger.warning(f"⚠ Deprecated env vars in use: {', '.join(deprecated)}")

    logger.info("=" * 60)

    # Fail fast if configured
    if fail_fast and not result["valid"]:
        missing_str = ", ".join(result["missing"])
        raise RuntimeError(
            f"Missing required environment variables: {missing_str}. "
            f"Set these in your environment or .env file."
        )

    return result


def log_startup_diagnostics(service_name: str) -> None:
    """
    Log safe startup diagnostics for API and worker services.

    This function is intended to be called at service startup to provide
    visibility into configuration state without exposing secrets.

    Args:
        service_name: Human-readable name of the service (e.g., 'API', 'IngestProcessor')
    """
    try:
        cfg = get_settings()
    except Exception as e:
        logger.error(f"[{service_name}] Failed to load settings: {e}")
        return

    # Collect safe diagnostics
    db_url_configured = bool(cfg.SUPABASE_DB_URL)
    service_role_key_valid = (
        bool(cfg.SUPABASE_SERVICE_ROLE_KEY) and len(cfg.SUPABASE_SERVICE_ROLE_KEY) >= 100
    )

    # Try to get git SHA (optional)
    git_sha = os.environ.get("GIT_SHA", os.environ.get("RENDER_GIT_COMMIT", "unknown"))[:8]

    deprecated = get_deprecated_keys_used()

    # Log the banner
    logger.info("=" * 60)
    logger.info(f"SERVICE STARTUP: {service_name}")
    logger.info("=" * 60)
    logger.info(f"  Environment     : {cfg.ENVIRONMENT}")
    logger.info(f"  Supabase Mode   : {cfg.supabase_mode}")
    logger.info(f"  DB URL Set      : {'✓' if db_url_configured else '✗'}")
    logger.info(f"  Service Key OK  : {'✓' if service_role_key_valid else '✗'}")
    logger.info(f"  Git SHA         : {git_sha}")
    if deprecated:
        logger.warning(f"  Deprecated Keys : {', '.join(deprecated)}")
    logger.info("=" * 60)
