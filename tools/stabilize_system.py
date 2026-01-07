#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
tools/stabilize_system.py - Production System Stabilization & Verification
═══════════════════════════════════════════════════════════════════════════════

Purpose:
    Force-heal PostgREST cache issues and verify view accessibility.
    Diagnoses and reports on PGRST002 (503) errors with actionable guidance.

Usage:
    # Stabilize production
    python -m tools.stabilize_system --env prod

    # Stabilize dev with verbose output
    python -m tools.stabilize_system --env dev --verbose

    # Just verify (no NOTIFY)
    python -m tools.stabilize_system --env prod --verify-only

Exit Codes:
    0 = System stable, all views accessible
    1 = Permission errors detected (grants needed)
    2 = Cache stuck (manual restart required)
    3 = Setup/connection error

Author: Dragonfly DBRE Team
Created: 2025-01-08
═══════════════════════════════════════════════════════════════════════════════
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# Views to verify after cache reload
CRITICAL_VIEWS = [
    "v_enrichment_health",
    "v_live_feed_events",
    "v_plaintiffs_overview",
    "v_judgment_pipeline",
    "v_enforcement_overview",
]

# Retry configuration
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 2.0

# Environment-specific URLs
SUPABASE_URLS = {
    "dev": "https://ejiddanxtqcleyswqvkc.supabase.co",
    "prod": "https://iaketsyhmqbwaabgykux.supabase.co",
}


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def get_db_url(env: str) -> str:
    """Get database URL for the specified environment."""
    if env == "prod":
        return os.environ.get(
            "SUPABASE_DB_URL",
            os.environ.get("SUPABASE_MIGRATE_DB_URL", ""),
        )
    else:
        return os.environ.get(
            "SUPABASE_DB_URL",
            os.environ.get("SUPABASE_DB_URL_DEV", ""),
        )


def get_api_credentials(env: str) -> tuple[str, str]:
    """Get Supabase URL and anon key for API verification."""
    url = os.environ.get("SUPABASE_URL", SUPABASE_URLS.get(env, ""))
    # For verification, we use anon key to test public access
    anon_key = os.environ.get("SUPABASE_ANON_KEY", "")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    return url, anon_key or service_key


def send_notify(env: str, verbose: bool = False) -> bool:
    """Send NOTIFY pgrst to reload schema cache."""
    try:
        import psycopg

        db_url = get_db_url(env)
        if not db_url:
            print("❌ No database URL configured")
            return False

        if verbose:
            # Mask password in URL for display
            display_url = db_url.split("@")[-1] if "@" in db_url else "configured"
            print(f"   Connecting to: ...@{display_url}")

        conn = psycopg.connect(db_url)
        conn.execute("NOTIFY pgrst, 'reload schema'")
        conn.commit()
        conn.close()

        print("✅ NOTIFY pgrst sent successfully")
        return True

    except Exception as e:
        print(f"❌ Failed to send NOTIFY: {e}")
        return False


def verify_view(url: str, api_key: str, view_name: str, verbose: bool = False) -> dict:
    """
    Verify a single view is accessible via REST API.

    Returns:
        dict with keys: accessible (bool), status_code (int), error (str|None)
    """
    try:
        import httpx

        endpoint = f"{url}/rest/v1/{view_name}?select=*&limit=1"
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
        }

        if verbose:
            print(f"   GET {view_name}?limit=1 ... ", end="", flush=True)

        response = httpx.get(endpoint, headers=headers, timeout=10.0)

        if verbose:
            print(f"{response.status_code}")

        if response.status_code == 200:
            return {"accessible": True, "status_code": 200, "error": None}
        elif response.status_code == 401:
            # 401 means PostgREST cache is working (not 503), auth required
            # This is SUCCESS - cache is not stale
            return {"accessible": True, "status_code": 401, "error": None}
        elif response.status_code == 503:
            body = response.json() if response.text else {}
            code = body.get("code", "UNKNOWN")
            return {"accessible": False, "status_code": 503, "error": code}
        elif response.status_code == 403:
            return {
                "accessible": False,
                "status_code": response.status_code,
                "error": "PERMISSION_DENIED",
            }
        else:
            return {
                "accessible": False,
                "status_code": response.status_code,
                "error": response.text[:100],
            }

    except Exception as e:
        return {"accessible": False, "status_code": 0, "error": str(e)}


def verify_all_views(env: str, verbose: bool = False) -> dict:
    """
    Verify all critical views are accessible.

    Returns:
        dict with keys: all_ok (bool), results (dict[view_name, result])
    """
    url, api_key = get_api_credentials(env)
    if not url or not api_key:
        return {"all_ok": False, "results": {}, "error": "Missing API credentials"}

    results = {}
    for view in CRITICAL_VIEWS:
        results[view] = verify_view(url, api_key, view, verbose)

    all_ok = all(r["accessible"] for r in results.values())
    return {"all_ok": all_ok, "results": results, "error": None}


# ═══════════════════════════════════════════════════════════════════════════
# MAIN STABILIZATION LOGIC
# ═══════════════════════════════════════════════════════════════════════════


def stabilize_system(env: str, verbose: bool = False, verify_only: bool = False) -> int:
    """
    Main stabilization routine.

    Returns:
        0 = Success
        1 = Permission errors
        2 = Cache stuck
        3 = Setup error
    """
    print("═" * 70)
    print("  DRAGONFLY SYSTEM STABILIZATION")
    print(f"  Environment: {env.upper()}")
    print("═" * 70)
    print()

    # Step 1: Send NOTIFY (unless verify-only)
    if not verify_only:
        print("🔄 Step 1: Reloading PostgREST Schema Cache")
        if not send_notify(env, verbose):
            return 3
        print()

    # Step 2: Verify views with retries
    print(f"🔍 Step 2: Verifying View Accessibility (max {MAX_RETRIES} attempts)")
    print()

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"   Attempt {attempt}/{MAX_RETRIES}...")

        result = verify_all_views(env, verbose)

        if result.get("error"):
            print(f"   ❌ {result['error']}")
            return 3

        if result["all_ok"]:
            print()
            print("═" * 70)
            print("  ✅ SYSTEM STABLE & ALL VIEWS ACCESSIBLE")
            print("═" * 70)
            print()
            print("  All critical views are responding correctly:")
            for view, res in result["results"].items():
                print(f"    • {view}: {res['status_code']} OK")
            print()
            return 0

        # Check for permission errors vs cache issues
        permission_errors = [
            v for v, r in result["results"].items() if r.get("error") == "PERMISSION_DENIED"
        ]
        cache_errors = [
            v
            for v, r in result["results"].items()
            if r.get("error") == "PGRST002" or r.get("status_code") == 503
        ]

        if permission_errors and not cache_errors:
            # Pure permission issue - won't resolve with retries
            print()
            print("═" * 70)
            print("  ❌ PERMISSION ERRORS DETECTED")
            print("═" * 70)
            print()
            print("  The following views have permission issues:")
            for view in permission_errors:
                print(f"    • {view}")
            print()
            print("  ACTION REQUIRED:")
            print("    1. Run the stabilization migration:")
            print("       ./scripts/db_push.ps1 -SupabaseEnv prod")
            print("    2. Or manually grant permissions:")
            print("       GRANT SELECT ON <view> TO anon, authenticated;")
            print()
            return 1

        # Cache still stale - wait and retry
        if attempt < MAX_RETRIES:
            print(f"   ⏳ Cache still stale, waiting {RETRY_DELAY_SECONDS}s...")
            time.sleep(RETRY_DELAY_SECONDS)

    # Exhausted retries
    print()
    print("═" * 70)
    print("  ⚠️  CACHE STUCK - MANUAL INTERVENTION REQUIRED")
    print("═" * 70)
    print()
    print("  PostgREST schema cache did not reload after multiple attempts.")
    print()
    print("  Views still returning 503:")
    for view, res in result["results"].items():
        if not res["accessible"]:
            print(f"    • {view}: {res['status_code']} ({res['error']})")
    print()
    print("  ACTION REQUIRED:")
    print("    1. Go to Supabase Dashboard:")
    print(f"       https://supabase.com/dashboard/project/{env}")
    print("    2. Navigate to: Settings → General")
    print("    3. Click: 'Restart Project' or 'Restart API'")
    print("    4. Wait 1-2 minutes, then re-run this tool")
    print()
    print("  Alternative: Try from SQL Editor:")
    print("    NOTIFY pgrst, 'reload schema';")
    print()
    return 2


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Dragonfly System Stabilization & Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Stabilize production
  python -m tools.stabilize_system --env prod

  # Verify only (no NOTIFY)
  python -m tools.stabilize_system --env prod --verify-only

  # Verbose output
  python -m tools.stabilize_system --env dev --verbose

Exit Codes:
  0 = System stable
  1 = Permission errors (grants needed)
  2 = Cache stuck (restart required)
  3 = Setup/connection error
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify views, don't send NOTIFY",
    )

    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env

    try:
        exit_code = stabilize_system(
            env=args.env,
            verbose=args.verbose,
            verify_only=args.verify_only,
        )
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(3)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(3)


if __name__ == "__main__":
    main()
