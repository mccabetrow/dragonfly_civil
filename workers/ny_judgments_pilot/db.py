"""
NY Judgments Pilot Worker - Database Operations

All database operations for the ingestion worker.
Uses psycopg3 (sync) for simplicity - this is a batch worker, not an API.

Design decisions:
- psycopg3 (sync) chosen over asyncpg because:
  1. Worker is synchronous by design (run once, exit)
  2. No concurrent requests to benefit from async
  3. Simpler error handling and debugging
  4. Matches existing backend/db.py patterns

- Explicit transactions for:
  1. Batch inserts (commit per batch, not per record)
  2. Ingest run lifecycle (start/end in separate transactions)

- ON CONFLICT DO NOTHING for idempotent upserts
  (we don't update existing records - append-only landing zone)
"""

from __future__ import annotations

import logging
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .config import WorkerConfig

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

# Application name for Postgres connection (visible in pg_stat_activity)
APP_NAME = "dragonfly_ny_pilot"

# Batch size for inserts (balance between memory and transaction size)
DEFAULT_BATCH_SIZE = 100


# ============================================================================
# Data Types
# ============================================================================


@dataclass
class InsertResult:
    """Result of a batch insert operation."""

    inserted: int = 0
    skipped: int = 0  # Duplicates (ON CONFLICT DO NOTHING)
    errored: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    def merge(self, other: "InsertResult") -> "InsertResult":
        """Merge another result into this one."""
        return InsertResult(
            inserted=self.inserted + other.inserted,
            skipped=self.skipped + other.skipped,
            errored=self.errored + other.errored,
            errors=self.errors + other.errors,
        )


@dataclass
class IngestRunStats:
    """Statistics for an ingest run."""

    records_fetched: int = 0
    records_inserted: int = 0
    records_skipped: int = 0
    records_errored: int = 0


# ============================================================================
# Connection Management
# ============================================================================


def get_connection(dsn: str, *, autocommit: bool = False) -> psycopg.Connection:
    """
    Create a database connection with standard settings.

    Args:
        dsn: PostgreSQL connection string.
        autocommit: If True, disable transaction blocks.

    Returns:
        psycopg.Connection configured for this worker.

    Raises:
        psycopg.OperationalError: If connection fails.
    """
    # Build connection options
    # Note: Supabase pooler (port 6543) doesn't support 'options' parameter
    conn = psycopg.connect(
        dsn,
        autocommit=autocommit,
        row_factory=dict_row,
        application_name=APP_NAME,
        connect_timeout=10,
    )

    logger.info(
        "[DB] Connected",
        extra={
            "host": _extract_host(dsn),
            "application_name": APP_NAME,
        },
    )

    return conn


def _extract_host(dsn: str) -> str:
    """Extract host from DSN for logging (no credentials)."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(dsn)
        return parsed.hostname or "unknown"
    except Exception:
        return "unknown"


# ============================================================================
# Ingest Run Management
# ============================================================================


def create_ingest_run(
    conn: psycopg.Connection,
    config: WorkerConfig,
) -> UUID:
    """
    Create a new ingest run record at the start of execution.

    Args:
        conn: Database connection.
        config: Worker configuration.

    Returns:
        UUID of the created ingest run.

    Raises:
        psycopg.Error: On database error.
    """
    run_id = uuid4()
    hostname = _get_hostname()

    query = """
        INSERT INTO public.ingest_runs (
            id,
            worker_name,
            worker_version,
            source_system,
            source_county,
            started_at,
            status,
            hostname,
            environment,
            triggered_by
        ) VALUES (
            %(id)s,
            %(worker_name)s,
            %(worker_version)s,
            %(source_system)s,
            %(source_county)s,
            %(started_at)s,
            %(status)s,
            %(hostname)s,
            %(environment)s,
            %(triggered_by)s
        )
    """

    params = {
        "id": str(run_id),
        "worker_name": config.worker_name,
        "worker_version": config.worker_version,
        "source_system": config.source_system,
        "source_county": config.pilot_county,
        "started_at": datetime.now(timezone.utc),
        "status": "running",
        "hostname": hostname,
        "environment": config.env,
        "triggered_by": "scheduler",  # TODO: Could be "manual" or "backfill"
    }

    with conn.cursor() as cur:
        cur.execute(query, params)

    conn.commit()

    logger.info(
        "[DB] Ingest run created",
        extra={
            "ingest_run_id": str(run_id),
            "worker_name": config.worker_name,
            "source_system": config.source_system,
            "source_county": config.pilot_county,
        },
    )

    return run_id


def finalize_ingest_run(
    conn: psycopg.Connection,
    run_id: UUID,
    stats: IngestRunStats,
    status: str,
    error_message: str | None = None,
    error_details: dict[str, Any] | None = None,
) -> None:
    """
    Finalize an ingest run with final statistics and status.

    Args:
        conn: Database connection.
        run_id: UUID of the ingest run.
        stats: Final statistics.
        status: Final status ("completed", "failed", "partial").
        error_message: Top-level error message if failed.
        error_details: Structured error details if failed.

    Raises:
        psycopg.Error: On database error.
    """
    query = """
        UPDATE public.ingest_runs
        SET
            finished_at = %(finished_at)s,
            records_fetched = %(records_fetched)s,
            records_inserted = %(records_inserted)s,
            records_skipped = %(records_skipped)s,
            records_errored = %(records_errored)s,
            status = %(status)s,
            error_message = %(error_message)s,
            error_details = %(error_details)s
        WHERE id = %(id)s
    """

    params = {
        "id": str(run_id),
        "finished_at": datetime.now(timezone.utc),
        "records_fetched": stats.records_fetched,
        "records_inserted": stats.records_inserted,
        "records_skipped": stats.records_skipped,
        "records_errored": stats.records_errored,
        "status": status,
        "error_message": error_message,
        "error_details": psycopg.types.json.Json(error_details) if error_details else None,
    }

    with conn.cursor() as cur:
        cur.execute(query, params)
        if cur.rowcount == 0:
            logger.error(
                "[DB] Ingest run not found for finalization",
                extra={"ingest_run_id": str(run_id)},
            )

    conn.commit()

    logger.info(
        "[DB] Ingest run finalized",
        extra={
            "ingest_run_id": str(run_id),
            "status": status,
            "records_fetched": stats.records_fetched,
            "records_inserted": stats.records_inserted,
            "records_skipped": stats.records_skipped,
            "records_errored": stats.records_errored,
        },
    )


# ============================================================================
# Judgment Raw Operations
# ============================================================================


def upsert_judgment_raw(
    conn: psycopg.Connection,
    record: dict[str, Any],
) -> tuple[bool, str | None]:
    """
    Insert a single judgment_raw record with ON CONFLICT DO NOTHING.

    Args:
        conn: Database connection (should be in a transaction).
        record: Normalized record dict with all required fields.

    Returns:
        Tuple of (was_inserted, error_message).
        - (True, None) if inserted successfully
        - (False, None) if skipped (duplicate)
        - (False, error_message) if failed

    Note:
        Does NOT commit - caller manages transaction.
    """
    query = """
        INSERT INTO public.judgments_raw (
            id,
            source_system,
            source_county,
            source_court,
            case_type,
            external_id,
            source_url,
            judgment_entered_at,
            filed_at,
            raw_payload,
            raw_text,
            raw_html,
            content_hash,
            dedupe_key,
            ingest_run_id,
            status
        ) VALUES (
            %(id)s,
            %(source_system)s,
            %(source_county)s,
            %(source_court)s,
            %(case_type)s,
            %(external_id)s,
            %(source_url)s,
            %(judgment_entered_at)s,
            %(filed_at)s,
            %(raw_payload)s,
            %(raw_text)s,
            %(raw_html)s,
            %(content_hash)s,
            %(dedupe_key)s,
            %(ingest_run_id)s,
            %(status)s
        )
        ON CONFLICT (dedupe_key) DO NOTHING
    """

    try:
        # Prepare params with proper JSON handling
        params = {
            "id": str(record["id"]),
            "source_system": record["source_system"],
            "source_county": record.get("source_county"),
            "source_court": record.get("source_court"),
            "case_type": record.get("case_type"),
            "external_id": record.get("external_id"),
            "source_url": record["source_url"],
            "judgment_entered_at": record.get("judgment_entered_at"),
            "filed_at": record.get("filed_at"),
            "raw_payload": psycopg.types.json.Json(record.get("raw_payload", {})),
            "raw_text": record.get("raw_text"),
            "raw_html": record.get("raw_html"),
            "content_hash": record["content_hash"],
            "dedupe_key": record["dedupe_key"],
            "ingest_run_id": str(record["ingest_run_id"]),
            "status": record.get("status", "pending"),
        }

        with conn.cursor() as cur:
            cur.execute(query, params)
            was_inserted = cur.rowcount > 0

        return (was_inserted, None)

    except psycopg.Error as e:
        error_msg = f"{type(e).__name__}: {str(e)[:200]}"
        logger.warning(
            "[DB] Failed to insert record",
            extra={
                "dedupe_key": record.get("dedupe_key", "unknown"),
                "error": error_msg,
            },
        )
        return (False, error_msg)


def upsert_judgment_raw_batch(
    conn: psycopg.Connection,
    records: list[dict[str, Any]],
) -> InsertResult:
    """
    Insert a batch of judgment_raw records with ON CONFLICT DO NOTHING.

    Uses a single transaction for the entire batch.
    Partial failures within the batch are captured, not raised.

    Args:
        conn: Database connection.
        records: List of normalized record dicts.

    Returns:
        InsertResult with counts and any errors.

    Note:
        Commits on success, rolls back on catastrophic failure only.
    """
    if not records:
        return InsertResult()

    result = InsertResult()

    try:
        for record in records:
            was_inserted, error = upsert_judgment_raw(conn, record)

            if error:
                result.errored += 1
                result.errors.append(
                    {
                        "dedupe_key": record.get("dedupe_key"),
                        "error": error,
                    }
                )
            elif was_inserted:
                result.inserted += 1
            else:
                result.skipped += 1

        # Commit the batch
        conn.commit()

        logger.debug(
            "[DB] Batch inserted",
            extra={
                "batch_size": len(records),
                "inserted": result.inserted,
                "skipped": result.skipped,
                "errored": result.errored,
            },
        )

    except psycopg.Error as e:
        # Catastrophic failure - rollback and mark all as errored
        conn.rollback()
        error_msg = f"{type(e).__name__}: {str(e)[:200]}"

        logger.error(
            "[DB] Batch insert failed catastrophically",
            extra={
                "batch_size": len(records),
                "error": error_msg,
            },
        )

        # Mark all records as errored
        result = InsertResult(
            errored=len(records),
            errors=[{"batch_error": error_msg}],
        )

    return result


def check_existing_dedupe_keys(
    conn: psycopg.Connection,
    dedupe_keys: list[str],
) -> set[str]:
    """
    Check which dedupe_keys already exist in judgments_raw.

    Useful for pre-filtering before expensive normalization.

    Args:
        conn: Database connection.
        dedupe_keys: List of dedupe_keys to check.

    Returns:
        Set of dedupe_keys that already exist.
    """
    if not dedupe_keys:
        return set()

    query = """
        SELECT dedupe_key
        FROM public.judgments_raw
        WHERE dedupe_key = ANY(%(keys)s)
    """

    with conn.cursor() as cur:
        cur.execute(query, {"keys": dedupe_keys})
        rows = cur.fetchall()

    existing = {row["dedupe_key"] for row in rows}

    logger.debug(
        "[DB] Checked existing dedupe_keys",
        extra={
            "checked": len(dedupe_keys),
            "existing": len(existing),
        },
    )

    return existing


# ============================================================================
# Utility Functions
# ============================================================================


def _get_hostname() -> str:
    """Get hostname for audit trail."""
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def ping(conn: psycopg.Connection) -> bool:
    """
    Check if database connection is alive.

    Args:
        conn: Database connection.

    Returns:
        True if connection is healthy.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            return row is not None and row.get("?column?") == 1
    except Exception as e:
        logger.error("[DB] Ping failed", extra={"error": str(e)})
        return False


def get_last_ingest_run(
    conn: psycopg.Connection,
    worker_name: str,
    source_system: str,
    source_county: str | None = None,
) -> dict[str, Any] | None:
    """
    Get the most recent successful ingest run for delta calculation.

    Args:
        conn: Database connection.
        worker_name: Name of the worker.
        source_system: Source system identifier.
        source_county: Optional county filter.

    Returns:
        Dict with run details, or None if no previous run.
    """
    query = """
        SELECT
            id,
            started_at,
            finished_at,
            records_fetched,
            records_inserted,
            status
        FROM public.ingest_runs
        WHERE
            worker_name = %(worker_name)s
            AND source_system = %(source_system)s
            AND (%(source_county)s IS NULL OR source_county = %(source_county)s)
            AND status = 'completed'
        ORDER BY finished_at DESC
        LIMIT 1
    """

    with conn.cursor() as cur:
        cur.execute(
            query,
            {
                "worker_name": worker_name,
                "source_system": source_system,
                "source_county": source_county,
            },
        )
        row = cur.fetchone()

    if row:
        logger.debug(
            "[DB] Found last ingest run",
            extra={
                "ingest_run_id": str(row["id"]),
                "finished_at": str(row["finished_at"]),
            },
        )

    return row
