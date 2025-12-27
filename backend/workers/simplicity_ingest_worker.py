#!/usr/bin/env python3
"""
Dragonfly Engine - Simplicity Ingest Worker

Background worker that processes Simplicity vendor CSV import jobs.
Uses the 3-step pipeline:
    1. Stage → intake.simplicity_raw_rows
    2. Transform/Validate → intake.simplicity_validated_rows
    3. Upsert → public.judgments

Polls for jobs with job_type = 'simplicity_ingest' and status = 'pending'.

Architecture:
    Inherits from WorkerBootstrap to get:
    - Signal handling for graceful shutdown
    - Exponential backoff on transient failures
    - Heartbeat status transitions (via RPCClient)
    - Automatic transaction rollback on errors

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
from typing import Any
from uuid import uuid4

import pandas as pd
import psycopg

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.core.logging import configure_worker_logging
from backend.services.simplicity_mapper import (
    BatchResult,
    is_simplicity_format,
    process_simplicity_batch,
)
from backend.workers.bootstrap import WorkerBootstrap
from backend.workers.db_connect import get_safe_application_name
from backend.workers.rpc_client import RPCClient
from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

# Configure logging (INFO->stdout, WARNING+->stderr)
logger = configure_worker_logging("simplicity_ingest_worker")

# Worker configuration
POLL_INTERVAL_SECONDS = 2.0
LOCK_TIMEOUT_MINUTES = 30
JOB_TYPE = "simplicity_ingest"


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

    This function is passed to WorkerBootstrap.run() as the job_processor.
    Signature matches: (conn, job_dict) -> None

    On success: return normally (bootstrap marks completed)
    On failure: raise exception (bootstrap handles retry/DLQ)

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
        raise ValueError("Missing file_path in job payload")

    # Load CSV from storage
    df = load_csv_from_storage(file_path)

    if df.empty:
        logger.warning(f"[{run_id}] CSV is empty: {file_path}")
        # Empty CSV is a success (no rows to process)
        return

    # Validate format
    if not is_simplicity_format(df):
        raise ValueError(f"CSV does not match Simplicity format. Columns: {list(df.columns)}")

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
        raise RuntimeError(result.error_summary)

    logger.info(f"[{run_id}] Job {job_id} completed")


# =============================================================================
# Worker Bootstrap Entry Point
# =============================================================================


def run_worker() -> int:
    """
    Run the Simplicity Ingest Worker using WorkerBootstrap.

    WorkerBootstrap provides:
    - Signal handling for graceful shutdown
    - Exponential backoff on transient failures
    - Heartbeat management (via RPCClient.register_heartbeat)
    - Automatic transaction rollback on errors
    - Crash loop protection

    Returns:
        Exit code (0 for clean shutdown, non-zero for errors)
    """
    bootstrap = WorkerBootstrap(
        worker_type="simplicity_ingest_worker",
        job_types=[JOB_TYPE],
        poll_interval=POLL_INTERVAL_SECONDS,
        heartbeat_interval=30.0,
        lock_timeout_minutes=LOCK_TIMEOUT_MINUTES,
    )

    # Use default job_claimer which correctly passes worker_id to RPC
    return bootstrap.run(job_processor=process_job)


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

    app_name = get_safe_application_name("simplicity_direct")
    with psycopg.connect(dsn, application_name=app_name) as conn:
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
    import sys

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
        print(f"\n{'=' * 60}")
        print(f"Batch ID:    {result.batch_id}")
        print(f"Total Rows:  {result.total_rows}")
        print(f"Staged:      {result.staged_rows}")
        print(f"Valid:       {result.valid_rows}")
        print(f"Invalid:     {result.invalid_rows}")
        print(f"Inserted:    {result.inserted_rows}")
        print(f"Duplicates:  {result.duplicate_rows}")
        if result.error_summary:
            print(f"Error:       {result.error_summary}")
        print(f"{'=' * 60}")
    elif args.once:
        # Single job mode - claim with worker_id for traceability
        import socket

        env = get_supabase_env()
        dsn = get_supabase_db_url(env)
        app_name = get_safe_application_name("simplicity_once")
        worker_id = f"simplicity_once_{socket.gethostname()}_{os.getpid()}"
        conn = psycopg.connect(dsn, application_name=app_name)
        try:
            rpc = RPCClient(conn)
            claimed = rpc.claim_pending_job(
                job_types=[JOB_TYPE],
                lock_timeout_minutes=LOCK_TIMEOUT_MINUTES,
                worker_id=worker_id,
            )
            if claimed:
                job = {
                    "id": str(claimed.job_id),
                    "job_type": claimed.job_type,
                    "payload": claimed.payload,
                    "attempts": claimed.attempts,
                }
                logger.info(f"Processing job: {job['id']} (worker: {worker_id})")
                try:
                    process_job(conn, job)
                    rpc.update_job_status(job_id=job["id"], status="completed")
                    logger.info(f"Job {job['id']} completed")
                except Exception as e:
                    error_msg = str(e)[:500]
                    logger.exception(f"Job {job['id']} failed: {e}")
                    rpc.update_job_status(
                        job_id=job["id"],
                        status="failed",
                        error=error_msg,
                    )
            else:
                logger.info("No pending jobs found")
        finally:
            conn.close()
    else:
        # Worker loop mode using WorkerBootstrap
        exit_code = run_worker()
        sys.exit(exit_code)
