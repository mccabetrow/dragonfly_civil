# backend/worker.py
"""
Dragonfly Enrichment Worker - Railway Entrypoint

Clean entrypoint for running the enrichment worker as a Railway service.
Handles database initialization and runs the job processing loop.
"""

import asyncio
import sys

# Windows compatibility for psycopg async
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from backend.core.logging import configure_logging, get_logger

# Configure structured JSON logging for production
configure_logging(service_name="dragonfly-worker")

logger = get_logger(__name__)


async def start_worker() -> None:
    """Initialize database and start the worker loop."""
    from backend.db import init_db_pool
    from backend.services.enrichment_service import worker_loop

    logger.info("Initializing database connection...")
    await init_db_pool()

    logger.info("Starting enrichment worker loop...")
    await worker_loop()


if __name__ == "__main__":
    print("🚀 Starting Dragonfly Enrichment Worker...")
    try:
        asyncio.run(start_worker())
    except KeyboardInterrupt:
        print("👋 Worker shut down by user.")
    except Exception as e:
        logger.exception(f"Worker crashed: {e}")
        sys.exit(1)
