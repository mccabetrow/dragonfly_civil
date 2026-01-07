#!/usr/bin/env python3
"""
Dragonfly Civil - Migration Directory Cleanup Tool

Moves non-migration files out of the supabase/migrations/ directory to
keep it clean and prevent Supabase CLI warnings.

Files moved:
    - rollback_template.sql -> docs/templates/rollback_template.sql

Usage:
    python -m tools.cleanup_migrations
    python -m tools.cleanup_migrations --dry-run

Exit Codes:
    0 - Cleanup successful (or nothing to clean)
    1 - Cleanup failed
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cleanup_migrations")


# Files that should not be in the migrations directory
NON_MIGRATION_FILES = {
    "rollback_template.sql": "docs/templates/rollback_template.sql",
    "README.md": "docs/migrations_README.md",  # If ever added
}


def cleanup_migrations(
    migrations_dir: Path,
    project_root: Path,
    dry_run: bool = False,
) -> tuple[int, int]:
    """
    Move non-migration files out of the migrations directory.

    Args:
        migrations_dir: Path to supabase/migrations/
        project_root: Path to project root
        dry_run: If True, only report what would be done

    Returns:
        Tuple of (files_moved, errors)
    """
    files_moved = 0
    errors = 0

    for filename, destination in NON_MIGRATION_FILES.items():
        source_path = migrations_dir / filename
        dest_path = project_root / destination

        if not source_path.exists():
            continue

        logger.info(f"Found: {filename}")

        if dry_run:
            logger.info(f"  Would move to: {dest_path}")
            files_moved += 1
            continue

        try:
            # Create destination directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            # Move the file
            shutil.move(str(source_path), str(dest_path))
            logger.info(f"  Moved to: {dest_path}")
            files_moved += 1

        except Exception as e:
            logger.error(f"  Failed to move: {e}")
            errors += 1

    return files_moved, errors


def check_for_invalid_migrations(migrations_dir: Path) -> list[str]:
    """
    Check for files that don't match migration naming conventions.

    Returns:
        List of suspicious filenames.
    """
    import re

    suspicious = []
    valid_pattern = re.compile(r"^\d+_.+\.sql$")

    for file in migrations_dir.glob("*.sql"):
        if file.name in NON_MIGRATION_FILES:
            continue
        if not valid_pattern.match(file.name):
            suspicious.append(file.name)

    return suspicious


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Clean up non-migration files from the migrations directory"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=PROJECT_ROOT / "supabase" / "migrations",
        help="Path to migrations directory",
    )

    args = parser.parse_args()

    print()
    print("=" * 70)
    print("  Migration Directory Cleanup")
    print("=" * 70)
    print()

    migrations_dir = args.migrations_dir
    if not migrations_dir.exists():
        logger.error(f"Migrations directory not found: {migrations_dir}")
        return 1

    print(f"Scanning: {migrations_dir}")
    print()

    # Check for non-migration files
    files_moved, errors = cleanup_migrations(
        migrations_dir,
        PROJECT_ROOT,
        dry_run=args.dry_run,
    )

    # Check for suspicious files
    suspicious = check_for_invalid_migrations(migrations_dir)
    if suspicious:
        print()
        print("⚠️  Found files with non-standard naming:")
        for filename in suspicious:
            print(f"    • {filename}")
        print()
        print("  These files may cause issues with Supabase CLI.")

    print()
    if args.dry_run:
        if files_moved > 0:
            print(f"Dry-run: Would move {files_moved} file(s)")
            print("Run without --dry-run to execute cleanup.")
        else:
            print("✅ Migration directory is clean.")
        return 0

    if files_moved > 0:
        if errors == 0:
            print(f"✅ Cleaned up migration directory. Moved {files_moved} file(s).")
        else:
            print(f"⚠️  Moved {files_moved} file(s) with {errors} error(s).")
            return 1
    else:
        print("✅ Migration directory is already clean.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
