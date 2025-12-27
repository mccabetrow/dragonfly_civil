#!/usr/bin/env python3
"""
Dragonfly Engine - Worker Config Validator

Run this script inside the worker container (during startup or manually)
to verify the worker can connect to the database.

Usage:
    python -m tools.check_worker_config

Exit Codes:
    0: All checks passed
    1: Connection failed (FATAL)

Environment Required:
    SUPABASE_DB_URL - Database connection string (pooler, port 6543)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def mask_url(url: str) -> str:
    """Mask password in connection string for safe logging."""
    # Pattern: postgresql://user:password@host:port/db
    return re.sub(
        r"(://[^:]+:)([^@]+)(@)",
        r"\1***@",
        url,
    )


def check_db_connection() -> bool:
    """
    Verify database connectivity.

    Returns:
        True if connection successful, False otherwise.
    """
    print("=" * 60)
    print("Dragonfly Worker Config Validator")
    print("=" * 60)
    print()

    # Step 1: Check environment variable
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("SUPABASE_MIGRATE_DB_URL")

    if not db_url:
        print("❌ FATAL: SUPABASE_DB_URL not set")
        print()
        print("The worker requires SUPABASE_DB_URL to connect to the database.")
        print("Set this environment variable in your Railway/Docker configuration.")
        return False

    print(f"✓ SUPABASE_DB_URL: {mask_url(db_url)}")

    # Step 2: Parse and validate URL format
    if "supabase.co" not in db_url and "localhost" not in db_url:
        print("⚠ Warning: URL doesn't appear to be a Supabase connection")

    # Check for pooler port (6543) vs direct port (5432)
    if ":6543" in db_url:
        print("✓ Using Supabase Pooler (port 6543) - recommended")
    elif ":5432" in db_url:
        print("⚠ Using Direct Connection (port 5432) - OK for migrations, not ideal for workers")
    else:
        print("⚠ Non-standard port detected")

    print()

    # Step 3: Attempt connection
    print("Attempting database connection...")

    try:
        import psycopg
    except ImportError:
        print("❌ FATAL: psycopg library not installed")
        print("Run: pip install psycopg[binary]")
        return False

    try:
        conn = psycopg.connect(db_url, connect_timeout=10)

        # Step 4: Run test query
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS test, current_database() AS db, current_user AS user")
            row = cur.fetchone()

            if row and row[0] == 1:
                print(f"✓ Connected to database: {row[1]}")
                print(f"✓ Connected as user: {row[2]}")
            else:
                print("⚠ Query returned unexpected result")

        # Step 5: Verify required tables exist
        print()
        print("Verifying required tables...")

        required_tables = [
            ("ops", "job_queue"),
            ("ops", "worker_heartbeats"),
            ("intake", "simplicity_batches"),
        ]

        with conn.cursor() as cur:
            for schema, table in required_tables:
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = %s AND table_name = %s
                    )
                    """,
                    (schema, table),
                )
                exists = cur.fetchone()[0]
                status = "✓" if exists else "✗"
                print(f"  {status} {schema}.{table}")

        conn.close()

        print()
        print("=" * 60)
        print("✅ Worker DB Connection OK")
        print("=" * 60)
        return True

    except psycopg.OperationalError as e:
        print()
        print("❌ FATAL: Worker cannot connect to DB")
        print()
        print(f"Error: {e}")
        print()

        # Provide helpful diagnostics
        error_str = str(e).lower()

        if "circuit breaker" in error_str:
            print("Diagnosis: Supabase connection pooler is rate-limiting.")
            print("  - Wait a few seconds and retry")
            print("  - Check if too many connections are open")
            print("  - Verify project is not paused (free tier)")

        elif "authentication failed" in error_str or "password" in error_str:
            print("Diagnosis: Authentication failure.")
            print("  - Verify password in SUPABASE_DB_URL is correct")
            print("  - Check if database password was recently changed")

        elif "could not connect" in error_str or "connection refused" in error_str:
            print("Diagnosis: Network connectivity issue.")
            print("  - Verify host/port in SUPABASE_DB_URL")
            print("  - Check if Supabase project is active")
            print("  - Verify network/firewall allows outbound 6543")

        elif "timeout" in error_str:
            print("Diagnosis: Connection timeout.")
            print("  - Network may be slow or blocked")
            print("  - Supabase may be temporarily unavailable")

        return False

    except Exception as e:
        print()
        print("❌ FATAL: Unexpected error")
        print(f"Error: {type(e).__name__}: {e}")
        return False


def main() -> int:
    """Entry point."""
    success = check_db_connection()
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
