#!/usr/bin/env python3
"""
Dragonfly Civil - Direct Database URL Formatter
═══════════════════════════════════════════════════════════════════════════

Generates the CORRECT direct connection string for Supabase.

CRITICAL RULES for Direct Connection (Port 5432):
  - Host: db.{PROJECT_REF}.supabase.co
  - Port: 5432 (NOT 6543)
  - User: dragonfly_app (NO suffix like .iaketsyhmqbwaabgykux)
  - SSL: sslmode=require

The Pooler (Port 6543) requires a different username format which is
currently failing with "Tenant or user not found". Use direct until resolved.

Usage:
    python -m tools.format_direct_db_url
    python -m tools.format_direct_db_url --password "mypassword"
    python -m tools.format_direct_db_url --password "mypassword" --user postgres
"""

from __future__ import annotations

import argparse
import getpass
import sys
from urllib.parse import quote_plus

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION - Supabase Prod Project
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_REF = "iaketsyhmqbwaabgykux"
DATABASE = "postgres"

# Direct connection host (Port 5432)
DIRECT_HOST = f"db.{PROJECT_REF}.supabase.co"
DIRECT_PORT = 5432

# Pooler host (Port 6543) - NOT WORKING, documented for reference
POOLER_HOST = "aws-0-us-east-1.pooler.supabase.com"
POOLER_PORT = 6543


def format_direct_url(user: str, password: str) -> str:
    """
    Format a direct connection URL (Port 5432).

    IMPORTANT: Username has NO suffix for direct connections.
    """
    # URL-encode the password in case it has special characters
    encoded_password = quote_plus(password)

    return (
        f"postgresql://{user}:{encoded_password}"
        f"@{DIRECT_HOST}:{DIRECT_PORT}/{DATABASE}"
        f"?sslmode=require"
    )


def format_pooler_url(user: str, password: str) -> str:
    """
    Format a pooler connection URL (Port 6543).

    IMPORTANT: Username MUST have .PROJECT_REF suffix for pooler.
    Currently NOT WORKING - "Tenant or user not found" error.
    """
    # URL-encode the password in case it has special characters
    encoded_password = quote_plus(password)

    # Pooler requires username.project_ref format
    pooler_user = f"{user}.{PROJECT_REF}"

    return (
        f"postgresql://{pooler_user}:{encoded_password}"
        f"@{POOLER_HOST}:{POOLER_PORT}/{DATABASE}"
        f"?sslmode=require"
    )


def mask_password(url: str, password: str) -> str:
    """Mask the password in a URL for safe display."""
    return url.replace(password, "***")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Supabase direct connection URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.format_direct_db_url
  python -m tools.format_direct_db_url --password "mypass"
  python -m tools.format_direct_db_url --user postgres --password "mypass"
        """,
    )
    parser.add_argument(
        "--user", "-u", default="dragonfly_app", help="Database user (default: dragonfly_app)"
    )
    parser.add_argument("--password", "-p", help="Database password (will prompt if not provided)")
    parser.add_argument(
        "--show-pooler", action="store_true", help="Also show pooler URL format (currently broken)"
    )

    args = parser.parse_args()

    # Get password
    password = args.password
    if not password:
        password = getpass.getpass("Enter database password: ")

    if not password:
        print("❌ Password is required.", file=sys.stderr)
        return 1

    # Generate URLs
    direct_url = format_direct_url(args.user, password)

    print()
    print("=" * 70)
    print(" DIRECT CONNECTION STRING (Port 5432) - USE THIS")
    print("=" * 70)
    print()
    print(f"User: {args.user}")
    print(f"Host: {DIRECT_HOST}")
    print(f"Port: {DIRECT_PORT}")
    print()
    print("[FULL URL - Copy this to Railway SUPABASE_DB_URL]")
    print()
    print(direct_url)
    print()

    if args.show_pooler:
        pooler_url = format_pooler_url(args.user, password)
        print("-" * 70)
        print(" POOLER CONNECTION (Port 6543) - CURRENTLY BROKEN")
        print("-" * 70)
        print()
        print(f"User: {args.user}.{PROJECT_REF}")
        print(f"Host: {POOLER_HOST}")
        print(f"Port: {POOLER_PORT}")
        print()
        print("[URL - NOT WORKING: 'Tenant or user not found']")
        print()
        print(pooler_url)
        print()

    print("=" * 70)
    print(" VERIFICATION")
    print("=" * 70)
    print()
    print("Test this URL locally before deploying:")
    print()
    print(f'  python -m tools.verify_db_auth "{direct_url}"')
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
