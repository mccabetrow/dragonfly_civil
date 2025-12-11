#!/usr/bin/env python3
"""
Dragonfly Engine - Simplicity Ingest Worker

Background worker that processes Simplicity vendor CSV import jobs.
Uses the 3-step pipeline:
    1. Stage → intake.simplicity_raw_rows
    2. Transform/Validate → intake.simplicity_validated_rows
    3. Upsert → public.judgments

Polls for jobs with job_type = 'simplicity_ingest' and status = 'pending'.

Usage:
    python -m backend.workers.simplicity_ingest_worker

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
"""

from __future__ import annotations

import io
import logging
import os
import sys
import time
from typing import Any
from uuid import uuid4

import pandas as pd
import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.services.simplicity_mapper import (
    BatchResult,
    is_simplicity_format,
    process_simplicity_batch,
)
from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("simplicity_ingest_worker")

# Worker configuration
POLL_INTERVAL_SECONDS = 2.0
LOCK_TIMEOUT_MINUTES = 30
JOB_TYPE = "simplicity_ingest"


# =============================================================================
# Job Queue Management
# =============================================================================


def claim_pending_job(conn: psycopg.Connection) -> dict[str, Any] | None:
    """
    Claim a pending simplicity_ingest job using FOR UPDATE SKIP LOCKED.

    Returns the job row dict, or None if no jobs available.
    """
    with conn.cursor(row_factory=dict_row) as cur:
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
            (error[:2000], job_id),
        )
        conn.commit()


# =============================================================================
# CSV Loading
# =============================================================================


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
    parts = file_path.split("/", 1)
    if len(parts) == 2 and parts[0] in ("intake", "imports", "csv", "simplicity"):
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


# =============================================================================
# Job Processing
# =============================================================================


def process_job(conn: psycopg.Connection, job: dict[str, Any]) -> None:
    """
    Process a single simplicity_ingest job.

    Expected payload:
    {
        "file_path": "simplicity/dec_2024_export.csv",
        "source_reference": "vendor-batch-dec-2024"  # Optional, for idempotency
    }
    """
    job_id = str(job["id"])
    payload = job.get("payload", {})

    file_path = payload.get("file_path")
    source_reference = payload.get("source_reference")

    run_id = str(uuid4())[:8]
    logger.info(f"[{run_id}] Processing job {job_id}: file_path={file_path}")

    if not file_path:
        error = "Missing file_path in job payload"
        logger.error(f"[{run_id}] {error}")
        mark_job_failed(conn, job_id, error)
        return

    try:
        # Load CSV from storage
        df = load_csv_from_storage(file_path)

        if df.empty:
            logger.warning(f"[{run_id}] CSV is empty: {file_path}")
            mark_job_completed(conn, job_id)
            return

        # Validate format
        if not is_simplicity_format(df):
            error = f"CSV does not match Simplicity format. Columns: {list(df.columns)}"
            logger.error(f"[{run_id}] {error}")
            mark_job_failed(conn, job_id, error)
            return

        # Process through 3-step pipeline
        filename = file_path.split("/")[-1] if "/" in file_path else file_path
        result: BatchResult = process_simplicity_batch(conn, df, filename, source_reference)

        # Log result
        logger.info(
            f"[{run_id}] Batch {result.batch_id[:8]} complete: "
            f"{result.inserted_rows}/{result.total_rows} inserted, "
            f"{result.invalid_rows} invalid, {result.duplicate_rows} duplicates"
        )

        if result.error_summary:
            mark_job_failed(conn, job_id, result.error_summary)
        else:
            mark_job_completed(conn, job_id)

        logger.info(f"[{run_id}] Job {job_id} completed")

    except Exception as e:
        error_msg = str(e)[:500]
        logger.exception(f"[{run_id}] Job {job_id} failed: {e}")
        mark_job_failed(conn, job_id, error_msg)


# =============================================================================
# Worker Loop
# =============================================================================


def run_worker_loop() -> None:
    """
    Main worker loop - polls for pending simplicity_ingest jobs.
    """
    env = get_supabase_env()
    dsn = get_supabase_db_url(env)

    logger.info(f"🚀 Starting Simplicity Ingest Worker (env={env})")
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
                    time.sleep(POLL_INTERVAL_SECONDS)

            except psycopg.OperationalError as e:
                logger.error(f"Database connection error: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
                time.sleep(5)
                conn = psycopg.connect(dsn)

            except KeyboardInterrupt:
                logger.info("Worker interrupted by user")
                break

            except Exception as e:
                logger.exception(f"Unexpected error in worker loop: {e}")
                time.sleep(POLL_INTERVAL_SECONDS)

    finally:
        conn.close()
        logger.info("Worker shutdown complete")


# =============================================================================
# Direct Processing (for testing/CLI usage)
# =============================================================================


def process_csv_file(
    file_path: str,
    source_reference: str | None = None,
    env: str | None = None,
) -> BatchResult:
    """
    Process a CSV file directly without job queue.

    Useful for testing and CLI usage.

    Args:
        file_path: Path to CSV file (local path, not file:// URI)
        source_reference: Optional batch identifier for idempotency
        env: Environment override (dev/prod)

    Returns:
        BatchResult with processing statistics
    """
    if env:
        os.environ["SUPABASE_MODE"] = env

    target_env = get_supabase_env()
    dsn = get_supabase_db_url(target_env)

    logger.info(f"Processing {file_path} in {target_env} environment")

    df = pd.read_csv(file_path)
    logger.info(f"Loaded {len(df)} rows from {file_path}")

    if not is_simplicity_format(df):
        raise ValueError(f"CSV does not match Simplicity format. Columns: {list(df.columns)}")

    filename = os.path.basename(file_path)

    with psycopg.connect(dsn) as conn:
        result = process_simplicity_batch(conn, df, filename, source_reference)

    logger.info(
        f"Batch {result.batch_id[:8]}: "
        f"{result.inserted_rows}/{result.total_rows} inserted, "
        f"{result.invalid_rows} invalid"
    )

    return result


# =============================================================================
# Entry Point
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Simplicity Ingest Worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one job and exit (for testing)",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Process a specific CSV file directly (bypasses job queue)",
    )
    parser.add_argument(
        "--source-ref",
        type=str,
        help="Source reference for idempotency (used with --file)",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Override SUPABASE_MODE environment",
    )
    args = parser.parse_args()

    if args.env:
        os.environ["SUPABASE_MODE"] = args.env

    if args.file:
        # Direct file processing mode
        result = process_csv_file(args.file, args.source_ref, args.env)
        print(f"\n{'='*60}")
        print(f"Batch ID:    {result.batch_id}")
        print(f"Total Rows:  {result.total_rows}")
        print(f"Staged:      {result.staged_rows}")
        print(f"Valid:       {result.valid_rows}")
        print(f"Invalid:     {result.invalid_rows}")
        print(f"Inserted:    {result.inserted_rows}")
        print(f"Duplicates:  {result.duplicate_rows}")
        if result.error_summary:
            print(f"Error:       {result.error_summary}")
        print(f"{'='*60}")
    elif args.once:
        # Single job mode
        env = get_supabase_env()
        dsn = get_supabase_db_url(env)
        conn = psycopg.connect(dsn)
        try:
            job = claim_pending_job(conn)
            if job:
                logger.info(f"Processing job: {job['id']}")
                process_job(conn, job)
            else:
                logger.info("No pending jobs found")
        finally:
            conn.close()
    else:
        # Worker loop mode
        run_worker_loop()
