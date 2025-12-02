#!/usr/bin/env python3
"""CLI for running the call queue sync worker.

Synchronizes the call queue by ensuring every plaintiff who needs
a call has an open 'call' task via the upsert_plaintiff_task RPC.

Usage:
    # Run once (dry sync) against dev
    python -m tools.call_queue_worker --env dev --once

    # Run continuously (poll mode) against prod
    python -m tools.call_queue_worker --env prod --poll-interval 60

    # Verbose output
    python -m tools.call_queue_worker --env dev --once --verbose
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI output."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Reduce noise from httpx/httpcore
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Call queue sync worker - ensures plaintiffs have call tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Sync all plaintiffs once (dev)
    python -m tools.call_queue_worker --env dev --once

    # Run as a continuous worker (prod)
    python -m tools.call_queue_worker --env prod --poll-interval 300

    # Single plaintiff sync
    python -m tools.call_queue_worker --env dev --once --plaintiff-id <uuid>
        """,
    )

    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: SUPABASE_MODE or dev)",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (don't poll queue)",
    )

    parser.add_argument(
        "--poll-interval",
        type=int,
        default=60,
        help="Seconds between queue polls (default: 60)",
    )

    parser.add_argument(
        "--plaintiff-id",
        type=str,
        help="Sync a single plaintiff by ID",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    return parser.parse_args()


async def run_once(plaintiff_id: str | None = None, dry_run: bool = False) -> int:
    """Run the sync once and return exit code."""
    from workers.call_queue_sync_handler import (
        sync_all_call_tasks,
        fetch_single_plaintiff,
        upsert_call_task,
    )
    from src.supabase_client import create_supabase_client

    logger = logging.getLogger(__name__)

    if plaintiff_id:
        # Single plaintiff sync
        client = create_supabase_client()
        plaintiff = fetch_single_plaintiff(client, plaintiff_id)

        if not plaintiff:
            logger.error("plaintiff_not_found plaintiff_id=%s", plaintiff_id)
            return 1

        logger.info(
            "single_sync plaintiff_id=%s name=%s status=%s",
            plaintiff_id,
            plaintiff.get("plaintiff_name", "?"),
            plaintiff.get("status", "?"),
        )

        if dry_run:
            logger.info("dry_run skipping upsert for plaintiff_id=%s", plaintiff_id)
            return 0

        result = upsert_call_task(client, plaintiff_id)
        if result.get("success"):
            logger.info(
                "task_upserted task_id=%s is_new=%s",
                result.get("task_id"),
                result.get("is_new"),
            )
            return 0
        else:
            logger.error("upsert_failed error=%s", result.get("error"))
            return 1

    else:
        # Full sync
        logger.info("batch_sync_start")

        if dry_run:
            from workers.call_queue_sync_handler import fetch_plaintiffs_needing_calls

            client = create_supabase_client()
            plaintiffs = fetch_plaintiffs_needing_calls(client)
            logger.info("dry_run would_sync_count=%d", len(plaintiffs))
            for p in plaintiffs[:10]:
                logger.info(
                    "  - %s (%s) status=%s",
                    p.get("plaintiff_name", "?"),
                    p["plaintiff_id"][:8],
                    p.get("status", "?"),
                )
            if len(plaintiffs) > 10:
                logger.info("  ... and %d more", len(plaintiffs) - 10)
            return 0

        result = await sync_all_call_tasks()

        logger.info(
            "batch_sync_complete total=%d success=%d failed=%d created=%d updated=%d",
            result["total_plaintiffs"],
            result["success_count"],
            result["failure_count"],
            result["created_count"],
            result["updated_count"],
        )

        return 0 if result["failure_count"] == 0 else 1


async def poll_queue(interval: int) -> None:
    """Poll the PGMQ queue for call_queue_sync jobs."""
    from workers.call_queue_sync_handler import handle_call_queue_sync
    from src.supabase_client import create_supabase_client

    logger = logging.getLogger(__name__)
    logger.info("poll_start kind=call_queue_sync interval=%ds", interval)

    client = create_supabase_client()

    while True:
        try:
            # Dequeue one job
            response = client.rpc(
                "dequeue_job",
                {"queue_kind": "call_queue_sync", "vt": 300},
            ).execute()

            job = response.data

            if job:
                msg_id = job.get("msg_id", "?")
                logger.info("job_dequeued kind=call_queue_sync msg_id=%s", msg_id)

                success = await handle_call_queue_sync(job)

                if success:
                    # Delete completed job
                    client.rpc(
                        "delete_job",
                        {"queue_kind": "call_queue_sync", "p_msg_id": msg_id},
                    ).execute()
                    logger.info("job_deleted kind=call_queue_sync msg_id=%s", msg_id)

            else:
                logger.debug("no_jobs_available kind=call_queue_sync")

        except Exception as e:
            logger.exception("poll_error kind=call_queue_sync")

        await asyncio.sleep(interval)


def main() -> int:
    """Main entry point."""
    args = parse_args()

    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env
    logger.info("call_queue_worker env=%s", args.env)

    try:
        if args.once:
            return asyncio.run(run_once(args.plaintiff_id, args.dry_run))
        else:
            asyncio.run(poll_queue(args.poll_interval))
            return 0  # Never reached in poll mode

    except KeyboardInterrupt:
        logger.info("worker_shutdown signal=interrupt")
        return 0
    except Exception as e:
        logger.exception("worker_fatal")
        return 1


if __name__ == "__main__":
    sys.exit(main())
