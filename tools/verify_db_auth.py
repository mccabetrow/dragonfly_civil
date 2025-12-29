#!/usr/bin/env python3
"""
Dragonfly Civil - Database Authentication Verifier
═══════════════════════════════════════════════════════════════════════════

Tests a PostgreSQL connection string to verify credentials work.

Usage:
    python -m tools.verify_db_auth "postgresql://user:pass@host:port/db"
    python -m tools.verify_db_auth  # prompts for URL or uses env var

Examples:
    python -m tools.verify_db_auth "postgresql://dragonfly_app:xxx@db.xxx.supabase.co:5432/postgres"
    python -m tools.verify_db_auth  # uses SUPABASE_DB_URL from environment
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

# Try psycopg (v3) first, fall back to psycopg2
try:
    import psycopg

    DRIVER = "psycopg3"
except ImportError:
    try:
        import psycopg2 as psycopg  # type: ignore[import]

        DRIVER = "psycopg2"
    except ImportError:
        psycopg = None  # type: ignore[assignment]
        DRIVER = None


def mask_password(url: str) -> str:
    """Mask the password in a connection URL for safe logging."""
    try:
        parsed = urlparse(url)
        if parsed.password:
            masked = url.replace(f":{parsed.password}@", ":***@")
            return masked
    except Exception:
        pass
    return url[:50] + "..." if len(url) > 50 else url


def verify_connection(db_url: str) -> tuple[bool, str]:
    """
    Attempt to connect to the database and run a simple query.

    Returns:
        (success: bool, message: str)
    """
    if psycopg is None:
        return False, "❌ No PostgreSQL driver installed. Run: pip install psycopg[binary]"

    try:
        # Connect with a short timeout
        if DRIVER == "psycopg3":
            conn = psycopg.connect(db_url, connect_timeout=10)
        else:
            conn = psycopg.connect(db_url, connect_timeout=10)

        # Run a simple query
        cursor = conn.cursor()
        cursor.execute("SELECT current_user, current_database(), version();")
        row = cursor.fetchone()

        if row:
            user, database, version = row
            # Extract just the PostgreSQL version
            pg_version = version.split(",")[0] if version else "unknown"

            cursor.close()
            conn.close()

            return True, (
                f"✅ Auth Success!\n"
                f"   User: {user}\n"
                f"   Database: {database}\n"
                f"   Version: {pg_version}"
            )
        else:
            cursor.close()
            conn.close()
            return True, "✅ Auth Success (no version info)"

    except Exception as e:
        error_msg = str(e)

        # Provide helpful hints based on error type
        if "password authentication failed" in error_msg.lower():
            hint = "\n   → Password mismatch. Run: .\\scripts\\generate_db_strings.ps1"
        elif "role" in error_msg.lower() and "does not exist" in error_msg.lower():
            hint = "\n   → Role doesn't exist. Create it in Supabase SQL Editor."
        elif "connection refused" in error_msg.lower():
            hint = "\n   → Check hostname and port. Is the database running?"
        elif "timeout" in error_msg.lower():
            hint = "\n   → Connection timed out. Check network/firewall."
        elif "ssl" in error_msg.lower():
            hint = "\n   → SSL issue. Try adding ?sslmode=require to the URL."
        else:
            hint = ""

        return False, f"❌ Auth Failed: {error_msg}{hint}"


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Verify PostgreSQL database authentication",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.verify_db_auth "postgresql://user:pass@host:5432/db"
  python -m tools.verify_db_auth  # uses SUPABASE_DB_URL env var
        """,
    )
    parser.add_argument(
        "db_url", nargs="?", help="PostgreSQL connection URL (or uses SUPABASE_DB_URL env var)"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Minimal output (just success/failure)"
    )

    args = parser.parse_args()

    # Get the database URL
    db_url = args.db_url

    if not db_url:
        # Try environment variable
        db_url = os.environ.get("SUPABASE_DB_URL")

        if not db_url:
            # Prompt the user
            print("Enter PostgreSQL connection URL:")
            db_url = input("> ").strip()

    if not db_url:
        print("❌ No database URL provided.", file=sys.stderr)
        print("   Usage: python -m tools.verify_db_auth <db_url>", file=sys.stderr)
        return 1

    # Validate URL format
    if not db_url.startswith(("postgresql://", "postgres://")):
        print(
            "❌ Invalid URL format. Must start with postgresql:// or postgres://", file=sys.stderr
        )
        return 1

    # Show what we're testing (masked)
    if not args.quiet:
        print(f"\n🔍 Testing: {mask_password(db_url)}")
        print(f"   Driver: {DRIVER or 'none'}")
        print()

    # Verify the connection
    success, message = verify_connection(db_url)

    print(message)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
