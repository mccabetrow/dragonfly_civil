"""
Quick runner to test ingest_simplicity_csv against dev.
Usage: python -m tools.run_batch_seed --csv data_in/batch_seed_test.csv
"""

import argparse
import asyncio
import logging
import os
import sys

# Windows needs SelectorEventLoop for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load .env before anything else
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# Ensure dev environment
os.environ.setdefault("SUPABASE_MODE", "dev")

from backend.services.ingest_service import ingest_simplicity_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main(csv_path: str) -> None:
    logger.info(f"Running batch seed ingest from: {csv_path}")

    if not os.path.exists(csv_path):
        logger.error(f"File not found: {csv_path}")
        sys.exit(1)

    try:
        result = await ingest_simplicity_csv(csv_path)
        logger.info("=" * 60)
        logger.info("INGEST RESULT")
        logger.info("=" * 60)
        logger.info(f"  Rows processed: {result['rows']}")
        logger.info(f"  Inserted:       {result['inserted']}")
        logger.info(f"  Failed:         {result['failed']}")
        logger.info("=" * 60)

        if result["inserted"] > 0:
            logger.info("✅ Batch seed complete - judgments inserted into dev DB")

            # Verify the insertions
            from backend.db import get_connection

            async with get_connection() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, case_number FROM public.judgments 
                    WHERE case_number LIKE '2024-CV-%'
                    ORDER BY id DESC
                """
                )
                logger.info(
                    f"Verification: Found {len(rows)} rows with 2024-CV-% prefix"
                )
                for r in rows:
                    logger.info(f"  - {r['id']}: {r['case_number']}")
        else:
            logger.warning("⚠️ No new rows inserted (may be duplicates)")

    except Exception as e:
        logger.exception(f"Ingest failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run batch seed ingest")
    parser.add_argument(
        "--csv",
        default="data_in/batch_seed_test.csv",
        help="Path to the CSV file to ingest",
    )
    args = parser.parse_args()

    asyncio.run(main(args.csv))
