#!/usr/bin/env python3
"""
tools/probe_db.py
=================
Production-grade database connectivity probe with Supabase Pooler Identity Contract.

CANONICAL PROJECT REF: iaketsyhmqbwaabgykux

This tool provides definitive PASS/FAIL verification before deploying to production.
It validates both connectivity AND the pooler identity contract.

SUPABASE POOLER IDENTITY CONTRACT:

SHARED POOLER (aws-*.pooler.supabase.com):
    - Username MUST be: <db_user>.<project_ref>
    - Example: postgres.iaketsyhmqbwaabgykux

DEDICATED POOLER (db.<ref>.supabase.co:6543):
    - Username is plain: <db_user>
    - Project ref is in the hostname

DIRECT CONNECTION (db.<ref>.supabase.co:5432):
    - FORBIDDEN in production (bypasses pooler)

Usage:
    # Probe with explicit DSN
    python -m tools.probe_db "postgresql://user:pass@host:6543/postgres?sslmode=require"

    # Interactive mode (prompts for DSN)
    python -m tools.probe_db

    # From environment variable
    python -m tools.probe_db --env

Exit Codes:
    0 - Connection successful AND identity valid (PASS)
    1 - Connection failed or identity invalid (FAIL)
    2 - No DSN provided

Author: Principal Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
import time
from typing import Optional
from urllib.parse import parse_qs, urlparse

# =============================================================================
# Constants
# =============================================================================

# Single DSN Contract: DATABASE_URL is the ONLY canonical variable
CANONICAL_VAR = "DATABASE_URL"
DEPRECATED_VAR = "SUPABASE_DB_URL"  # Maps to DATABASE_URL with warning

CONNECT_TIMEOUT = 5  # seconds

# Project references for environment validation
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"

# Default expected ref (used when --env not specified)
EXPECTED_PROJECT_REF = PROD_PROJECT_REF

# Ports
POOLER_PORT = 6543
DIRECT_PORT = 5432

# Host patterns
SHARED_POOLER_PATTERN = re.compile(r"^(aws-[a-z0-9-]+)\.pooler\.supabase\.com$")
DEDICATED_POOLER_PATTERN = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$")


# =============================================================================
# Pooler Identity Types
# =============================================================================


class PoolerMode:
    """Connection pooler modes."""

    SHARED = "shared"  # aws-*.pooler.supabase.com
    DEDICATED = "dedicated"  # db.<ref>.supabase.co:6543
    DIRECT = "direct"  # db.<ref>.supabase.co:5432 (FORBIDDEN)
    UNKNOWN = "unknown"


class IdentityError:
    """Pooler identity error codes."""

    VALID = "VALID"
    SHARED_POOLER_USER_MISSING_REF = "SHARED_POOLER_USER_MISSING_REF"
    PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER = "PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER"
    DEDICATED_POOLER_HOST_REF_MISMATCH = "DEDICATED_POOLER_HOST_REF_MISMATCH"
    DIRECT_CONNECTION_FORBIDDEN = "DIRECT_CONNECTION_FORBIDDEN"
    MISSING_SSLMODE = "MISSING_SSLMODE"
    WRONG_PORT = "WRONG_PORT"


# =============================================================================
# Helper functions
# =============================================================================


def extract_host_port(dsn: str) -> tuple[str | None, int | None]:
    """
    Extract host and port from a DSN string.

    Returns:
        Tuple of (host, port). Both may be None if parsing fails.
    """
    try:
        parsed = urlparse(dsn)
        return parsed.hostname, parsed.port
    except Exception:
        return None, None


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def parse_dsn_components(dsn: str) -> dict:
    """
    Parse DSN into components.

    Returns dict with keys:
        host, port, user, password, database, sslmode,
        user_base, user_project_ref, host_project_ref, pooler_mode
    """
    try:
        parsed = urlparse(dsn)
    except Exception:
        return {"error": "Could not parse DSN"}

    host = parsed.hostname
    port = parsed.port
    user = parsed.username
    password = parsed.password
    database = parsed.path.lstrip("/") if parsed.path else "postgres"

    # Parse query params
    query_params = parse_qs(parsed.query)
    sslmode_list = query_params.get("sslmode", [])
    sslmode = sslmode_list[0] if sslmode_list else None

    # Extract user components
    user_base = user
    user_project_ref = None
    if user and "." in user:
        parts = user.split(".", 1)
        user_base = parts[0]
        user_project_ref = parts[1]

    # Detect pooler mode and extract host ref
    pooler_mode = PoolerMode.UNKNOWN
    host_project_ref = None
    pooler_region = None

    if host:
        # Check shared pooler
        shared_match = SHARED_POOLER_PATTERN.match(host)
        if shared_match:
            pooler_mode = PoolerMode.SHARED
            pooler_region = shared_match.group(1)

        # Check dedicated/direct
        dedicated_match = DEDICATED_POOLER_PATTERN.match(host)
        if dedicated_match:
            host_project_ref = dedicated_match.group(1)
            if port == POOLER_PORT:
                pooler_mode = PoolerMode.DEDICATED
            elif port == DIRECT_PORT:
                pooler_mode = PoolerMode.DIRECT
            else:
                pooler_mode = PoolerMode.UNKNOWN

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "sslmode": sslmode,
        "user_base": user_base,
        "user_project_ref": user_project_ref,
        "host_project_ref": host_project_ref,
        "pooler_mode": pooler_mode,
        "pooler_region": pooler_region,
    }


def validate_pooler_identity(
    components: dict,
    expected_ref: str = EXPECTED_PROJECT_REF,
) -> tuple[bool, str, str]:
    """
    Validate DSN against Supabase pooler identity contract.

    Args:
        components: Parsed DSN components from parse_dsn_components()
        expected_ref: Expected project reference

    Returns:
        Tuple of (is_valid, error_code, suggestion)
    """
    pooler_mode = components.get("pooler_mode", PoolerMode.UNKNOWN)
    sslmode = components.get("sslmode")
    user = components.get("user")
    user_base = components.get("user_base")
    user_project_ref = components.get("user_project_ref")
    host_project_ref = components.get("host_project_ref")
    port = components.get("port")

    # Check sslmode
    if sslmode != "require":
        return (
            False,
            IdentityError.MISSING_SSLMODE,
            f"Add ?sslmode=require to DSN (current: {sslmode})",
        )

    # Check port
    if port and port != POOLER_PORT:
        if pooler_mode == PoolerMode.DIRECT:
            return (
                False,
                IdentityError.DIRECT_CONNECTION_FORBIDDEN,
                "Direct connections (port 5432) FORBIDDEN. Use port 6543 or shared pooler.",
            )
        elif port != POOLER_PORT:
            return (
                False,
                IdentityError.WRONG_PORT,
                f"Port {port} is wrong. Use 6543 for pooler.",
            )

    # SHARED POOLER validation
    if pooler_mode == PoolerMode.SHARED:
        if not user_project_ref:
            return (
                False,
                IdentityError.SHARED_POOLER_USER_MISSING_REF,
                f"Username '{user}' missing project ref. Use '{user_base}.{expected_ref}'.",
            )

        if user_project_ref != expected_ref:
            return (
                False,
                IdentityError.PROJECT_REF_MISMATCH_BETWEEN_HOST_AND_USER,
                f"Username ref '{user_project_ref}' != expected '{expected_ref}'. "
                f"Use '{user_base}.{expected_ref}'.",
            )

        return (True, IdentityError.VALID, "")

    # DEDICATED POOLER validation
    if pooler_mode == PoolerMode.DEDICATED:
        if host_project_ref != expected_ref:
            return (
                False,
                IdentityError.DEDICATED_POOLER_HOST_REF_MISMATCH,
                f"Host ref '{host_project_ref}' != expected '{expected_ref}'. "
                f"Use 'db.{expected_ref}.supabase.co'.",
            )

        return (True, IdentityError.VALID, "")

    # Unknown pooler mode - allow but warn
    return (True, IdentityError.VALID, "")


def get_effective_project_ref(components: dict) -> Optional[str]:
    """Get the effective project ref from DSN components."""
    return components.get("host_project_ref") or components.get("user_project_ref")


def analyze_connection_error(error: Exception) -> tuple[str, str]:
    """
    Analyze connection error and provide actionable guidance.

    Returns:
        Tuple of (short_error, suggestion)
    """
    error_str = str(error).lower()

    if "password authentication failed" in error_str:
        return (
            "Password authentication failed",
            "Check Password or URL Encoding. Special chars (!@#$%) must be URL-encoded.",
        )

    if "tenant or user not found" in error_str:
        return (
            "Tenant or user not found",
            "Username format is wrong. For shared pooler: use '<user>.<project_ref>' "
            "not just '<user>'. For dedicated: use plain '<user>'.",
        )

    if "could not translate host name" in error_str or "name resolution" in error_str:
        return (
            "Host name resolution failed",
            "Host is wrong or unreachable. Check the hostname in your DSN.",
        )

    if "connection refused" in error_str:
        return (
            "Connection refused",
            "Port is wrong or database is not accepting connections. "
            "Pooler uses 6543, direct uses 5432.",
        )

    if "timeout" in error_str:
        return (
            "Connection timeout",
            "Network issue or firewall blocking. Check if project is paused in Supabase dashboard.",
        )

    if "ssl" in error_str:
        return (
            "SSL error",
            "Add ?sslmode=require to your DSN.",
        )

    if "database" in error_str and "does not exist" in error_str:
        return (
            "Database does not exist",
            "Check database name in DSN. Default is 'postgres'.",
        )

    # Generic error
    return (
        str(error).split("\n")[0][:100],
        "Check DSN format: postgresql://user:pass@host:port/database?sslmode=require",
    )


# =============================================================================
# Main probe function
# =============================================================================


def probe_database(dsn: str, expected_ref: str = EXPECTED_PROJECT_REF) -> dict:
    """
    Probe database connectivity with full identity validation.

    Args:
        dsn: PostgreSQL connection string
        expected_ref: Expected project reference

    Returns:
        Dict with probe results
    """
    redacted = redact_dsn(dsn)
    components = parse_dsn_components(dsn)

    result = {
        "dsn_redacted": redacted,
        "pooler_mode": components.get("pooler_mode", PoolerMode.UNKNOWN),
        "host": components.get("host"),
        "port": components.get("port"),
        "user": components.get("user"),
        "user_base": components.get("user_base"),
        "user_project_ref": components.get("user_project_ref"),
        "host_project_ref": components.get("host_project_ref"),
        "effective_project_ref": get_effective_project_ref(components),
        "expected_project_ref": expected_ref,
        "elapsed_seconds": 0.0,
        "identity_valid": False,
        "identity_error": None,
        "identity_suggestion": None,
        "connection_success": False,
        "connection_error": None,
        "connection_suggestion": None,
        "server_user": None,
        "server_database": None,
        "server_addr": None,
        "server_time": None,
    }

    # Validate identity FIRST (before trying to connect)
    identity_valid, identity_error, identity_suggestion = validate_pooler_identity(
        components, expected_ref
    )
    result["identity_valid"] = identity_valid
    result["identity_error"] = identity_error
    result["identity_suggestion"] = identity_suggestion

    # If identity is invalid, don't bother connecting
    if not identity_valid:
        return result

    # Try to connect
    try:
        import psycopg
    except ImportError:
        result["connection_error"] = "psycopg not installed"
        result["connection_suggestion"] = "Run: pip install psycopg[binary]"
        return result

    start_time = time.time()

    try:
        with psycopg.connect(dsn, connect_timeout=CONNECT_TIMEOUT) as conn:
            # Run diagnostic query
            row = conn.execute(
                """
                SELECT 
                    current_user, 
                    current_database(), 
                    inet_server_addr()::text,
                    now()
            """
            ).fetchone()

            result["elapsed_seconds"] = time.time() - start_time
            result["connection_success"] = True
            result["server_user"] = row[0]
            result["server_database"] = row[1]
            result["server_addr"] = row[2]
            result["server_time"] = str(row[3])

    except Exception as e:
        result["elapsed_seconds"] = time.time() - start_time
        short_error, suggestion = analyze_connection_error(e)
        result["connection_error"] = short_error
        result["connection_suggestion"] = suggestion

    return result


# =============================================================================
# Output formatting
# =============================================================================


def print_result(result: dict) -> None:
    """Print probe result with pooler identity details."""
    pooler_mode = result["pooler_mode"]
    identity_valid = result["identity_valid"]
    connection_success = result["connection_success"]
    expected_ref = result["expected_project_ref"]
    effective_ref = result["effective_project_ref"]

    # Overall success requires both identity AND connection
    overall_success = identity_valid and connection_success

    print()
    print("=" * 70)

    if overall_success:
        print("  ✅ CONNECTION SUCCESSFUL")
    else:
        print("  ❌ CONNECTION FAILED")

    print("=" * 70)
    print()

    # Pooler mode section
    print(f"  Pooler Mode:     {pooler_mode.upper()}")

    if pooler_mode == PoolerMode.SHARED:
        print(f"  Region:          {result.get('pooler_region', 'unknown')}")
        print(f"  User (base):     {result['user_base']}")
        print(f"  User (ref):      {result['user_project_ref']}")
    elif pooler_mode == PoolerMode.DEDICATED:
        print(f"  Host (ref):      {result['host_project_ref']}")
        print(f"  User:            {result['user']}")
    elif pooler_mode == PoolerMode.DIRECT:
        print(f"  Host (ref):      {result['host_project_ref']}")
        print("  ⚠️  DIRECT CONNECTION FORBIDDEN IN PRODUCTION")
    else:
        print(f"  Host:            {result['host']}")
        print(f"  User:            {result['user']}")

    print()

    # Project ref validation
    if effective_ref:
        if effective_ref == expected_ref:
            print(f"  Project Ref:     {effective_ref} ✓ (matches expected)")
        else:
            print(f"  Project Ref:     {effective_ref} ⚠️  (expected: {expected_ref})")
    else:
        print("  Project Ref:     (none detected)")

    print()
    print("-" * 70)

    # Identity validation result
    if identity_valid:
        print("  Identity:        ✅ VALID")
    else:
        print(f"  Identity:        ❌ {result['identity_error']}")
        print(f"  Fix:             {result['identity_suggestion']}")
        print()
        print("-" * 70)
        # Single-line FAIL for operators
        print(f"  FAIL [{result['identity_error']}]: {result['identity_suggestion']}")
        print("=" * 70)
        print()
        return

    # Connection result (only if identity was valid)
    if connection_success:
        print("  Connection:      ✅ SUCCESS")
        print()
        print(f"  Server User:     {result['server_user']}")
        print(f"  Server Database: {result['server_database']}")
        print(f"  Server Address:  {result['server_addr']}")
        print(f"  Server Time:     {result['server_time']}")
        print(f"  Connect Time:    {result['elapsed_seconds']:.2f}s")
        print()
        print("-" * 70)
        print("  This DSN is valid. Safe to deploy to Railway.")
    else:
        print(f"  Connection:      ❌ {result['connection_error']}")
        print(f"  Fix:             {result['connection_suggestion']}")
        print()
        print("-" * 70)
        # Single-line FAIL for operators
        print(
            f"  FAIL [CONNECTION]: {result['connection_error']}. {result['connection_suggestion']}"
        )

    print("=" * 70)
    print()


# =============================================================================
# CLI
# =============================================================================


def get_dsn_from_env() -> str | None:
    """
    Get DSN from environment using Single DSN Contract.

    Priority:
        1. DATABASE_URL (canonical)
        2. SUPABASE_DB_URL (deprecated, with warning)
    """
    import warnings

    # Priority 1: Canonical
    dsn = os.environ.get(CANONICAL_VAR, "").strip()
    if dsn:
        return dsn

    # Priority 2: Deprecated (with warning)
    dsn = os.environ.get(DEPRECATED_VAR, "").strip()
    if dsn:
        msg = f"WARNING: '{DEPRECATED_VAR}' is DEPRECATED. " f"Use '{CANONICAL_VAR}' instead."
        print(msg, file=sys.stderr)
        warnings.warn(msg, DeprecationWarning, stacklevel=2)
        return dsn

    return None


def main() -> int:
    """
    Main entrypoint with --env dev|prod support.

    Exit Codes:
        0 - PASS: Connection successful AND identity valid
        1 - FAIL: Identity mismatch OR connection failed
        2 - ERROR: No DSN provided or invalid format
    """
    parser = argparse.ArgumentParser(
        description="Production database connectivity probe with Supabase Pooler Identity Contract",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
SINGLE DSN CONTRACT:
  Canonical Variable: {CANONICAL_VAR}
  Deprecated (with warning): {DEPRECATED_VAR}

PROJECT REFERENCES:
  --env prod => {PROD_PROJECT_REF} (port 6543 required)
  --env dev  => {DEV_PROJECT_REF} (or localhost)

SUPABASE POOLER IDENTITY CONTRACT:

  SHARED POOLER (aws-*.pooler.supabase.com):
      Username MUST be: <db_user>.<project_ref>
      Example: postgres.{PROD_PROJECT_REF}

  DEDICATED POOLER (db.<ref>.supabase.co:6543):
      Username is plain: <db_user>
      Project ref is in the hostname

  DIRECT (db.<ref>.supabase.co:5432):
      FORBIDDEN in production

Examples:
    # Validate for production environment
    python -m tools.probe_db --env prod

    # Validate for dev environment
    python -m tools.probe_db --env dev

    # Explicit DSN with prod validation
    python -m tools.probe_db --env prod "postgresql://user:pass@db.{PROD_PROJECT_REF}.supabase.co:6543/postgres?sslmode=require"

    # Legacy: Read from environment (deprecated flag)
    python -m tools.probe_db --from-env

EXIT CODES:
    0 - PASS: Connection successful, identity valid
    1 - FAIL: Identity mismatch or connection failed
    2 - ERROR: Configuration error (no DSN, invalid format)
""",
    )

    parser.add_argument(
        "dsn",
        nargs="?",
        help="PostgreSQL connection string (DSN). If omitted, reads from environment.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        help="Target environment. Determines expected project ref (dev={}, prod={})".format(
            DEV_PROJECT_REF, PROD_PROJECT_REF
        ),
    )
    parser.add_argument(
        "--from-env",
        action="store_true",
        dest="from_env",
        help=f"Read DSN from ${CANONICAL_VAR} (or deprecated ${DEPRECATED_VAR})",
    )
    parser.add_argument(
        "--project-ref",
        dest="project_ref",
        help="Override expected project ref (for custom validation)",
    )

    args = parser.parse_args()

    # Determine expected project ref based on --env
    if args.project_ref:
        expected_ref = args.project_ref
    elif args.env == "dev":
        expected_ref = DEV_PROJECT_REF
    elif args.env == "prod":
        expected_ref = PROD_PROJECT_REF
    else:
        # Default to prod for safety
        expected_ref = PROD_PROJECT_REF

    # Determine DSN source
    dsn: Optional[str] = None

    if args.dsn:
        dsn = args.dsn
    elif args.from_env or args.env:
        # If --env is specified without DSN, read from environment
        dsn = get_dsn_from_env()
        if not dsn:
            print(
                f"ERROR: No DSN found in environment.\n"
                f"Set {CANONICAL_VAR} (or deprecated {DEPRECATED_VAR})",
                file=sys.stderr,
            )
            return 2
    else:
        # Interactive mode
        print()
        print("=" * 70)
        print("  DRAGONFLY DATABASE CONNECTIVITY PROBE")
        print("  with Supabase Pooler Identity Contract")
        print("=" * 70)
        print()
        print(f"Expected Project Ref: {expected_ref}")
        print()
        print("Paste your PostgreSQL DSN (connection string):")
        print("(Input will be hidden for security)")
        print()
        dsn = getpass.getpass("DSN: ")

        if not dsn.strip():
            print("ERROR: No DSN provided", file=sys.stderr)
            return 2

    # Validate DSN format
    if not dsn.startswith(("postgres://", "postgresql://")):
        print("ERROR: DSN must start with postgres:// or postgresql://", file=sys.stderr)
        return 2

    # Print probe context
    if args.env:
        print(f"\n[Probe: {args.env.upper()} environment, expected ref: {expected_ref}]")

    # Run probe
    result = probe_database(dsn, expected_ref)
    print_result(result)

    # Exit code: 0 = PASS, 1 = FAIL
    if result["identity_valid"] and result["connection_success"]:
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
