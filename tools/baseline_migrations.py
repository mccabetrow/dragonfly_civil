#!/usr/bin/env python3
"""
tools/baseline_migrations.py
============================
Baseline Production Migrations - Mark all local migrations as applied.

This script resolves "Migration Drift" by inserting records into the
supabase_migrations.schema_migrations table for every migration file
in the local supabase/migrations/ folder.

After running this, prod_gate migration check should show 0 pending.

Usage:
    python -m tools.baseline_migrations --dry-run
    python -m tools.baseline_migrations --commit

Author: Principal Database Reliability Engineer
Date: 2026-01-18
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import psycopg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# =============================================================================
# Configuration
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "supabase" / "migrations"

# Production project ref (for validation)
PROD_PROJECT_REF = "iaketsyhmqbwaabgykux"


def redact_dsn(dsn: str) -> str:
    """Redact password from DSN for safe logging."""
    return re.sub(r"(://[^:]+:)([^@]+)(@)", r"\1****\3", dsn)


def get_migration_version(filename: str) -> str:
    """Extract version from filename (e.g., '20251201182738' from '20251201182738_fix.sql')."""
    match = re.match(r"^(\d+)", filename)
    if match:
        return match.group(1)
    # Fallback for non-numeric prefixed files
    return filename.replace(".sql", "")


def discover_migrations() -> list[tuple[str, str]]:
    """Discover all migration files and return (version, name) tuples."""
    if not MIGRATIONS_DIR.exists():
        print(f"[FATAL] Migrations directory not found: {MIGRATIONS_DIR}")
        sys.exit(1)

    migrations = []
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = get_migration_version(f.name)
        name = f.stem  # filename without .sql
        migrations.append((version, name))

    return migrations


def main() -> int:
    parser = argparse.ArgumentParser(description="Baseline production migrations")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without making changes",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Actually insert the migration records",
    )
    parser.add_argument(
        "--env",
        default=os.environ.get("SUPABASE_MODE", "prod"),
        help="Target environment (default: $SUPABASE_MODE or prod)",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.commit:
        print("ERROR: Must specify either --dry-run or --commit")
        return 2

    print()
    print("=" * 78)
    print("  DRAGONFLY MIGRATION BASELINER")
    print("  Mark all local migrations as applied in production")
    print("=" * 78)
    print()

    # Get DSN
    env = args.env.lower()
    try:
        dsn = get_supabase_db_url()
    except Exception as e:
        dsn = os.environ.get("DATABASE_URL", "")
        if not dsn:
            print(f"[FATAL] Cannot get DSN: {e}")
            return 1

    # Validate DSN is for prod
    if PROD_PROJECT_REF not in dsn:
        print(f"[FATAL] DSN does not contain production project ref: {PROD_PROJECT_REF}")
        print("        This script is for PRODUCTION baselining only.")
        return 1

    print(f"[DSN] Target: {redact_dsn(dsn)}")
    print(f"[ENV] {env}")
    print()

    # Discover migrations
    migrations = discover_migrations()
    print(f"[FOUND] {len(migrations)} migration files")
    if migrations:
        print(f"        First: {migrations[0][1]}.sql")
        print(f"        Last:  {migrations[-1][1]}.sql")
    print()

    if not migrations:
        print("[WARN] No migration files found. Nothing to baseline.")
        return 0

    # Dry run mode
    if args.dry_run:
        print("[DRY-RUN] Would insert the following records:")
        print("-" * 78)
        for version, name in migrations[:5]:
            print(f"  {version}: {name}")
        if len(migrations) > 10:
            print(f"  ... ({len(migrations) - 10} more) ...")
        for version, name in migrations[-5:]:
            print(f"  {version}: {name}")
        print("-" * 78)
        print()
        print("[DRY-RUN] No changes made. Use --commit to execute.")
        return 0

    # Commit mode - confirmation gate
    print("=" * 78)
    print("  ⚠️  WARNING: PRODUCTION DATABASE MODIFICATION")
    print("=" * 78)
    print()
    print(f"  This will INSERT {len(migrations)} records into:")
    print("    supabase_migrations.schema_migrations")
    print()
    print("  This marks all local migrations as 'applied' in production.")
    print("  Only proceed if the production schema is already correct.")
    print()

    confirm = input("Type 'BASELINE' to proceed: ")
    if confirm != "BASELINE":
        print("[ABORT] Confirmation not received. Exiting.")
        return 0

    # Execute
    print()
    print("[EXEC] Inserting migration records...")

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                inserted = 0
                skipped = 0

                for version, name in migrations:
                    # Schema uses: version, statements (array), name
                    # We insert empty statements array - the SQL is already applied
                    cur.execute(
                        """
                        INSERT INTO supabase_migrations.schema_migrations 
                            (version, statements, name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (version) DO NOTHING
                        """,
                        (version, [], name),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                    else:
                        skipped += 1

                conn.commit()

        print(f"[OK] Inserted: {inserted}, Skipped (already existed): {skipped}")

    except Exception as e:
        print(f"[ERROR] Failed to insert: {e}")
        return 1

    # Verification
    print()
    print("[VERIFY] Checking migration count in database...")

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM supabase_migrations.schema_migrations")
                db_count = cur.fetchone()[0]

        print()
        print("=" * 78)
        print("  ✅ BASELINE COMPLETE")
        print("=" * 78)
        print()
        print(f"  Local migrations:    {len(migrations)}")
        print(f"  Database records:    {db_count}")
        print()
        print("  Next step: Run 'python -m tools.prod_gate --mode prod' to verify")
        print()

    except Exception as e:
        print(f"[WARN] Could not verify: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
