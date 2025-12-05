#!/usr/bin/env python
"""
Intake Smoke Test Script

Reads a sample CSV file and directly invokes the intake processing logic
without going through the HTTP layer. Useful for debugging and verifying
the intake pipeline is wired up correctly.

Usage:
    python -m tools.intake_smoke [--csv PATH] [--env dev|prod]

Example:
    python -m tools.intake_smoke --csv data_in/simplicity_test_10.csv --env dev
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("intake_smoke")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Smoke test the intake pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("data_in/simplicity_test_10.csv"),
        help="Path to CSV file to process (default: data_in/simplicity_test_10.csv)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Target environment (default: dev)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and validate only, don't write to database",
    )
    return parser.parse_args()


async def run_smoke_test(csv_path: Path, env: str, dry_run: bool) -> int:
    """
    Run the intake smoke test.

    Returns:
        Exit code: 0 for success, 1 for failure
    """
    import os

    # Set environment before importing Supabase-dependent modules
    os.environ["SUPABASE_MODE"] = env
    logger.info("Environment: %s", env)

    # Validate CSV file exists
    if not csv_path.exists():
        logger.error("CSV file not found: %s", csv_path)
        return 1

    logger.info("CSV file: %s", csv_path)

    # Read and parse CSV
    try:
        import csv

        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        logger.info("Parsed %d rows from CSV", len(rows))

        if not rows:
            logger.warning("CSV file is empty")
            return 1

        # Show sample of column names
        columns = list(rows[0].keys())
        logger.info("Columns: %s", ", ".join(columns[:10]))
        if len(columns) > 10:
            logger.info("  ... and %d more columns", len(columns) - 10)

    except Exception as e:
        logger.exception("Failed to parse CSV: %s", e)
        return 1

    if dry_run:
        logger.info("[DRY RUN] Would process %d rows", len(rows))
        logger.info("[DRY RUN] Skipping database write")
        return 0

    # Try to import and run the intake service
    try:
        from contextlib import asynccontextmanager
        from backend.db import get_pool, init_db_pool, close_db_pool
        from backend.services.intake_service import IntakeService

        # Initialize the database pool
        await init_db_pool()
        conn = await get_pool()

        # Wrap the connection to provide pool-like interface
        # IntakeService expects pool.connection() context manager
        class ConnectionWrapper:
            """Wrapper to provide pool-like interface for a single connection."""

            def __init__(self, conn):
                self._conn = conn

            @asynccontextmanager
            async def connection(self):
                """Yield the underlying connection."""
                yield self._conn

        pool = ConnectionWrapper(conn)

        service = IntakeService(pool)
        logger.info("IntakeService initialized with database pool")

        # Process the CSV file using the service
        result = await service.process_simplicity_upload(
            file_path=csv_path,
            source="simplicity",
            created_by="intake_smoke",
        )

        logger.info("✅ Batch processed: %s", result.batch_id)
        logger.info("   Total rows: %d", result.total_rows)
        logger.info("   Valid rows: %d", result.valid_rows)
        logger.info("   Error rows: %d", result.error_rows)
        logger.info("   Duration: %.2fs", result.duration_seconds)

        # Close the pool
        await close_db_pool()

    except ImportError as e:
        logger.error("Failed to import IntakeService: %s", e)
        logger.info("This may be expected if the service isn't fully wired up yet")
        return 1
    except Exception as e:
        logger.exception("Intake processing failed: %s", e)
        return 1

    logger.info("🎉 Smoke test completed successfully")
    return 0


def main() -> int:
    """Entry point."""
    args = parse_args()

    # On Windows, psycopg async requires SelectorEventLoop
    import platform

    if platform.system() == "Windows":
        import selectors

        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
        )

    return asyncio.run(run_smoke_test(args.csv, args.env, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
