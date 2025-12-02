"""CLI runner for the enforcement action worker.

This script starts a PGMQ-based worker loop that processes ``enforcement_action``
jobs. Each job reads a judgment's enrichment data and determines appropriate
enforcement actions (levy, garnishment, subpoena, etc.) to plan.

The worker uses the ``log_enforcement_action`` RPC to persist actions
atomically in the enforcement_actions table.

Usage::

    # Run continuously
    python -m tools.enforcement_action_worker --env dev

    # Process a single job and exit
    python -m tools.enforcement_action_worker --env dev --once

    # With debug logging
    python -m tools.enforcement_action_worker --env dev --verbose

Or run via VS Code task "Workers: Enforcement Action (Dev)".
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Optional, Sequence

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the enforcement action worker loop.",
        epilog="Set SUPABASE_MODE=dev|prod or use --env to target an environment.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Supabase environment to target (defaults to SUPABASE_MODE env var).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process a single job and exit (useful for testing).",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Seconds between queue polls (default: 2.0).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    # Set environment before imports that read SUPABASE_MODE
    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Late import to honor SUPABASE_MODE
    from src.supabase_client import get_supabase_env
    from workers.enforcement_action_handler import handle_enforcement_action
    from workers.runner import worker_loop

    env = get_supabase_env()
    logger.info("Starting enforcement action worker (env=%s, once=%s)", env, args.once)

    try:
        if args.once:
            # Process a single job and exit
            asyncio.run(_run_once())
        else:
            # Run the worker loop indefinitely
            asyncio.run(
                worker_loop(
                    kind="enforcement_action",
                    handler=handle_enforcement_action,
                    poll_interval=args.poll_interval,
                )
            )
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as exc:
        logger.exception("Worker failed: %s", exc)
        return 1

    return 0


async def _run_once() -> None:
    """Process a single enforcement action job (for testing)."""
    from workers.enforcement_action_handler import handle_enforcement_action
    from workers.queue_client import QueueClient

    with QueueClient() as qc:
        job = qc.dequeue("enforcement_action")
        if not job:
            logger.info("No pending enforcement action jobs")
            return

        msg_id = job.get("msg_id")
        payload = job.get("payload") or job.get("body") or {}

        logger.info("Processing job %s: %s", msg_id, payload)
        try:
            await handle_enforcement_action(job)
            if msg_id:
                qc.ack("enforcement_action", msg_id)
            logger.info("Job %s completed successfully", msg_id)
        except Exception as exc:
            logger.error("Job %s failed: %s", msg_id, exc)
            raise


if __name__ == "__main__":
    sys.exit(main())
