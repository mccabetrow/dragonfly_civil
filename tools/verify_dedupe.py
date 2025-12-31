#!/usr/bin/env python3
"""
tools/verify_dedupe.py - Verify plaintiff deduplication was successful.

Usage:
    python -m tools.verify_dedupe
    python -m tools.verify_dedupe --env prod
    python -m tools.verify_dedupe --verbose

Checks:
    1. No duplicate dedupe_keys exist in public.plaintiffs
    2. The unique index ux_plaintiffs_dedupe_key (or idx_plaintiffs_dedupe_key) exists
    3. The normalize_party_name function exists
    4. (Optional) No duplicate dedupe_keys in public.judgments
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

import psycopg

if TYPE_CHECKING:
    from psycopg import Connection


def get_db_url(env: str) -> str:
    """Resolve database URL for the given environment."""
    import os

    os.environ.setdefault("SUPABASE_MODE", env)

    # Import after setting env var
    from src.supabase_client import get_supabase_db_url

    return get_supabase_db_url()


def check_duplicate_plaintiffs(conn: Connection, verbose: bool = False) -> tuple[bool, int]:
    """Check for duplicate dedupe_keys in public.plaintiffs."""
    with conn.cursor() as cur:
        # First check if dedupe_key column exists
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'plaintiffs'
              AND column_name = 'dedupe_key'
        """
        )
        if not cur.fetchone():
            print("  ⚠️  dedupe_key column does not exist on public.plaintiffs")
            return False, -1

        cur.execute(
            """
            SELECT dedupe_key, COUNT(*) as cnt
            FROM public.plaintiffs
            WHERE dedupe_key IS NOT NULL
            GROUP BY dedupe_key
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 10
        """
        )
        duplicates = cur.fetchall()

        if duplicates:
            print(f"  ❌ Found {len(duplicates)} duplicate dedupe_key groups:")
            if verbose:
                for key, cnt in duplicates:
                    print(f"      '{key}': {cnt} rows")
            return False, len(duplicates)

        return True, 0


def check_unique_index(conn: Connection, table: str, index_name: str) -> bool:
    """Check if a unique index exists on the table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = %s
              AND indexname = %s
        """,
            (table, index_name),
        )
        result = cur.fetchone()

        if result:
            is_unique = "UNIQUE" in result[1].upper()
            return is_unique

        return False


def check_function_exists(conn: Connection, func_name: str) -> bool:
    """Check if a function exists in public schema."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'public'
              AND p.proname = %s
        """,
            (func_name,),
        )
        return cur.fetchone() is not None


def check_duplicate_judgments(conn: Connection, verbose: bool = False) -> tuple[bool, int]:
    """Check for duplicate dedupe_keys in public.judgments."""
    with conn.cursor() as cur:
        # First check if dedupe_key column exists
        cur.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'judgments'
              AND column_name = 'dedupe_key'
        """
        )
        if not cur.fetchone():
            return True, -1  # Column doesn't exist, skip check

        cur.execute(
            """
            SELECT dedupe_key, COUNT(*) as cnt
            FROM public.judgments
            WHERE dedupe_key IS NOT NULL
            GROUP BY dedupe_key
            HAVING COUNT(*) > 1
            ORDER BY cnt DESC
            LIMIT 10
        """
        )
        duplicates = cur.fetchall()

        if duplicates:
            if verbose:
                print(f"  ⚠️  Found {len(duplicates)} duplicate judgment dedupe_keys")
            return False, len(duplicates)

        return True, 0


def main() -> int:
    """Run dedupe verification checks."""
    parser = argparse.ArgumentParser(description="Verify plaintiff deduplication was successful")
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
    args = parser.parse_args()

    print(f"\n{'=' * 60}")
    print(f"  DEDUPE VERIFICATION - Environment: {args.env.upper()}")
    print(f"{'=' * 60}\n")

    try:
        db_url = get_db_url(args.env)
    except Exception as e:
        print(f"❌ Failed to resolve database URL: {e}")
        return 1

    all_passed = True

    try:
        with psycopg.connect(db_url) as conn:
            # Check 1: No duplicate plaintiffs
            print("[Check 1] Duplicate plaintiffs by dedupe_key...")
            passed, count = check_duplicate_plaintiffs(conn, args.verbose)
            if passed:
                print("  ✅ No duplicate plaintiffs found")
            else:
                all_passed = False

            # Check 2: Unique index exists (check both naming conventions)
            print("\n[Check 2] Unique index on plaintiffs.dedupe_key...")
            if check_unique_index(conn, "plaintiffs", "ux_plaintiffs_dedupe_key"):
                print("  ✅ Unique index ux_plaintiffs_dedupe_key exists")
            elif check_unique_index(conn, "plaintiffs", "idx_plaintiffs_dedupe_key"):
                print("  ✅ Unique index idx_plaintiffs_dedupe_key exists")
            else:
                print("  ❌ Unique index on plaintiffs.dedupe_key NOT found")
                all_passed = False

            # Check 3: normalize_party_name function exists
            print("\n[Check 3] normalize_party_name function...")
            if check_function_exists(conn, "normalize_party_name"):
                print("  ✅ normalize_party_name function exists")
            else:
                print("  ❌ normalize_party_name function NOT found")
                all_passed = False

            # Check 4: compute_judgment_dedupe_key function exists
            print("\n[Check 4] compute_judgment_dedupe_key function...")
            if check_function_exists(conn, "compute_judgment_dedupe_key"):
                print("  ✅ compute_judgment_dedupe_key function exists")
            else:
                print("  ⚠️  compute_judgment_dedupe_key function NOT found (optional)")

            # Check 5: No duplicate judgments (optional)
            print("\n[Check 5] Duplicate judgments by dedupe_key...")
            passed, count = check_duplicate_judgments(conn, args.verbose)
            if count == -1:
                print("  ⏭️  judgments.dedupe_key column not present (skipped)")
            elif passed:
                print("  ✅ No duplicate judgments found")
            else:
                print(f"  ⚠️  {count} duplicate judgment groups found")

    except psycopg.OperationalError as e:
        print(f"❌ Database connection failed: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1

    # Summary
    print(f"\n{'=' * 60}")
    if all_passed:
        print("  ✅ ALL CHECKS PASSED - Deduplication verified")
        print(f"{'=' * 60}\n")
        return 0
    else:
        print("  ❌ SOME CHECKS FAILED - Remediation required")
        print(f"{'=' * 60}")
        print("\nTo fix, run the remediation migration:")
        print("  ./scripts/db_push.ps1 -SupabaseEnv dev")
        print("\nOr manually apply:")
        print("  supabase/migrations/20250105000000_dedupe_plaintiffs_remediation.sql\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
