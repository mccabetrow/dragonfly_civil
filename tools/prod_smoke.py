#!/usr/bin/env python3
"""
Dragonfly Civil – Production Smoke Test

Post-deployment validation that verifies:
1. Railway API health endpoint returns 200
2. Postgres connectivity via SUPABASE_DB_URL (with SUPABASE_MODE=prod)
3. Critical views are queryable:
   - enforcement.v_enforcement_pipeline_status
   - finance.v_portfolio_stats

Usage:
    # Ensure env vars are set (use canonical names)
    export SUPABASE_MODE=prod
    export SUPABASE_DB_URL=postgres://...

    # Run smoke test
    python -m tools.prod_smoke

    # Show help (works without env vars)
    python -m tools.prod_smoke --help

Exit codes:
    0 - All checks passed
    1 - One or more checks failed (CI should fail)
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

import httpx
import psycopg2

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

RAILWAY_HEALTH_URL = "https://dragonflycivil-production-d57a.up.railway.app/api/health"
DB_TIMEOUT_SECONDS = 15
HTTP_TIMEOUT_SECONDS = 30


# ─────────────────────────────────────────────────────────────────────────────
# Check functions
# ─────────────────────────────────────────────────────────────────────────────


def check_railway_health() -> tuple[bool, str]:
    """
    Hit the Railway API health endpoint and assert HTTP 200.

    Returns:
        (success, message)
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            resp = client.get(RAILWAY_HEALTH_URL)
            if resp.status_code == 200:
                data = resp.json()
                env = data.get("environment", "unknown")
                return True, f"HTTP 200 – environment={env}"
            else:
                return False, f"HTTP {resp.status_code} – expected 200"
    except httpx.ConnectError as e:
        return False, f"Connection failed: {e}"
    except httpx.TimeoutException:
        return False, f"Timeout after {HTTP_TIMEOUT_SECONDS}s"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def check_postgres_connection(dsn: str) -> tuple[bool, str]:
    """
    Verify we can connect to Postgres.

    Returns:
        (success, message)
    """
    try:
        conn = psycopg2.connect(dsn, connect_timeout=DB_TIMEOUT_SECONDS)
        conn.close()
        return True, "Connection established"
    except psycopg2.OperationalError as e:
        return False, f"OperationalError: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


def check_view_query(dsn: str, view_name: str) -> tuple[bool, str]:
    """
    Run SELECT COUNT(*) against a view and verify we get a row back.

    Returns:
        (success, message)
    """
    query = f"SELECT COUNT(*) FROM {view_name};"
    try:
        conn = psycopg2.connect(dsn, connect_timeout=DB_TIMEOUT_SECONDS)
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
                if row is None:
                    return False, "Query returned no rows"
                count = row[0]
                return True, f"row_count={count}"
        finally:
            conn.close()
    except psycopg2.errors.UndefinedTable:
        return False, f"View does not exist: {view_name}"
    except psycopg2.Error as e:
        return False, f"Query error: {e}"
    except Exception as e:
        return False, f"Unexpected error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    """Run all smoke checks. Returns 0 on success, 1 on failure."""
    print("=" * 60)
    print("🔥 Dragonfly Civil – Production Smoke Test")
    print(f"   Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    # Collect DSN using canonical SUPABASE_DB_URL
    dsn = os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        print("❌ SUPABASE_DB_URL is not set")
        print("   Set SUPABASE_DB_URL and SUPABASE_MODE=prod for production smoke tests.")
        return 1

    results: list[tuple[str, bool, str]] = []

    # ── Check 1: Railway Health ──────────────────────────────────────────────
    print("1️⃣  Railway API health check")
    print(f"    URL: {RAILWAY_HEALTH_URL}")
    ok, msg = check_railway_health()
    results.append(("Railway /api/health", ok, msg))
    icon = "✅" if ok else "❌"
    print(f"    {icon} {msg}")
    print()

    # ── Check 2: Postgres connection ─────────────────────────────────────────
    print("2️⃣  Postgres connection check")
    # Mask DSN in output for security
    dsn_masked = dsn[:20] + "..." if len(dsn) > 20 else dsn
    print(f"    DSN: {dsn_masked}")
    ok, msg = check_postgres_connection(dsn)
    results.append(("Postgres connection", ok, msg))
    icon = "✅" if ok else "❌"
    print(f"    {icon} {msg}")
    print()

    # ── Check 3: enforcement.v_enforcement_pipeline_status ───────────────────
    view1 = "enforcement.v_enforcement_pipeline_status"
    print(f"3️⃣  Query view: {view1}")
    ok, msg = check_view_query(dsn, view1)
    results.append((view1, ok, msg))
    icon = "✅" if ok else "❌"
    print(f"    {icon} {msg}")
    print()

    # ── Check 4: finance.v_portfolio_stats ───────────────────────────────────
    view2 = "finance.v_portfolio_stats"
    print(f"4️⃣  Query view: {view2}")
    ok, msg = check_view_query(dsn, view2)
    results.append((view2, ok, msg))
    icon = "✅" if ok else "❌"
    print(f"    {icon} {msg}")
    print()

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    total = len(results)

    if failed == 0:
        print(f"✅ ALL {passed}/{total} CHECKS PASSED")
        print("=" * 60)
        return 0
    else:
        print(f"❌ {failed}/{total} CHECKS FAILED")
        print()
        print("Failed checks:")
        for name, ok, msg in results:
            if not ok:
                print(f"   • {name}: {msg}")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="prod_smoke",
        description="Dragonfly Civil – Production Smoke Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Verifies post-deployment:
  1. Railway API health endpoint returns 200
  2. Postgres connectivity via SUPABASE_DB_URL
  3. Critical views are queryable

Examples:
  python -m tools.prod_smoke           # Run all smoke checks
  python -m tools.prod_smoke --help    # Show this help
""",
    )
    # Parse args first (allows --help to work without env vars)
    parser.parse_args()
    sys.exit(main())
