"""
NY Judgments Pilot Worker - Configuration

Strict configuration loader for the worker.
Uses ONLY DATABASE_URL and ENV - no fallbacks to API service variables.

Environment Variables (REQUIRED):
    DATABASE_URL    PostgreSQL connection string (direct, not pooled)
    SOURCE_SYSTEM   Source identifier (e.g., "ny_ecourts")
    PILOT_COUNTY    County filter (e.g., "kings")
    PILOT_COURT     Court filter (e.g., "civil")
    PILOT_CASE_TYPE Case type filter (e.g., "money_judgment")

Environment Variables (OPTIONAL):
    ENV                   Environment: dev, staging, prod (default: "dev")
    PILOT_RANGE_MONTHS    Initial backfill range in months (default: 6)
    DELTA_LOOKBACK_DAYS   Overlap days for delta runs (default: 3)
    LOG_LEVEL             Logging level (default: "INFO")

IMPORTANT:
    This worker does NOT fall back to SUPABASE_DB_URL or ENVIRONMENT.
    Railway/deployment must explicitly map DATABASE_URL and ENV.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""

    pass


# Worker metadata
WORKER_NAME = "ny_judgments_pilot"
WORKER_VERSION = "1.0.0"


@dataclass(frozen=True)
class WorkerConfig:
    """
    Immutable configuration for the NY Judgments Pilot Worker.

    All values are validated at construction time.
    """

    # Core settings (REQUIRED)
    database_url: str
    source_system: str
    pilot_county: str
    pilot_court: str
    pilot_case_type: str

    # Environment (OPTIONAL with default)
    env: Literal["dev", "staging", "prod"] = "dev"

    # Backfill/delta settings (OPTIONAL with defaults)
    pilot_range_months: int = 6
    delta_lookback_days: int = 3

    # Logging (OPTIONAL with default)
    log_level: str = "INFO"

    # Worker metadata (computed)
    worker_name: str = WORKER_NAME
    worker_version: str = WORKER_VERSION


def load_config() -> WorkerConfig:
    """
    Load and validate worker configuration from environment variables.

    STRICT POLICY:
        - Uses DATABASE_URL only (not SUPABASE_DB_URL)
        - Uses ENV only (not ENVIRONMENT)
        - No fallbacks to API service variables

    Returns:
        WorkerConfig instance with validated settings.

    Raises:
        ConfigError: If required variables are missing or invalid.
    """
    errors: list[str] = []

    # -------------------------------------------------------------------------
    # Required: DATABASE_URL (strict - no fallback)
    # -------------------------------------------------------------------------
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        errors.append(
            "DATABASE_URL is required. "
            "Do not use SUPABASE_DB_URL - map explicitly in deployment."
        )
    elif not database_url.startswith(("postgres://", "postgresql://")):
        errors.append(
            f"DATABASE_URL must start with postgres:// or postgresql://, "
            f"got: {database_url[:20]}..."
        )

    # -------------------------------------------------------------------------
    # Required: SOURCE_SYSTEM
    # -------------------------------------------------------------------------
    source_system = os.environ.get("SOURCE_SYSTEM", "").strip().lower()
    if not source_system:
        errors.append("SOURCE_SYSTEM is required (e.g., 'ny_ecourts')")

    # -------------------------------------------------------------------------
    # Required: PILOT_COUNTY
    # -------------------------------------------------------------------------
    pilot_county = os.environ.get("PILOT_COUNTY", "").strip().lower()
    if not pilot_county:
        errors.append("PILOT_COUNTY is required (e.g., 'kings', 'queens')")

    # -------------------------------------------------------------------------
    # Required: PILOT_COURT
    # -------------------------------------------------------------------------
    pilot_court = os.environ.get("PILOT_COURT", "").strip().lower()
    if not pilot_court:
        errors.append("PILOT_COURT is required (e.g., 'civil', 'small_claims')")

    # -------------------------------------------------------------------------
    # Required: PILOT_CASE_TYPE
    # -------------------------------------------------------------------------
    pilot_case_type = os.environ.get("PILOT_CASE_TYPE", "").strip().lower()
    if not pilot_case_type:
        errors.append("PILOT_CASE_TYPE is required (e.g., 'money_judgment')")

    # -------------------------------------------------------------------------
    # Optional: ENV (strict - no fallback to ENVIRONMENT)
    # -------------------------------------------------------------------------
    env_raw = os.environ.get("ENV", "dev").strip().lower()
    if env_raw not in ("dev", "staging", "prod"):
        errors.append(
            f"ENV must be 'dev', 'staging', or 'prod', got: '{env_raw}'. "
            "Do not use ENVIRONMENT - map explicitly in deployment."
        )
        env: Literal["dev", "staging", "prod"] = "dev"
    else:
        env = env_raw  # type: ignore[assignment]

    # -------------------------------------------------------------------------
    # Optional: PILOT_RANGE_MONTHS
    # -------------------------------------------------------------------------
    range_months_raw = os.environ.get("PILOT_RANGE_MONTHS", "6").strip()
    try:
        pilot_range_months = int(range_months_raw)
        if pilot_range_months < 1 or pilot_range_months > 24:
            errors.append(f"PILOT_RANGE_MONTHS must be 1-24, got: {pilot_range_months}")
    except ValueError:
        errors.append(f"PILOT_RANGE_MONTHS must be an integer, got: '{range_months_raw}'")
        pilot_range_months = 6

    # -------------------------------------------------------------------------
    # Optional: DELTA_LOOKBACK_DAYS
    # -------------------------------------------------------------------------
    lookback_raw = os.environ.get("DELTA_LOOKBACK_DAYS", "3").strip()
    try:
        delta_lookback_days = int(lookback_raw)
        if delta_lookback_days < 1 or delta_lookback_days > 30:
            errors.append(f"DELTA_LOOKBACK_DAYS must be 1-30, got: {delta_lookback_days}")
    except ValueError:
        errors.append(f"DELTA_LOOKBACK_DAYS must be an integer, got: '{lookback_raw}'")
        delta_lookback_days = 3

    # -------------------------------------------------------------------------
    # Optional: LOG_LEVEL
    # -------------------------------------------------------------------------
    log_level = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    if log_level not in valid_levels:
        errors.append(f"LOG_LEVEL must be one of {valid_levels}, got: '{log_level}'")
        log_level = "INFO"

    # -------------------------------------------------------------------------
    # Fail fast if any errors
    # -------------------------------------------------------------------------
    if errors:
        error_msg = "Configuration validation failed:\n  - " + "\n  - ".join(errors)
        raise ConfigError(error_msg)

    # -------------------------------------------------------------------------
    # Build immutable config
    # -------------------------------------------------------------------------
    return WorkerConfig(
        database_url=database_url,
        source_system=source_system,
        pilot_county=pilot_county,
        pilot_court=pilot_court,
        pilot_case_type=pilot_case_type,
        env=env,
        pilot_range_months=pilot_range_months,
        delta_lookback_days=delta_lookback_days,
        log_level=log_level,
    )


def validate_config(config: WorkerConfig) -> None:
    """
    Additional runtime validation (call after load_config if needed).

    Currently a no-op, but can be extended for database connectivity checks.
    """
    pass
