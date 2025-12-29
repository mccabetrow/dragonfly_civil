#!/usr/bin/env python3
"""
Dragonfly Engine - Golden Path Orchestrator

The "Brain" worker that manages state transitions through the Golden Path
pipeline. Monitors batches in intake.simplicity_batches and orchestrates
the downstream job flow:

Pipeline Flow:
    intake.simplicity_batches (status='uploaded')
        → process_batch() via IngestionService → 'completed'/'failed'

    intake.simplicity_batches (status='validated')
        → ENTITY_RESOLVE (entity_resolve)
        → JUDGMENT_CREATE (judgment_create)
        → ENRICHMENT_REQUEST (enrichment_request)

Architecture:
    - Poll-based: Checks for 'uploaded' and 'validated' batches
    - Event-driven: Can also respond to database triggers (future)
    - Idempotent: Safe to run multiple instances (uses FOR UPDATE SKIP LOCKED)
    - Transactional: All state changes are atomic

Usage:
    python -m backend.workers.orchestrator

    # Single tick (for testing/cron)
    python -m backend.workers.orchestrator --once

Environment:
    SUPABASE_MODE: dev | prod (determines which Supabase project to use)
    SUPABASE_DB_URL: Postgres connection string (canonical)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.config.job_types import (
    JobType,
    PipelineStage,
    get_job_for_stage,
    get_next_stage,
    is_terminal_stage,
)
from backend.core.logging import configure_worker_logging
from src.supabase_client import get_supabase_db_url, get_supabase_env

# Configure logging
logger = configure_worker_logging("orchestrator")

# Worker configuration
POLL_INTERVAL_SECONDS = 5.0
BATCH_LOCK_TIMEOUT_MINUTES = 60


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class BatchOrchestration:
    """Represents a batch being orchestrated through the pipeline."""

    id: UUID
    batch_id: UUID
    stage: PipelineStage
    jobs_total: int
    jobs_completed: int
    jobs_failed: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]


@dataclass
class ImportRow:
    """A validated import row ready for processing."""

    id: UUID
    batch_id: UUID
    row_index: int
    data: Dict[str, Any]


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


def get_db_connection() -> psycopg.Connection:
    """Get a database connection using environment configuration."""
    dsn = get_supabase_db_url()
    return psycopg.connect(dsn, row_factory=dict_row)


def find_uploaded_batches(conn: psycopg.Connection, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Find batches that have been uploaded but not yet processed.

    Returns batches from intake.simplicity_batches where status = 'uploaded'.
    Uses FOR UPDATE SKIP LOCKED for safe concurrent access.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                b.id AS batch_id,
                b.filename,
                b.source_reference,
                b.row_count_total,
                b.created_at,
                b.status
            FROM intake.simplicity_batches b
            WHERE b.status = 'uploaded'
            ORDER BY b.created_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        return cur.fetchall()


async def process_uploaded_batch(batch_id: UUID) -> bool:
    """
    Process an uploaded batch using the IngestionService.

    This triggers the full ingestion pipeline:
    - Parse CSV
    - Validate rows
    - Dedupe against existing judgments
    - Insert to public.judgments

    Returns True if processing completed (success or failure),
    False if an error occurred.
    """
    from backend.services.ingestion_service import BatchProcessResult, process_batch

    try:
        logger.info(f"Processing uploaded batch: {batch_id}")
        result: BatchProcessResult = await process_batch(batch_id)
        logger.info(
            f"Batch {batch_id} processed: {result.status} "
            f"({result.rows_inserted} inserted, {result.rows_failed} failed)"
        )
        return True
    except Exception as e:
        logger.exception(f"Failed to process batch {batch_id}: {e}")
        return False


def find_batches_ready_for_orchestration(
    conn: psycopg.Connection, limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Find batches that have completed validation and are ready for orchestration.

    Returns batches from intake.simplicity_batches where status = 'validated'.
    Uses FOR UPDATE SKIP LOCKED for safe concurrent access.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                b.id AS batch_id,
                b.filename,
                b.source_reference,
                b.row_count_valid,
                b.transformed_at AS validation_completed_at,
                b.status
            FROM intake.simplicity_batches b
            WHERE b.status = 'validated'
            ORDER BY b.created_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        return cur.fetchall()


def create_orchestration_record(conn: psycopg.Connection, batch_id: UUID) -> None:
    """
    Transition a batch from 'validated' to 'upserting' status.

    This marks the batch as being actively processed by the orchestrator.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE intake.simplicity_batches
            SET status = 'upserting'
            WHERE id = %s AND status = 'validated'
            """,
            (str(batch_id),),
        )


def get_orchestration_by_batch(
    conn: psycopg.Connection, batch_id: UUID
) -> Optional[BatchOrchestration]:
    """Get the batch state from intake.simplicity_batches."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, row_count_valid
            FROM intake.simplicity_batches
            WHERE id = %s
            """,
            (str(batch_id),),
        )
        row = cur.fetchone()
        if not row:
            return None

        # Map batch status to pipeline stage
        status_to_stage = {
            "validated": PipelineStage.VALIDATED,
            "upserting": PipelineStage.ENTITY_RESOLVING,
            "completed": PipelineStage.COMPLETE,
            "failed": PipelineStage.FAILED,
        }
        stage = status_to_stage.get(row["status"], PipelineStage.VALIDATED)

        return BatchOrchestration(
            id=UUID(str(row["id"])),
            batch_id=UUID(str(row["id"])),  # batch_id == id for this table
            stage=stage,
            jobs_total=row["row_count_valid"] or 0,
            jobs_completed=0,
            jobs_failed=0,
            started_at=None,
            completed_at=None,
            error_message=None,
        )


def update_orchestration_stage(
    conn: psycopg.Connection,
    batch_id: UUID,
    stage: PipelineStage,
    jobs_total: Optional[int] = None,
    jobs_completed: Optional[int] = None,
    jobs_failed: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Update the batch status in intake.simplicity_batches."""
    # Map pipeline stage to batch status
    stage_to_status = {
        PipelineStage.VALIDATED: "validated",
        PipelineStage.ENTITY_RESOLVING: "upserting",
        PipelineStage.ENTITY_RESOLVED: "upserting",
        PipelineStage.JUDGMENT_CREATING: "upserting",
        PipelineStage.JUDGMENT_CREATED: "upserting",
        PipelineStage.ENRICHING: "upserting",
        PipelineStage.ENRICHED: "upserting",
        PipelineStage.COMPLETE: "completed",
        PipelineStage.FAILED: "failed",
    }

    new_status = stage_to_status.get(stage, "upserting")

    updates = ["status = %s"]
    params: List[Any] = [new_status]

    if error_message is not None:
        updates.append("error_summary = %s")
        params.append(error_message)

    if stage == PipelineStage.COMPLETE:
        updates.append("completed_at = NOW()")

    params.append(str(batch_id))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE intake.simplicity_batches
            SET {", ".join(updates)}
            WHERE id = %s
            """,
            params,
        )


def get_validated_rows_for_batch(conn: psycopg.Connection, batch_id: UUID) -> List[ImportRow]:
    """Get all validated rows for a batch from intake.simplicity_validated_rows."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, batch_id, row_index,
                   jsonb_build_object(
                       'case_number', case_number,
                       'plaintiff_name', plaintiff_name,
                       'defendant_name', defendant_name,
                       'judgment_amount', judgment_amount,
                       'entry_date', entry_date,
                       'judgment_date', judgment_date,
                       'court', court,
                       'county', county
                   ) AS parsed_data
            FROM intake.simplicity_validated_rows
            WHERE batch_id = %s
              AND validation_status = 'valid'
            ORDER BY row_index
            """,
            (str(batch_id),),
        )
        rows = cur.fetchall()
        return [
            ImportRow(
                id=(
                    UUID(str(r["id"]))
                    if isinstance(r["id"], str)
                    else UUID(int=r["id"]) if r["id"] else uuid4()
                ),
                batch_id=UUID(str(r["batch_id"])),
                row_index=r["row_index"],
                data=r["parsed_data"] or {},
            )
            for r in rows
        ]


def enqueue_job(
    conn: psycopg.Connection,
    job_type: JobType,
    payload: Dict[str, Any],
    dedup_key: Optional[str] = None,
    correlation_id: Optional[UUID] = None,
) -> UUID:
    """
    Enqueue a job to ops.job_queue.

    Uses ON CONFLICT to ensure idempotency when dedup_key is provided.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.job_queue (job_type, payload, dedup_key, correlation_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (job_type, dedup_key)
                WHERE dedup_key IS NOT NULL
            DO UPDATE SET updated_at = NOW()
            RETURNING id
            """,
            (
                job_type.value,
                psycopg.types.json.Json(payload),
                dedup_key,
                str(correlation_id) if correlation_id else None,
            ),
        )
        row = cur.fetchone()
        return UUID(str(row["id"]))


def count_jobs_by_status(
    conn: psycopg.Connection,
    job_type: JobType,
    batch_id: UUID,
) -> Dict[str, int]:
    """
    Count jobs for a batch by status.

    Assumes dedup_key format: {job_type}-{batch_id}-{row_index}
    """
    dedup_prefix = f"{job_type.value}-{batch_id}-"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*) as count
            FROM ops.job_queue
            WHERE job_type = %s
              AND dedup_key LIKE %s
            GROUP BY status
            """,
            (job_type.value, f"{dedup_prefix}%"),
        )
        return {row["status"]: row["count"] for row in cur.fetchall()}


# =============================================================================
# ORCHESTRATION LOGIC
# =============================================================================


def enqueue_entity_resolve_jobs(
    conn: psycopg.Connection,
    orchestration: BatchOrchestration,
) -> int:
    """
    Enqueue entity_resolve jobs for all validated rows in a batch.

    Returns the number of jobs enqueued.
    """
    rows = get_validated_rows_for_batch(conn, orchestration.batch_id)

    if not rows:
        logger.warning(f"Batch {orchestration.batch_id} has no validated rows")
        return 0

    enqueued = 0
    for row in rows:
        payload = {
            "batch_id": str(orchestration.batch_id),
            "row_id": str(row.id),
            "row_index": row.row_index,
            "data": row.data,
        }
        dedup_key = f"{JobType.ENTITY_RESOLVE.value}-{orchestration.batch_id}-{row.row_index}"

        enqueue_job(
            conn,
            JobType.ENTITY_RESOLVE,
            payload,
            dedup_key=dedup_key,
            correlation_id=orchestration.batch_id,
        )
        enqueued += 1

    logger.info(f"Enqueued {enqueued} entity_resolve jobs for batch {orchestration.batch_id}")
    return enqueued


def check_stage_completion(
    conn: psycopg.Connection,
    orchestration: BatchOrchestration,
    job_type: JobType,
) -> tuple[bool, int, int, int]:
    """
    Check if all jobs for a stage have completed.

    Returns: (is_complete, total, completed, failed)
    """
    counts = count_jobs_by_status(conn, job_type, orchestration.batch_id)

    total = sum(counts.values())
    completed = counts.get("completed", 0) + counts.get("success", 0)
    failed = counts.get("failed", 0) + counts.get("dead_letter", 0)
    pending = counts.get("pending", 0) + counts.get("processing", 0) + counts.get("locked", 0)

    is_complete = pending == 0 and total > 0

    return is_complete, total, completed, failed


def advance_pipeline(
    conn: psycopg.Connection,
    orchestration: BatchOrchestration,
) -> bool:
    """
    Attempt to advance a batch through the pipeline.

    Returns True if the batch was advanced, False if no action taken.
    """
    stage = orchestration.stage

    # Terminal stages - nothing to do
    if is_terminal_stage(stage):
        return False

    # VALIDATED → ENTITY_RESOLVING: Enqueue entity resolve jobs
    if stage == PipelineStage.VALIDATED:
        jobs_count = enqueue_entity_resolve_jobs(conn, orchestration)
        if jobs_count > 0:
            update_orchestration_stage(
                conn,
                orchestration.batch_id,
                PipelineStage.ENTITY_RESOLVING,
                jobs_total=jobs_count,
                jobs_completed=0,
                jobs_failed=0,
            )
            logger.info(
                f"Batch {orchestration.batch_id}: VALIDATED → ENTITY_RESOLVING ({jobs_count} jobs)"
            )
            return True
        else:
            # No rows to process - mark as complete
            update_orchestration_stage(conn, orchestration.batch_id, PipelineStage.COMPLETE)
            logger.info(f"Batch {orchestration.batch_id}: No rows, marked COMPLETE")
            return True

    # ENTITY_RESOLVING → ENTITY_RESOLVED: Check if all jobs done
    if stage == PipelineStage.ENTITY_RESOLVING:
        is_done, total, completed, failed = check_stage_completion(
            conn, orchestration, JobType.ENTITY_RESOLVE
        )
        if is_done:
            if failed > 0 and completed == 0:
                # All jobs failed
                update_orchestration_stage(
                    conn,
                    orchestration.batch_id,
                    PipelineStage.FAILED,
                    jobs_completed=completed,
                    jobs_failed=failed,
                    error_message=f"All {failed} entity_resolve jobs failed",
                )
                logger.error(f"Batch {orchestration.batch_id}: ENTITY_RESOLVING → FAILED")
            else:
                update_orchestration_stage(
                    conn,
                    orchestration.batch_id,
                    PipelineStage.ENTITY_RESOLVED,
                    jobs_completed=completed,
                    jobs_failed=failed,
                )
                logger.info(
                    f"Batch {orchestration.batch_id}: ENTITY_RESOLVING → ENTITY_RESOLVED ({completed}/{total})"
                )
            return True
        else:
            # Update progress
            update_orchestration_stage(
                conn, orchestration.batch_id, stage, jobs_completed=completed, jobs_failed=failed
            )
            return False

    # ENTITY_RESOLVED → JUDGMENT_CREATING: Enqueue judgment create jobs
    if stage == PipelineStage.ENTITY_RESOLVED:
        # For now, we reuse the same rows - in production, we'd read resolved data
        rows = get_validated_rows_for_batch(conn, orchestration.batch_id)
        jobs_count = 0
        for row in rows:
            payload = {
                "batch_id": str(orchestration.batch_id),
                "row_id": str(row.id),
                "row_index": row.row_index,
            }
            dedup_key = f"{JobType.JUDGMENT_CREATE.value}-{orchestration.batch_id}-{row.row_index}"
            enqueue_job(conn, JobType.JUDGMENT_CREATE, payload, dedup_key=dedup_key)
            jobs_count += 1

        if jobs_count > 0:
            update_orchestration_stage(
                conn,
                orchestration.batch_id,
                PipelineStage.JUDGMENT_CREATING,
                jobs_total=jobs_count,
                jobs_completed=0,
                jobs_failed=0,
            )
            logger.info(
                f"Batch {orchestration.batch_id}: ENTITY_RESOLVED → JUDGMENT_CREATING ({jobs_count} jobs)"
            )
            return True
        else:
            update_orchestration_stage(conn, orchestration.batch_id, PipelineStage.COMPLETE)
            return True

    # JUDGMENT_CREATING → JUDGMENT_CREATED: Check if all jobs done
    if stage == PipelineStage.JUDGMENT_CREATING:
        is_done, total, completed, failed = check_stage_completion(
            conn, orchestration, JobType.JUDGMENT_CREATE
        )
        if is_done:
            update_orchestration_stage(
                conn,
                orchestration.batch_id,
                PipelineStage.JUDGMENT_CREATED,
                jobs_completed=completed,
                jobs_failed=failed,
            )
            logger.info(f"Batch {orchestration.batch_id}: JUDGMENT_CREATING → JUDGMENT_CREATED")
            return True
        return False

    # JUDGMENT_CREATED → ENRICHING: Enqueue enrichment jobs
    if stage == PipelineStage.JUDGMENT_CREATED:
        # Query judgments created from this batch and enqueue enrichment
        # For simplicity, skip enrichment in MVP - mark complete
        update_orchestration_stage(conn, orchestration.batch_id, PipelineStage.COMPLETE)
        logger.info(
            f"Batch {orchestration.batch_id}: JUDGMENT_CREATED → COMPLETE (enrichment skipped in MVP)"
        )
        return True

    # ENRICHING → ENRICHED → COMPLETE handled similarly
    # For MVP, we skip to complete after judgment creation

    return False


def process_one_batch(conn: psycopg.Connection) -> bool:
    """
    Process one batch through the pipeline.

    Returns True if a batch was processed, False if no work available.
    """
    # Find batches ready for orchestration
    batches = find_batches_ready_for_orchestration(conn, limit=1)

    if not batches:
        return False

    batch_info = batches[0]
    batch_id = UUID(str(batch_info["batch_id"]))

    # Transition batch to 'upserting' status
    create_orchestration_record(conn, batch_id)
    conn.commit()
    logger.info(f"Batch {batch_id} transitioned to upserting")

    # Get current orchestration state
    orchestration = get_orchestration_by_batch(conn, batch_id)
    if not orchestration:
        logger.error(f"Failed to get orchestration for batch {batch_id}")
        return False

    # Attempt to advance the pipeline
    try:
        advanced = advance_pipeline(conn, orchestration)
        conn.commit()
        return advanced
    except Exception as e:
        conn.rollback()
        logger.exception(f"Error advancing batch {batch_id}: {e}")
        # Mark as failed
        try:
            update_orchestration_stage(
                conn, orchestration.batch_id, PipelineStage.FAILED, error_message=str(e)[:500]
            )
            conn.commit()
        except Exception:
            logger.exception("Failed to mark batch as failed")
        return False


# =============================================================================
# MAIN LOOP
# =============================================================================


def process_uploaded_batches_sync() -> bool:
    """
    Find and process any uploaded batches.

    This is the synchronous entry point that runs the async process_batch.
    Returns True if any work was done.
    """
    with get_db_connection() as conn:
        # Find uploaded batches
        uploaded = find_uploaded_batches(conn, limit=1)

        if not uploaded:
            return False

        batch_info = uploaded[0]
        batch_id = UUID(str(batch_info["batch_id"]))
        filename = batch_info.get("filename", "unknown")

        logger.info(f"Found uploaded batch: {batch_id} ({filename})")

        # Release the lock before async processing
        conn.commit()

    # Run the async processing
    try:
        did_process = asyncio.run(process_uploaded_batch(batch_id))
        return did_process
    except Exception as e:
        logger.exception(f"Error processing uploaded batch {batch_id}: {e}")
        return False


def run_once() -> bool:
    """
    Run a single orchestration tick. Returns True if work was done.

    Priority:
    1. Process uploaded batches (CSV → judgments via IngestionService)
    2. Advance validated batches through the pipeline (future entity resolution)
    """
    # First, check for uploaded batches that need processing
    if process_uploaded_batches_sync():
        return True

    # Then, check for validated batches ready for orchestration
    with get_db_connection() as conn:
        return process_one_batch(conn)


def run_loop() -> None:
    """Run the orchestrator in a continuous loop."""
    logger.info("Golden Path Orchestrator starting...")
    logger.info(f"Environment: {get_supabase_env()}")
    logger.info(f"Poll interval: {POLL_INTERVAL_SECONDS}s")

    consecutive_idle = 0

    while True:
        try:
            did_work = run_once()

            if did_work:
                consecutive_idle = 0
                # Immediately check for more work
                continue
            else:
                consecutive_idle += 1
                # Log periodically when idle
                if consecutive_idle % 60 == 0:  # Every 5 minutes at 5s interval
                    logger.debug("Orchestrator idle, no batches to process")

            time.sleep(POLL_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Orchestrator shutting down (KeyboardInterrupt)")
            break
        except Exception as e:
            logger.exception(f"Orchestrator loop error: {e}")
            # Back off on errors
            time.sleep(POLL_INTERVAL_SECONDS * 2)


def main() -> None:
    """Entry point for the orchestrator worker."""
    parser = argparse.ArgumentParser(description="Golden Path Orchestrator")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single tick and exit",
    )
    args = parser.parse_args()

    if args.once:
        did_work = run_once()
        if did_work:
            logger.info("Orchestrator tick: work completed")
            sys.exit(0)
        else:
            logger.info("Orchestrator tick: no work available")
            sys.exit(0)
    else:
        run_loop()


if __name__ == "__main__":
    main()
