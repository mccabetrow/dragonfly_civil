#!/usr/bin/env python
"""
Dragonfly Civil - Schema Repair Runner

Executes all schema repair SQL files against the configured Supabase database.
Used by SchemaGuard for automatic repair, or can be run manually.

Usage:
    python -m tools.run_schema_repair [--env dev|prod] [--dry-run]

This script:
1. Loads repair SQL files from supabase/recovery/
2. Executes each file via direct database connection
3. Logs success/failure for each file
4. Sends Discord notification on completion
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Recovery SQL files in execution order
RECOVERY_FILES = [
    "ops_intake_schema_repair.sql",
    "core_schema_repair.sql",
    "enforcement_schema_repair.sql",
]

RECOVERY_DIR = PROJECT_ROOT / "supabase" / "recovery"


async def execute_sql_file(conn: Any, file_path: Path, dry_run: bool = False) -> dict[str, Any]:
    """
    Execute a SQL file against the database.

    Args:
        conn: Database connection
        file_path: Path to SQL file
        dry_run: If True, validate but don't execute

    Returns:
        Dict with execution result
    """
    file_name = file_path.name
    result = {
        "file": file_name,
        "success": False,
        "error": None,
        "dry_run": dry_run,
    }

    if not file_path.exists():
        result["error"] = f"File not found: {file_path}"
        logger.warning(f"[repair] Skipping missing file: {file_name}")
        return result

    try:
        sql_content = file_path.read_text(encoding="utf-8")

        if dry_run:
            logger.info(f"[repair] [DRY-RUN] Would execute: {file_name} ({len(sql_content)} bytes)")
            result["success"] = True
            return result

        logger.info(f"[repair] Executing: {file_name}")

        # Execute the SQL
        await conn.execute(sql_content)

        logger.info(f"[repair] ✅ Completed: {file_name}")
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[repair] ❌ Failed {file_name}: {e}")

    return result


async def run_repair(env: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """
    Execute all schema repair scripts.

    Args:
        env: Environment (dev/prod). If None, uses SUPABASE_MODE
        dry_run: If True, validate but don't execute

    Returns:
        Dict with overall result and per-file details
    """
    # Resolve environment
    if env is None:
        env = get_supabase_env()

    logger.info(f"[repair] Starting schema repair (env={env}, dry_run={dry_run})")

    result = {
        "success": False,
        "env": env,
        "dry_run": dry_run,
        "started_at": datetime.utcnow().isoformat(),
        "files_executed": [],
        "files_failed": [],
        "errors": [],
    }

    # Get database URL
    try:
        db_url = get_supabase_db_url()
    except Exception as e:
        result["errors"].append(f"Failed to get database URL: {e}")
        logger.error(f"[repair] Cannot get DB URL: {e}")
        return result

    # Connect to database
    try:
        import psycopg

        async with await psycopg.AsyncConnection.connect(db_url) as conn:
            # Execute each repair file
            for file_name in RECOVERY_FILES:
                file_path = RECOVERY_DIR / file_name

                file_result = await execute_sql_file(conn, file_path, dry_run)

                if file_result["success"]:
                    result["files_executed"].append(file_name)
                else:
                    result["files_failed"].append(file_name)
                    if file_result["error"]:
                        result["errors"].append(f"{file_name}: {file_result['error']}")

            # Commit if not dry run
            if not dry_run:
                await conn.commit()

    except Exception as e:
        result["errors"].append(f"Database connection error: {e}")
        logger.error(f"[repair] Database error: {e}")
        return result

    # Determine overall success
    result["success"] = len(result["files_failed"]) == 0
    result["completed_at"] = datetime.utcnow().isoformat()

    # Log summary
    logger.info(
        f"[repair] Completed: {len(result['files_executed'])} succeeded, "
        f"{len(result['files_failed'])} failed"
    )

    # Send Discord notification on failure
    if not result["success"] and not dry_run:
        await _notify_failure(result)

    return result


async def _notify_failure(result: dict[str, Any]) -> None:
    """Send Discord notification on repair failure."""
    try:
        # Try to use backend discord service
        try:
            from backend.services.discord_service import DiscordService

            async with DiscordService() as discord:
                message = (
                    f"🔧 **Schema Repair Failed**\n\n"
                    f"Environment: `{result['env']}`\n"
                    f"Failed files: {', '.join(result['files_failed'])}\n\n"
                    f"Errors:\n```\n{chr(10).join(result['errors'][:3])}\n```"
                )
                await discord.send_message(message, username="Schema Repair")
        except ImportError:
            # Fallback to ETL discord alert
            from etl.src.alerts.discord import post_simple

            post_simple(
                f"Schema repair failed: {', '.join(result['files_failed'])}",
                level="ERROR",
            )

    except Exception as e:
        logger.error(f"[repair] Failed to send Discord notification: {e}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Execute schema repair scripts against Supabase")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Target environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate files without executing",
    )

    args = parser.parse_args()

    # Set environment if specified
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    # Run repair
    result = asyncio.run(run_repair(env=args.env, dry_run=args.dry_run))

    # Exit with appropriate code
    if result["success"]:
        print("\n✅ Schema repair completed successfully")
        print(f"   Files executed: {result['files_executed']}")
        sys.exit(0)
    else:
        print("\n❌ Schema repair failed")
        print(f"   Failed files: {result['files_failed']}")
        for error in result["errors"]:
            print(f"   - {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
