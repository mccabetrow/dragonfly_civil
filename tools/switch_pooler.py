#!/usr/bin/env python3
"""
Switch Pooler DSN Constructor

Helps construct the correct Shared Transaction Pooler DSN for Supabase
when the dedicated pooler is experiencing connection timeouts.

Shared Pooler Format:
    Host: aws-0-{region}.pooler.supabase.com
    User: postgres.{project_ref}
    Port: 6543
    SSLMode: require

Usage:
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --region us-east-1
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --password-env SUPABASE_DB_PASSWORD

Exit Codes:
    0 = Success (DSN constructed and verified)
    1 = Connection failed
    2 = Configuration error
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from urllib.parse import quote_plus

import psycopg

# =============================================================================
# Constants
# =============================================================================

DEFAULT_REGION = "us-east-1"
DEFAULT_PORT = 6543
DEFAULT_DATABASE = "postgres"
DEFAULT_SSLMODE = "require"

# Shared pooler host template
SHARED_POOLER_HOST_TEMPLATE = "aws-0-{region}.pooler.supabase.com"

# Known project refs
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"
DEV_PROJECT_REF = "ejiddanxtqcleyswqvkc"

# Exit codes
EXIT_SUCCESS = 0
EXIT_CONNECTION_FAILED = 1
EXIT_CONFIG_ERROR = 2


# =============================================================================
# DSN Construction
# =============================================================================


def construct_shared_pooler_dsn(
    project_ref: str,
    password: str,
    region: str = DEFAULT_REGION,
    port: int = DEFAULT_PORT,
    database: str = DEFAULT_DATABASE,
    sslmode: str = DEFAULT_SSLMODE,
) -> str:
    """
    Construct a Shared Transaction Pooler DSN.

    Args:
        project_ref: Supabase project reference (e.g., iaketsyhmqbwaabgykux)
        password: Database password (will be URL-encoded)
        region: AWS region (default: us-east-1)
        port: Connection port (default: 6543)
        database: Database name (default: postgres)
        sslmode: SSL mode (default: require)

    Returns:
        Full PostgreSQL DSN string
    """
    # Construct shared pooler host
    host = SHARED_POOLER_HOST_TEMPLATE.format(region=region)

    # Construct shared pooler user: postgres.{ref}
    user = f"postgres.{project_ref}"

    # URL-encode the password
    encoded_password = quote_plus(password)

    # Build the DSN
    dsn = f"postgresql://{user}:{encoded_password}@{host}:{port}/{database}" f"?sslmode={sslmode}"

    return dsn


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    import re

    return re.sub(r"(://[^:]+:)[^@]+(@)", r"\1***REDACTED***\2", dsn)


# =============================================================================
# Connection Verification
# =============================================================================


def verify_connection(dsn: str, timeout: int = 10) -> tuple[bool, str]:
    """
    Verify the DSN works by attempting a connection.

    Args:
        dsn: PostgreSQL DSN
        timeout: Connection timeout in seconds

    Returns:
        (success: bool, message: str)
    """
    try:
        with psycopg.connect(
            dsn,
            connect_timeout=timeout,
            application_name="switch_pooler_verify",
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 as probe, current_database(), current_user")
                row = cur.fetchone()
                if row and row[0] == 1:
                    return True, f"Connected as {row[2]} to {row[1]}"
                return False, "Unexpected query result"
    except psycopg.OperationalError as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            return False, f"Connection timeout: {error_msg[:100]}"
        elif "authentication" in error_msg.lower():
            return False, f"Authentication failed: {error_msg[:100]}"
        else:
            return False, f"Connection error: {error_msg[:100]}"
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}: {str(e)[:100]}"


# =============================================================================
# CLI
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Construct and verify a Shared Transaction Pooler DSN",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Interactive password prompt
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux

    # Password from environment variable
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --password-env DB_PASSWORD

    # Explicit password (not recommended - visible in shell history)
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --password "secret"

    # Custom region
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --region eu-central-1

    # Skip verification
    python -m tools.switch_pooler --ref iaketsyhmqbwaabgykux --no-verify
""",
    )

    parser.add_argument(
        "--ref",
        required=True,
        help="Supabase project reference (e.g., iaketsyhmqbwaabgykux)",
    )

    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"AWS region for shared pooler (default: {DEFAULT_REGION})",
    )

    parser.add_argument(
        "--password",
        help="Database password (prefer --password-env for security)",
    )

    parser.add_argument(
        "--password-env",
        metavar="VAR",
        help="Environment variable containing the password",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Connection port (default: {DEFAULT_PORT})",
    )

    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Database name (default: {DEFAULT_DATABASE})",
    )

    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip connection verification",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Connection timeout in seconds (default: 10)",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Only output the DSN (for scripting)",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # =================================================================
    # Resolve password
    # =================================================================
    password: str | None = None

    if args.password:
        password = args.password
    elif args.password_env:
        password = os.environ.get(args.password_env)
        if not password:
            print(
                f"❌ Environment variable {args.password_env} is not set",
                file=sys.stderr,
            )
            return EXIT_CONFIG_ERROR
    else:
        # Interactive prompt
        if not args.quiet:
            print("Shared Pooler DSN Constructor")
            print(f"  Project Ref: {args.ref}")
            print(f"  Region:      {args.region}")
            print(f"  Host:        aws-0-{args.region}.pooler.supabase.com")
            print(f"  User:        postgres.{args.ref}")
            print()

        try:
            password = getpass.getpass("Database Password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return EXIT_CONFIG_ERROR

    if not password:
        print("❌ Password is required", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    # =================================================================
    # Construct DSN
    # =================================================================
    dsn = construct_shared_pooler_dsn(
        project_ref=args.ref,
        password=password,
        region=args.region,
        port=args.port,
        database=args.database,
    )

    if args.quiet:
        print(dsn)
        return EXIT_SUCCESS

    # =================================================================
    # Display results
    # =================================================================
    print()
    print("=" * 70)
    print("SHARED TRANSACTION POOLER DSN")
    print("=" * 70)
    print()
    print(f"Redacted: {redact_dsn(dsn)}")
    print()
    print("Full DSN (copy this):")
    print()
    print(dsn)
    print()

    # =================================================================
    # Verify connection
    # =================================================================
    if args.no_verify:
        print("⚠️  Skipping connection verification (--no-verify)")
        return EXIT_SUCCESS

    print("=" * 70)
    print("VERIFYING CONNECTION")
    print("=" * 70)
    print()
    print(f"Connecting with {args.timeout}s timeout...")

    success, message = verify_connection(dsn, timeout=args.timeout)

    if success:
        print(f"✅ {message}")
        print()
        print("SUCCESS: DSN is valid and connection works!")
        print()
        print("Next steps:")
        print("  1. Update your .env file with DATABASE_URL=<dsn>")
        print("  2. Run: python -m tools.probe_db --env prod")
        return EXIT_SUCCESS
    else:
        print(f"❌ {message}")
        print()
        print("FAILED: Connection could not be established.")
        print()
        print("Troubleshooting:")
        print("  1. Verify password is correct")
        print("  2. Run: python -m tools.check_network")
        print("  3. Check Supabase status: https://status.supabase.com/")
        return EXIT_CONNECTION_FAILED


if __name__ == "__main__":
    sys.exit(main())
