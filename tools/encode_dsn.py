#!/usr/bin/env python3
"""
tools/encode_dsn.py
===================
DSN Encoder Tool for Railway Deployment

Generates properly URL-encoded PostgreSQL DSN strings for Railway environment
variables. Handles special characters in passwords correctly.

PRODUCTION DEFAULTS:
    - Project: iaketsyhmqbwaabgykux (Dragonfly PROD)
    - Role: dragonfly_app
    - Port: 6543 (Transaction Pooler - REQUIRED for prod)
    - SSL: require

Usage:
    python -m tools.encode_dsn

    # Or with arguments
    python -m tools.encode_dsn --project prod --role dragonfly_app

Output:
    The verified Transaction Pooler DSN ready for Railway:
    postgresql://dragonfly_app:encoded_password@db.iaketsyhmqbwaabgykux.supabase.co:6543/postgres?sslmode=require

Author: Principal Site Reliability Engineer
Date: 2026-01-15
"""

from __future__ import annotations

import argparse
import getpass
import sys
from urllib.parse import quote, urlparse

# =============================================================================
# Canonical Project References
# =============================================================================

PROJECTS = {
    "prod": "iaketsyhmqbwaabgykux",
    "dev": "ejiddanxtqcleyswqvkc",
}

# Default values for production deployment
DEFAULT_PROJECT = "prod"
DEFAULT_ROLE = "dragonfly_app"
DEFAULT_DATABASE = "postgres"

# Transaction Pooler port (REQUIRED for production)
TRANSACTION_POOLER_PORT = 6543


# =============================================================================
# DSN Building
# =============================================================================


def encode_password(password: str) -> str:
    """
    URL-encode password for safe inclusion in DSN.

    Handles special characters that would break URL parsing:
    - @ # $ % & + = / ? : ; [ ] { } | \\ ^ ~ ` < >
    """
    # safe='' means encode everything that needs encoding
    return quote(password, safe="")


def build_transaction_pooler_dsn(
    project_ref: str,
    role: str,
    password: str,
    database: str = "postgres",
) -> str:
    """
    Build a verified Transaction Pooler DSN.

    Format: postgresql://{role}:{enc_pw}@db.{ref}.supabase.co:6543/postgres?sslmode=require

    Args:
        project_ref: Supabase project reference (e.g., iaketsyhmqbwaabgykux)
        role: Database role (e.g., dragonfly_app)
        password: Raw password (will be URL-encoded)
        database: Database name (default: postgres)

    Returns:
        Complete DSN string ready for Railway
    """
    encoded_password = encode_password(password)

    return (
        f"postgresql://{role}:{encoded_password}"
        f"@db.{project_ref}.supabase.co:{TRANSACTION_POOLER_PORT}"
        f"/{database}?sslmode=require"
    )


def verify_dsn(dsn: str) -> dict:
    """
    Parse and verify DSN components.

    Returns dict with parsed components for verification display.
    """
    parsed = urlparse(dsn)
    return {
        "scheme": parsed.scheme,
        "username": parsed.username,
        "host": parsed.hostname,
        "port": parsed.port,
        "database": parsed.path.lstrip("/"),
        "sslmode": "require" if "sslmode=require" in dsn else "unknown",
    }


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe display."""
    import re

    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


# =============================================================================
# CLI
# =============================================================================


def main() -> int:
    """CLI entrypoint for DSN encoding."""
    parser = argparse.ArgumentParser(
        description="Generate URL-encoded PostgreSQL DSN for Railway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Interactive mode (prompts for password)
    python -m tools.encode_dsn
    
    # Specify project and role
    python -m tools.encode_dsn --project prod --role dragonfly_app
    
    # Dev environment
    python -m tools.encode_dsn --project dev
        """,
    )

    parser.add_argument(
        "--project",
        choices=list(PROJECTS.keys()),
        default=DEFAULT_PROJECT,
        help=f"Project environment (default: {DEFAULT_PROJECT})",
    )

    parser.add_argument(
        "--role",
        default=DEFAULT_ROLE,
        help=f"Database role (default: {DEFAULT_ROLE})",
    )

    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Database name (default: {DEFAULT_DATABASE})",
    )

    parser.add_argument(
        "--password",
        help="Password (if not provided, will prompt securely)",
    )

    args = parser.parse_args()

    # Get project reference
    project_ref = PROJECTS.get(args.project)
    if not project_ref:
        print(f"ERROR: Unknown project '{args.project}'")
        return 1

    # Display header
    print()
    print("=" * 60)
    print("  DRAGONFLY DSN ENCODER")
    print("  Transaction Pooler DSN Generator for Railway")
    print("=" * 60)
    print()
    print(f"Project:  {args.project.upper()} ({project_ref})")
    print(f"Role:     {args.role}")
    print(f"Database: {args.database}")
    print(f"Port:     {TRANSACTION_POOLER_PORT} (Transaction Pooler)")
    print("SSL:      require")
    print()

    # Get password
    if args.password:
        password = args.password
    else:
        try:
            password = getpass.getpass("Enter password: ")
        except EOFError:
            print("ERROR: No password provided")
            return 1

    if not password:
        print("ERROR: Password cannot be empty")
        return 1

    # Build DSN
    dsn = build_transaction_pooler_dsn(
        project_ref=project_ref,
        role=args.role,
        password=password,
        database=args.database,
    )

    # Verify DSN
    verified = verify_dsn(dsn)

    print()
    print("-" * 60)
    print("VERIFIED DSN COMPONENTS:")
    print("-" * 60)
    for key, value in verified.items():
        print(f"  {key:12}: {value}")
    print()

    # Output DSN
    print("-" * 60)
    print("RAILWAY DATABASE_URL:")
    print("-" * 60)
    print()
    print(dsn)
    print()

    # Safety reminder
    print("-" * 60)
    print("SAFETY NOTES:")
    print("-" * 60)
    print("  1. Copy this DSN to Railway's DATABASE_URL variable")
    print("  2. Do NOT commit this value to git")
    print("  3. The password has been URL-encoded for special characters")
    print()
    print(f"  Redacted preview: {redact_dsn(dsn)}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
