"""CLI runner for the tier assignment worker.

Usage:
    python -m tools.tier_worker [OPTIONS]

Options:
    --env dev|prod          Supabase environment (default: dev)
    --once                  Process one job then exit
    --verbose               Enable debug logging
    --poll-interval SECS    Seconds between polls (default: 30)
    --help                  Show this message

Examples:
    # Process one job (dev) with verbose logging
    python -m tools.tier_worker --env dev --once --verbose

    # Run continuous polling (prod) every 60 seconds
    python -m tools.tier_worker --env prod --poll-interval 60
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workers.tier_assignment_handler import handle_tier_assignment
from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)

QUEUE_KIND = "tier_assignment"
DEFAULT_POLL_INTERVAL = 30


def configure_logging(verbose: bool = False):
    """Configure structured logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Suppress noisy httpx logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def dequeue_job(client, kind: str) -> dict | None:
    """Dequeue one job from the queue via RPC."""
    try:
        response = client.rpc("dequeue_job", {"kind": kind}).execute()
        if response.data:
            return response.data
        return None
    except Exception as e:
        logger.error("dequeue_job_failed kind=%s error=%s", kind, e)
        return None


def delete_job(client, msg_id: int, kind: str = QUEUE_KIND) -> bool:
    """Acknowledge/delete a processed job from the queue."""
    try:
        client.rpc("pgmq_delete", {"queue_name": kind, "msg_id": msg_id}).execute()
        return True
    except Exception as e:
        logger.error("pgmq_delete_failed kind=%s msg_id=%s error=%s", kind, msg_id, e)
        return False


async def process_one(client) -> bool:
    """Process a single job from the queue.

    Returns:
        True if a job was processed, False if queue was empty
    """
    job = dequeue_job(client, QUEUE_KIND)
    if not job:
        logger.debug("tier_worker_no_jobs kind=%s", QUEUE_KIND)
        return False

    msg_id = job.get("msg_id")
    logger.info("tier_worker_dequeued kind=%s msg_id=%s", QUEUE_KIND, msg_id)

    try:
        success = await handle_tier_assignment(job)
        if success:
            delete_job(client, msg_id)
            logger.info("tier_worker_acked kind=%s msg_id=%s", QUEUE_KIND, msg_id)
        else:
            logger.warning("tier_worker_retry kind=%s msg_id=%s", QUEUE_KIND, msg_id)
        return True
    except Exception as e:
        logger.exception(
            "tier_worker_handler_error kind=%s msg_id=%s", QUEUE_KIND, msg_id
        )
        # Delete even on error to avoid infinite retry loops on bad data
        delete_job(client, msg_id)
        return True


async def run_worker(once: bool = False, poll_interval: int = DEFAULT_POLL_INTERVAL):
    """Main worker loop.

    Args:
        once: If True, process one job and exit
        poll_interval: Seconds between queue polls (continuous mode)
    """
    logger.info(
        "tier_worker_start kind=%s once=%s poll_interval=%d env=%s",
        QUEUE_KIND,
        once,
        poll_interval,
        os.environ.get("SUPABASE_MODE", "dev"),
    )

    client = create_supabase_client()

    if once:
        processed = await process_one(client)
        if not processed:
            logger.info("tier_worker_queue_empty kind=%s", QUEUE_KIND)
        return

    # Continuous polling mode
    consecutive_empty = 0
    while True:
        try:
            processed = await process_one(client)
            if processed:
                consecutive_empty = 0
                # Small delay between jobs to avoid hammering
                await asyncio.sleep(1)
            else:
                consecutive_empty += 1
                # Log periodic heartbeat every 10 empty polls
                if consecutive_empty % 10 == 0:
                    logger.debug(
                        "tier_worker_polling kind=%s empty_polls=%d",
                        QUEUE_KIND,
                        consecutive_empty,
                    )
                await asyncio.sleep(poll_interval)
        except KeyboardInterrupt:
            logger.info("tier_worker_shutdown kind=%s", QUEUE_KIND)
            break
        except Exception as e:
            logger.exception("tier_worker_loop_error kind=%s", QUEUE_KIND)
            await asyncio.sleep(poll_interval)


def main():
    parser = argparse.ArgumentParser(
        description="Tier assignment worker - assigns enforcement tiers to judgments"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Supabase environment (default: dev)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one job then exit",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds between queue polls (default: {DEFAULT_POLL_INTERVAL})",
    )

    args = parser.parse_args()

    # Set environment before importing supabase client
    os.environ["SUPABASE_MODE"] = args.env

    configure_logging(args.verbose)

    logger.info("tier_worker_init env=%s", args.env)

    asyncio.run(run_worker(once=args.once, poll_interval=args.poll_interval))


if __name__ == "__main__":
    main()
