#!/usr/bin/env python3
"""
tools/fix_schema_cache.py - Schema Cache Healer

Reloads the PostgREST schema cache and verifies the fix.
Resolves PGRST002 errors ("Could not query the database for the schema cache").

Usage:
    python -m tools.fix_schema_cache
    python -m tools.fix_schema_cache --env prod
    python -m tools.fix_schema_cache --retries 5 --delay 3

Failure Mode: PostgREST Schema Cache Stale (PGRST002)
Resolution: Send NOTIFY pgrst, 'reload schema' and verify API health
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import TYPE_CHECKING

import httpx
import psycopg

if TYPE_CHECKING:
    pass

# ---------------------------------------------------------------------------
# Environment Setup
# ---------------------------------------------------------------------------


def get_config(env: str) -> dict[str, str]:
    """Load configuration for the specified environment."""
    os.environ["SUPABASE_MODE"] = env

    from src.supabase_client import get_supabase_credentials, get_supabase_db_url, get_supabase_env

    api_url, _ = get_supabase_credentials(env)

    return {
        "env": get_supabase_env(),
        "db_url": get_supabase_db_url(),
        "api_url": api_url,
        "anon_key": os.environ.get("SUPABASE_ANON_KEY", ""),
        "service_key": os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
    }


def send_notify_reload(db_url: str) -> tuple[bool, str]:
    """
    Send NOTIFY pgrst to reload PostgREST schema cache.

    Returns:
        (success, message)
    """
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Send the reload notification
                cur.execute("NOTIFY pgrst, 'reload schema'")
            conn.commit()
        return True, "NOTIFY pgrst sent successfully"
    except Exception as e:
        return False, f"Failed to send NOTIFY: {e}"


def check_api_health(api_url: str, auth_key: str, timeout: float = 10.0) -> tuple[bool, int, str]:
    """
    Check PostgREST API health by querying a simple endpoint.

    Returns:
        (healthy, status_code, message)
    """
    # Try the REST API root endpoint
    health_url = f"{api_url}/rest/v1/"

    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(health_url, headers=headers)

            # Check for PGRST002 error
            if response.status_code == 503:
                try:
                    body = response.json()
                    if body.get("code") == "PGRST002":
                        return False, 503, f"PGRST002: {body.get('message', 'Schema cache error')}"
                except Exception:
                    pass
                return False, 503, "Service Unavailable"

            # Any 2xx or 4xx (auth issues, but server responding) means cache is OK
            if response.status_code < 500:
                return True, response.status_code, "API responding normally"

            return False, response.status_code, f"HTTP {response.status_code}"

    except httpx.TimeoutException:
        return False, 0, "Request timed out"
    except httpx.RequestError as e:
        return False, 0, f"Request error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Reload PostgREST schema cache and verify")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="Number of health check retries (default: 5)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay between retries in seconds (default: 2)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip API health verification after reload",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  SCHEMA CACHE HEALER - PostgREST PGRST002 Resolution")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print()

    # Load configuration
    try:
        config = get_config(args.env)
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return 1

    # Step 1: Check current health
    print("─" * 70)
    print("  STEP 1: Pre-Check API Health")
    print("─" * 70)

    auth_key = config["service_key"] or config["anon_key"]
    if not auth_key:
        print("  ⚠️  No API key found, skipping pre-check")
        pre_healthy = False
    else:
        pre_healthy, status, msg = check_api_health(config["api_url"], auth_key)
        if pre_healthy:
            print(f"  ✅ API already healthy (HTTP {status})")
            print(f"     {msg}")
            print()
            print("  No action needed - schema cache is current.")
            return 0
        else:
            print(f"  ⚠️  API unhealthy: {msg}")
            print("     Proceeding with schema cache reload...")
    print()

    # Step 2: Send NOTIFY to reload schema
    print("─" * 70)
    print("  STEP 2: Send Schema Reload Command")
    print("─" * 70)

    success, message = send_notify_reload(config["db_url"])
    if success:
        print(f"  ✅ {message}")
    else:
        print(f"  ❌ {message}")
        return 1
    print()

    # Step 3: Verify the fix
    if args.skip_verify:
        print("─" * 70)
        print("  STEP 3: Verification Skipped (--skip-verify)")
        print("─" * 70)
        print("  ⚠️  Schema reload sent but not verified")
        return 0

    print("─" * 70)
    print("  STEP 3: Verify API Health")
    print("─" * 70)

    if not auth_key:
        print("  ⚠️  No API key available for verification")
        print("     Reload sent - manually verify at:")
        print(f"     {config['api_url']}/rest/v1/")
        return 0

    # Retry loop for verification
    for attempt in range(1, args.retries + 1):
        print(f"  Attempt {attempt}/{args.retries}...", end=" ", flush=True)

        healthy, status, msg = check_api_health(config["api_url"], auth_key)

        if healthy:
            print(f"✅ HTTP {status}")
            print()
            print("─" * 70)
            print("  ✅ SCHEMA CACHE RELOADED & VERIFIED")
            print("─" * 70)
            print()
            print("  PostgREST schema cache has been refreshed.")
            print("  PGRST002 errors should now be resolved.")
            return 0

        print(f"⏳ {msg}")

        if attempt < args.retries:
            time.sleep(args.delay)

    # All retries exhausted
    print()
    print("─" * 70)
    print("  ❌ SCHEMA RELOAD FAILED - Manual Intervention Required")
    print("─" * 70)
    print()
    print("  The schema cache did not recover after reload.")
    print()
    print("  Troubleshooting steps:")
    print("    1. Check Supabase Dashboard -> Database -> Replication")
    print("    2. Verify PostgREST is running in project settings")
    print("    3. Check for recent schema changes that may have errors")
    print("    4. Review Supabase logs for detailed error messages")
    print()
    print("  Dashboard URL:")
    print(
        f"    https://supabase.com/dashboard/project/{config['api_url'].split('//')[1].split('.')[0]}"
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
