#!/usr/bin/env python3
"""
Dragonfly System Contract Verification

Verifies that the database schema matches the expected contract hash.
This prevents API drift between database migrations and application code.

Usage:
    python -m tools.verify_contract [--env dev|prod] [--show-hash] [--details]

Options:
    --env       Target environment (default: from SUPABASE_MODE)
    --show-hash Just print the current hash (for updating contract.py)
    --details   Show detailed component breakdown
    --update    Update the contract.py file with current hash (use after migration)

Exit Codes:
    0 - Contract verified (or --show-hash mode)
    1 - Contract mismatch or error

Example workflow after a migration:
    1. python -m tools.verify_contract --show-hash
    2. Copy the hash to backend/config/contract.py
    3. python -m tools.verify_contract  # Should now pass
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.supabase_client import get_supabase_db_url


def get_migrate_db_url() -> str:
    """Get the direct database URL (not pooler) for schema queries."""
    migrate_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if migrate_url:
        return migrate_url
    # Fall back to regular URL if migrate URL not set
    return get_supabase_db_url()


def get_contract_hash(dsn: str) -> str | None:
    """Fetch the current contract hash from the database."""
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ops.get_system_contract_hash() AS hash")
                row = cur.fetchone()
                return row["hash"] if row else None
    except psycopg.errors.UndefinedFunction:
        print("❌ ERROR: ops.get_system_contract_hash() not found.")
        print("   Run the contract_versioning migration first.")
        return None
    except Exception as e:
        print(f"❌ ERROR: Failed to fetch contract hash: {e}")
        return None


def get_contract_details(dsn: str) -> list[dict]:
    """Fetch detailed contract components from the database."""
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.get_system_contract_details()")
                return list(cur.fetchall())
    except Exception as e:
        print(f"❌ ERROR: Failed to fetch contract details: {e}")
        return []


def get_expected_hash() -> str:
    """Load the expected contract hash from config."""
    try:
        from backend.config.contract import EXPECTED_CONTRACT_HASH

        return EXPECTED_CONTRACT_HASH
    except ImportError:
        print("❌ ERROR: Could not import backend.config.contract")
        return ""


def update_contract_file(new_hash: str) -> bool:
    """Update the contract.py file with a new hash."""
    contract_path = Path(__file__).resolve().parents[1] / "backend" / "config" / "contract.py"

    try:
        content = contract_path.read_text()

        # Find and replace the hash
        import re

        new_content = re.sub(
            r'EXPECTED_CONTRACT_HASH = "[^"]*"', f'EXPECTED_CONTRACT_HASH = "{new_hash}"', content
        )

        # Update the date
        today = datetime.now().strftime("%Y-%m-%d")
        new_content = re.sub(
            r'CONTRACT_LAST_UPDATED = "[^"]*"', f'CONTRACT_LAST_UPDATED = "{today}"', new_content
        )

        contract_path.write_text(new_content)
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to update contract.py: {e}")
        return False


def main() -> int:
    """Run contract verification."""
    parser = argparse.ArgumentParser(
        description="Verify system contract hash matches expected value"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--show-hash",
        action="store_true",
        help="Just print the current hash and exit",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Show detailed component breakdown",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update contract.py with current hash",
    )
    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env

    print("=" * 60)
    print("SYSTEM CONTRACT VERIFICATION")
    print("=" * 60)
    print(f"Environment: {args.env.upper()}")

    # Get database URL (use direct connection, not pooler)
    try:
        dsn = get_migrate_db_url()
    except Exception as e:
        print(f"❌ ERROR: Could not get database URL: {e}")
        return 1

    # Fetch current hash
    print("\nFetching contract hash from database...")
    current_hash = get_contract_hash(dsn)

    if current_hash is None:
        return 1

    print(f"Current Hash: {current_hash}")

    # Show details if requested
    if args.details:
        print("\n" + "-" * 60)
        print("CONTRACT COMPONENTS")
        print("-" * 60)
        details = get_contract_details(dsn)
        for row in details:
            print(f"  [{row['component_type']}] {row['component_name']}")
            if row["signature"]:
                sig = (
                    row["signature"][:80] + "..."
                    if len(row["signature"]) > 80
                    else row["signature"]
                )
                print(f"    → {sig}")
        print(f"\nTotal components: {len(details)}")

    # Just show hash mode
    if args.show_hash:
        print("\n" + "=" * 60)
        print("Copy this hash to backend/config/contract.py:")
        print(f'EXPECTED_CONTRACT_HASH = "{current_hash}"')
        print("=" * 60)
        return 0

    # Update mode
    if args.update:
        print("\nUpdating backend/config/contract.py...")
        if update_contract_file(current_hash):
            print(f"✅ Contract hash updated to: {current_hash}")
            return 0
        return 1

    # Verification mode
    print("\nVerifying against expected hash...")
    expected_hash = get_expected_hash()

    if expected_hash == "PENDING_INITIAL_DEPLOYMENT":
        print("\n⚠️  WARNING: Contract hash not yet set!")
        print("   Run: python -m tools.verify_contract --update")
        print("   Then commit the updated contract.py")
        return 1

    print(f"Expected Hash: {expected_hash}")

    if current_hash == expected_hash:
        print("\n" + "=" * 60)
        print(f"✅ CONTRACT VERIFIED: {current_hash}")
        print("=" * 60)
        return 0
    else:
        print("\n" + "=" * 60)
        print("❌ FATAL: DB CONTRACT DIVERGENCE!")
        print("=" * 60)
        print(f"  Expected: {expected_hash}")
        print(f"  Got:      {current_hash}")
        print()
        print("This means the database schema has changed but the code")
        print("hasn't been updated to match. Either:")
        print()
        print("  1. You forgot to update the hash after a migration:")
        print("     python -m tools.verify_contract --update")
        print()
        print("  2. Someone else ran a migration you don't have:")
        print("     git pull && DB Push (Dev)")
        print()
        print("  3. There's an unexpected schema drift in production:")
        print("     python -m tools.verify_contract --details")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
