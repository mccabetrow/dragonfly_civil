"""
Dragonfly Civil - Configuration Guard

CRITICAL STARTUP VALIDATION
============================

This module MUST be imported at the very top of all entrypoints:
- backend/api/main.py
- backend/workers/base.py
- Any standalone worker scripts

It enforces strict separation between Runtime and Migration environments,
preventing accidental exposure of direct database credentials in production.

SECURITY MODEL:
- Runtime services use SUPABASE_DB_URL (port 6543, connection pooler)
- Migrations use SUPABASE_MIGRATE_DB_URL (port 5432, direct connection)
- These MUST NEVER be mixed in production

Usage:
    # At the very top of your entrypoint (before other imports)
    from backend.core.config_guard import validate_production_config
    validate_production_config()

    # Now safe to import the rest of your application
    from backend.main import app

Author: Principal DevOps Engineer
Date: 2026-01-07
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

# Use basic logging since this runs before structured logging is configured
logger = logging.getLogger("dragonfly.config_guard")

# ANSI colors for terminal output (falls back gracefully)
RED = "\033[91m"
YELLOW = "\033[93m"
GREEN = "\033[92m"
RESET = "\033[0m"
BOLD = "\033[1m"


@dataclass
class ConfigValidationResult:
    """Result of configuration validation."""

    passed: bool
    fatal_errors: list[str]
    warnings: list[str]
    missing_vars: list[str]


class ConfigurationSecurityViolation(SystemExit):
    """Raised when a critical security misconfiguration is detected."""

    def __init__(self, message: str):
        super().__init__(1)
        self.message = message


def _get_env() -> str:
    """Get the current environment name."""
    return os.environ.get(
        "DRAGONFLY_ENV",
        os.environ.get("ENVIRONMENT", os.environ.get("RAILWAY_ENVIRONMENT", "dev")),
    ).lower()


def _is_production() -> bool:
    """Check if running in production environment."""
    env = _get_env()
    return env in ("prod", "production")


def _parse_db_port(url: Optional[str]) -> Optional[int]:
    """Extract port from database URL."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        return parsed.port
    except Exception:
        return None


def _log_banner(title: str, color: str = RED) -> None:
    """Print a prominent banner for visibility in logs."""
    border = "=" * 70
    print(f"\n{color}{BOLD}{border}", file=sys.stderr)
    print(f"  {title}", file=sys.stderr)
    print(f"{border}{RESET}\n", file=sys.stderr)


def check_forbidden_vars() -> tuple[bool, Optional[str]]:
    """
    Check 1: Forbidden Variables (Anti-Footgun)

    In production, SUPABASE_MIGRATE_DB_URL must NEVER be present.
    This URL provides direct database access (port 5432) which bypasses
    the connection pooler and can exhaust database connections.

    Returns:
        Tuple of (passed, error_message)
    """
    if not _is_production():
        return True, None

    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        return False, (
            "⛔ SECURITY VIOLATION: Migration credentials detected in Runtime!\n"
            "\n"
            "SUPABASE_MIGRATE_DB_URL (port 5432) is set in a production runtime.\n"
            "This bypasses the connection pooler and can exhaust DB connections.\n"
            "\n"
            "IMMEDIATE ACTION REQUIRED:\n"
            "  1. Go to Railway Dashboard → Your Service → Variables\n"
            "  2. DELETE the SUPABASE_MIGRATE_DB_URL variable\n"
            "  3. Redeploy the service\n"
            "\n"
            "Runtime services must ONLY use SUPABASE_DB_URL (port 6543).\n"
            "Migration URLs are for CI/CD pipelines, not runtime services."
        )

    return True, None


def check_pooler_enforcement() -> tuple[bool, Optional[str]]:
    """
    Check 2: Pooler Enforcement

    Runtime database connections should use the Transaction Pooler (port 6543)
    instead of direct connections (port 5432).

    Returns:
        Tuple of (passed, warning_message)
    """
    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")

    if not db_url:
        # No DB URL - will be caught by critical vars check
        return True, None

    port = _parse_db_port(db_url)

    if port is None:
        return True, None  # Can't parse, don't warn

    if port == 6543:
        return True, None  # Correct port

    if port == 5432:
        return False, (
            f"⚠️  Runtime is NOT connected to the Transaction Pooler!\n"
            f"\n"
            f"Current port: {port} (direct connection)\n"
            f"Expected port: 6543 (transaction pooler)\n"
            f"\n"
            f"Direct connections can exhaust the database connection limit.\n"
            f"Consider updating your SUPABASE_DB_URL to use port 6543."
        )

    # Non-standard port - just note it
    return True, f"Database using non-standard port {port}"


def check_critical_vars() -> tuple[bool, list[str]]:
    """
    Check 3: Critical Variables

    Ensure all required environment variables are present for production.

    Returns:
        Tuple of (passed, list_of_missing_vars)
    """
    # Required in production
    critical_vars = [
        "SUPABASE_SERVICE_ROLE_KEY",
        "DRAGONFLY_API_KEY",
    ]

    # These are required for observability but not fatal if missing
    observability_vars = [
        "RAILWAY_GIT_COMMIT_SHA",
    ]

    missing_critical = []
    missing_observability = []

    for var in critical_vars:
        if not os.environ.get(var):
            missing_critical.append(var)

    for var in observability_vars:
        if not os.environ.get(var):
            missing_observability.append(var)

    # In production, critical vars are fatal
    if _is_production() and missing_critical:
        return False, missing_critical

    # Log observability warnings but don't fail
    if missing_observability:
        logger.warning(
            f"Missing observability vars (non-fatal): {', '.join(missing_observability)}"
        )

    return True, missing_critical


def validate_production_config() -> ConfigValidationResult:
    """
    Validate production configuration at startup.

    This function MUST be called at the very top of all entrypoints,
    BEFORE importing any other application modules.

    Exits with code 1 if critical security violations are detected.

    Returns:
        ConfigValidationResult with validation details

    Raises:
        SystemExit: If fatal security violations are detected in production
    """
    env = _get_env()
    is_prod = _is_production()

    result = ConfigValidationResult(
        passed=True,
        fatal_errors=[],
        warnings=[],
        missing_vars=[],
    )

    # =========================================================================
    # CHECK 1: Forbidden Variables (FATAL in production)
    # =========================================================================
    passed, error = check_forbidden_vars()
    if not passed and error:
        result.passed = False
        result.fatal_errors.append(error)

    # =========================================================================
    # CHECK 2: Pooler Enforcement (WARNING only)
    # =========================================================================
    passed, warning = check_pooler_enforcement()
    if not passed and warning:
        result.warnings.append(warning)

    # =========================================================================
    # CHECK 3: Critical Variables (FATAL in production)
    # =========================================================================
    passed, missing = check_critical_vars()
    if not passed:
        result.passed = False
        result.missing_vars = missing
        result.fatal_errors.append(f"Missing critical environment variables: {', '.join(missing)}")

    # =========================================================================
    # OUTPUT RESULTS
    # =========================================================================

    # Print warnings (non-fatal)
    for warning in result.warnings:
        _log_banner("CONFIGURATION WARNING", YELLOW)
        print(f"{YELLOW}{warning}{RESET}\n", file=sys.stderr)

    # Print fatal errors and exit
    if result.fatal_errors:
        _log_banner("CONFIGURATION SECURITY VIOLATION", RED)
        for error in result.fatal_errors:
            print(f"{RED}{error}{RESET}\n", file=sys.stderr)

        if is_prod:
            print(
                f"{RED}{BOLD}APPLICATION STARTUP BLOCKED{RESET}\n",
                file=sys.stderr,
            )
            print(
                f"{RED}Environment: {env.upper()}{RESET}\n",
                file=sys.stderr,
            )
            print(
                f"{RED}Fix the above issues and redeploy.{RESET}\n",
                file=sys.stderr,
            )
            # Log to structured logging as well
            logger.critical(
                "Configuration security violation - startup blocked",
                extra={
                    "errors": result.fatal_errors,
                    "environment": env,
                },
            )
            raise ConfigurationSecurityViolation(result.fatal_errors[0])
        else:
            # In dev, warn but don't crash
            print(
                f"{YELLOW}[DEV MODE] Would block in production. Continuing...{RESET}\n",
                file=sys.stderr,
            )

    # Success message
    if result.passed:
        logger.debug(f"Configuration validated OK (env={env})")

    return result


def require_pooler_connection() -> None:
    """
    Strict check that REQUIRES pooler connection (port 6543).

    Use this for workers that absolutely must use the pooler.
    Raises SystemExit if not using pooler in production.
    """
    if not _is_production():
        return

    db_url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("DATABASE_URL")
    port = _parse_db_port(db_url)

    if port and port != 6543:
        _log_banner("POOLER CONNECTION REQUIRED", RED)
        print(
            f"{RED}This worker requires connection pooler (port 6543).{RESET}\n",
            f"{RED}Current port: {port}{RESET}\n",
            file=sys.stderr,
        )
        sys.exit(1)


# Auto-validate if this module is run directly
if __name__ == "__main__":
    # Configure basic logging for standalone run
    logging.basicConfig(level=logging.DEBUG)

    print("Running configuration validation...\n")

    result = validate_production_config()

    print("\n" + "=" * 50)
    print("VALIDATION RESULT")
    print("=" * 50)
    print(f"Environment: {_get_env()}")
    print(f"Production: {_is_production()}")
    print(f"Passed: {result.passed}")
    print(f"Fatal Errors: {len(result.fatal_errors)}")
    print(f"Warnings: {len(result.warnings)}")
    print(f"Missing Vars: {result.missing_vars}")

    if result.passed:
        print(f"\n{GREEN}✅ Configuration is valid{RESET}")
    else:
        print(f"\n{RED}❌ Configuration has issues{RESET}")
        sys.exit(1)
