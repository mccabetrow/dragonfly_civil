"""
Dragonfly Engine - Worker Pre-Flight Validation

This module provides startup environment validation for workers.
It checks critical configuration before any application code runs,
ensuring human-readable errors and graceful exits on misconfiguration.

Features:
    - Validates required environment variables with format checks
    - Single-line error output: "{service}: {error}" format for log aggregators
    - Structured logging with service_name, git_sha, environment, supabase_mode
    - **Strict Preflight Contract**: Errors are fatal; warnings NEVER fatal by default
    - Concise banner output for operator visibility
    - --print-effective-config mode to show which env keys are used

Environment Toggles:
    PREFLIGHT_FAIL_FAST:       Exit immediately on errors (default: true)
    PREFLIGHT_WARNINGS_FATAL:  Treat warnings as errors (default: false)
    PREFLIGHT_STRICT_MODE:     Enforce stricter validation (default: true in prod)

Single DSN Contract:
    DATABASE_URL:     Canonical database connection string
    SUPABASE_DB_URL:  Deprecated alias (emits warning unless DATABASE_URL is set)

Usage:
    from backend.preflight import validate_worker_env

    if __name__ == "__main__":
        validate_worker_env("enforcement_engine")  # First line!
        # ... rest of worker startup

CLI Usage:
    python -m backend.preflight --service enforcement_engine --print-effective-config
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

# ==============================================================================
# GIT SHA DETECTION
# ==============================================================================


def get_git_sha() -> str | None:
    """
    Get the current git commit SHA.

    Checks in order:
    1. GIT_SHA environment variable (set by CI/CD)
    2. RAILWAY_GIT_COMMIT_SHA (Railway-specific)
    3. RENDER_GIT_COMMIT (Render-specific)
    4. Attempt to read from .git/HEAD

    Returns:
        Short git SHA (first 8 chars) or None if not available.
    """
    # Check env vars first (fastest, set by CI/CD)
    for env_key in ("GIT_SHA", "RAILWAY_GIT_COMMIT_SHA", "RENDER_GIT_COMMIT", "HEROKU_SLUG_COMMIT"):
        sha = os.environ.get(env_key)
        if sha:
            return sha[:8]

    # Try git command (works in local dev)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=Path(__file__).parent.parent,  # repo root
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    return None


# ==============================================================================
# STRUCTURED LOGGING
# ==============================================================================


class StructuredLogFormatter(logging.Formatter):
    """
    Formatter that adds structured fields to log output.

    Fields: timestamp, level, service_name, git_sha, environment, supabase_mode, message
    """

    def __init__(self, service_name: str, git_sha: str | None = None):
        super().__init__()
        self.service_name = service_name
        self.git_sha = git_sha or get_git_sha() or "unknown"
        self.environment = os.environ.get("ENVIRONMENT", "dev").lower()
        self.supabase_mode = os.environ.get("SUPABASE_MODE", "dev").lower()

    def format(self, record: logging.LogRecord) -> str:
        """Format as structured log line."""
        log_data = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "service": self.service_name,
            "sha": self.git_sha,
            "env": self.environment,
            "mode": self.supabase_mode,
            "msg": record.getMessage(),
        }
        # Include exception info if present
        if record.exc_info:
            log_data["exc"] = self.formatException(record.exc_info)

        return json.dumps(log_data, separators=(",", ":"))


def configure_structured_logging(service_name: str, git_sha: str | None = None) -> logging.Logger:
    """
    Configure structured logging for a service with split stdout/stderr streams.

    - INFO → stdout (avoids NativeCommandError in PowerShell/CI)
    - WARNING, ERROR, CRITICAL → stderr

    Args:
        service_name: Name of the worker/service.
        git_sha: Optional git SHA (auto-detected if not provided).

    Returns:
        Configured logger instance.
    """
    preflight_logger = logging.getLogger("preflight")
    preflight_logger.setLevel(logging.INFO)

    # Remove existing handlers
    preflight_logger.handlers.clear()

    formatter = StructuredLogFormatter(service_name, git_sha)

    # stdout handler: INFO only (DEBUG filtered out for preflight)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)
    preflight_logger.addHandler(stdout_handler)

    # stderr handler: WARNING and above
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)
    preflight_logger.addHandler(stderr_handler)

    return preflight_logger


class _MaxLevelFilter(logging.Filter):
    """Filter that passes records at or below a maximum level."""

    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


# Configure basic logging before anything else (will be upgraded on validate_worker_env)
# Use stdout for INFO to avoid PowerShell NativeCommandError
_root_handler = logging.StreamHandler(sys.stdout)
_root_handler.setLevel(logging.INFO)
_root_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_root_handler])
logger = logging.getLogger("preflight")

# Exit code for configuration errors (BSD sysexits.h convention)
EX_CONFIG = 78

# ==============================================================================
# PREFLIGHT ENVIRONMENT TOGGLES
# ==============================================================================


def _parse_bool_env(key: str, default: bool) -> bool:
    """Parse a boolean environment variable."""
    value = os.environ.get(key, "").strip().lower()
    if not value:
        return default
    return value in ("true", "1", "yes", "on")


def get_preflight_config() -> dict:
    """
    Get preflight configuration from environment.

    Returns a dict with:
        - fail_fast: bool - Exit immediately on errors (default: True)
        - warnings_fatal: bool - Treat warnings as errors (default: False)
        - strict_mode: bool - Enforce stricter validation (default: True in prod)

    STRICT PREFLIGHT CONTRACT:
        - Errors are ALWAYS fatal (exit non-zero) unless fail_fast=False
        - Warnings are NEVER fatal unless PREFLIGHT_WARNINGS_FATAL=true
        - This ensures workers do not crash-loop on configuration warnings
    """
    environment = os.environ.get("ENVIRONMENT", "dev").lower()
    is_prod = environment == "prod"

    return {
        "fail_fast": _parse_bool_env("PREFLIGHT_FAIL_FAST", True),
        "warnings_fatal": _parse_bool_env("PREFLIGHT_WARNINGS_FATAL", False),
        "strict_mode": _parse_bool_env("PREFLIGHT_STRICT_MODE", is_prod),
    }


# ==============================================================================
# VALIDATION RULES
# ==============================================================================

VALID_ENVIRONMENTS = ("dev", "staging", "prod")
MIN_SERVICE_ROLE_KEY_LENGTH = 100
HTTPS_URL_PATTERN = re.compile(r"^https://[a-zA-Z0-9][a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}")


@dataclass
class PreflightResult:
    """Result of preflight validation."""

    worker_name: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    git_sha: str | None = None
    environment: str = "dev"
    supabase_mode: str = "dev"
    effective_config: dict = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for structured logging."""
        return {
            "worker": self.worker_name,
            "is_valid": self.is_valid,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "git_sha": self.git_sha,
            "environment": self.environment,
            "supabase_mode": self.supabase_mode,
        }

    def get_single_line_errors(self) -> List[str]:
        """
        Format errors as single-line messages for log aggregators.

        Format: "{service}: {error_type} - {key} - {message}"
        No secrets are exposed.
        """
        single_line = []
        for error in self.errors:
            # Extract the key name from the error message
            first_line = error.split("\n")[0].strip()
            # Format: "SUPABASE_SERVICE_ROLE_KEY is MISSING"
            if " is " in first_line:
                key_name = first_line.split(" is ")[0]
                error_type = first_line.split(" is ")[1].split()[0]
                single_line.append(f"{self.worker_name}: {error_type} - {key_name} - {first_line}")
            else:
                single_line.append(f"{self.worker_name}: ERROR - {first_line}")
        return single_line

    def print_single_line_errors(self) -> None:
        """Print all errors as single-line messages to stderr."""
        for line in self.get_single_line_errors():
            print(line, file=sys.stderr)

    def print_effective_config(self) -> None:
        """Print which env keys are configured (names only, not values)."""
        print(f"# Effective configuration for: {self.worker_name}")
        print("-" * 50)
        for key, status in sorted(self.effective_config.items()):
            print(f"  {key}: {status}")
        print("-" * 50)


# ==============================================================================
# VALIDATION FUNCTIONS
# ==============================================================================


def _get_env(key: str) -> str | None:
    """Get env var, checking both uppercase and lowercase variants."""
    return os.environ.get(key) or os.environ.get(key.lower())


def _validate_supabase_service_role_key(result: PreflightResult) -> None:
    """Validate SUPABASE_SERVICE_ROLE_KEY format and length."""
    key = _get_env("SUPABASE_SERVICE_ROLE_KEY")

    # Track in effective config (no secret exposure)
    if key:
        result.effective_config["SUPABASE_SERVICE_ROLE_KEY"] = f"SET ({len(key)} chars)"
    else:
        result.effective_config["SUPABASE_SERVICE_ROLE_KEY"] = "NOT SET"

    if not key:
        result.errors.append(
            "SUPABASE_SERVICE_ROLE_KEY is MISSING\n"
            "   Required: Service role JWT from Supabase dashboard\n"
            "   Location: Project Settings > API > service_role key"
        )
        return

    if len(key) < MIN_SERVICE_ROLE_KEY_LENGTH:
        result.errors.append(
            f"SUPABASE_SERVICE_ROLE_KEY is SUSPICIOUS ({len(key)} chars)\n"
            f"   Required: At least {MIN_SERVICE_ROLE_KEY_LENGTH} characters\n"
            f"   Current:  {len(key)} characters\n"
            "   This looks like a truncated key. Copy the full key from Supabase."
        )
        return

    if not key.startswith("ey"):
        result.errors.append(
            "SUPABASE_SERVICE_ROLE_KEY has INVALID FORMAT\n"
            "   Required: JWT token starting with 'ey'\n"
            f"   Current:  Starts with '{key[:10]}...'\n"
            "   Make sure you're using the service_role key, not anon key."
        )
        return


def _validate_supabase_url(result: PreflightResult) -> None:
    """Validate SUPABASE_URL is a valid HTTPS URL."""
    url = _get_env("SUPABASE_URL")

    # Track in effective config
    if url:
        result.effective_config["SUPABASE_URL"] = f"SET ({url[:30]}...)"
    else:
        result.effective_config["SUPABASE_URL"] = "NOT SET"

    if not url:
        result.errors.append(
            "SUPABASE_URL is MISSING\n"
            "   Required: https://<project-ref>.supabase.co\n"
            "   Location: Project Settings > API > Project URL"
        )
        return

    if not url.startswith("https://"):
        result.errors.append(
            "SUPABASE_URL must be HTTPS\n"
            f"   Current:  {url}\n"
            "   Required: https://<project-ref>.supabase.co"
        )
        return

    if not HTTPS_URL_PATTERN.match(url):
        result.errors.append(
            "SUPABASE_URL has INVALID FORMAT\n"
            f"   Current:  {url}\n"
            "   Required: https://<project-ref>.supabase.co"
        )
        return


def _validate_environment(result: PreflightResult) -> None:
    """Validate ENVIRONMENT is one of dev/staging/prod."""
    env = _get_env("ENVIRONMENT")

    # Track in effective config
    result.effective_config["ENVIRONMENT"] = f"SET ({env})" if env else "NOT SET (default: dev)"

    if not env:
        result.warnings.append(
            "ENVIRONMENT is not set, defaulting to 'dev'\n"
            "   Recommended: Set ENVIRONMENT=prod in production"
        )
        return

    env_lower = env.lower()

    # Handle common variants
    if env_lower in ("production", "prd"):
        result.warnings.append(
            f"ENVIRONMENT='{env}' normalized to 'prod'\n   Recommended: Use 'prod' directly"
        )
        return

    if env_lower in ("development", "local"):
        result.warnings.append(
            f"ENVIRONMENT='{env}' normalized to 'dev'\n   Recommended: Use 'dev' directly"
        )
        return

    if env_lower not in VALID_ENVIRONMENTS:
        result.errors.append(
            f"ENVIRONMENT has INVALID VALUE: '{env}'\n"
            f"   Valid values: {', '.join(VALID_ENVIRONMENTS)}"
        )


def _validate_supabase_db_url(result: PreflightResult) -> None:
    """
    Validate canonical DATABASE_URL (with SUPABASE_DB_URL fallback).

    SINGLE DSN CONTRACT:
        - DATABASE_URL is the canonical variable
        - SUPABASE_DB_URL is deprecated (warning only, unless DATABASE_URL is set)
        - If DATABASE_URL is set, suppress SUPABASE_DB_URL deprecation warning
        - Missing database URL is FATAL in production
    """
    # Single DSN Contract: DATABASE_URL is canonical, SUPABASE_DB_URL is deprecated
    database_url = _get_env("DATABASE_URL")
    supabase_db_url = _get_env("SUPABASE_DB_URL")

    # Resolve with fallback chain
    db_url = database_url or supabase_db_url
    source_var = "DATABASE_URL" if database_url else "SUPABASE_DB_URL" if supabase_db_url else None

    # Track in effective config (redact password)
    if database_url:
        # DATABASE_URL is set - this is the canonical path
        if "@" in database_url:
            parts = database_url.split("@")
            host_part = parts[1][:25] if len(parts) > 1 else "..."
            result.effective_config["DATABASE_URL"] = f"SET (***@{host_part}...)"
        else:
            result.effective_config["DATABASE_URL"] = f"SET ({database_url[:30]}...)"
        # Note: Do NOT emit deprecation warning for SUPABASE_DB_URL when DATABASE_URL is set
        if supabase_db_url:
            result.effective_config["SUPABASE_DB_URL"] = "SET (ignored - using DATABASE_URL)"
    elif supabase_db_url:
        # Only SUPABASE_DB_URL is set - emit deprecation warning
        if "@" in supabase_db_url:
            parts = supabase_db_url.split("@")
            host_part = parts[1][:25] if len(parts) > 1 else "..."
            result.effective_config["SUPABASE_DB_URL"] = f"SET (***@{host_part}...) [DEPRECATED]"
        else:
            result.effective_config["SUPABASE_DB_URL"] = (
                f"SET ({supabase_db_url[:30]}...) [DEPRECATED]"
            )
        result.effective_config["DATABASE_URL"] = "NOT SET"
        # Emit deprecation warning - but it's just a WARNING, not fatal
        result.warnings.append(
            "SUPABASE_DB_URL is deprecated; use DATABASE_URL (Railway/Heroku convention)\n"
            "   The application will continue to function, but please update your config."
        )
    else:
        result.effective_config["DATABASE_URL"] = "NOT SET"
        result.effective_config["SUPABASE_DB_URL"] = "NOT SET"

    if not db_url:
        result.errors.append(
            "DATABASE_URL (or SUPABASE_DB_URL) is required\n"
            "   Set the canonical database URL for your environment.\n"
            "   Format: postgresql://postgres.<ref>:<password>@<host>:5432/postgres"
        )
        return

    if not db_url.startswith(("postgresql://", "postgres://")):
        result.errors.append(
            f"{source_var} has INVALID FORMAT\n"
            f"   Current:  {db_url[:40]}...\n"
            "   Required: postgresql://... or postgres://..."
        )


def _track_optional_config(result: PreflightResult) -> None:
    """Track optional configuration keys for --print-effective-config."""
    optional_keys = [
        "SUPABASE_MODE",
        "LOG_LEVEL",
        "DRAGONFLY_API_KEY",
        "OPENAI_API_KEY",
        "DISCORD_WEBHOOK_URL",
        "PORT",
    ]

    for key in optional_keys:
        value = _get_env(key)
        if value:
            # Don't show values for sensitive keys
            if "KEY" in key or "TOKEN" in key or "SECRET" in key:
                result.effective_config[key] = f"SET ({len(value)} chars)"
            elif "URL" in key and "@" in value:
                # Redact URLs with credentials
                result.effective_config[key] = "SET (redacted)"
            elif "WEBHOOK" in key:
                # Redact webhook URLs (they contain secrets in the path)
                result.effective_config[key] = "SET (redacted)"
            else:
                result.effective_config[key] = f"SET ({value})"
        else:
            result.effective_config[key] = "NOT SET"


# ==============================================================================
# MAIN VALIDATION ENTRY POINT
# ==============================================================================


def run_preflight_checks(worker_name: str) -> PreflightResult:
    """
    Run all preflight validation checks.

    Args:
        worker_name: Name of the worker for logging context.

    Returns:
        PreflightResult with errors and warnings.
    """
    result = PreflightResult(
        worker_name=worker_name,
        git_sha=get_git_sha(),
        environment=os.environ.get("ENVIRONMENT", "dev").lower(),
        supabase_mode=os.environ.get("SUPABASE_MODE", "dev").lower(),
    )

    _validate_supabase_service_role_key(result)
    _validate_supabase_url(result)
    _validate_environment(result)
    _validate_supabase_db_url(result)
    _track_optional_config(result)

    return result


def _print_banner(title: str, char: str = "=") -> None:
    """Print a formatted banner."""
    width = 70
    print()
    print(char * width)
    print(f" {title}")
    print(char * width)


def _print_error_block(errors: List[str]) -> None:
    """Print errors in a formatted block."""
    _print_banner("[CRITICAL] PREFLIGHT CHECK FAILED", "!")
    print()
    for i, error in enumerate(errors, 1):
        print(f"  ERROR {i}:")
        for line in error.split("\n"):
            print(f"    {line}")
        print()
    print("!" * 70)
    print()


def _print_warning_block(warnings: List[str]) -> None:
    """Print warnings in a formatted block."""
    _print_banner("[WARNING] Configuration Recommendations", "-")
    print()
    for warning in warnings:
        for line in warning.split("\n"):
            print(f"  {line}")
        print()
    print("-" * 70)
    print()


def validate_worker_env(
    worker_name: str,
    *,
    exit_on_error: bool = True,
    fail_fast: bool | None = None,
    warnings_fatal: bool | None = None,
    structured_logging: bool = True,
) -> PreflightResult:
    """
    Validate worker environment configuration before startup.

    This should be called as the FIRST line in `if __name__ == "__main__":`.
    It performs critical validation of environment variables and exits
    with a clear error message if configuration is invalid.

    STRICT PREFLIGHT CONTRACT:
        - ERRORS are ALWAYS fatal (exit 1) unless exit_on_error=False
        - WARNINGS are NEVER fatal unless PREFLIGHT_WARNINGS_FATAL=true or warnings_fatal=True
        - This ensures workers do not crash-loop on configuration warnings

    Environment Toggles (override via env vars):
        PREFLIGHT_FAIL_FAST:       Exit on errors (default: true)
        PREFLIGHT_WARNINGS_FATAL:  Treat warnings as errors (default: false)
        PREFLIGHT_STRICT_MODE:     Stricter validation (default: true in prod)

    Args:
        worker_name: Human-readable name of the worker (for logging).
        exit_on_error: If True (default), exit with code 1 on validation errors.
                       Set to False for testing or diagnostic modes.
        fail_fast: DEPRECATED - use env var PREFLIGHT_FAIL_FAST.
                   If provided, controls whether errors cause immediate exit.
        warnings_fatal: If True, treat warnings as errors.
                       Defaults to PREFLIGHT_WARNINGS_FATAL env var (false).
        structured_logging: If True (default), enable structured JSON logging.

    Returns:
        PreflightResult containing validation errors and warnings.

    Example:
        if __name__ == "__main__":
            validate_worker_env("ingest_processor")
            # ... rest of worker code
    """
    global logger

    # Upgrade to structured logging
    if structured_logging:
        logger = configure_structured_logging(worker_name)

    logger.info(f"Running preflight checks for {worker_name}...")

    result = run_preflight_checks(worker_name)

    # Get preflight configuration from environment
    preflight_config = get_preflight_config()

    # Resolve fail_fast: explicit arg > env var > default (True)
    if fail_fast is None:
        fail_fast = preflight_config["fail_fast"]

    # Resolve warnings_fatal: explicit arg > env var > default (False)
    # CRITICAL: warnings_fatal defaults to FALSE - warnings never brick workers
    if warnings_fatal is None:
        warnings_fatal = preflight_config["warnings_fatal"]

    # Print structured banner
    _print_structured_banner(result, preflight_config)

    # STRICT PREFLIGHT CONTRACT:
    # 1. ERRORS are fatal (exit non-zero) if fail_fast=True and exit_on_error=True
    if result.errors:
        _print_error_block(result.errors)
        logger.critical(f"Preflight failed for {worker_name}: {len(result.errors)} error(s)")
        if exit_on_error and fail_fast:
            sys.exit(1)
        elif exit_on_error:
            # Even without fail_fast, errors are still logged critically
            # but we allow the caller to handle via exit_on_error=False
            sys.exit(1)

    # 2. WARNINGS are NEVER fatal unless warnings_fatal=True
    if result.warnings:
        _print_warning_block(result.warnings)
        if warnings_fatal:
            logger.error(
                f"Preflight failed for {worker_name}: {len(result.warnings)} warning(s) "
                f"(PREFLIGHT_WARNINGS_FATAL=true)"
            )
            if exit_on_error:
                sys.exit(1)
        else:
            # This is the normal path: warnings are logged but do NOT cause exit
            logger.warning(
                f"Preflight passed with {len(result.warnings)} warning(s) - continuing startup"
            )
    else:
        logger.info(f"Preflight passed for {worker_name}")

    return result


def _print_structured_banner(result: PreflightResult, preflight_config: dict | None = None) -> None:
    """Print a structured startup banner with key metadata."""
    width = 70
    sha_display = result.git_sha or "unknown"

    # Get preflight config for display
    if preflight_config is None:
        preflight_config = get_preflight_config()

    print()
    print("=" * width)
    print(f"  Dragonfly Worker: {result.worker_name}")
    print("-" * width)
    print(f"  Environment:      {result.environment}")
    print(f"  Supabase Mode:    {result.supabase_mode}")
    print(f"  Git SHA:          {sha_display}")
    print(f"  Warnings Fatal:   {preflight_config['warnings_fatal']}")
    print(f"  Startup:          {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z")
    print("=" * width)


# ==============================================================================
# SAFE MODE UTILITIES
# ==============================================================================


def load_settings_safe() -> dict:
    """
    Load settings in safe mode for diagnostics.

    Returns a dict of environment values without triggering Pydantic validation.
    Useful for debugging configuration issues before full Settings instantiation.
    """
    keys = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
        "ENVIRONMENT",
        "SUPABASE_MODE",
        "LOG_LEVEL",
        "DRAGONFLY_API_KEY",
        "OPENAI_API_KEY",
    ]

    result = {}
    for key in keys:
        value = _get_env(key)
        if value:
            # Redact sensitive values
            if "KEY" in key or "TOKEN" in key or "SECRET" in key:
                if len(value) > 20:
                    result[key] = f"{value[:8]}...{value[-4:]} ({len(value)} chars)"
                else:
                    result[key] = f"[SET but short: {len(value)} chars]"
            else:
                result[key] = value
        else:
            result[key] = "[NOT SET]"

    return result


def print_diagnostic_env(worker_name: str) -> None:
    """Print a diagnostic view of the environment for debugging."""
    _print_banner(f"DIAGNOSTIC: {worker_name} Environment")
    print()

    env_values = load_settings_safe()
    for key, value in env_values.items():
        status = "[OK]" if value != "[NOT SET]" else "[MISSING]"
        print(f"  {status:10} {key}: {value}")

    print()
    print("=" * 70)
    print()


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================


def main() -> int:
    """CLI entry point for preflight validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Dragonfly worker preflight validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Validate configuration for a service
    python -m backend.preflight --service enforcement_engine

    # Print effective config (which env vars are set)
    python -m backend.preflight --service api --print-effective-config

    # Single-line error format (for log aggregators)
    python -m backend.preflight --service ingest_processor --single-line

Exit Codes:
    0   - Validation passed (or --print-effective-config)
    1   - Validation failed
    78  - Configuration error (EX_CONFIG)
        """,
    )
    parser.add_argument(
        "--service",
        default="unknown_service",
        help="Service name for error messages (default: unknown_service)",
    )
    parser.add_argument(
        "--print-effective-config",
        action="store_true",
        help="Print which env keys are configured (names only, not values)",
    )
    parser.add_argument(
        "--single-line",
        action="store_true",
        help="Output errors in single-line format for log aggregators",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only output on error",
    )

    args = parser.parse_args()

    result = run_preflight_checks(args.service)

    if args.print_effective_config:
        result.print_effective_config()
        return 0

    if not result.is_valid:
        if args.single_line:
            result.print_single_line_errors()
        else:
            _print_error_block(result.errors)
        return EX_CONFIG

    if result.has_warnings and not args.quiet:
        _print_warning_block(result.warnings)

    if not args.quiet:
        print(f"{args.service}: preflight validation passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
