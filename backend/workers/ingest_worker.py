#!/usr/bin/env python3
"""
Dragonfly Engine - Ingest Worker (Exactly-Once Processing)

Implements the "Claim & Commit" pattern for CSV/file ingestion with
exactly-once semantics via ingest.import_runs tracking table.

Architecture:
    1. Parse Envelope: Extract source_batch_id and file_hash from payload
    2. Idempotency Check: Query ingest.import_runs
       - If completed: Skip duplicate, ack message
       - If processing < 1h: Skip (already running), nack message
    3. Claim: Insert/Update import_runs -> status='processing'
    4. Process: Parse CSV, upsert data with ON CONFLICT
    5. Commit: Update import_runs -> status='completed', completed_at=now()
    6. Error: Update import_runs -> status='failed', error_details

Data Moat Contract:
    - Same file uploaded 5x → processed exactly once
    - Worker crash midway → next worker safely resumes or skips
    - No duplicates in plaintiffs/judgments tables

Usage:
    python -m backend.workers.ingest_worker

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    SUPABASE_DB_URL: Postgres connection string
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.core.logging import configure_worker_logging
from backend.workers.base import BaseWorker
from backend.workers.db_connect import get_safe_application_name
from backend.workers.envelope import JobEnvelope
from src.supabase_client import create_supabase_client, get_supabase_db_url, get_supabase_env

# Configure logging first (before optional imports that might log)
logger = configure_worker_logging("ingest_worker")

# Optional Discord alerting
try:
    from backend.utils.alerting import IncidentType, Severity, alert_incident

    _ALERTING_AVAILABLE = True
except ImportError:
    _ALERTING_AVAILABLE = False
    logger.debug("Discord alerting not available")

# Processing timeout: if a run is 'processing' for longer than this, consider it stale
PROCESSING_TIMEOUT_HOURS = 1


def send_discord_alert(message: str) -> None:
    """Send Discord alert for ingest failures (fire-and-forget)."""
    if not _ALERTING_AVAILABLE:
        logger.warning(f"Discord alerting unavailable: {message}")
        return

    try:
        # Fire async alert in background (don't await - fire-and-forget)
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(
                alert_incident(
                    incident_type=IncidentType.CONFIG_ERROR,  # Reuse existing type
                    message=message,
                    severity=Severity.ERROR,
                )
            )
        else:
            loop.run_until_complete(
                alert_incident(
                    incident_type=IncidentType.CONFIG_ERROR,
                    message=message,
                    severity=Severity.ERROR,
                )
            )
    except Exception as e:
        logger.warning(f"Failed to send Discord alert: {e}")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ImportRunStatus:
    """Status of an import run from ingest.import_runs."""

    id: str | None
    status: str | None
    started_at: datetime | None
    file_hash: str | None

    @property
    def is_completed(self) -> bool:
        return self.status == "completed"

    @property
    def is_processing(self) -> bool:
        return self.status == "processing"

    @property
    def is_stale(self) -> bool:
        """Check if a 'processing' run is older than timeout."""
        if not self.is_processing or not self.started_at:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(hours=PROCESSING_TIMEOUT_HOURS)
        return self.started_at < cutoff


@dataclass
class IngestResult:
    """Result of processing an ingest job."""

    source_batch_id: str
    file_hash: str
    record_count: int
    inserted: int
    updated: int
    skipped: int
    errors: list[str]


# =============================================================================
# CSV Loading
# =============================================================================


def load_csv_from_storage(file_path: str) -> tuple[pd.DataFrame, str]:
    """
    Load a CSV file from Supabase Storage or local filesystem.

    Args:
        file_path: Path in storage bucket (e.g., 'intake/batch_123.csv')
                   OR local path prefixed with 'file://' for testing

    Returns:
        Tuple of (DataFrame, file_hash)
    """
    if file_path.startswith("file://"):
        local_path = file_path[7:]
        logger.info(f"Loading CSV from local path: {local_path}")
        with open(local_path, "rb") as f:
            content = f.read()
        file_hash = hashlib.sha256(content).hexdigest()
        df = pd.read_csv(io.BytesIO(content))
        logger.info(f"Loaded {len(df)} rows from local file (hash: {file_hash[:16]})")
        return df, file_hash

    client = create_supabase_client()

    # Parse bucket and path
    parts = file_path.split("/", 1)
    if len(parts) == 2 and parts[0] in ("intake", "imports", "csv", "ingest"):
        bucket = parts[0]
        path = parts[1]
    else:
        bucket = "intake"
        path = file_path

    logger.info(f"Downloading CSV from storage: bucket={bucket}, path={path}")

    response = client.storage.from_(bucket).download(path)
    file_hash = hashlib.sha256(response).hexdigest()
    df = pd.read_csv(io.BytesIO(response))
    logger.info(f"Loaded {len(df)} rows from storage (hash: {file_hash[:16]})")
    return df, file_hash


# =============================================================================
# Import Run Tracking (ingest.import_runs)
# =============================================================================


def get_import_run_status(conn: psycopg.Connection, source_batch_id: str) -> ImportRunStatus:
    """
    Query ingest.import_runs for existing run status.

    Returns ImportRunStatus with None values if no existing run found.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT id, status, started_at, file_hash
            FROM ingest.import_runs
            WHERE source_batch_id = %s
            """,
            (source_batch_id,),
        )
        row = cur.fetchone()

    if not row:
        return ImportRunStatus(id=None, status=None, started_at=None, file_hash=None)

    return ImportRunStatus(
        id=str(row["id"]),
        status=row["status"],
        started_at=row["started_at"],
        file_hash=row["file_hash"],
    )


def claim_import_run(
    conn: psycopg.Connection,
    source_batch_id: str,
    file_hash: str,
) -> str:
    """
    Claim an import run by inserting or updating to 'processing' status.

    Uses ON CONFLICT to handle race conditions gracefully.

    Returns:
        The import run ID.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO ingest.import_runs (source_batch_id, file_hash, status, started_at)
            VALUES (%s, %s, 'processing', NOW())
            ON CONFLICT (source_batch_id) DO UPDATE
            SET status = 'processing',
                file_hash = EXCLUDED.file_hash,
                started_at = NOW(),
                completed_at = NULL,
                error_details = NULL
            RETURNING id
            """,
            (source_batch_id, file_hash),
        )
        row = cur.fetchone()
        conn.commit()

    return str(row["id"])


def complete_import_run(
    conn: psycopg.Connection,
    source_batch_id: str,
    record_count: int,
) -> None:
    """Mark an import run as completed."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingest.import_runs
            SET status = 'completed',
                completed_at = NOW(),
                record_count = %s
            WHERE source_batch_id = %s
            """,
            (record_count, source_batch_id),
        )
    conn.commit()


def fail_import_run(
    conn: psycopg.Connection,
    source_batch_id: str,
    error_details: dict[str, Any],
) -> None:
    """Mark an import run as failed with error details."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingest.import_runs
            SET status = 'failed',
                completed_at = NOW(),
                error_details = %s
            WHERE source_batch_id = %s
            """,
            (json.dumps(error_details), source_batch_id),
        )
    conn.commit()


# =============================================================================
# Data Processing (Upsert Logic)
# =============================================================================


def process_csv_data(
    conn: psycopg.Connection,
    df: pd.DataFrame,
    source_batch_id: str,
) -> IngestResult:
    """
    Process CSV data with idempotent upserts.

    Uses ON CONFLICT on natural keys to prevent duplicates.
    Tracks inserted vs updated counts.

    Returns:
        IngestResult with processing statistics.
    """
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    file_hash = hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()

    # Detect format and process accordingly
    if "Case Number" in df.columns:
        # Simplicity format -> public.judgments
        for idx, row in df.iterrows():
            try:
                result = upsert_judgment(conn, row, source_batch_id)
                if result == "inserted":
                    inserted += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)[:200]}")
                logger.warning(f"Row {idx} failed: {e}")
    elif "plaintiff_name" in df.columns or "Plaintiff Name" in df.columns:
        # Plaintiff format -> public.plaintiffs
        for idx, row in df.iterrows():
            try:
                result = upsert_plaintiff(conn, row, source_batch_id)
                if result == "inserted":
                    inserted += 1
                elif result == "updated":
                    updated += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"Row {idx}: {str(e)[:200]}")
                logger.warning(f"Row {idx} failed: {e}")
    else:
        raise ValueError(f"Unknown CSV format. Columns: {list(df.columns)[:10]}")

    return IngestResult(
        source_batch_id=source_batch_id,
        file_hash=file_hash,
        record_count=len(df),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        errors=errors[:50],  # Limit error list size
    )


def upsert_judgment(
    conn: psycopg.Connection,
    row: pd.Series,
    source_batch_id: str,
) -> str:
    """
    Upsert a judgment row into public.judgments.

    Uses ON CONFLICT (case_number) DO UPDATE for idempotency.

    Returns: 'inserted', 'updated', or 'skipped'
    """
    case_number = str(row.get("Case Number", "")).strip()
    if not case_number:
        raise ValueError("Missing Case Number")

    plaintiff_name = str(row.get("Plaintiff", "")).strip()
    defendant_name = str(row.get("Defendant", "")).strip()

    # Parse amount
    amount_str = str(row.get("Judgment Amount", "")).replace("$", "").replace(",", "").strip()
    try:
        judgment_amount = float(amount_str) if amount_str else None
    except ValueError:
        judgment_amount = None

    # Parse date
    filing_date = None
    date_str = str(row.get("Filing Date", "")).strip()
    if date_str:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                filing_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue

    county = str(row.get("County", "")).strip() or None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO public.judgments (
                case_number, plaintiff_name, defendant_name,
                judgment_amount, filing_date, county, source_file
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_number) DO UPDATE SET
                plaintiff_name = COALESCE(EXCLUDED.plaintiff_name, judgments.plaintiff_name),
                defendant_name = COALESCE(EXCLUDED.defendant_name, judgments.defendant_name),
                judgment_amount = COALESCE(EXCLUDED.judgment_amount, judgments.judgment_amount),
                filing_date = COALESCE(EXCLUDED.filing_date, judgments.filing_date),
                county = COALESCE(EXCLUDED.county, judgments.county),
                updated_at = NOW()
            RETURNING (xmax = 0) AS is_insert
            """,
            (
                case_number,
                plaintiff_name or None,
                defendant_name or None,
                judgment_amount,
                filing_date,
                county,
                f"batch:{source_batch_id}",
            ),
        )
        result = cur.fetchone()

    return "inserted" if result and result["is_insert"] else "updated"


def upsert_plaintiff(
    conn: psycopg.Connection,
    row: pd.Series,
    source_batch_id: str,
) -> str:
    """
    Upsert a plaintiff row into public.plaintiffs.

    Uses ON CONFLICT (source_id) DO UPDATE for idempotency.

    Returns: 'inserted', 'updated', or 'skipped'
    """
    # Normalize column names (handle both cases)
    name = str(row.get("plaintiff_name", row.get("Plaintiff Name", ""))).strip()
    if not name:
        raise ValueError("Missing plaintiff name")

    source_id = str(row.get("source_id", row.get("Source ID", ""))).strip()
    if not source_id:
        # Generate from name + batch
        source_id = f"{source_batch_id}:{hashlib.md5(name.encode()).hexdigest()[:12]}"

    email = str(row.get("email", row.get("Email", ""))).strip() or None
    phone = str(row.get("phone", row.get("Phone", ""))).strip() or None
    address = str(row.get("address", row.get("Address", ""))).strip() or None

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            INSERT INTO public.plaintiffs (
                name, source_id, email, phone, address
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                name = COALESCE(EXCLUDED.name, plaintiffs.name),
                email = COALESCE(EXCLUDED.email, plaintiffs.email),
                phone = COALESCE(EXCLUDED.phone, plaintiffs.phone),
                address = COALESCE(EXCLUDED.address, plaintiffs.address),
                updated_at = NOW()
            RETURNING (xmax = 0) AS is_insert
            """,
            (name, source_id, email, phone, address),
        )
        result = cur.fetchone()

    return "inserted" if result and result["is_insert"] else "updated"


# =============================================================================
# Ingest Worker (BaseWorker Implementation)
# =============================================================================


class IngestWorker(BaseWorker):
    """
    Worker that processes CSV ingest jobs with exactly-once semantics.

    Implements the "Claim & Commit" pattern using ingest.import_runs.

    Expected envelope payload:
    {
        "source_batch_id": "simplicity-2026-01-07-export.csv",
        "file_path": "intake/simplicity-2026-01-07-export.csv",
        "file_hash": "abc123..."  # Optional - computed if not provided
    }
    """

    queue_name = "q_ingest_raw"
    batch_size = 1  # Process one file at a time
    visibility_timeout = 300  # 5 minutes for large files
    max_retries = 3
    poll_interval = 2.0

    def process(self, envelope: JobEnvelope) -> dict[str, Any] | None:
        """
        Process an ingest job with exactly-once semantics.

        Implements:
        1. Parse envelope for source_batch_id and file_path
        2. Check ingest.import_runs for duplicate/in-progress
        3. Claim the run (set status='processing')
        4. Process CSV data with ON CONFLICT upserts
        5. Commit (set status='completed') or fail (set status='failed')
        """
        payload = envelope.payload
        source_batch_id = payload.get("source_batch_id") or envelope.idempotency_key
        file_path = payload.get("file_path")

        if not file_path:
            raise ValueError("Missing file_path in payload")

        logger.info(f"Processing ingest job: source_batch_id={source_batch_id}, file={file_path}")

        # Get database connection
        env = get_supabase_env()
        dsn = get_supabase_db_url(env)
        app_name = get_safe_application_name("ingest_worker")

        with psycopg.connect(dsn, application_name=app_name) as conn:
            # =====================================================================
            # Step 1: Idempotency & Stale Check (The Guard)
            # =====================================================================
            existing = get_import_run_status(conn, source_batch_id)

            # Case A: Already completed - skip duplicate
            if existing.is_completed:
                logger.info(f"[SKIP] Idempotency Guard: Duplicate batch: {source_batch_id}")
                return {
                    "status": "skipped",
                    "reason": "duplicate_completed",
                    "source_batch_id": source_batch_id,
                }

            # Case B: Fresh processing - job running elsewhere
            if existing.is_processing and not existing.is_stale:
                age_sec = (datetime.now(timezone.utc) - existing.started_at).total_seconds()
                logger.info(
                    f"[SKIP] Idempotency Guard: Job running elsewhere "
                    f"(age: {int(age_sec)}s): {source_batch_id}"
                )
                # Return success to ack message (don't retry)
                return {
                    "status": "skipped",
                    "reason": "already_processing",
                    "source_batch_id": source_batch_id,
                }

            # Case C: Stale processing - take over dead job
            if existing.is_processing and existing.is_stale:
                age_hours = (
                    datetime.now(timezone.utc) - existing.started_at
                ).total_seconds() / 3600
                logger.warning(
                    f"[STALE TAKEOVER] Processing run older than {PROCESSING_TIMEOUT_HOURS}h "
                    f"(age: {age_hours:.1f}h) - Taking over: {source_batch_id}"
                )
                # Update to pending so we can reclaim it
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE ingest.import_runs
                        SET status = 'pending'
                        WHERE source_batch_id = %s
                        """,
                        (source_batch_id,),
                    )
                conn.commit()

            # Case D: New import - proceed to claim

            # =====================================================================
            # Step 2: Load CSV and compute hash
            # =====================================================================
            try:
                df, file_hash = load_csv_from_storage(file_path)
            except Exception as e:
                logger.error(f"Failed to load CSV: {e}")
                fail_import_run(
                    conn,
                    source_batch_id,
                    {
                        "error": "load_failed",
                        "message": str(e)[:1000],
                    },
                )
                raise

            if df.empty:
                logger.warning(f"Empty CSV file: {file_path}")
                claim_import_run(conn, source_batch_id, file_hash)
                complete_import_run(conn, source_batch_id, 0)
                return {
                    "status": "completed",
                    "record_count": 0,
                    "source_batch_id": source_batch_id,
                }

            # =====================================================================
            # Step 3: Claim the import run
            # =====================================================================
            run_id = claim_import_run(conn, source_batch_id, file_hash)
            logger.info(f"Claimed import run: id={run_id}, batch={source_batch_id}")

            # =====================================================================
            # Step 4: Process the data
            # =====================================================================
            try:
                result = process_csv_data(conn, df, source_batch_id)
                conn.commit()

                # =====================================================================
                # Step 5: Mark completed
                # =====================================================================
                complete_import_run(conn, source_batch_id, result.record_count)

                logger.info(
                    f"Completed ingest: batch={source_batch_id}, "
                    f"records={result.record_count}, inserted={result.inserted}, "
                    f"updated={result.updated}, errors={len(result.errors)}"
                )

                return {
                    "status": "completed",
                    "source_batch_id": source_batch_id,
                    "record_count": result.record_count,
                    "inserted": result.inserted,
                    "updated": result.updated,
                    "skipped": result.skipped,
                    "error_count": len(result.errors),
                }

            except Exception as e:
                # =====================================================================
                # Step 6: Mark failed + Alert
                # =====================================================================
                logger.exception(f"Ingest failed for {source_batch_id}: {e}")
                conn.rollback()

                error_details = {
                    "error": type(e).__name__,
                    "message": str(e)[:1000],
                }
                fail_import_run(conn, source_batch_id, error_details)

                # Send Discord alert (fire-and-forget)
                alert_msg = (
                    f"[INGEST FAILURE] {source_batch_id}\n"
                    f"Error: {type(e).__name__}\n"
                    f"Message: {str(e)[:200]}"
                )
                send_discord_alert(alert_msg)

                raise  # Re-raise to trigger DLQ handling


# =============================================================================
# Entry Point
# =============================================================================


def main() -> int:
    """Run the Ingest Worker."""
    logger.info("=" * 60)
    logger.info("  DRAGONFLY INGEST WORKER (Exactly-Once)")
    logger.info("  Queue: q_ingest_raw")
    logger.info("  Tracking: ingest.import_runs")
    logger.info("=" * 60)

    worker = IngestWorker()
    return worker.run()


if __name__ == "__main__":
    sys.exit(main())
