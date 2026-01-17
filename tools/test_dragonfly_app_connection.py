#!/usr/bin/env python3
"""
test_dragonfly_app_connection.py - Test the dragonfly_app database connection.

Run this AFTER:
1. Applying the migration (./scripts/db_push.ps1 -SupabaseEnv prod)
2. Setting the password in Supabase SQL Editor:
   ALTER ROLE dragonfly_app WITH PASSWORD 'your-password';

Usage:
    python tools/test_dragonfly_app_connection.py
"""

from __future__ import annotations

import sys
from urllib.parse import quote_plus

# Configure these for your environment
POOLER_HOST = "aws-0-us-east-1.pooler.supabase.com"
PASSWORD = "billiondollarsystem!!"
USER = "dragonfly_app"
PORT = 6543
DATABASE = "postgres"


def main() -> int:
    """Test the dragonfly_app connection."""

    # URL-encode the password
    encoded_password = quote_plus(PASSWORD)

    dsn = f"postgresql://{USER}:{encoded_password}@{POOLER_HOST}:{PORT}/{DATABASE}?sslmode=require"

    print()
    print("=" * 60)
    print("  DRAGONFLY_APP CONNECTION TEST")
    print("=" * 60)
    print()
    print(f"Host:     {POOLER_HOST}")
    print(f"Port:     {PORT}")
    print(f"User:     {USER}")
    print(f"Database: {DATABASE}")
    print("SSL:      require")
    print()
    print("Attempting connection...")
    print()

    try:
        import psycopg
    except ImportError:
        print("❌ psycopg not installed. Installing...")
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "psycopg[binary]", "-q"])
        import psycopg

    try:
        with psycopg.connect(dsn, connect_timeout=10) as conn:
            # Test 1: Basic connectivity
            result = conn.execute("SELECT current_user, current_database(), version()").fetchone()
            print("✅ CONNECTION SUCCESSFUL!")
            print()
            print(f"   Current user:     {result[0]}")
            print(f"   Current database: {result[1]}")
            print(f"   PostgreSQL:       {result[2][:50]}...")
            print()

            # Test 2: Check schema access
            print("Checking schema access...")
            schemas = conn.execute(
                """
                SELECT nspname, has_schema_privilege(%s, nspname, 'USAGE') as has_usage
                FROM pg_namespace
                WHERE nspname IN ('public', 'ingest', 'intake', 'judgments', 'audit', 'ops')
                ORDER BY nspname
            """,
                [USER],
            ).fetchall()

            for schema, has_usage in schemas:
                status = "✅" if has_usage else "❌"
                expected = "❌" if schema == "ops" else "✅"
                match = (
                    "OK"
                    if (has_usage and schema != "ops") or (not has_usage and schema == "ops")
                    else "UNEXPECTED"
                )
                print(f"   {schema}: {status} ({match})")

            print()

            # Test 3: Check table access (sample)
            print("Checking table access (public.plaintiffs)...")
            try:
                count = conn.execute("SELECT COUNT(*) FROM public.plaintiffs").fetchone()[0]
                print(f"   ✅ Can read plaintiffs table ({count} rows)")
            except Exception as e:
                print(f"   ❌ Cannot read plaintiffs: {e}")

            print()
            print("=" * 60)
            print("  CONNECTION TEST PASSED")
            print("=" * 60)
            print()
            print("DSN for Railway (copy this to DATABASE_URL):")
            print(f"  {dsn}")
            print()

            return 0

    except Exception as e:
        print(f"❌ CONNECTION FAILED: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Did you apply the migration? (./scripts/db_push.ps1 -SupabaseEnv prod)")
        print("  2. Did you set the password in Supabase SQL Editor?")
        print("     ALTER ROLE dragonfly_app WITH PASSWORD 'your-password';")
        print("  3. Is the pooler hostname correct? Check Supabase Dashboard.")
        print("  4. Is the password correct?")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
