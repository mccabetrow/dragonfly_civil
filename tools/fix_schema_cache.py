#!/usr/bin/env python3
"""
tools/fix_schema_cache.py - Operator-Grade Schema Cache Recovery

Reloads the PostgREST schema cache and verifies the fix.
Resolves PGRST002 errors ("Could not query the database for the schema cache").

Recovery Flow:
    1. Run check_health probe (strict PGRST002 detection)
    2. If Red: Send NOTIFY pgrst, 'reload schema'
    3. Wait 3s and re-check
    4. If still Red: Escalate to human via Discord

Usage:
    python -m tools.fix_schema_cache
    python -m tools.fix_schema_cache --env prod
    python -m tools.fix_schema_cache --retries 3 --delay 3

Failure Mode: PostgREST Schema Cache Stale (PGRST002)
Resolution: Send NOTIFY pgrst, 'reload schema' and verify via health probe
Escalation: Discord webhook alert if automation fails
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    pass

# Import the strict health probe
from tools.check_postgrest_health import check_health

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


def send_discord_escalation(env: str, project_ref: str) -> None:
    """
    Send Discord webhook alert for manual intervention.
    Fire-and-forget - failures are logged but don't block.

    Uses the standardized alert_pgrst_cache_stale() function.
    """
    # Try using the standardized alerting first
    try:
        from backend.utils.discord import alert_pgrst_cache_stale

        success = alert_pgrst_cache_stale(
            environment=env,
            recovery_attempted=True,
            recovery_success=False,
        )

        if success:
            print("  ✅ Discord alert sent (via DiscordMessenger)")
            return
    except ImportError:
        pass  # Fall back to direct webhook
    except Exception as e:
        print(f"  ⚠️  DiscordMessenger failed, falling back: {e}")

    # Fallback: Direct webhook (for when backend module isn't available)
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("  ⚠️  No DISCORD_WEBHOOK_URL found - skipping alert")
        return

    try:
        import httpx

        payload = {
            "embeds": [
                {
                    "title": "🔥 CRITICAL: PostgREST Unhealthy",
                    "description": f"**Environment:** {env.upper()}\n"
                    f"**Status:** Automated recovery failed\n"
                    f"**Action Required:** Manual project restart",
                    "color": 0xFF0000,  # Red
                    "fields": [
                        {
                            "name": "Dashboard",
                            "value": f"https://supabase.com/dashboard/project/{project_ref}",
                            "inline": False,
                        },
                        {
                            "name": "Recovery Steps",
                            "value": "1. Go to Settings → Restart Project\n"
                            "2. Wait for restart to complete\n"
                            "3. Run health check again",
                            "inline": False,
                        },
                    ],
                }
            ]
        }

        with httpx.Client(timeout=10.0) as client:
            response = client.post(webhook_url, json=payload)
            if response.status_code == 204:
                print("  ✅ Discord alert sent")
            else:
                print(f"  ⚠️  Discord alert failed: HTTP {response.status_code}")

    except Exception as e:
        print(f"  ⚠️  Discord alert failed: {e}")


def check_api_health(api_url: str, auth_key: str, timeout: float = 10.0) -> tuple[bool, int, str]:
    """
    DEPRECATED: Use check_health() from check_postgrest_health.py instead.
    This is kept for backwards compatibility only.
    """
    import httpx

    health_url = f"{api_url}/rest/v1/"
    headers = {
        "apikey": auth_key,
        "Authorization": f"Bearer {auth_key}",
    }

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.get(health_url, headers=headers)

            if response.status_code == 503:
                try:
                    body = response.json()
                    if body.get("code") == "PGRST002":
                        return False, 503, f"PGRST002: {body.get('message', 'Schema cache error')}"
                except Exception:
                    pass
                return False, 503, "Service Unavailable"

            if response.status_code < 500:
                return True, response.status_code, "API responding normally"

            return False, response.status_code, f"HTTP {response.status_code}"

    except httpx.TimeoutException:
        return False, 0, "Request timed out"
    except httpx.RequestError as e:
        return False, 0, f"Request error: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Operator-Grade PostgREST schema cache recovery")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Number of health check retries after reload (default: 3)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=3.0,
        help="Delay between retries in seconds (default: 3)",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  OPERATOR-GRADE SCHEMA CACHE RECOVERY")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print()

    # Load configuration
    try:
        config = get_config(args.env)
        project_ref = config["api_url"].split("//")[1].split(".")[0]
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return 1

    # STEP 1: Pre-Check with Strict Health Probe
    print("─" * 70)
    print("  STEP 1: Run Health Probe (Strict PGRST002 Detection)")
    print("─" * 70)

    try:
        is_healthy = check_health(args.env)
    except Exception as e:
        print(f"  ❌ Health probe failed: {e}")
        return 1

    if is_healthy:
        print("  ✅ PostgREST is healthy - no action needed")
        print()
        return 0

    print("  ⚠️  Detected Stale Cache. Attempting NOTIFY reload...")
    print()

    # STEP 2: Send NOTIFY to reload schema
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

    # STEP 3: Wait and re-verify
    print("─" * 70)
    print(f"  STEP 3: Wait {args.delay}s and Re-Check")
    print("─" * 70)

    time.sleep(args.delay)

    # Retry loop for verification
    for attempt in range(1, args.retries + 1):
        print(f"  Attempt {attempt}/{args.retries}...", end=" ", flush=True)

        try:
            is_healthy = check_health(args.env)
        except Exception as e:
            print(f"❌ Error: {e}")
            if attempt < args.retries:
                time.sleep(args.delay)
            continue

        if is_healthy:
            print("✅ Healthy")
            print()
            print("─" * 70)
            print("  ✅ AUTOMATED RECOVERY SUCCESSFUL")
            print("─" * 70)
            print()
            print("  PostgREST schema cache has been refreshed.")
            print("  PGRST002 errors should now be resolved.")
            return 0

        print("⏳ Still unhealthy")

        if attempt < args.retries:
            time.sleep(args.delay)

    # STEP 4: Escalation - All retries exhausted
    print()
    print("─" * 70)
    print("  ❌ AUTOMATED RECOVERY FAILED")
    print("─" * 70)
    print()
    print("  🚨 ACTION REQUIRED: Go to Supabase Dashboard → Settings → Restart Project")
    print()
    print("  Dashboard URL:")
    print(f"    https://supabase.com/dashboard/project/{project_ref}/settings/general")
    print()

    # Send Discord escalation alert
    send_discord_escalation(args.env, project_ref)

    print()
    print("  Troubleshooting steps:")
    print("    1. Check Supabase Dashboard → Database → Replication")
    print("    2. Verify PostgREST is running in project settings")
    print("    3. Check for recent schema changes that may have errors")
    print("    4. Review Supabase logs for detailed error messages")
    print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
