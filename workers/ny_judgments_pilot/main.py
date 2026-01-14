"""
NY Judgments Pilot Worker - Main Orchestration

Coordinates config, scraping, normalization, and database operations.

Usage:
    python -m workers.ny_judgments_pilot

Exit codes:
    0 - Success (all records processed)
    1 - Partial success (some records failed)
    2 - Configuration error
    3 - Database error
    4 - Source/scraper error

Note:
    The canonical entrypoint is __main__.py, not this file.
    This module exports run() which returns an exit code.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

# Local imports - these modules contain the actual logic
from .config import ConfigError, WorkerConfig, load_config
from .db import (
    DEFAULT_BATCH_SIZE,
    IngestRunStats,
    InsertResult,
    create_ingest_run,
    finalize_ingest_run,
    get_connection,
    get_last_ingest_run,
    upsert_judgment_raw_batch,
)
from .normalize import normalize_record, prepare_for_insert
from .scraper import FetchResult, ScraperError, fetch_judgments

# ============================================================================
# Exit Codes
# ============================================================================

EXIT_SUCCESS = 0
EXIT_PARTIAL = 1
EXIT_CONFIG_ERROR = 2
EXIT_DB_ERROR = 3
EXIT_SOURCE_ERROR = 4

# ============================================================================
# Safety Caps
# ============================================================================

MAX_RECORDS_PER_RUN = 5000

# ============================================================================
# Logging Setup
# ============================================================================

logger = logging.getLogger(__name__)


def configure_logging(log_level: str) -> None:
    """Configure structured logging for the worker."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    # JSON-like structured format for production parsing
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    logging.basicConfig(
        level=level,
        format=log_format,
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
    )

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ============================================================================
# Delta Window Calculation
# ============================================================================


@dataclass
class DateWindow:
    """Date range for fetching judgments."""

    start_date: datetime
    end_date: datetime
    is_backfill: bool = False

    def __str__(self) -> str:
        return f"{self.start_date.date()} to {self.end_date.date()}"


def compute_delta_window(
    config: WorkerConfig,
    last_run_finished_at: datetime | None,
) -> DateWindow:
    """
    Compute the date window for fetching judgments.

    Logic:
    - If no previous run: use PILOT_RANGE_MONTHS for initial backfill
    - If previous run exists: use DELTA_LOOKBACK_DAYS from last run

    Args:
        config: Worker configuration.
        last_run_finished_at: When the last successful run finished.

    Returns:
        DateWindow with start_date, end_date, and backfill flag.
    """
    now = datetime.now(timezone.utc)
    end_date = now

    if last_run_finished_at is None:
        # Initial backfill - use PILOT_RANGE_MONTHS
        start_date = now - timedelta(days=config.pilot_range_months * 30)
        is_backfill = True
        logger.info(
            "[WINDOW] Initial backfill",
            extra={
                "range_months": config.pilot_range_months,
                "start_date": str(start_date.date()),
                "end_date": str(end_date.date()),
            },
        )
    else:
        # Delta run - overlap by DELTA_LOOKBACK_DAYS
        start_date = last_run_finished_at - timedelta(days=config.delta_lookback_days)
        is_backfill = False
        logger.info(
            "[WINDOW] Delta run",
            extra={
                "lookback_days": config.delta_lookback_days,
                "last_run": str(last_run_finished_at),
                "start_date": str(start_date.date()),
                "end_date": str(end_date.date()),
            },
        )

    return DateWindow(
        start_date=start_date,
        end_date=end_date,
        is_backfill=is_backfill,
    )


# ============================================================================
# Record Processing
# ============================================================================


def process_records(
    raw_records: list[dict],
    config: WorkerConfig,
    ingest_run_id: UUID,
) -> tuple[list[dict], list[dict]]:
    """
    Normalize raw records for database insertion.

    Args:
        raw_records: Raw records from scraper.
        config: Worker configuration.
        ingest_run_id: UUID of current ingest run.

    Returns:
        Tuple of (normalized_records, failed_records).
    """
    normalized = []
    failed = []

    for raw in raw_records:
        try:
            # Normalize the record
            record = normalize_record(raw, config.source_system)

            # Prepare for insertion (add runtime fields)
            prepared = prepare_for_insert(record, ingest_run_id)

            normalized.append(prepared)

        except Exception as e:
            failed.append(
                {
                    "raw": raw,
                    "error": f"{type(e).__name__}: {str(e)[:200]}",
                }
            )
            logger.warning(
                "[NORMALIZE] Record failed",
                extra={
                    "error": str(e)[:200],
                    "external_id": raw.get("external_id", "unknown"),
                },
            )

    logger.info(
        "[NORMALIZE] Complete",
        extra={
            "total": len(raw_records),
            "normalized": len(normalized),
            "failed": len(failed),
        },
    )

    return normalized, failed


def batch_insert(
    conn,
    records: list[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> InsertResult:
    """
    Insert records in batches, accumulating results.

    Args:
        conn: Database connection.
        records: Normalized records to insert.
        batch_size: Records per batch.

    Returns:
        Aggregated InsertResult.
    """
    total_result = InsertResult()

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(records) + batch_size - 1) // batch_size

        logger.debug(
            "[INSERT] Processing batch",
            extra={
                "batch": batch_num,
                "total_batches": total_batches,
                "batch_size": len(batch),
            },
        )

        result = upsert_judgment_raw_batch(conn, batch)
        total_result = total_result.merge(result)

    logger.info(
        "[INSERT] Complete",
        extra={
            "inserted": total_result.inserted,
            "skipped": total_result.skipped,
            "errored": total_result.errored,
        },
    )

    return total_result


# ============================================================================
# Main Execution
# ============================================================================


def run() -> int:
    """
    Execute the ingestion workflow.

    Returns:
        Exit code (0=success, 1=partial, 2=config, 3=db, 4=source).
    """
    ingest_run_id: UUID | None = None
    conn = None
    stats = IngestRunStats()

    # -------------------------------------------------------------------------
    # Phase 1: Load Configuration
    # -------------------------------------------------------------------------
    try:
        config = load_config()
        configure_logging(config.log_level)
    except ConfigError as e:
        # Can't log properly yet, use print
        print(f"[FATAL] Configuration error: {e}", file=sys.stderr)
        return EXIT_CONFIG_ERROR

    logger.info(
        "[START] NY Judgments Pilot Worker",
        extra={
            "worker_name": config.worker_name,
            "worker_version": config.worker_version,
            "env": config.env,
            "source_system": config.source_system,
            "pilot_county": config.pilot_county,
            "pilot_court": config.pilot_court,
        },
    )

    # -------------------------------------------------------------------------
    # Phase 2: Database Connection
    # -------------------------------------------------------------------------
    try:
        conn = get_connection(config.database_url)
    except Exception as e:
        logger.critical(
            "[FATAL] Database connection failed",
            extra={"error": str(e)},
        )
        return EXIT_DB_ERROR

    # -------------------------------------------------------------------------
    # Phase 3: Create Ingest Run
    # -------------------------------------------------------------------------
    try:
        ingest_run_id = create_ingest_run(conn, config)
    except Exception as e:
        logger.critical(
            "[FATAL] Failed to create ingest run",
            extra={"error": str(e)},
        )
        if conn:
            conn.close()
        return EXIT_DB_ERROR

    # -------------------------------------------------------------------------
    # From here on, we MUST finalize the ingest run
    # -------------------------------------------------------------------------
    final_status = "completed"
    error_message: str | None = None
    error_details: dict | None = None

    try:
        # ---------------------------------------------------------------------
        # Phase 4: Compute Delta Window
        # ---------------------------------------------------------------------
        last_run = get_last_ingest_run(
            conn,
            worker_name=config.worker_name,
            source_system=config.source_system,
            source_county=config.pilot_county,
        )

        last_run_finished = last_run["finished_at"] if last_run else None
        window = compute_delta_window(config, last_run_finished)

        # ---------------------------------------------------------------------
        # Phase 5: Fetch Records from Source
        # ---------------------------------------------------------------------
        logger.info(
            "[FETCH] Starting",
            extra={
                "window": str(window),
                "is_backfill": window.is_backfill,
            },
        )

        fetch_result: FetchResult = fetch_judgments(
            config=config,
            start_date=window.start_date,
            end_date=window.end_date,
        )

        stats.records_fetched = len(fetch_result.records)

        if fetch_result.errors:
            logger.warning(
                "[FETCH] Completed with errors",
                extra={
                    "fetched": stats.records_fetched,
                    "errors": len(fetch_result.errors),
                },
            )

        # Safety cap check
        if stats.records_fetched > MAX_RECORDS_PER_RUN:
            logger.warning(
                "[FETCH] Safety cap exceeded, truncating",
                extra={
                    "fetched": stats.records_fetched,
                    "cap": MAX_RECORDS_PER_RUN,
                },
            )
            fetch_result.records = fetch_result.records[:MAX_RECORDS_PER_RUN]
            stats.records_fetched = MAX_RECORDS_PER_RUN

        # ---------------------------------------------------------------------
        # Phase 6: Normalize Records
        # ---------------------------------------------------------------------
        if fetch_result.records:
            normalized, normalize_failed = process_records(
                fetch_result.records,
                config,
                ingest_run_id,
            )

            stats.records_errored += len(normalize_failed)

            # -----------------------------------------------------------------
            # Phase 7: Insert Records
            # -----------------------------------------------------------------
            if normalized:
                insert_result = batch_insert(conn, normalized)

                stats.records_inserted = insert_result.inserted
                stats.records_skipped = insert_result.skipped
                stats.records_errored += insert_result.errored

                if insert_result.errors:
                    error_details = {"insert_errors": insert_result.errors[:10]}

        # Determine final status
        if stats.records_errored > 0:
            final_status = "partial"
        elif stats.records_fetched == 0:
            final_status = "completed"  # Empty run is still success

    except ScraperError as e:
        final_status = "failed"
        error_message = f"Scraper error: {str(e)[:500]}"
        error_details = {"scraper_error": str(e), "error_type": type(e).__name__}
        logger.error(
            "[FATAL] Scraper failed",
            extra={"error": str(e)},
        )

    except Exception as e:
        final_status = "failed"
        error_message = f"Unexpected error: {str(e)[:500]}"
        error_details = {"exception": str(e), "exception_type": type(e).__name__}
        logger.exception(
            "[FATAL] Unexpected error",
            extra={"error": str(e)},
        )

    # -------------------------------------------------------------------------
    # Phase 8: Finalize Ingest Run (ALWAYS executes)
    # -------------------------------------------------------------------------
    finally:
        if ingest_run_id and conn:
            try:
                finalize_ingest_run(
                    conn,
                    ingest_run_id,
                    stats,
                    final_status,
                    error_message,
                    error_details,
                )
            except Exception as e:
                logger.error(
                    "[FATAL] Failed to finalize ingest run",
                    extra={
                        "ingest_run_id": str(ingest_run_id),
                        "error": str(e),
                    },
                )

        if conn:
            try:
                conn.close()
                logger.debug("[DB] Connection closed")
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Phase 9: Log Summary and Exit
    # -------------------------------------------------------------------------
    logger.info(
        "[SUMMARY] Worker complete",
        extra={
            "ingest_run_id": str(ingest_run_id) if ingest_run_id else None,
            "status": final_status,
            "records_fetched": stats.records_fetched,
            "records_inserted": stats.records_inserted,
            "records_skipped": stats.records_skipped,
            "records_errored": stats.records_errored,
        },
    )

    # Map status to exit code
    if final_status == "completed":
        return EXIT_SUCCESS
    elif final_status == "partial":
        return EXIT_PARTIAL
    elif error_message and "scraper" in error_message.lower():
        return EXIT_SOURCE_ERROR
    else:
        return EXIT_DB_ERROR


# Note: Entry point is in __main__.py
# Run via: python -m workers.ny_judgments_pilot
