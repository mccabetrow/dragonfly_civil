"""
src/dsn_compat.py
=================
Single DSN Contract - DATABASE_URL is the ONLY canonical variable.

CANONICAL VARIABLE: DATABASE_URL
================================
All runtime code MUST use get_database_url() from this module.

DEPRECATED VARIABLES (with shim):
- SUPABASE_DB_URL       -> maps to DATABASE_URL with deprecation warning
- SUPABASE_DB_URI       -> maps to DATABASE_URL with deprecation warning
- SUPABASE_MIGRATE_DB_URL -> allowed ONLY for migration scripts

PROJECT REFERENCES:
- PROD: iaketsyhmqbwaabgykux (port 6543 required)
- DEV:  ejiddanxtqcleyswqvkc (or localhost)

Usage:
------
    from src.dsn_compat import get_database_url

    db_url = get_database_url()  # Returns DATABASE_URL with validation

Author: Principal Database Reliability Engineer
Date: 2026-01-15
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# =============================================================================
# CANONICAL VARIABLE NAME - DO NOT CHANGE
# =============================================================================

CANONICAL_VAR = "DATABASE_URL"

# Deprecated variable names that map to DATABASE_URL (with warning)
DEPRECATED_VARS = (
    "SUPABASE_DB_URL",
    "SUPABASE_DB_URI",
)

# Migration-only variable (allowed for scripts, not runtime)
MIGRATION_VAR = "SUPABASE_MIGRATE_DB_URL"


# =============================================================================
# Project References
# =============================================================================

PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"
PROD_REQUIRED_PORT = 6543


# =============================================================================
# DSN Parsing
# =============================================================================


def extract_host_port(dsn: str) -> tuple[str | None, int | None]:
    """
    Extract host and port from a DSN string.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Tuple of (host, port). Both may be None if parsing fails.
    """
    try:
        parsed = urlparse(dsn)
        return parsed.hostname, parsed.port
    except Exception:
        return None, None


def extract_project_ref(dsn: str) -> str | None:
    """
    Extract Supabase project reference from DSN.

    Checks for patterns:
    - db.<ref>.supabase.co (dedicated pooler)
    - <user>.<ref> (shared pooler username)

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Project reference string or None if not found
    """
    try:
        parsed = urlparse(dsn)
        host = parsed.hostname

        if not host:
            return None

        # Pattern 1: Dedicated pooler - db.<ref>.supabase.co
        dedicated_match = re.match(r"^db\.([a-z0-9]+)\.supabase\.co$", host, re.IGNORECASE)
        if dedicated_match:
            return dedicated_match.group(1).lower()

        # Pattern 2: Shared pooler - check username for <user>.<ref>
        user = parsed.username
        if user and "." in user:
            # Username format: postgres.iaketsyhmqbwaabgykux
            parts = user.split(".", 1)
            if len(parts) == 2 and len(parts[1]) > 10:
                return parts[1].lower()

        return None
    except Exception:
        return None


def redact_dsn(dsn: str) -> str:
    """
    Redact password from DSN for safe logging.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        DSN with password replaced by ****
    """
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def validate_dsn_for_env(dsn: str, env: str) -> tuple[bool, str]:
    """
    Validate DSN matches expected environment.

    Args:
        dsn: PostgreSQL connection string
        env: Expected environment (prod, dev)

    Returns:
        Tuple of (is_valid, error_message)
    """
    host, port = extract_host_port(dsn)
    project_ref = extract_project_ref(dsn)

    env = env.lower().strip()

    if env == "prod":
        # PROD requires:
        # 1. Host contains PROD_PROJECT_REF
        # 2. Port is 6543 (Transaction Pooler)
        if project_ref != PROD_PROJECT_REF:
            return False, (
                f"PROD requires project ref '{PROD_PROJECT_REF}'. "
                f"Found: '{project_ref or 'none'}'"
            )
        if port != PROD_REQUIRED_PORT:
            return False, (
                f"PROD requires port {PROD_REQUIRED_PORT} (Transaction Pooler). "
                f"Found: {port}. Direct connections (5432) are FORBIDDEN."
            )
        return True, ""

    elif env in ("dev", "staging", "development", "local"):
        # DEV allows:
        # 1. DEV_PROJECT_REF
        # 2. localhost/127.0.0.1
        if not host:
            return False, "Cannot parse host from DSN"

        host_lower = host.lower()

        # Check for localhost
        if any(local in host_lower for local in ("localhost", "127.0.0.1", "host.docker.internal")):
            return True, ""

        # Check for dev project ref
        if project_ref == DEV_PROJECT_REF:
            return True, ""

        # Check if accidentally using prod in dev (dangerous!)
        if project_ref == PROD_PROJECT_REF:
            return False, (
                f"DEV environment is using PROD project ref '{PROD_PROJECT_REF}'! "
                "This would write dev data to production!"
            )

        return False, (
            f"DEV requires project ref '{DEV_PROJECT_REF}' or localhost. "
            f"Found: '{project_ref or 'none'}'"
        )

    else:
        return False, f"Unknown environment: {env}"


# =============================================================================
# Core Function
# =============================================================================


def get_database_url(
    *,
    require: bool = True,
    check_env: str | None = None,
    suppress_deprecation: bool = False,
) -> str | None:
    """
    Get the canonical DATABASE_URL.

    This is the ONLY function runtime code should use to get the database URL.

    Priority:
        1. DATABASE_URL (canonical)
        2. SUPABASE_DB_URL (deprecated, with warning)
        3. SUPABASE_DB_URI (deprecated, with warning)

    Args:
        require: If True, raise RuntimeError when not found. Default True.
        check_env: If provided, validate DSN matches this environment (prod/dev).
        suppress_deprecation: If True, don't emit deprecation warnings (for tests).

    Returns:
        Database URL string, or None if not required and not found.

    Raises:
        RuntimeError: If require=True and no database URL is configured.
        RuntimeError: If check_env is provided and DSN doesn't match.
    """
    db_url: str | None = None
    source_var: str | None = None

    # Priority 1: Canonical DATABASE_URL
    db_url = os.environ.get(CANONICAL_VAR, "").strip() or None
    if db_url:
        source_var = CANONICAL_VAR

    # Priority 2+: Deprecated variables (with warning)
    if not db_url:
        for deprecated_var in DEPRECATED_VARS:
            value = os.environ.get(deprecated_var, "").strip()
            if value:
                db_url = value
                source_var = deprecated_var

                if not suppress_deprecation:
                    msg = (
                        f"Environment variable '{deprecated_var}' is DEPRECATED. "
                        f"Use '{CANONICAL_VAR}' instead. "
                        f"This variable will be removed in a future release."
                    )
                    warnings.warn(msg, DeprecationWarning, stacklevel=2)
                    logger.warning(msg)
                break

    # Handle missing
    if not db_url:
        if require:
            raise RuntimeError(
                f"Missing required environment variable: {CANONICAL_VAR}\n\n"
                f"The canonical database URL variable is {CANONICAL_VAR}.\n\n"
                f"Set it in your environment:\n"
                f"  {CANONICAL_VAR}=postgresql://user:pass@host:6543/postgres?sslmode=require\n\n"
                f"Note: SUPABASE_DB_URL is deprecated and will be removed."
            )
        return None

    # Validate format
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError(
            f"{source_var} must start with postgres:// or postgresql://\n" f"Got: {db_url[:50]}..."
        )

    # Environment validation (optional)
    if check_env:
        is_valid, error_msg = validate_dsn_for_env(db_url, check_env)
        if not is_valid:
            raise RuntimeError(
                f"DSN validation failed for environment '{check_env}':\n"
                f"{error_msg}\n\n"
                f"DSN (redacted): {redact_dsn(db_url)}"
            )

    return db_url


def get_database_url_or_exit(
    env: str | None = None,
    exit_code: int = 2,
) -> str:
    """
    Get DATABASE_URL or exit immediately.

    This is the recommended function for worker entrypoints.

    Args:
        env: Environment to validate against (prod/dev). If None, uses SUPABASE_MODE/ENV.
        exit_code: Exit code on failure (default: 2 for config error).

    Returns:
        Database URL string.

    Exits:
        With exit_code if DATABASE_URL is missing or invalid.
    """
    import sys

    # Determine environment
    if env is None:
        env = os.environ.get("SUPABASE_MODE") or os.environ.get("ENV") or "dev"

    try:
        return get_database_url(require=True, check_env=env)
    except RuntimeError as e:
        logger.critical(f"Fatal configuration error: {e}")
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(exit_code)


# =============================================================================
# CLI for manual verification
# =============================================================================


def main() -> int:
    """CLI entrypoint for DATABASE_URL verification."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Verify DATABASE_URL configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Canonical Variable: {CANONICAL_VAR}
Deprecated (with shim): {', '.join(DEPRECATED_VARS)}

Project References:
  PROD: {PROD_PROJECT_REF} (port {PROD_REQUIRED_PORT} required)
  DEV:  {DEV_PROJECT_REF} (or localhost)

Examples:
    python -m src.dsn_compat --env prod
    python -m src.dsn_compat --env dev --show-redacted
""",
    )

    parser.add_argument(
        "--env",
        choices=["prod", "dev"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Environment to validate against (default: $SUPABASE_MODE or dev)",
    )
    parser.add_argument(
        "--show-redacted",
        action="store_true",
        help="Show the redacted DSN in output",
    )

    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  SINGLE DSN CONTRACT VERIFICATION")
    print("=" * 60)
    print()
    print(f"  Canonical Variable: {CANONICAL_VAR}")
    print(f"  Environment:        {args.env}")
    print()

    # Check what's set
    print("  Variable Status:")
    for var in [CANONICAL_VAR] + list(DEPRECATED_VARS):
        value = os.environ.get(var, "")
        if value:
            status = "✓ SET" if var == CANONICAL_VAR else "⚠️ SET (deprecated)"
            print(f"    {var}: {status}")
        else:
            print(f"    {var}: (not set)")
    print()

    try:
        db_url = get_database_url(require=True, check_env=args.env)

        if args.show_redacted:
            print(f"  DSN (redacted): {redact_dsn(db_url)}")
            print()

        project_ref = extract_project_ref(db_url)
        host, port = extract_host_port(db_url)

        print(f"  Project Ref:      {project_ref or '(none detected)'}")
        print(f"  Host:             {host}")
        print(f"  Port:             {port}")
        print()
        print("-" * 60)
        print("  ✅ PASS - DATABASE_URL validated for", args.env.upper())
        print("=" * 60)
        print()
        return 0

    except RuntimeError as e:
        print(f"  ❌ FAIL: {e}")
        print("=" * 60)
        print()
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
