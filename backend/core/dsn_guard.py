"""
backend/core/dsn_guard.py
=========================
DSN Guard - Zero Drift Policy Enforcement (World Class Edition)

HARD RULES (Non-Negotiable):
============================
PROD Environment (SUPABASE_MODE=prod):
  - Host MUST contain: iaketsyhmqbwaabgykux
  - Port MUST be: 6543 (Transaction Pooler)
  - Direct connections (5432) are FORBIDDEN in prod

  TIME-BOXED WAIVER (expires 2026-02-15):
    Set DB_CONNECTION_MODE=direct_waiver to allow 5432 temporarily.
    This logs CRITICAL warnings and emits db_connection_mode metric.
    After expiry date, waiver is ignored and direct connections crash.

DEV Environment (SUPABASE_MODE=dev):
  - Host MUST contain: ejiddanxtqcleyswqvkc OR localhost/127.0.0.1
  - Port can be 5432 (direct) or 6543 (pooler)

This guard is called BEFORE any database connection is attempted.
Failure raises DSNEnvironmentMismatchError - no connection attempt is made.

Usage:
    from backend.core.dsn_guard import validate_dsn_for_environment

    # Called at startup, before pool creation
    validate_dsn_for_environment(dsn, environment)

Author: Principal Site Reliability Engineer
Date: 2026-01-18 (Updated with time-boxed waiver)
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

from loguru import logger

# =============================================================================
# CANONICAL PROJECT REFERENCES (DO NOT CHANGE WITHOUT APPROVAL)
# =============================================================================

# Production Supabase project
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"

# Development Supabase project
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"

# Required port for production (Transaction Pooler)
PROD_REQUIRED_PORT = 6543

# Direct connection port (allowed only with waiver)
DIRECT_CONNECTION_PORT = 5432

# Environment variable for direct connection waiver
DIRECT_WAIVER_ENV_VAR = "DB_CONNECTION_MODE"
DIRECT_WAIVER_VALUE = "direct_waiver"

# =============================================================================
# TIME-BOXED WAIVER CONFIGURATION
# =============================================================================
# The waiver expires on this date. After expiry, direct connections crash.
# To extend: update this date and document the reason in RUNBOOK_POOLER.md
DIRECT_WAIVER_EXPIRY = datetime(2026, 2, 15, 0, 0, 0, tzinfo=timezone.utc)

# Reason for current waiver (for logging/metrics)
DIRECT_WAIVER_REASON = "Supabase pooler returns 'Tenant or user not found' - pending investigation"

# =============================================================================
# METRICS / OBSERVABILITY
# =============================================================================
# Current connection mode for metrics export
_connection_mode: str = "unknown"


def get_db_connection_mode() -> str:
    """Return current connection mode for metrics: 'pooler', 'direct_waiver', or 'unknown'."""
    return _connection_mode


def get_waiver_status() -> dict:
    """Return waiver status for observability."""
    now = datetime.now(timezone.utc)
    is_expired = now >= DIRECT_WAIVER_EXPIRY
    days_remaining = (DIRECT_WAIVER_EXPIRY - now).days if not is_expired else 0

    return {
        "waiver_active": _connection_mode == "direct_waiver",
        "waiver_expired": is_expired,
        "expiry_date": DIRECT_WAIVER_EXPIRY.isoformat(),
        "days_remaining": days_remaining,
        "reason": DIRECT_WAIVER_REASON if _connection_mode == "direct_waiver" else None,
        "connection_mode": _connection_mode,
    }


# Allowed dev hosts (includes local development)
DEV_ALLOWED_HOSTS = (
    DEV_PROJECT_REF,
    "localhost",
    "127.0.0.1",
    "host.docker.internal",
)


# =============================================================================
# Custom Exception
# =============================================================================


class DSNEnvironmentMismatchError(Exception):
    """
    Raised when DSN does not match expected environment.

    This is a FATAL error - the application must not start.
    """

    def __init__(self, message: str, environment: str, dsn_host: str, dsn_port: int | None):
        self.environment = environment
        self.dsn_host = dsn_host
        self.dsn_port = dsn_port
        super().__init__(message)


# =============================================================================
# DSN Parsing Helpers
# =============================================================================


def _extract_host_port(dsn: str) -> tuple[str | None, int | None]:
    """Extract host and port from DSN string."""
    try:
        parsed = urlparse(dsn)
        return parsed.hostname, parsed.port
    except Exception:
        return None, None


def _redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def _host_contains_ref(host: str | None, ref: str) -> bool:
    """Check if host contains the project reference."""
    if not host:
        return False
    return ref.lower() in host.lower()


def _is_dev_host(host: str | None) -> bool:
    """Check if host is valid for dev environment."""
    if not host:
        return False
    host_lower = host.lower()
    return any(allowed in host_lower for allowed in DEV_ALLOWED_HOSTS)


# =============================================================================
# Main Guard Function
# =============================================================================


def validate_dsn_for_environment(
    dsn: str,
    environment: str,
    *,
    fatal_on_mismatch: bool = True,
) -> bool:
    """
    Validate DSN matches the expected environment.

    Args:
        dsn: PostgreSQL connection string
        environment: Expected environment (prod, dev, staging)
        fatal_on_mismatch: If True, raises exception on mismatch.
                          If False, returns False (for testing).

    Returns:
        True if DSN matches environment

    Raises:
        DSNEnvironmentMismatchError: If DSN doesn't match environment
        ValueError: If environment is unknown
    """
    environment = environment.lower().strip()

    # Parse DSN
    host, port = _extract_host_port(dsn)
    redacted = _redact_dsn(dsn)

    if not host:
        msg = f"DSN Guard: Cannot parse host from DSN: {redacted}"
        logger.critical(msg)
        if fatal_on_mismatch:
            raise DSNEnvironmentMismatchError(msg, environment, "", None)
        return False

    # ==========================================================================
    # PRODUCTION RULES (Strictest)
    # ==========================================================================
    if environment == "prod":
        # Rule 1: Host MUST contain prod project ref
        if not _host_contains_ref(host, PROD_PROJECT_REF):
            msg = (
                f"DSN Guard FATAL: PROD environment requires host containing '{PROD_PROJECT_REF}'. "
                f"Got host: {host}. "
                f"This looks like a DEV or wrong project DSN being used in PROD!"
            )
            logger.critical(msg)
            logger.critical(f"DSN (redacted): {redacted}")
            if fatal_on_mismatch:
                raise DSNEnvironmentMismatchError(msg, environment, host, port)
            return False

        # Rule 2: Port MUST be 6543 (Transaction Pooler) - unless waiver is active
        if port != PROD_REQUIRED_PORT:
            global _connection_mode

            # Check for direct connection waiver
            waiver_value = os.environ.get(DIRECT_WAIVER_ENV_VAR, "").lower().strip()
            has_waiver = waiver_value == DIRECT_WAIVER_VALUE

            # Check if waiver has expired
            now = datetime.now(timezone.utc)
            waiver_expired = now >= DIRECT_WAIVER_EXPIRY
            days_remaining = (DIRECT_WAIVER_EXPIRY - now).days

            if port == DIRECT_CONNECTION_PORT and has_waiver:
                if waiver_expired:
                    # Waiver has expired - HARD CRASH
                    _connection_mode = "waiver_expired"
                    msg = (
                        f"DSN Guard FATAL: Direct connection waiver EXPIRED on {DIRECT_WAIVER_EXPIRY.date()}.\n"
                        f"  Port {DIRECT_CONNECTION_PORT} is no longer allowed in production.\n"
                        f"  You MUST fix the pooler connection or extend the waiver in dsn_guard.py.\n"
                        f"  See RUNBOOK_POOLER.md for instructions."
                    )
                    logger.critical(msg)
                    if fatal_on_mismatch:
                        raise DSNEnvironmentMismatchError(msg, environment, host, port)
                    return False

                # Waiver granted and not expired - allow with warnings
                _connection_mode = "direct_waiver"
                logger.critical(
                    f"DSN Guard: ⚠️  DIRECT CONNECTION WAIVER ACTIVE ⚠️\n"
                    f"  Port {DIRECT_CONNECTION_PORT} (direct) is being used in PROD.\n"
                    f"  Reason: {DIRECT_WAIVER_REASON}\n"
                    f"  Expiry: {DIRECT_WAIVER_EXPIRY.date()} ({days_remaining} days remaining)\n"
                    f"  This bypasses connection pooling.\n"
                    f"  Performance may be degraded under load.\n"
                    f"  Remove {DIRECT_WAIVER_ENV_VAR}={DIRECT_WAIVER_VALUE} to enforce pooler."
                )
                logger.warning(
                    f"DSN Guard: Proceeding with direct connection (waiver active). "
                    f"Host: {host}, Port: {port}, Days until expiry: {days_remaining}"
                )
                return True  # Allow with waiver

            # No waiver - HARD CRASH
            _connection_mode = "rejected"
            msg = (
                f"DSN Guard FATAL: PROD environment requires port {PROD_REQUIRED_PORT} (Transaction Pooler). "
                f"Got port: {port}. "
                f"Direct connections (5432) are FORBIDDEN in production!\n"
                f"  To use direct connection temporarily, set: {DIRECT_WAIVER_ENV_VAR}={DIRECT_WAIVER_VALUE}\n"
                f"  Waiver expires: {DIRECT_WAIVER_EXPIRY.date()}"
            )
            logger.critical(msg)
            logger.critical(f"DSN (redacted): {redacted}")
            if fatal_on_mismatch:
                raise DSNEnvironmentMismatchError(msg, environment, host, port)
            return False

        # Prod validation passed - using pooler
        _connection_mode = "pooler"
        logger.info(
            f"DSN Guard: ✓ PROD environment validated "
            f"(host contains {PROD_PROJECT_REF}, port {port})"
        )
        return True

    # ==========================================================================
    # DEVELOPMENT / STAGING RULES
    # ==========================================================================
    elif environment in ("dev", "staging", "development", "local"):
        # Rule 1: Host must be dev project OR localhost
        if not _is_dev_host(host):
            # Check if they accidentally used prod DSN in dev
            if _host_contains_ref(host, PROD_PROJECT_REF):
                msg = (
                    f"DSN Guard FATAL: DEV environment is using PROD project ref '{PROD_PROJECT_REF}'! "
                    f"This would write dev data to production! "
                    f"Set SUPABASE_MODE=prod if this is intentional."
                )
                logger.critical(msg)
                if fatal_on_mismatch:
                    raise DSNEnvironmentMismatchError(msg, environment, host, port)
                return False

            msg = (
                f"DSN Guard FATAL: DEV environment requires host containing '{DEV_PROJECT_REF}' or localhost. "
                f"Got host: {host}"
            )
            logger.critical(msg)
            if fatal_on_mismatch:
                raise DSNEnvironmentMismatchError(msg, environment, host, port)
            return False

        # Dev validation passed
        logger.info(
            f"DSN Guard: ✓ DEV environment validated " f"(host: {host}, port: {port or 'default'})"
        )
        return True

    # ==========================================================================
    # UNKNOWN ENVIRONMENT
    # ==========================================================================
    else:
        msg = f"DSN Guard: Unknown environment '{environment}'. Expected: prod, dev, staging"
        logger.error(msg)
        if fatal_on_mismatch:
            raise ValueError(msg)
        return False


def guard_or_exit(dsn: str, environment: str, exit_code: int = 2) -> None:
    """
    Validate DSN for environment, exit immediately on mismatch.

    This is the recommended function for worker entrypoints.

    Args:
        dsn: PostgreSQL connection string
        environment: Expected environment
        exit_code: Exit code on failure (default: 2 for config error)
    """
    try:
        validate_dsn_for_environment(dsn, environment, fatal_on_mismatch=True)
    except (DSNEnvironmentMismatchError, ValueError) as e:
        logger.critical(f"DSN Guard: Fatal mismatch - {e}")
        logger.critical("Exiting immediately to prevent cross-environment data corruption.")
        sys.exit(exit_code)


# =============================================================================
# CLI for manual verification
# =============================================================================


def main() -> int:
    """CLI entrypoint for manual DSN verification."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Validate DSN matches expected environment")
    parser.add_argument(
        "--dsn",
        default=os.environ.get("DATABASE_URL", ""),
        help="DSN to validate (default: $DATABASE_URL)",
    )
    parser.add_argument(
        "--env",
        default=os.environ.get("SUPABASE_MODE", os.environ.get("ENV", "dev")),
        help="Environment to validate against (default: $SUPABASE_MODE or $ENV)",
    )

    args = parser.parse_args()

    if not args.dsn:
        print("ERROR: No DSN provided. Set DATABASE_URL or use --dsn")
        return 2

    print(f"Validating DSN for environment: {args.env}")
    print(f"DSN (redacted): {_redact_dsn(args.dsn)}")
    print()

    try:
        validate_dsn_for_environment(args.dsn, args.env)
        print("✅ DSN VALIDATED - Environment match confirmed")
        return 0
    except DSNEnvironmentMismatchError as e:
        print(f"❌ DSN REJECTED - {e}")
        return 1
    except ValueError as e:
        print(f"❌ INVALID - {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
