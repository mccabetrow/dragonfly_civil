#!/usr/bin/env python3
"""
tools/build_pooler_dsn.py
=========================
Builds a production-ready PostgreSQL DSN with proper URL encoding.

STDLIB-ONLY (except for validation): No external dependencies for core logic.

SUPABASE POOLER IDENTITY CONTRACT:

SHARED POOLER (aws-*.pooler.supabase.com):
    - Username MUST be: <db_user>.<project_ref>
    - Use --project-ref flag to specify (REQUIRED for shared pooler)
    - Example: postgres.iaketsyhmqbwaabgykux

DEDICATED POOLER (db.<ref>.supabase.co:6543):
    - Username is plain: <db_user>
    - Project ref is extracted from host
    - Example: postgres@db.iaketsyhmqbwaabgykux.supabase.co:6543

Features:
1. URL-encodes passwords (handles @, !, #, $, %, etc.)
2. Enforces correct username format per pooler type
3. Forces sslmode=require
4. Validates pooler identity contract

Usage:
    # Shared pooler (REQUIRES --project-ref)
    python -m tools.build_pooler_dsn \\
        --host aws-0-us-east-1.pooler.supabase.com \\
        --user dragonfly_app \\
        --project-ref iaketsyhmqbwaabgykux \\
        --password 'P@ss!'

    # Dedicated pooler (project ref extracted from host)
    python -m tools.build_pooler_dsn \\
        --host db.iaketsyhmqbwaabgykux.supabase.co \\
        --user dragonfly_app \\
        --password 'P@ss!'

    # Direct connection (use --direct flag)
    python -m tools.build_pooler_dsn \\
        --host db.iaketsyhmqbwaabgykux.supabase.co \\
        --user postgres \\
        --password 'P@ss!' \\
        --direct

Exit Codes:
    0 - DSN generated successfully
    1 - Invalid input or missing required fields
    2 - Password contains invalid characters
    3 - Pooler identity contract violation

Author: Principal Engineer
Date: 2026-01-14
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from urllib.parse import quote_plus

# =============================================================================
# Constants
# =============================================================================

DEFAULT_PORT = 6543  # Supabase Transaction Pooler
DIRECT_PORT = 5432  # Direct Postgres connection
REQUIRED_SSLMODE = "require"
DEFAULT_DATABASE = "postgres"

# Host patterns
SHARED_POOLER_PATTERN = re.compile(r"^(aws-[a-z0-9-]+)\.pooler\.supabase\.com$")
DEDICATED_HOST_PATTERN = re.compile(r"^db\.([a-z0-9]+)\.supabase\.co$")


# =============================================================================
# Core functions
# =============================================================================


def detect_pooler_mode(host: str) -> tuple[str, str | None]:
    """
    Detect pooler mode from hostname.

    Args:
        host: Hostname to analyze

    Returns:
        Tuple of (mode, extracted_ref)
        mode: "shared", "dedicated", or "unknown"
        extracted_ref: Project ref extracted from host (dedicated only)
    """
    if not host:
        return "unknown", None

    # Check shared pooler pattern
    shared_match = SHARED_POOLER_PATTERN.match(host)
    if shared_match:
        return "shared", None

    # Check dedicated/direct pattern
    dedicated_match = DEDICATED_HOST_PATTERN.match(host)
    if dedicated_match:
        return "dedicated", dedicated_match.group(1)

    return "unknown", None


def validate_host(host: str) -> tuple[bool, str]:
    """Validate that host looks like a Supabase pooler host.

    Args:
        host: Hostname to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not host:
        return False, "Host cannot be empty"

    # Remove any protocol prefix if accidentally included
    if host.startswith("postgresql://") or host.startswith("postgres://"):
        return False, "Host should not include protocol prefix (postgresql://)"

    mode, _ = detect_pooler_mode(host)

    if mode == "shared":
        return True, ""

    if mode == "dedicated":
        return True, ""

    # Allow other hosts but warn
    return True, f"Warning: '{host}' doesn't look like a Supabase pooler host"


def validate_password(password: str) -> tuple[bool, str]:
    """Validate password doesn't contain problematic characters.

    Args:
        password: Raw password to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not password:
        return False, "Password cannot be empty"

    if "\x00" in password:
        return False, "Password cannot contain null bytes"

    if "\n" in password or "\r" in password:
        return False, "Password cannot contain newlines"

    return True, ""


def build_dsn(
    host: str,
    user: str,
    password: str,
    database: str = DEFAULT_DATABASE,
    port: int = DEFAULT_PORT,
    sslmode: str = REQUIRED_SSLMODE,
    project_ref: str | None = None,
) -> str:
    """Build a PostgreSQL DSN with proper URL encoding and identity format.

    Args:
        host: Database host
        user: Base database user (e.g., dragonfly_app)
        password: Raw password (will be URL-encoded)
        database: Database name (default: postgres)
        port: Port number (default: 6543 for pooler)
        sslmode: SSL mode (forced to require)
        project_ref: Project reference for shared pooler username suffix

    Returns:
        Properly formatted DSN with URL-encoded password
    """
    # URL-encode the password to handle special characters
    encoded_password = quote_plus(password)

    # Force sslmode=require for security
    sslmode = REQUIRED_SSLMODE

    # Determine username format based on pooler mode
    mode, host_ref = detect_pooler_mode(host)

    if mode == "shared" and project_ref:
        # Shared pooler: username must be user.ref
        final_user = f"{user}.{project_ref}"
    else:
        # Dedicated/direct/unknown: plain username
        final_user = user

    return (
        f"postgresql://{final_user}:{encoded_password}@{host}:{port}/{database}?sslmode={sslmode}"
    )


def redact_password(dsn: str) -> str:
    """Redact password from DSN for safe logging.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        DSN with password replaced by ****
    """
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def get_encoding_hints(password: str) -> list[str]:
    """Get hints about which characters were URL-encoded.

    Args:
        password: Raw password

    Returns:
        List of encoding hints (e.g., "@ → %40")
    """
    hints = []
    char_map = {
        "@": "%40",
        "!": "%21",
        "#": "%23",
        "$": "%24",
        "%": "%25",
        "^": "%5E",
        "&": "%26",
        "*": "%2A",
        "(": "%28",
        ")": "%29",
        "+": "%2B",
        "=": "%3D",
        "/": "%2F",
        "?": "%3F",
        " ": "+",
    }

    for char, encoded in char_map.items():
        if char in password:
            hints.append(f"'{char}' → '{encoded}'")

    return hints


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Build a production-ready PostgreSQL DSN with URL encoding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
SUPABASE POOLER IDENTITY CONTRACT:

  SHARED POOLER (aws-*.pooler.supabase.com):
    - Username MUST be: <user>.<project_ref>
    - REQUIRES --project-ref flag
    
  DEDICATED POOLER (db.<ref>.supabase.co:6543):
    - Username is plain: <user>
    - Project ref extracted from host

Examples:
    # Shared pooler (requires --project-ref)
    python -m tools.build_pooler_dsn \\
        --host aws-0-us-east-1.pooler.supabase.com \\
        --user dragonfly_app \\
        --project-ref iaketsyhmqbwaabgykux \\
        --password 'MyP@ss!'

    # Dedicated pooler (ref from host)
    python -m tools.build_pooler_dsn \\
        --host db.iaketsyhmqbwaabgykux.supabase.co \\
        --user dragonfly_app \\
        --password 'MyP@ss!'

    # Read password from environment variable
    export DB_PASSWORD='MyP@ss!'
    python -m tools.build_pooler_dsn \\
        --host aws-0-us-east-1.pooler.supabase.com \\
        --user dragonfly_app \\
        --project-ref iaketsyhmqbwaabgykux \\
        --password-env DB_PASSWORD
""",
    )

    parser.add_argument(
        "--host",
        help="Pooler hostname (e.g., aws-0-us-east-1.pooler.supabase.com)",
    )
    parser.add_argument(
        "--user",
        default="dragonfly_app",
        help="Database user (default: dragonfly_app)",
    )
    parser.add_argument(
        "--project-ref",
        dest="project_ref",
        help="Supabase project reference (REQUIRED for shared pooler)",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Database name (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port number (default: {DEFAULT_PORT} pooler, use {DIRECT_PORT} for direct)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help=f"Use direct connection port ({DIRECT_PORT}) instead of pooler ({DEFAULT_PORT})",
    )
    parser.add_argument(
        "--password",
        help="Raw password (will be URL-encoded). Use --password-env for safer CI usage.",
    )
    parser.add_argument(
        "--password-env",
        metavar="VAR",
        help="Read password from this environment variable",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output the DSN (no formatting)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    # Get host
    host = args.host
    if not host:
        if args.quiet:
            print("ERROR: --host is required in quiet mode", file=sys.stderr)
            return 1
        print()
        print("=" * 60)
        print("  DRAGONFLY POOLER DSN BUILDER")
        print("=" * 60)
        print()
        print("Enter the Supabase Transaction Pooler hostname")
        print("(Find in: Supabase Dashboard > Settings > Database)")
        print()
        host = input("Host: ").strip()

    # Validate host
    is_valid, msg = validate_host(host)
    if not is_valid:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 1
    if msg and not args.quiet:
        print(f"  {msg}")

    # Detect pooler mode
    mode, host_ref = detect_pooler_mode(host)

    # Enforce project-ref for shared pooler
    project_ref = args.project_ref
    if mode == "shared" and not project_ref:
        if args.quiet:
            print(
                "ERROR: --project-ref is REQUIRED for shared pooler hosts",
                file=sys.stderr,
            )
            print(
                "  Shared pooler requires username format: <user>.<project_ref>",
                file=sys.stderr,
            )
            return 3
        print()
        print("⚠️  SHARED POOLER DETECTED")
        print("   Username must be in format: <user>.<project_ref>")
        print()
        project_ref = input("Project Reference: ").strip()
        if not project_ref:
            print("ERROR: Project reference is required for shared pooler", file=sys.stderr)
            return 3

    # Get user
    user = args.user
    if not user:
        user = input("User [dragonfly_app]: ").strip() or "dragonfly_app"

    # Get database
    database = args.database

    # Get port - --direct flag overrides --port
    port = DIRECT_PORT if args.direct else args.port

    # Get password
    password = None

    if args.password_env:
        password = os.environ.get(args.password_env)
        if not password:
            print(
                f"ERROR: Environment variable '{args.password_env}' is not set or empty",
                file=sys.stderr,
            )
            return 1
    elif args.password:
        password = args.password
    else:
        if args.quiet:
            print("ERROR: --password or --password-env is required in quiet mode", file=sys.stderr)
            return 1
        print()
        password = getpass.getpass("Password: ")
        password_confirm = getpass.getpass("Confirm password: ")
        if password != password_confirm:
            print("ERROR: Passwords do not match", file=sys.stderr)
            return 1

    # Validate password
    is_valid, msg = validate_password(password)
    if not is_valid:
        print(f"ERROR: {msg}", file=sys.stderr)
        return 2

    # Build DSN
    dsn = build_dsn(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        project_ref=project_ref,
    )

    redacted = redact_password(dsn)

    # Determine final username for display
    if mode == "shared" and project_ref:
        final_user = f"{user}.{project_ref}"
    else:
        final_user = user

    # Output
    if args.json:
        import json

        output = {
            "dsn": dsn,
            "dsn_redacted": redacted,
            "host": host,
            "port": port,
            "user": final_user,
            "user_base": user,
            "project_ref": project_ref or host_ref,
            "database": database,
            "sslmode": REQUIRED_SSLMODE,
            "pooler_mode": mode,
            "connection_type": "direct" if port == DIRECT_PORT else "pooler",
        }
        print(json.dumps(output, indent=2))
        return 0

    if args.quiet:
        print(dsn)
        return 0

    # Verbose output
    print()
    print("=" * 60)
    print("  DSN GENERATED SUCCESSFULLY")
    print("=" * 60)
    print()

    # Show pooler mode
    mode_display = {
        "shared": "SHARED (aws-*.pooler.supabase.com)",
        "dedicated": "DEDICATED (db.<ref>.supabase.co:6543)",
        "unknown": "UNKNOWN",
    }
    print(f"Pooler Mode: {mode_display.get(mode, mode)}")
    print(f"Project Ref: {project_ref or host_ref or '(none)'}")
    print(f"Username:    {final_user}")
    print()

    # Show encoding hints
    hints = get_encoding_hints(password)
    if hints:
        print("URL Encoding applied:")
        for hint in hints[:5]:
            print(f"  {hint}")
        if len(hints) > 5:
            print(f"  ... and {len(hints) - 5} more")
        print()

    print("DSN (copy to Railway DATABASE_URL):")
    print()
    print(f"  {dsn}")
    print()

    print("-" * 60)
    print()

    print("Verification command:")
    print()
    print(f'  python -m tools.probe_db "{redacted}"')
    print()

    print("psql command:")
    print()
    print(f'  psql "{dsn}"')
    print()

    print("=" * 60)
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
