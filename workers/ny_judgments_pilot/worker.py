"""
NY Judgments Pilot Worker - Core Worker Logic

CRON JOB DISCIPLINE:
    - Exit 0 = Success (including idempotent skip)
    - Exit 1 = Failure (recoverable - will retry next cron)
    - Exit 2 = Fatal configuration error (no retry until fixed)
    - Exit 3 = Scraper not implemented (expected stub state)
    - Exit 4 = Database unreachable (infrastructure issue)

IDEMPOTENCY (The Data Moat):
    Every run is tracked in ingest.import_runs:
    - source_batch_id: ny_judgments_{YYYY-MM-DD}
    - If already completed: Log "Duplicate Run", exit(0) - job already done
    - If processing: Log "Stale/Overlap", exit(0) - skip, let other complete
    - If new: Claim run → Execute scraper → Mark completed/failed

Author: Principal Site Reliability Engineer
Date: 2026-01-15
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import psycopg
from loguru import logger

from .config import WorkerConfig

# =============================================================================
# Exit Codes (Railway Cron Job Semantics)
# =============================================================================

EXIT_SUCCESS = 0  # Job completed successfully (or idempotent skip)
EXIT_FAILURE = 1  # Recoverable failure (will retry next cron)
EXIT_CONFIG_ERROR = 2  # Fatal config error (needs human intervention)
EXIT_SCRAPER_STUB = 3  # Scraper not implemented (expected during dev)
EXIT_DB_UNREACHABLE = 4  # Database unreachable (infrastructure issue)


# =============================================================================
# Import Run Status
# =============================================================================


@dataclass
class ImportRunStatus:
    """Status of an import run from ingest.import_runs."""

    run_id: Optional[str] = None
    status: Optional[str] = None  # 'processing', 'completed', 'failed'
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    row_count: int = 0


# =============================================================================
# Database Operations
# =============================================================================


def check_existing_run(conn: psycopg.Connection, source_batch_id: str) -> ImportRunStatus:
    """
    Check if a run already exists for this source_batch_id.

    Returns:
        ImportRunStatus with status if found, or status=None if not found.
    """
    result = conn.execute(
        """
        SELECT
            id::text,
            status,
            started_at,
            completed_at,
            error_message,
            COALESCE(row_count, 0) as row_count
        FROM ingest.import_runs
        WHERE source_batch_id = %s
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (source_batch_id,),
    ).fetchone()

    if result is None:
        return ImportRunStatus()

    return ImportRunStatus(
        run_id=result[0],
        status=result[1],
        started_at=result[2],
        completed_at=result[3],
        error_message=result[4],
        row_count=result[5],
    )


def claim_import_run(conn: psycopg.Connection, source_batch_id: str) -> Optional[str]:
    """
    Attempt to claim an import run (atomic insert).

    Uses INSERT ... ON CONFLICT DO NOTHING to ensure only one worker
    can claim a batch.

    Returns:
        Run ID if successfully claimed, None if already claimed by another.
    """
    result = conn.execute(
        """
        INSERT INTO ingest.import_runs (source_batch_id, status, started_at)
        VALUES (%s, 'processing', NOW())
        ON CONFLICT (source_batch_id) DO NOTHING
        RETURNING id::text
        """,
        (source_batch_id,),
    ).fetchone()

    return result[0] if result else None


def mark_run_completed(
    conn: psycopg.Connection,
    run_id: str,
    row_count: int = 0,
) -> None:
    """Mark an import run as completed."""
    conn.execute(
        """
        UPDATE ingest.import_runs
        SET status = 'completed',
            completed_at = NOW(),
            row_count = %s
        WHERE id = %s::uuid
        """,
        (row_count, run_id),
    )


def mark_run_failed(
    conn: psycopg.Connection,
    run_id: str,
    error_message: str,
) -> None:
    """Mark an import run as failed."""
    conn.execute(
        """
        UPDATE ingest.import_runs
        SET status = 'failed',
            completed_at = NOW(),
            error_message = %s
        WHERE id = %s::uuid
        """,
        (error_message, run_id),
    )


# =============================================================================
# Scraper Execution
# =============================================================================


def execute_scraper(config: WorkerConfig) -> tuple[int, int]:
    """
    Execute the scraper and return (exit_code, row_count).

    Returns:
        Tuple of (exit_code, row_count)
        - exit_code 0 = success
        - exit_code 3 = NotImplementedError (scraper stub)
        - exit_code 1 = other error
    """
    from .scraper import NYSupremeCourtScraper, ScraperNotImplementedError

    try:
        scraper = NYSupremeCourtScraper(county=config.county or "kings")
        result = scraper.run()

        logger.info(f"Scraper completed: {result.records_fetched} records fetched")
        return EXIT_SUCCESS, result.records_fetched

    except ScraperNotImplementedError as e:
        # Expected during development - scraper is a stub
        logger.warning(f"Scraper not implemented: {e}")
        return EXIT_SCRAPER_STUB, 0

    except Exception as e:
        logger.error(f"Scraper failed: {e}")
        return EXIT_FAILURE, 0


# =============================================================================
# Main Worker Orchestration
# =============================================================================


def run_worker(config: WorkerConfig) -> int:
    """
    Execute the NY Judgments Pilot Worker with full idempotency.

    Flow:
        1. Generate source_batch_id (ny_judgments_{date})
        2. Check ingest.import_runs for existing run
        3. If completed: exit(0) - duplicate, job already done
        4. If processing: exit(0) - stale/overlap, skip
        5. If new: claim run → execute scraper → update status

    Returns:
        Exit code (0-4)
    """
    source_batch_id = config.generate_source_batch_id()

    logger.info("=" * 60)
    logger.info(f"NY Judgments Pilot Worker v{config.worker_version}")
    logger.info(f"Environment: {config.env}")
    logger.info(f"Source Batch ID: {source_batch_id}")
    logger.info("=" * 60)

    # =========================================================================
    # Step 1: Connect to database
    # =========================================================================
    try:
        conn = psycopg.connect(config.database_url)
        logger.info("Database connection established")
    except psycopg.OperationalError as e:
        logger.critical(f"Database unreachable: {e}")
        return EXIT_DB_UNREACHABLE
    except Exception as e:
        logger.critical(f"Database connection failed: {e}")
        return EXIT_DB_UNREACHABLE

    try:
        # =====================================================================
        # Step 2: Check for existing run (idempotency check)
        # =====================================================================
        existing = check_existing_run(conn, source_batch_id)

        if existing.status == "completed":
            logger.info(
                f"Duplicate run detected: {source_batch_id} already completed "
                f"at {existing.completed_at} with {existing.row_count} rows"
            )
            logger.info("Exiting with success (idempotent skip)")
            return EXIT_SUCCESS

        if existing.status == "processing":
            elapsed = datetime.now(timezone.utc) - (
                existing.started_at.replace(tzinfo=timezone.utc)
                if existing.started_at
                else datetime.now(timezone.utc)
            )
            logger.warning(
                f"Stale/overlapping run detected: {source_batch_id} "
                f"has been processing for {elapsed}"
            )
            # TODO: Consider adding a timeout to mark stale runs as failed
            logger.info("Exiting with success (skip overlap)")
            return EXIT_SUCCESS

        # =====================================================================
        # Step 3: Claim the run (atomic)
        # =====================================================================
        run_id = claim_import_run(conn, source_batch_id)

        if run_id is None:
            # Race condition: another worker claimed it between check and claim
            logger.info(f"Run already claimed by another worker: {source_batch_id}")
            return EXIT_SUCCESS

        conn.commit()  # Commit the claim before executing scraper
        logger.info(f"Import run claimed: {run_id}")

        # =====================================================================
        # Step 4: Execute scraper
        # =====================================================================
        exit_code, row_count = execute_scraper(config)

        # =====================================================================
        # Step 5: Update run status based on result
        # =====================================================================
        if exit_code == EXIT_SUCCESS:
            mark_run_completed(conn, run_id, row_count)
            conn.commit()
            logger.info(f"Run completed successfully: {row_count} records processed")
            return EXIT_SUCCESS

        elif exit_code == EXIT_SCRAPER_STUB:
            mark_run_failed(conn, run_id, "Scraper not implemented (stub)")
            conn.commit()
            logger.warning(
                "Run marked as failed: Scraper not implemented. "
                "This is expected during development."
            )
            return EXIT_SCRAPER_STUB

        else:
            mark_run_failed(conn, run_id, f"Scraper failed with exit code {exit_code}")
            conn.commit()
            logger.error(f"Run failed with exit code {exit_code}")
            return exit_code

    except Exception as e:
        logger.exception(f"Unexpected error during worker execution: {e}")
        return EXIT_FAILURE

    finally:
        conn.close()
        logger.debug("Database connection closed")
