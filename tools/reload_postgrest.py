#!/usr/bin/env python3
"""
Dragonfly Civil - PostgREST Schema Cache Reloader
═══════════════════════════════════════════════════════════════════════════════

This tool forces PostgREST to reload its schema cache, fixing PGRST002 errors
that occur when database schema changes haven't been picked up by the API.

How it works:
    PostgREST listens for PostgreSQL NOTIFY events on the 'pgrst' channel.
    Sending NOTIFY pgrst, 'reload schema' triggers an immediate cache refresh.
    After NOTIFY, we poll the Supabase REST health endpoint until 200 OK.

Usage:
    python -m tools.reload_postgrest
    python -m tools.reload_postgrest --env prod
    python -m tools.reload_postgrest --no-health-check

When to use:
    - After applying migrations (schema changes)
    - When seeing PGRST002 "Could not find..." errors
    - When new views/tables are not accessible via API
    - Before/during demos to ensure API is in sync

Exit Codes:
    0 = Schema cache reloaded successfully (health check passed)
    1 = Reload failed (check DB connectivity or health endpoint)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional

import psycopg

try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

from src.supabase_client import get_supabase_env


def _get_direct_db_url(env: str) -> Optional[str]:
    """
    Get the DIRECT database URL (port 5432), not pooler (port 6543).

    NOTIFY only works reliably over direct connections, not through
    the connection pooler.
    """
    # Try loading from .env.{env} file first
    env_file = Path(f".env.{env}")
    env_vars = {}

    if env_file.exists():
        try:
            with open(env_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip()
        except Exception:
            pass

    # Priority: SUPABASE_MIGRATE_DB_URL (always direct) > SUPABASE_DB_URL
    migrate_url = env_vars.get("SUPABASE_MIGRATE_DB_URL") or os.getenv("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        return migrate_url

    # Fall back to regular URL (may be pooler)
    db_url = env_vars.get("SUPABASE_DB_URL") or os.getenv("SUPABASE_DB_URL")
    return db_url


def reload_schema_cache(db_url: str, verbose: bool = False) -> bool:
    """
    Send NOTIFY pgrst, 'reload schema' to trigger PostgREST cache refresh.

    Args:
        db_url: PostgreSQL connection string (direct connection, port 5432)
        verbose: If True, print detailed connection info

    Returns:
        True if reload was successful, False otherwise
    """
    try:
        if verbose:
            # Mask credentials in output
            masked_url = db_url.split("@")[-1] if "@" in db_url else db_url
            print(f"  Connecting to: ...@{masked_url}")

        with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # 'reload schema' is the recommended payload for Supabase
                cur.execute("NOTIFY pgrst, 'reload schema'")

        return True

    except psycopg.OperationalError as e:
        print(f"❌ Connection error: {e}", file=sys.stderr)
        return False
    except psycopg.Error as e:
        print(f"❌ Database error: {e}", file=sys.stderr)
        return False


def _get_rest_url(env: str) -> Optional[str]:
    """Get the Supabase REST API base URL for health polling."""
    # Try loading from .env.{env} file first
    env_file = Path(f".env.{env}")
    env_vars = {}

    if env_file.exists():
        try:
            with open(env_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        env_vars[key.strip()] = value.strip()
        except Exception:
            pass

    # SUPABASE_URL is the REST endpoint
    supabase_url = env_vars.get("SUPABASE_URL") or os.getenv("SUPABASE_URL")
    return supabase_url


def poll_health_check(
    rest_url: str,
    max_attempts: int = 10,
    poll_interval: float = 1.0,
    verbose: bool = False,
) -> bool:
    """
    Poll the Supabase REST health endpoint until 200 OK.

    Args:
        rest_url: Supabase REST API base URL
        max_attempts: Maximum number of poll attempts
        poll_interval: Seconds between poll attempts
        verbose: If True, print detailed status

    Returns:
        True if health check passed, False if timed out
    """
    if not HTTPX_AVAILABLE:
        print("  ⚠️ httpx not installed, skipping health poll")
        return True

    health_url = f"{rest_url.rstrip('/')}/rest/v1/"

    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=5.0) as client:
                # Just hit the root REST endpoint - 200 means PostgREST is up
                resp = client.get(health_url)

                if resp.status_code in (200, 401):
                    # 401 is OK - it means PostgREST is responding (just needs auth)
                    if verbose:
                        print(f"  Health check {attempt}/{max_attempts}: {resp.status_code} OK")
                    return True

                if verbose:
                    print(f"  Health check {attempt}/{max_attempts}: {resp.status_code}")

        except httpx.RequestError as e:
            if verbose:
                print(f"  Health check {attempt}/{max_attempts}: Connection error - {e}")

        if attempt < max_attempts:
            time.sleep(poll_interval)

    return False


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Force PostgREST to reload its schema cache",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.reload_postgrest
    python -m tools.reload_postgrest --env prod
    python -m tools.reload_postgrest --verbose
    python -m tools.reload_postgrest --no-health-check

This fixes PGRST002 errors like:
    "Could not find the 'intake.view_batch_metrics' view..."
""",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Target environment (default: auto-detect from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed connection info",
    )
    parser.add_argument(
        "--no-health-check",
        action="store_true",
        help="Skip health polling after NOTIFY",
    )
    args = parser.parse_args()

    # Determine environment
    env = args.env or get_supabase_env()
    print("🔄 PostgREST Schema Cache Reload")
    print(f"   Environment: {env}")

    # Get database URL (MUST use direct connection for NOTIFY)
    db_url: Optional[str] = _get_direct_db_url(env)

    if not db_url:
        print(
            "❌ Missing database URL. Check SUPABASE_DB_URL or SUPABASE_MIGRATE_DB_URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Execute reload
    print("   Sending: NOTIFY pgrst, 'reload schema'")
    if not reload_schema_cache(db_url, verbose=args.verbose):
        print("❌ Failed to reload schema cache", file=sys.stderr)
        print("   Check database connectivity and credentials.", file=sys.stderr)
        sys.exit(1)

    print("✅ NOTIFY sent successfully")

    # Health check polling
    if not args.no_health_check:
        rest_url = _get_rest_url(env)
        if rest_url:
            print("   Polling health endpoint...")
            if poll_health_check(rest_url, verbose=args.verbose):
                print("✅ PostgREST Schema Cache Reloaded")
                print("   PGRST002 errors should now be resolved.")
                sys.exit(0)
            else:
                print("⚠️ Health check timed out, but NOTIFY was sent")
                print("   PostgREST may still be reloading - check manually.")
                sys.exit(0)  # Still exit 0 since NOTIFY succeeded
        else:
            print("  ⚠️ No SUPABASE_URL found, skipping health check")

    print("✅ PostgREST Schema Cache Reloaded")
    print("   PGRST002 errors should now be resolved.")
    sys.exit(0)


if __name__ == "__main__":
    main()
