#!/usr/bin/env python3
"""
tools/test_discord.py - Discord Webhook Verification

QA tool to verify Discord alerting connectivity without waiting for a real incident.

Usage:
    python -m tools.test_discord
    python -m tools.test_discord --env prod
    python -m tools.test_discord --message "Custom test message"

Expected Output:
    ✅ Test Payload Sent. Check Discord Channel.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Discord Webhook Verification Tool")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--message",
        default="Production Alerting Link Established",
        help="Custom test message",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("  DISCORD WEBHOOK VERIFICATION")
    print("=" * 70)
    print(f"\n  Environment: {args.env.upper()}")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 1: Load Environment
    # ─────────────────────────────────────────────────────────────────────────
    print("─" * 70)
    print("  STEP 1: Load Environment")
    print("─" * 70)

    os.environ["SUPABASE_MODE"] = args.env

    # Load the appropriate .env file
    env_file = PROJECT_ROOT / f".env.{args.env}"
    if env_file.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(env_file, override=True)
            print(f"  ✅ Loaded {env_file.name}")
        except ImportError:
            print("  ⚠️  python-dotenv not installed, using system env vars only")
    else:
        print(f"  ⚠️  {env_file.name} not found, using system env vars only")

    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 2: Check Webhook URL
    # ─────────────────────────────────────────────────────────────────────────
    print("─" * 70)
    print("  STEP 2: Check Webhook URL")
    print("─" * 70)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    if not webhook_url:
        print("  ❌ No DISCORD_WEBHOOK_URL found in environment.")
        print()
        print("  To fix:")
        print(f"    1. Add DISCORD_WEBHOOK_URL to {env_file.name}")
        print("    2. Or set it as a system environment variable")
        print("    3. On Railway: Add to Variables in the service settings")
        print()
        return 1

    # Mask the webhook URL for security
    masked = webhook_url[:45] + "..." if len(webhook_url) > 48 else webhook_url
    print(f"  ✅ Webhook URL found: {masked}")
    print()

    # ─────────────────────────────────────────────────────────────────────────
    # Step 3: Send Test Alert
    # ─────────────────────────────────────────────────────────────────────────
    print("─" * 70)
    print("  STEP 3: Send Test Alert")
    print("─" * 70)

    try:
        from backend.utils.discord import AlertType, DiscordMessenger

        messenger = DiscordMessenger.get_instance()

        print(f"  Messenger configured: {messenger.is_configured}")
        print("  Sending AlertType.TEST...")
        print()

        success = messenger.send_alert(
            AlertType.TEST,
            args.message,
            {
                "Environment": args.env.upper(),
                "Status": "Online",
                "Test": "Webhook Verification",
                "Timestamp": __import__("datetime").datetime.now().isoformat(),
            },
        )

        if success:
            print("  ✅ Test Payload Sent. Check Discord Channel.")
            print()
            print("─" * 70)
            print("  SUCCESS: Discord alerting is operational!")
            print("─" * 70)
            print()
            return 0
        else:
            print("  ❌ Alert send returned False (check logs for details)")
            return 1

    except ImportError as e:
        print(f"  ❌ Import error: {e}")
        print("  Make sure you're running from the project root.")
        return 1
    except Exception as e:
        print(f"  ❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
