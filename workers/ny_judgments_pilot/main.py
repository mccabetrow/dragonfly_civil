"""
NY Judgments Pilot Worker - Orchestrator

Main orchestration logic for the ingestion pipeline.
Coordinates: config -> connect -> idempotency -> scrape -> normalize -> insert -> finalize

EXIT CODES:
    0 = Success (or idempotent skip)
    1 = Failure (recoverable - will retry)
    2 = Fatal configuration error (no retry)
    3 = Scraper not implemented (expected during development)
    4 = Database unreachable (infrastructure issue)
"""

from __future__ import annotations

import logging
import sys
import traceback
from datetime import date, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from .config import WorkerConfig, load_config
from .db import (
    check_database_health,
    check_existing_run,
    create_import_run,
    get_connection,
    insert_judgments_raw_batch,
    update_run_to_completed,
    update_run_to_failed,
)
from .normalize import normalize_batch
from .scraper import NYSupremeCourtScraper, ScraperError, ScraperNotImplementedError

if TYPE_CHECKING:
    import psycopg


# ============================================================================
# Exit Codes
# ============================================================================

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_CONFIG_ERROR = 2
EXIT_SCRAPER_NOT_IMPLEMENTED = 3
EXIT_DB_UNREACHABLE = 4


# ============================================================================
# Logging Setup
# ============================================================================

logger = logging.getLogger(__name__)


def configure_logging(env: str) -> None:
    """
    Configure structured key=value logging for operators.

    Args:
        env: Environment (dev, staging, prod).
    """
    level = logging.DEBUG if env == "dev" else logging.INFO

    # Structured format: key=value pairs for log aggregators
    log_format = "%(asctime)s level=%(levelname)s logger=%(name)s " "%(message)s"

    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        stream=sys.stdout,
    )

    # Quiet noisy libraries
    for lib in ("httpx", "httpcore", "urllib3", "psycopg"):
        logging.getLogger(lib).setLevel(logging.WARNING)


# ============================================================================
# Orchestrator
# ============================================================================


def run_sync() -> int:
    """
    Synchronous entry point for the worker.

    Returns:
        Exit code (0-4).

    GUARANTEE: This function NEVER raises.
    All exceptions are caught, logged, and converted to exit codes.
    """
    config: WorkerConfig | None = None
    conn: psycopg.Connection | None = None
    run_id: UUID | None = None
    source_batch_id: str = ""

    try:
        # =================================================================
        # STEP 1: Load Configuration
        # =================================================================
        try:
            config = load_config()
            configure_logging(config.env)
        except Exception as e:
            # Can't log properly yet - use stderr
            print(
                f"FATAL config_error={e} hint='Check DATABASE_URL and ENV'",
                file=sys.stderr,
            )
            return EXIT_CONFIG_ERROR

        logger.info(
            "worker_start worker=%s version=%s env=%s",
            config.worker_name,
            config.worker_version,
            config.env,
        )

        # Generate deterministic batch ID
        source_batch_id = config.generate_source_batch_id()
        file_hash = f"batch_{source_batch_id}"  # Placeholder - real impl hashes source

        logger.info(
            "batch_id_generated source_batch_id=%s",
            source_batch_id,
        )

        # =================================================================
        # STEP 2: Connect to Database
        # =================================================================
        try:
            conn = get_connection(config.database_url)
            logger.info("db_connected application_name=ny_judgments_pilot")
        except Exception as e:
            logger.critical(
                "db_connection_failed error=%s",
                str(e)[:200],
            )
            return EXIT_DB_UNREACHABLE

        # Quick health check
        health = check_database_health(conn)
        if not all(health.values()):
            failed_tables = [t for t, ok in health.items() if not ok]
            logger.critical(
                "db_health_failed missing_tables=%s",
                ",".join(failed_tables),
            )
            return EXIT_DB_UNREACHABLE

        # =================================================================
        # STEP 3: Idempotency Check
        # =================================================================
        existing_run = check_existing_run(conn, source_batch_id)

        if existing_run:
            status = existing_run["status"]

            if status == "completed":
                logger.info(
                    "idempotent_skip reason=already_completed "
                    "existing_run_id=%s source_batch_id=%s",
                    existing_run["id"],
                    source_batch_id,
                )
                return EXIT_SUCCESS

            elif status == "processing":
                logger.info(
                    "idempotent_skip reason=in_progress " "existing_run_id=%s source_batch_id=%s",
                    existing_run["id"],
                    source_batch_id,
                )
                return EXIT_SUCCESS

            elif status == "failed":
                logger.info(
                    "retry_after_failure previous_run_id=%s source_batch_id=%s",
                    existing_run["id"],
                    source_batch_id,
                )
                # Continue to create new run

            elif status == "pending":
                logger.info(
                    "reclaim_pending_run run_id=%s source_batch_id=%s",
                    existing_run["id"],
                    source_batch_id,
                )
                # Continue to create new run

        # =================================================================
        # STEP 4: Create Import Run
        # =================================================================
        run_id = create_import_run(conn, source_batch_id, file_hash)
        logger.info("import_run_created run_id=%s", run_id)

        # =================================================================
        # STEP 5: Execute Scraper
        # =================================================================
        try:
            scraper = NYSupremeCourtScraper(config)

            # Date range: today - 7 days
            end_date = date.today()
            start_date = end_date - timedelta(days=7)

            logger.info(
                "scraper_start start_date=%s end_date=%s",
                start_date.isoformat(),
                end_date.isoformat(),
            )

            result = scraper.run_sync(start_date, end_date)

            logger.info(
                "scraper_complete records_fetched=%d pages_scraped=%d errors=%d",
                result.total_found,
                result.pages_scraped,
                len(result.errors),
            )

        except ScraperNotImplementedError as e:
            logger.warning(
                "scraper_not_implemented message='%s'",
                str(e),
            )

            update_run_to_failed(
                conn,
                run_id,
                source_batch_id,
                error_message=str(e),
                error_details={"exception_type": "ScraperNotImplementedError"},
            )

            # Exit 3 - scraper not implemented (expected during development)
            return EXIT_SCRAPER_NOT_IMPLEMENTED

        except ScraperError as e:
            logger.error("scraper_failed error=%s", str(e))

            update_run_to_failed(
                conn,
                run_id,
                source_batch_id,
                error_message=str(e),
                error_details={
                    "exception_type": "ScraperError",
                    "traceback": traceback.format_exc(),
                },
            )

            return EXIT_FAILURE

        # =================================================================
        # STEP 6: Normalize Records
        # =================================================================
        normalized, errors = normalize_batch(
            records=result.records,
            source_system="ny_ecourts",
            source_county=config.county,
        )

        logger.info(
            "normalize_complete normalized=%d errors=%d",
            len(normalized),
            len(errors),
        )

        if errors:
            for idx, err_msg in errors[:10]:  # Log first 10
                logger.warning(
                    "normalize_error index=%d error=%s",
                    idx,
                    err_msg,
                )

        # =================================================================
        # STEP 7: Insert Records
        # =================================================================
        if normalized:
            inserted, skipped = insert_judgments_raw_batch(
                conn=conn,
                records=normalized,
                ingest_run_id=run_id,
            )

            logger.info(
                "insert_complete inserted=%d skipped=%d",
                inserted,
                skipped,
            )
        else:
            inserted, skipped = 0, 0

        # =================================================================
        # STEP 8: Finalize Run
        # =================================================================
        update_run_to_completed(
            conn,
            run_id,
            total_rows=len(normalized),
            inserted_rows=inserted,
            skipped_rows=skipped,
            error_rows=len(errors),
        )

        logger.info(
            "worker_complete run_id=%s inserted=%d skipped=%d errors=%d",
            run_id,
            inserted,
            skipped,
            len(errors),
        )

        return EXIT_SUCCESS

    except Exception as e:
        # =================================================================
        # CATCH-ALL: Never crash the container
        # =================================================================
        logger.exception(
            "unhandled_exception error=%s type=%s",
            str(e)[:500],
            type(e).__name__,
        )

        # Try to mark run as failed
        if conn and run_id:
            try:
                update_run_to_failed(
                    conn,
                    run_id,
                    source_batch_id,
                    error_message=f"Unhandled: {str(e)[:300]}",
                    error_details={
                        "exception_type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    },
                )
            except Exception:
                pass  # Best effort

        return EXIT_FAILURE

    finally:
        # =================================================================
        # CLEANUP: Always close connection
        # =================================================================
        if conn:
            try:
                conn.close()
                logger.debug("db_connection_closed")
            except Exception:
                pass

        logger.info("worker_shutdown")


async def run() -> int:
    """
    Async wrapper for compatibility with existing __main__.py.

    The actual work is synchronous (psycopg3 sync API).
    """
    return run_sync()
