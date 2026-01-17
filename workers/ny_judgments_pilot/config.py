"""
NY Judgments Pilot Worker - Configuration

Strict configuration using Pydantic with DSN Guard enforcement.
Uses ONLY DATABASE_URL and ENV - no API-specific variables.

ZERO DRIFT POLICY:
    - PROD: DSN must contain iaketsyhmqbwaabgykux AND port 6543
    - DEV: DSN must contain ejiddanxtqcleyswqvkc OR localhost

The DSN Guard runs IMMEDIATELY upon loading config.
Any mismatch triggers sys.exit(2) before ANY database connection.

IMPORTANT:
    This worker does NOT use SUPABASE_DB_URL or ENVIRONMENT.
    Railway must map: DATABASE_URL=${{SUPABASE_DB_URL}}, ENV=${{ENVIRONMENT}}
"""

from __future__ import annotations

import sys
from datetime import date

from loguru import logger
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings

# =============================================================================
# CANONICAL PROJECT REFERENCES (Must match dsn_guard.py)
# =============================================================================
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"
PROD_REQUIRED_PORT = 6543


class WorkerConfig(BaseSettings):
    """
    Immutable configuration for the NY Judgments Pilot Worker.

    Loaded from environment variables. Pydantic validates on construction.
    """

    # Core settings (REQUIRED)
    database_url: str = Field(
        ...,
        description="PostgreSQL connection string (direct, not pooled)",
    )

    # Environment (OPTIONAL with default)
    env: str = Field(
        default="dev",
        description="Environment: dev, staging, prod",
    )

    # Target county (optional - defaults to all)
    county: str | None = Field(
        default=None,
        description="Target county (e.g., 'kings', 'queens'). None = all counties.",
    )

    # Worker metadata
    worker_name: str = Field(
        default="ny_judgments_pilot",
        description="Worker identifier for logging and tracking",
    )
    worker_version: str = Field(
        default="1.0.0",
        description="Semantic version of the worker",
    )

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: str) -> str:
        """Ensure env is one of the allowed values."""
        allowed = ("dev", "staging", "prod")
        v_lower = v.lower().strip()
        if v_lower not in allowed:
            raise ValueError(f"env must be one of {allowed}, got: {v}")
        return v_lower

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        """Ensure DATABASE_URL looks like a Postgres connection string."""
        v = v.strip()
        if not v:
            raise ValueError("DATABASE_URL is required")
        if not v.startswith(("postgres://", "postgresql://")):
            raise ValueError("DATABASE_URL must start with postgres:// or postgresql://")
        return v

    def generate_source_batch_id(self, run_date: date | None = None) -> str:
        """
        Generate idempotent batch ID for the run.

        Format: ny_judgments_{YYYY-MM-DD}
        """
        if run_date is None:
            run_date = date.today()
        return f"ny_judgments_{run_date.isoformat()}"

    class Config:
        # Strict: do not allow extra env vars to be read
        extra = "ignore"
        # Case-insensitive env var matching
        case_sensitive = False


def load_config() -> WorkerConfig:
    """
    Load and validate worker configuration from environment variables.

    ZERO DRIFT ENFORCEMENT:
        After Pydantic validation, the DSN Guard validates that the
        DATABASE_URL matches the ENV (prod/dev). On mismatch, sys.exit(2).

    Returns:
        WorkerConfig instance with validated settings.

    Raises:
        pydantic.ValidationError: If required variables are missing or invalid.
        SystemExit: If DSN doesn't match environment (exit code 2).
    """
    config = WorkerConfig()

    # ==========================================================================
    # DSN GUARD: Zero Drift Policy Enforcement
    # Run IMMEDIATELY after config load, BEFORE any database connection
    # ==========================================================================
    from backend.core.dsn_guard import guard_or_exit

    logger.info(f"DSN Guard: Validating DATABASE_URL for environment '{config.env}'")
    guard_or_exit(config.database_url, config.env, exit_code=2)

    logger.info(
        f"Config loaded: env={config.env}, worker={config.worker_name}, "
        f"version={config.worker_version}"
    )

    return config
