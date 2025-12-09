#!/usr/bin/env python3
"""
Dragonfly Engine - Ingest Processor Worker

Background worker that processes CSV ingest jobs from ops.job_queue.
Polls for jobs with job_type = 'ingest_csv' and status = 'pending',
loads CSV from Supabase Storage, parses with pandas, generates
collectability scores, and inserts into public.judgments.

Architecture:
- Uses FOR UPDATE SKIP LOCKED for safe concurrent dequeue
- Transactional job state management
- Idempotent design (can safely retry failed jobs)
- Structured logging with correlation IDs

Usage:
    python -m backend.workers.ingest_processor

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    SUPABASE_DB_URL_DEV / SUPABASE_DB_URL_PROD: Postgres connection strings
"""

from __future__ import annotations

import io
import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional
from uuid import uuid4

import pandas as pd
import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingest_processor")

# Worker configuration
POLL_INTERVAL_SECONDS = 2.0
LOCK_TIMEOUT_MINUTES = 30
JOB_TYPE = "ingest_csv"

# Simplicity CSV expected columns
SIMPLICITY_COLUMNS = [
    "Case Number",
    "Plaintiff",
    "Defendant",
    "Judgment Amount",
    "Filing Date",
    "County",
]


# =============================================================================
# Simplicity Mapper Helpers
# =============================================================================


def _clean_currency(value: Any) -> Optional[Decimal]:
    """Convert common Simplicity currency strings to Decimal.

    Examples:
        "$1,200.00" -> Decimal("1200.00")
        "  500 "    -> Decimal("500")
        None / ""   -> None
    """
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    s = str(value).strip()
    if not s:
        return None

    # Remove $ and commas
    s = s.replace("$", "").replace(",", "")

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_simplicity_date(value: Any) -> Optional[datetime]:
    """Parse Simplicity dates (MM/DD/YYYY) into datetime.

    Returns None if the value is empty or unparseable.
    """
    if value is None:
        return None

    s = str(value).strip()
    if not s:
        return None

    # Common Simplicity format: 03/15/2021
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # If we can't parse, treat as missing
    return None


def _map_simplicity_row(row: pd.Series) -> Dict[str, Any]:
    """Map a single Simplicity CSV row -> public.judgments insert dict.

    Expected columns:
        - Case Number
        - Plaintiff
        - Defendant
        - Judgment Amount
        - Filing Date
        - County

    Raises:
        ValueError if required columns are missing or Judgment Amount is invalid.
    """
    missing_cols = [c for c in SIMPLICITY_COLUMNS if c not in row.index]
    if missing_cols:
        raise ValueError(f"Simplicity row missing required columns: {missing_cols}")

    amount = _clean_currency(row.get("Judgment Amount"))
    if amount is None:
        # We treat missing/invalid amount as a hard validation failure
        raise ValueError("Missing or invalid Judgment Amount")

    filed_at = _parse_simplicity_date(row.get("Filing Date"))

    return {
        "case_number": (row.get("Case Number") or "").strip(),
        "plaintiff_name": (row.get("Plaintiff") or "").strip(),
        "defendant_name": (row.get("Defendant") or "").strip(),
        "judgment_amount": amount,
        "filing_date": filed_at.date().isoformat() if filed_at else None,
        "county": (row.get("County") or "").strip(),
    }


def _log_invalid_row(
    conn: psycopg.Connection,
    batch_id: str,
    raw_row: Dict[str, Any],
    error_message: str,
) -> None:
    """Write a record into ops.intake_logs for invalid rows.

    This provides 'does not crash but logs' behavior for bad data.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ops.intake_logs (batch_id, level, message, raw_payload, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT DO NOTHING
                """,
                (batch_id, "ERROR", error_message[:1000], json.dumps(raw_row, default=str)),
            )
            conn.commit()
    except Exception as e:
        # Table might not exist yet - rollback and continue
        try:
            conn.rollback()
        except Exception:
            pass
        logger.debug(f"Could not log invalid row to ops.intake_logs: {e}")


def _is_simplicity_format(df: pd.DataFrame) -> bool:
    """Check if DataFrame appears to be in Simplicity format.

    Returns True if all required Simplicity columns are present.
    """
    return all(col in df.columns for col in SIMPLICITY_COLUMNS)


def process_simplicity_frame(conn: psycopg.Connection, df: pd.DataFrame, batch_id: str) -> int:
    """Process a Simplicity DataFrame into public.judgments rows.

    Uses the hardened mapper with per-row error handling.
    Invalid rows are logged to ops.intake_logs but don't crash the worker.

    Returns the number of successfully inserted rows.
    """
    success_count = 0

    for idx, row in df.iterrows():
        raw = row.to_dict()

        try:
            mapped = _map_simplicity_row(row)
        except ValueError as exc:
            # Validation error – log and continue
            logger.warning("Validation failed for row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, str(exc))
            continue
        except Exception as exc:
            # Unexpected error – log with full context and continue
            logger.exception("Unexpected error mapping row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, f"Unexpected error: {exc}")
            continue

        # Generate collectability score for new inserts
        collectability_score = generate_collectability_score()

        # Insert into public.judgments
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        county,
                        collectability_score,
                        source_file,
                        status,
                        created_at
                    )
                    VALUES (
                        %(case_number)s,
                        %(plaintiff_name)s,
                        %(defendant_name)s,
                        %(judgment_amount)s,
                        %(filing_date)s,
                        %(county)s,
                        %(collectability_score)s,
                        %(source_file)s,
                        'pending',
                        now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        plaintiff_name = EXCLUDED.plaintiff_name,
                        defendant_name = EXCLUDED.defendant_name,
                        judgment_amount = EXCLUDED.judgment_amount,
                        entry_date = EXCLUDED.entry_date,
                        county = EXCLUDED.county,
                        collectability_score = EXCLUDED.collectability_score,
                        updated_at = now()
                    """,
                    {
                        **mapped,
                        "collectability_score": collectability_score,
                        "source_file": f"batch:{batch_id}",
                    },
                )
            conn.commit()
            success_count += 1
        except Exception as exc:
            logger.exception("DB error inserting mapped row %s: %s", idx, exc)
            _log_invalid_row(conn, batch_id, raw, f"DB error: {exc}")
            # Rollback this row's failed transaction
            try:
                conn.rollback()
            except Exception:
                pass

    return success_count


# =============================================================================
# Job Processing
# =============================================================================


def claim_pending_job(conn: psycopg.Connection) -> dict[str, Any] | None:
    """
    Claim a pending ingest_csv job using FOR UPDATE SKIP LOCKED.

    Returns the job row dict, or None if no jobs available.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        # Use text-based query since job_type might be enum or text
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'processing',
                locked_at = now(),
                attempts = attempts + 1
            WHERE id = (
                SELECT id FROM ops.job_queue
                WHERE job_type::text = %s
                  AND status::text = 'pending'
                  AND (locked_at IS NULL OR locked_at < now() - interval '%s minutes')
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
            """,
            (JOB_TYPE, LOCK_TIMEOUT_MINUTES),
        )
        row = cur.fetchone()
        conn.commit()
        return dict(row) if row else None


def mark_job_completed(conn: psycopg.Connection, job_id: str) -> None:
    """Mark a job as completed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'completed', locked_at = NULL
            WHERE id = %s
            """,
            (job_id,),
        )
        conn.commit()


def mark_job_failed(conn: psycopg.Connection, job_id: str, error: str) -> None:
    """Mark a job as failed with error message."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.job_queue
            SET status = 'failed', locked_at = NULL, last_error = %s
            WHERE id = %s
            """,
            (error[:2000], job_id),  # Truncate error to avoid column overflow
        )
        conn.commit()


def update_batch_status(
    conn: psycopg.Connection,
    batch_id: str,
    status: str,
    row_count_valid: int = 0,
    error_summary: str | None = None,
) -> None:
    """Update the ingest_batches status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.ingest_batches
            SET status = %s,
                row_count_valid = %s,
                processed_at = now(),
                error_summary = %s
            WHERE id = %s
            """,
            (status, row_count_valid, error_summary, batch_id),
        )
        conn.commit()


def load_csv_from_storage(file_path: str) -> pd.DataFrame:
    """
    Load a CSV file from Supabase Storage or local filesystem.

    Args:
        file_path: Path in storage bucket (e.g., 'intake/batch_123.csv')
                   OR local path prefixed with 'file://' for testing

    Returns:
        pandas DataFrame with CSV contents
    """
    # Support local file paths for testing (file:// prefix)
    if file_path.startswith("file://"):
        local_path = file_path[7:]  # Strip 'file://' prefix
        logger.info(f"Loading CSV from local path: {local_path}")
        try:
            df = pd.read_csv(local_path)
            logger.info(f"Loaded {len(df)} rows from local file")
            return df
        except Exception as e:
            logger.error(f"Failed to load local CSV: {e}")
            raise

    client = create_supabase_client()

    # Parse bucket and path
    # Expected format: "bucket_name/path/to/file.csv" or just "path/to/file.csv"
    parts = file_path.split("/", 1)
    if len(parts) == 2 and parts[0] in ("intake", "imports", "csv"):
        bucket = parts[0]
        path = parts[1]
    else:
        bucket = "intake"
        path = file_path

    logger.info(f"Downloading CSV from storage: bucket={bucket}, path={path}")

    try:
        response = client.storage.from_(bucket).download(path)
        df = pd.read_csv(io.BytesIO(response))
        logger.info(f"Loaded {len(df)} rows from {file_path}")
        return df
    except Exception as e:
        logger.error(f"Failed to load CSV from storage: {e}")
        raise


def generate_collectability_score() -> int:
    """Generate a random collectability score between 0-100."""
    return random.randint(0, 100)


def insert_judgments(conn: psycopg.Connection, df: pd.DataFrame, batch_id: str) -> int:
    """
    Insert judgment rows from DataFrame into public.judgments.

    Auto-detects format:
    - Simplicity format: Uses hardened mapper with strict validation
    - Generic format: Uses flexible column mapping with fallbacks

    Returns:
        Number of rows successfully inserted
    """
    # Check if this is Simplicity format (has all required Simplicity columns)
    if _is_simplicity_format(df):
        logger.info(f"Detected Simplicity format CSV ({len(df)} rows)")
        return process_simplicity_frame(conn, df, batch_id)

    # Generic format - use flexible column mapping
    logger.info(f"Using generic format processing ({len(df)} rows)")

    # Normalize column names
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]

    # Map common column name variations
    column_mapping = {
        "case_no": "case_number",
        "caseno": "case_number",
        "case_num": "case_number",
        "plaintiff": "plaintiff_name",
        "defendant": "defendant_name",
        "amount": "judgment_amount",
        "judgment_amt": "judgment_amount",
        "date": "entry_date",
        "jdgmt_date": "judgment_date",
    }
    df = df.rename(columns=column_mapping)

    inserted = 0
    errors = []

    with conn.cursor() as cur:
        for idx, row in df.iterrows():
            try:
                # Extract values with fallbacks
                case_number = row.get("case_number", f"INTAKE-{batch_id[:8]}-{idx}")
                plaintiff_name = row.get("plaintiff_name", "Unknown Plaintiff")
                defendant_name = row.get("defendant_name", "Unknown Defendant")

                # Handle numeric judgment amount
                judgment_amount = row.get("judgment_amount")
                if pd.isna(judgment_amount):
                    judgment_amount = 0.0
                else:
                    try:
                        judgment_amount = float(
                            str(judgment_amount).replace(",", "").replace("$", "")
                        )
                    except (ValueError, TypeError):
                        judgment_amount = 0.0

                # Handle dates
                entry_date = row.get("entry_date") or row.get("judgment_date")
                if pd.notna(entry_date):
                    try:
                        entry_date = pd.to_datetime(entry_date).date()
                    except Exception:
                        entry_date = None
                else:
                    entry_date = None

                collectability_score = generate_collectability_score()

                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        collectability_score,
                        court,
                        county,
                        source_file,
                        status,
                        created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', now()
                    )
                    ON CONFLICT (case_number) DO UPDATE SET
                        collectability_score = EXCLUDED.collectability_score,
                        updated_at = now()
                    """,
                    (
                        str(case_number),
                        str(plaintiff_name)[:500],
                        str(defendant_name)[:500],
                        judgment_amount,
                        entry_date,
                        collectability_score,
                        row.get("court", None),
                        row.get("county", None),
                        f"batch:{batch_id}",
                    ),
                )
                inserted += 1

            except Exception as e:
                errors.append(f"Row {idx}: {str(e)[:100]}")
                logger.warning(f"Failed to insert row {idx}: {e}")

        conn.commit()

    if errors:
        logger.warning(f"{len(errors)} rows failed during insert")

    return inserted


def process_job(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """
    Process a single ingest_csv job.

    Expected payload:
    {
        "file_path": "intake/batch_123.csv",
        "batch_id": "uuid-of-ingest-batch"
    }
    """
    job_id = str(job["id"])
    payload = job.get("payload", {})

    file_path = payload.get("file_path")
    batch_id = payload.get("batch_id")

    run_id = str(uuid4())[:8]
    logger.info(f"[{run_id}] Processing job {job_id}: file_path={file_path}, batch_id={batch_id}")

    if not file_path:
        error = "Missing file_path in job payload"
        logger.error(f"[{run_id}] {error}")
        mark_job_failed(conn, job_id, error)
        if batch_id:
            update_batch_status(conn, batch_id, "failed", error_summary=error)
        return

    try:
        # Load CSV from storage
        df = load_csv_from_storage(file_path)

        if df.empty:
            logger.warning(f"[{run_id}] CSV is empty: {file_path}")
            mark_job_completed(conn, job_id)
            if batch_id:
                update_batch_status(conn, batch_id, "completed", row_count_valid=0)
            return

        # Insert judgments
        inserted = insert_judgments(conn, df, batch_id or job_id)

        logger.info(f"[{run_id}] Inserted {inserted}/{len(df)} judgments")

        # Mark success
        mark_job_completed(conn, job_id)
        if batch_id:
            update_batch_status(conn, batch_id, "completed", row_count_valid=inserted)

        logger.info(f"[{run_id}] Job {job_id} completed successfully")

    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception(f"[{run_id}] Job {job_id} failed: {e}")
        mark_job_failed(conn, job_id, error_msg)
        if batch_id:
            update_batch_status(conn, batch_id, "failed", error_summary=error_msg)


# =============================================================================
# Worker Loop
# =============================================================================


def run_worker_loop() -> None:
    """
    Main worker loop - polls for pending jobs and processes them.
    """
    env = get_supabase_env()
    dsn = get_supabase_db_url(env)

    logger.info(f"🚀 Starting Ingest Processor Worker (env={env})")
    logger.info(f"   Poll interval: {POLL_INTERVAL_SECONDS}s")
    logger.info(f"   Job type: {JOB_TYPE}")

    conn = psycopg.connect(dsn)

    try:
        while True:
            try:
                job = claim_pending_job(conn)

                if job:
                    logger.info(f"Claimed job: {job['id']}")
                    process_job(conn, job)
                else:
                    # No jobs available, sleep before polling again
                    import time

                    time.sleep(POLL_INTERVAL_SECONDS)

            except psycopg.OperationalError as e:
                logger.error(f"Database connection error: {e}")
                # Reconnect
                try:
                    conn.close()
                except Exception:
                    pass
                import time

                time.sleep(5)
                conn = psycopg.connect(dsn)

            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                break

            except Exception as e:
                logger.exception(f"Unexpected error in worker loop: {e}")
                import time

                time.sleep(POLL_INTERVAL_SECONDS)

    finally:
        conn.close()
        logger.info("Worker shutdown complete")


# =============================================================================
# Entry Point
# =============================================================================


if __name__ == "__main__":
    run_worker_loop()
