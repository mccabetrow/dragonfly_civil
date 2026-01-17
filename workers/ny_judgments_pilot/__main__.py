"""
NY Judgments Pilot Worker - Canonical Entrypoint

CRON JOB DISCIPLINE:
    This module enables running the worker as a disciplined cron job via:
        python -m workers.ny_judgments_pilot

    This is the ONLY supported way to run this worker.
    Do not use standalone scripts or import main() directly.

EXIT CODES:
    0 = Success (or idempotent skip - job already done)
    1 = Failure (recoverable - will retry next cron)
    2 = Fatal configuration error (needs human intervention)
    3 = Scraper not implemented (expected during development)
    4 = Database unreachable (infrastructure issue)

EXCEPTION HANDLING:
    - SystemExit: Re-raised to preserve exit code
    - Exception: Logged as CRITICAL, sys.exit(1)

ZERO DRIFT POLICY:
    The DSN Guard validates DATABASE_URL matches ENV before any DB connection.
    Mismatches exit with code 2 immediately.

Author: Principal Site Reliability Engineer
Date: 2026-01-15
"""

import sys

from loguru import logger


def main() -> None:
    """
    Canonical entrypoint for the NY Judgments Pilot Worker.

    Uses synchronous execution (psycopg3 sync API).
    Exits with appropriate code (0-4).
    """
    try:
        # Load config first - this runs DSN Guard
        from .config import load_config

        config = load_config()

        # Execute worker
        from .worker import run_worker

        exit_code = run_worker(config)

        sys.exit(exit_code)

    except SystemExit:
        # Re-raise to preserve exit code (from DSN Guard or worker)
        raise

    except Exception as e:
        logger.critical(f"Fatal error in worker: {e}")
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
