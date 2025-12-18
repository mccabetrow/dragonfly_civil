"""
Dragonfly Engine - Runtime Startup Validator

This module provides fail-fast startup validation for all services (API + workers).
It checks critical environment variables BEFORE any application code runs and
exits with a clear, single-line error if configuration is invalid.

Features:
    - Single-line error output: "{service}: {error}" format for log aggregators
    - No secret exposure in error messages
    - --print-effective-config mode to show which env keys are used
    - Exit code 78 (EX_CONFIG) for configuration errors

Usage:
    from backend.startup_validator import validate_startup_config

    if __name__ == "__main__":
        validate_startup_config("enforcement_worker")  # First line!
        # ... rest of application startup

CLI Usage:
    python -m backend.startup_validator --service api
    python -m backend.startup_validator --service enforcement_worker --print-effective-config
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# Exit code for configuration errors (BSD sysexits.h convention)
EX_CONFIG = 78

# Minimum length for service role JWT (they're typically 200+ chars)
MIN_SERVICE_ROLE_KEY_LENGTH = 100


@dataclass
class ValidationError:
    """A single validation error."""

    key_name: str
    error_type: str  # MISSING, INVALID, SUSPICIOUS
    message: str

    def to_single_line(self, service_name: str) -> str:
        """Format as single-line error for log aggregators."""
        return f"{service_name}: {self.error_type} - {self.key_name} - {self.message}"


@dataclass
class StartupValidationResult:
    """Result of startup validation checks."""

    service_name: str
    errors: List[ValidationError] = field(default_factory=list)
    effective_config: dict[str, str] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def print_errors(self) -> None:
        """Print all errors as single-line messages (no secrets)."""
        for error in self.errors:
            print(error.to_single_line(self.service_name), file=sys.stderr)

    def print_effective_config(self) -> None:
        """Print which env keys are configured (names only, not values)."""
        print(f"# Effective configuration for: {self.service_name}")
        print("-" * 50)
        for key, status in sorted(self.effective_config.items()):
            print(f"  {key}: {status}")
        print("-" * 50)


# ==============================================================================
# VALIDATION RULES
# ==============================================================================


def _get_env(key: str) -> str | None:
    """Get env var, stripping whitespace."""
    value = os.environ.get(key)
    if value:
        return value.strip()
    return None


def _validate_supabase_service_role_key(result: StartupValidationResult) -> None:
    """
    Validate SUPABASE_SERVICE_ROLE_KEY is present and looks valid.

    Checks:
    - Not missing
    - Length >= 100 chars (JWTs are typically 200+)
    - Starts with 'ey' (JWT header)
    """
    key = _get_env("SUPABASE_SERVICE_ROLE_KEY")

    # Track in effective config
    if key:
        result.effective_config["SUPABASE_SERVICE_ROLE_KEY"] = f"SET ({len(key)} chars)"
    else:
        result.effective_config["SUPABASE_SERVICE_ROLE_KEY"] = "NOT SET"

    if not key:
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_SERVICE_ROLE_KEY",
                error_type="MISSING",
                message="Required service role JWT not found in environment",
            )
        )
        return

    if len(key) < MIN_SERVICE_ROLE_KEY_LENGTH:
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_SERVICE_ROLE_KEY",
                error_type="SUSPICIOUS",
                message=f"Key too short ({len(key)} chars, expected {MIN_SERVICE_ROLE_KEY_LENGTH}+)",
            )
        )
        return

    if not key.startswith("ey"):
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_SERVICE_ROLE_KEY",
                error_type="INVALID",
                message="Key does not start with 'ey' (not a valid JWT)",
            )
        )


def _validate_supabase_url(result: StartupValidationResult) -> None:
    """Validate SUPABASE_URL is present and is HTTPS."""
    url = _get_env("SUPABASE_URL")

    if url:
        result.effective_config["SUPABASE_URL"] = f"SET ({url[:30]}...)"
    else:
        result.effective_config["SUPABASE_URL"] = "NOT SET"

    if not url:
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_URL",
                error_type="MISSING",
                message="Required Supabase project URL not found",
            )
        )
        return

    if not url.startswith("https://"):
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_URL",
                error_type="INVALID",
                message="URL must start with https://",
            )
        )


def _validate_supabase_db_url(result: StartupValidationResult) -> None:
    """Validate SUPABASE_DB_URL if present."""
    db_url = _get_env("SUPABASE_DB_URL")
    db_url_prod = _get_env("SUPABASE_DB_URL_PROD")
    db_url_dev = _get_env("SUPABASE_DB_URL_DEV")

    # Track effective DB URL
    effective = db_url or db_url_prod or db_url_dev
    if effective:
        # Redact password from display
        if "@" in effective:
            # Format: postgresql://user:pass@host:port/db
            prefix = effective.split("@")[0]
            suffix = effective.split("@")[1] if "@" in effective else ""
            if ":" in prefix:
                # Has password
                user_part = prefix.split(":")[0]
                result.effective_config["SUPABASE_DB_URL"] = (
                    f"SET ({user_part}:***@{suffix[:20]}...)"
                )
            else:
                result.effective_config["SUPABASE_DB_URL"] = f"SET ({effective[:30]}...)"
        else:
            result.effective_config["SUPABASE_DB_URL"] = f"SET ({effective[:30]}...)"
    else:
        result.effective_config["SUPABASE_DB_URL"] = "NOT SET (optional for REST-only)"

    # DB URL is optional - some services only use REST API
    if effective and not effective.startswith(("postgresql://", "postgres://")):
        result.errors.append(
            ValidationError(
                key_name="SUPABASE_DB_URL",
                error_type="INVALID",
                message="URL must start with postgresql:// or postgres://",
            )
        )


def _track_optional_config(result: StartupValidationResult) -> None:
    """Track optional configuration keys for --print-effective-config."""
    optional_keys = [
        "ENVIRONMENT",
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
            else:
                result.effective_config[key] = f"SET ({value})"
        else:
            result.effective_config[key] = "NOT SET"


# ==============================================================================
# MAIN VALIDATION ENTRY POINT
# ==============================================================================


def run_startup_validation(service_name: str) -> StartupValidationResult:
    """
    Run all startup validation checks.

    Args:
        service_name: Name of the service (for error messages).

    Returns:
        StartupValidationResult with errors and effective config.
    """
    result = StartupValidationResult(service_name=service_name)

    # Critical checks (will cause exit)
    _validate_supabase_service_role_key(result)
    _validate_supabase_url(result)
    _validate_supabase_db_url(result)

    # Track optional config (for --print-effective-config)
    _track_optional_config(result)

    return result


def validate_startup_config(
    service_name: str,
    *,
    exit_on_error: bool = True,
    print_effective_config: bool = False,
) -> StartupValidationResult:
    """
    Validate startup configuration for a service.

    Call this as the FIRST line in your service's main() or if __name__ == "__main__".
    If validation fails, prints a single-line error and exits with code 78.

    Args:
        service_name: Human-readable service name (e.g., "enforcement_worker", "api")
        exit_on_error: If True (default), exit with code 78 on errors
        print_effective_config: If True, print config and exit (for diagnostics)

    Returns:
        StartupValidationResult (only if exit_on_error=False or validation passes)

    Example:
        if __name__ == "__main__":
            validate_startup_config("enforcement_worker")
            # ... rest of worker startup
    """
    result = run_startup_validation(service_name)

    if print_effective_config:
        result.print_effective_config()
        if not exit_on_error:
            return result
        sys.exit(0)

    if not result.is_valid:
        result.print_errors()
        if exit_on_error:
            sys.exit(EX_CONFIG)

    return result


# ==============================================================================
# CLI ENTRY POINT
# ==============================================================================


def main() -> int:
    """CLI entry point for startup validation."""
    parser = argparse.ArgumentParser(
        description="Dragonfly runtime startup validator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Validate configuration for a service
    python -m backend.startup_validator --service api

    # Print effective config (which env vars are set)
    python -m backend.startup_validator --service enforcement_worker --print-effective-config

Exit Codes:
    0   - Validation passed (or --print-effective-config)
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
        "--quiet",
        action="store_true",
        help="Only output on error",
    )

    args = parser.parse_args()

    result = run_startup_validation(args.service)

    if args.print_effective_config:
        result.print_effective_config()
        return 0

    if not result.is_valid:
        result.print_errors()
        return EX_CONFIG

    if not args.quiet:
        print(f"{args.service}: startup validation passed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
