"""CLI runner for the judgment enrichment worker.

This script starts a PGMQ-based worker loop that processes ``judgment_enrich``
jobs.  Each job fetches judgment data, calls the configured skip-trace vendor,
logs FCRA access via RPC, persists intelligence via RPC, and updates
collectability scores atomically.

The worker uses the ``complete_enrichment`` RPC to ensure all mutations
(FCRA audit, intelligence upsert, status update) occur in a single transaction.

Usage::

    # Run continuously
    python -m tools.enrich_worker --env dev

    # Process a single job and exit
    python -m tools.enrich_worker --env dev --once

    # With debug logging
    python -m tools.enrich_worker --env dev --verbose

Or run via VS Code task "Workers: Enrichment (Dev)".
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
        description="Run the judgment enrichment worker loop.",
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
    from workers.judgment_enrich_handler import handle_judgment_enrich
    from workers.runner import worker_loop

    env = get_supabase_env()
    logger.info("Starting enrichment worker (env=%s, once=%s)", env, args.once)

    try:
        if args.once:
            # Process a single job and exit
            asyncio.run(_run_once())
        else:
            # Run the worker loop indefinitely
            asyncio.run(
                worker_loop(
                    kind="judgment_enrich",
                    handler=handle_judgment_enrich,
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
    """Process a single enrichment job (for testing)."""
    from workers.judgment_enrich_handler import handle_judgment_enrich
    from workers.queue_client import QueueClient

    with QueueClient() as qc:
        job = qc.dequeue("judgment_enrich")
        if not job:
            logger.info("No pending enrichment jobs")
            return

        msg_id = job.get("msg_id")
        payload = job.get("payload") or job.get("body") or {}

        logger.info("Processing job %s: %s", msg_id, payload)
        try:
            await handle_judgment_enrich(payload)
            if msg_id:
                qc.ack("judgment_enrich", msg_id)
            logger.info("Job %s completed successfully", msg_id)
        except Exception as exc:
            logger.error("Job %s failed: %s", msg_id, exc)
            raise


if __name__ == "__main__":
    sys.exit(main())
