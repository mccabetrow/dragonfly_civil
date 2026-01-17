"""
NY Judgments Pilot Worker - Database Operations

All database operations are isolated in this module.
Uses psycopg3 (sync) with explicit transaction control.

DESIGN PRINCIPLES:
    - Pure database operations, no business logic
    - Explicit transaction boundaries (caller commits)
    - Uses ON CONFLICT (dedupe_key) DO NOTHING for idempotency
    - All queries are parameterized (no SQL injection)

TABLES:
    - public.ingest_runs: Tracks ingestion worker executions
    - public.judgments_raw: Raw judgment records landing zone
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from .normalize import NormalizedRecord

# ============================================================================
# Logging
# ============================================================================

logger = logging.getLogger(__name__)


# ============================================================================
# Connection Factory
# ============================================================================


def get_connection(dsn: str) -> psycopg.Connection:
    """
    Create a database connection with standard settings.

    Args:
        dsn: PostgreSQL connection string.

    Returns:
        psycopg.Connection configured for this worker.

    Raises:
        psycopg.OperationalError: On connection failure.
    """
    conn = psycopg.connect(
        dsn,
        row_factory=dict_row,
        application_name="ny_judgments_pilot",
        connect_timeout=10,
    )

    # Set session timezone to UTC for consistency
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")

    return conn


# ============================================================================
# Ingest Run Operations (public.ingest_runs)
# ============================================================================


def check_existing_run(
    conn: psycopg.Connection,
    source_batch_id: str,
) -> dict[str, Any] | None:
    """
    Check if an ingest run already exists for this batch.

    Uses worker_name + source_system + date as the identity.

    Args:
        conn: Database connection.
        source_batch_id: Unique batch identifier (e.g., ny_judgments_2026-01-14).

    Returns:
        Existing run record, or None if not found.
    """
    # The source_batch_id encodes the date, so we search by pattern matching
    # Format: ny_judgments_YYYY-MM-DD
    query = """
        SELECT id, worker_name, source_system, source_county, status,
               started_at, finished_at, records_fetched, records_inserted
        FROM public.ingest_runs
        WHERE worker_name = 'ny_judgments_pilot'
          AND DATE(started_at) = %(run_date)s
        ORDER BY started_at DESC
        LIMIT 1
    """

    # Extract date from source_batch_id (ny_judgments_YYYY-MM-DD)
    try:
        run_date = source_batch_id.replace("ny_judgments_", "")
    except Exception:
        run_date = datetime.now(timezone.utc).date().isoformat()

    with conn.cursor() as cur:
        cur.execute(query, {"run_date": run_date})
        row = cur.fetchone()

    return dict(row) if row else None


def create_ingest_run(
    conn: psycopg.Connection,
    source_batch_id: str,
    source_county: str | None = None,
    environment: str = "dev",
) -> UUID:
    """
    Create a new ingest run record with 'running' status.

    Args:
        conn: Database connection.
        source_batch_id: Unique batch identifier.
        source_county: County being ingested (or None for all).
        environment: Environment (dev, staging, prod).

    Returns:
        UUID of the created run.
    """
    query = """
        INSERT INTO public.ingest_runs (
            worker_name,
            worker_version,
            source_system,
            source_county,
            status,
            started_at,
            environment,
            triggered_by
        ) VALUES (
            'ny_judgments_pilot',
            '1.0.0',
            'ny_ecourts',
            %(source_county)s,
            'running',
            %(started_at)s,
            %(environment)s,
            'scheduler'
        )
        RETURNING id
    """

    params = {
        "source_county": source_county,
        "started_at": datetime.now(timezone.utc),
        "environment": environment,
    }

    with conn.cursor() as cur:
        cur.execute(query, params)
        row = cur.fetchone()

    conn.commit()

    run_id = row["id"]
    logger.info(
        "created ingest_run run_id=%s source_batch_id=%s",
        run_id,
        source_batch_id,
    )

    return run_id


def create_import_run(
    conn: psycopg.Connection,
    source_batch_id: str,
    file_hash: str,
) -> UUID:
    """
    Backwards-compatible wrapper for create_ingest_run.

    Args:
        conn: Database connection.
        source_batch_id: Unique batch identifier.
        file_hash: Hash of the source (ignored - for compatibility).

    Returns:
        UUID of the created run.
    """
    return create_ingest_run(conn, source_batch_id)


def update_run_to_failed(
    conn: psycopg.Connection,
    run_id: UUID | None,
    source_batch_id: str,
    error_message: str,
    error_details: dict[str, Any] | None = None,
) -> None:
    """
    Update ingest run to 'failed' status.

    Args:
        conn: Database connection.
        run_id: UUID of the run (None to create new failed record).
        source_batch_id: Batch identifier.
        error_message: Short error message.
        error_details: Structured error details.
    """
    if run_id is None:
        # Create a failed run record if we couldn't create one earlier
        query = """
            INSERT INTO public.ingest_runs (
                worker_name,
                worker_version,
                source_system,
                status,
                started_at,
                finished_at,
                error_message,
                error_details
            ) VALUES (
                'ny_judgments_pilot',
                '1.0.0',
                'ny_ecourts',
                'failed',
                %(started_at)s,
                %(finished_at)s,
                %(error_message)s,
                %(error_details)s
            )
        """
        now = datetime.now(timezone.utc)
        params = {
            "started_at": now,
            "finished_at": now,
            "error_message": error_message[:500] if error_message else None,
            "error_details": Json(error_details) if error_details else None,
        }
    else:
        query = """
            UPDATE public.ingest_runs
            SET
                status = 'failed',
                finished_at = %(finished_at)s,
                error_message = %(error_message)s,
                error_details = %(error_details)s
            WHERE id = %(run_id)s
        """
        params = {
            "run_id": str(run_id),
            "finished_at": datetime.now(timezone.utc),
            "error_message": error_message[:500] if error_message else None,
            "error_details": Json(error_details) if error_details else None,
        }

    with conn.cursor() as cur:
        cur.execute(query, params)

    conn.commit()

    logger.error(
        "run_failed run_id=%s error=%s",
        run_id or "N/A",
        error_message,
    )


def update_run_to_completed(
    conn: psycopg.Connection,
    run_id: UUID,
    total_rows: int,
    inserted_rows: int,
    skipped_rows: int,
    error_rows: int,
) -> None:
    """
    Update ingest run to 'completed' status with row counts.

    Args:
        conn: Database connection.
        run_id: UUID of the run.
        total_rows: Total records fetched.
        inserted_rows: Records successfully inserted.
        skipped_rows: Records skipped (duplicates).
        error_rows: Records that failed.
    """
    query = """
        UPDATE public.ingest_runs
        SET
            status = 'completed',
            finished_at = %(finished_at)s,
            records_fetched = %(records_fetched)s,
            records_inserted = %(records_inserted)s,
            records_skipped = %(records_skipped)s,
            records_errored = %(records_errored)s
        WHERE id = %(run_id)s
    """

    params = {
        "run_id": str(run_id),
        "finished_at": datetime.now(timezone.utc),
        "records_fetched": total_rows,
        "records_inserted": inserted_rows,
        "records_skipped": skipped_rows,
        "records_errored": error_rows,
    }

    with conn.cursor() as cur:
        cur.execute(query, params)

    conn.commit()

    logger.info(
        "run_completed run_id=%s total=%d inserted=%d skipped=%d errors=%d",
        run_id,
        total_rows,
        inserted_rows,
        skipped_rows,
        error_rows,
    )


# ============================================================================
# Judgments Raw Operations (public.judgments_raw)
# ============================================================================


def insert_judgment_raw(
    conn: psycopg.Connection,
    record: NormalizedRecord,
    ingest_run_id: UUID,
) -> bool:
    """
    Insert a single normalized record into judgments_raw.

    Uses ON CONFLICT (dedupe_key) DO NOTHING for idempotency.

    Args:
        conn: Database connection.
        record: NormalizedRecord to insert.
        ingest_run_id: UUID of the current ingest run.

    Returns:
        True if inserted, False if duplicate (skipped).
    """
    query = """
        INSERT INTO public.judgments_raw (
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
            ingest_run_id
        ) VALUES (
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
            %(ingest_run_id)s
        )
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
    """

    data = record.to_dict()
    data["raw_payload"] = Json(data["raw_payload"])
    data["ingest_run_id"] = str(ingest_run_id)

    with conn.cursor() as cur:
        cur.execute(query, data)
        row = cur.fetchone()

    # If RETURNING returned a row, we inserted successfully
    return row is not None


def insert_judgments_raw_batch(
    conn: psycopg.Connection,
    records: list[NormalizedRecord],
    ingest_run_id: UUID,
    batch_size: int = 100,
) -> tuple[int, int]:
    """
    Insert a batch of normalized records into judgments_raw.

    Uses ON CONFLICT for efficient bulk inserts.

    Args:
        conn: Database connection.
        records: List of NormalizedRecords to insert.
        ingest_run_id: UUID of the current ingest run.
        batch_size: Records per transaction batch.

    Returns:
        Tuple of (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]

        for record in batch:
            if insert_judgment_raw(conn, record, ingest_run_id):
                inserted += 1
            else:
                skipped += 1

        # Commit after each batch
        conn.commit()

        logger.debug(
            "batch_inserted offset=%d count=%d inserted=%d skipped=%d",
            i,
            len(batch),
            inserted,
            skipped,
        )

    return inserted, skipped


# ============================================================================
# Health Check
# ============================================================================


def check_database_health(conn: psycopg.Connection) -> dict[str, bool]:
    """
    Check database health and table accessibility.

    Args:
        conn: Database connection.

    Returns:
        Dict of table_name -> accessible boolean.
    """
    tables = [
        ("public.ingest_runs", "SELECT 1 FROM public.ingest_runs LIMIT 1"),
        ("public.judgments_raw", "SELECT 1 FROM public.judgments_raw LIMIT 1"),
    ]

    results = {}

    for table_name, query in tables:
        try:
            with conn.cursor() as cur:
                cur.execute(query)
            results[table_name] = True
        except Exception:
            results[table_name] = False

    return results
