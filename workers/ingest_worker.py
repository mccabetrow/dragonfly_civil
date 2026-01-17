"""
workers/ingest_worker.py
=========================
Production-grade ingest worker with transactional claim pattern.

This module provides exactly-once ingestion semantics using the
ingest.import_runs table for idempotency tracking.

Design Principles:
- Idempotency key: source_batch_id (caller-provided, e.g., filename, S3 key)
- File hash: SHA-256 for duplicate content detection
- Transactional claim: UPDATE ... WHERE status='pending' RETURNING
- Heartbeat: Updates updated_at during processing for stale takeover
- Stale takeover: Jobs stuck > STALE_THRESHOLD_SECONDS can be reclaimed

States:
- pending: Job created, awaiting processing
- processing: Job claimed, work in progress
- completed: Job finished successfully
- failed: Job finished with error

Usage:
    from workers.ingest_worker import IngestWorker

    worker = IngestWorker()
    result = await worker.process_batch(
        source_batch_id="vendor_export_2026-01-13.csv",
        file_hash="sha256:abc123...",
        processor=my_processing_function,
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional
from uuid import UUID

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

logger = logging.getLogger(__name__)

# Configuration
STALE_THRESHOLD_SECONDS: int = 300  # 5 minutes - jobs older than this can be taken over
HEARTBEAT_INTERVAL_SECONDS: float = 30.0  # Update updated_at every 30 seconds


class ImportRunStatus(str, Enum):
    """Import run status values matching ingest.import_run_status enum."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ClaimResult(str, Enum):
    """Result of attempting to claim a job."""

    CLAIMED = "claimed"  # Successfully claimed for processing
    ALREADY_RUNNING = "already_running"  # Another worker is processing
    ALREADY_COMPLETED = "already_completed"  # Job already finished successfully
    ALREADY_FAILED = "already_failed"  # Job already failed
    STALE_TAKEOVER = "stale_takeover"  # Took over a stale job


class IngestError(Exception):
    """Base exception for ingest worker errors."""

    pass


class DuplicateBatchError(IngestError):
    """Raised when a batch with the same source_batch_id is already completed."""

    def __init__(self, source_batch_id: str, completed_at: datetime | None = None):
        self.source_batch_id = source_batch_id
        self.completed_at = completed_at
        super().__init__(f"Batch '{source_batch_id}' already completed at {completed_at}")


class JobAlreadyRunningError(IngestError):
    """Raised when a batch is currently being processed by another worker."""

    def __init__(self, source_batch_id: str, started_at: datetime | None = None):
        self.source_batch_id = source_batch_id
        self.started_at = started_at
        super().__init__(
            f"Batch '{source_batch_id}' is currently being processed (started {started_at})"
        )


def compute_file_hash(content: bytes) -> str:
    """Compute SHA-256 hash of file content.

    Args:
        content: Raw file bytes

    Returns:
        Hash string in format "sha256:<hex>"
    """
    digest = hashlib.sha256(content).hexdigest()
    return f"sha256:{digest}"


ProcessorFunc = Callable[[str, str], Awaitable[int]]  # (source_batch_id, file_hash) -> record_count


class IngestWorker:
    """
    Production ingest worker with transactional claim pattern.

    Provides exactly-once semantics for batch ingestion using PostgreSQL
    transactions and the ingest.import_runs table.

    Example:
        worker = IngestWorker()

        async def my_processor(source_batch_id: str, file_hash: str) -> int:
            # ... process the batch ...
            return record_count

        result = await worker.process_batch(
            source_batch_id="export_2026-01-13.csv",
            file_hash="sha256:abc123",
            processor=my_processor,
        )
    """

    def __init__(self, db_url: str | None = None):
        """Initialize worker.

        Args:
            db_url: PostgreSQL connection string. If None, uses get_supabase_db_url().
        """
        self._db_url = db_url or get_supabase_db_url()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._current_job_id: UUID | None = None
        self._stop_heartbeat = asyncio.Event()

    async def _get_connection(self) -> psycopg.AsyncConnection[Dict[str, Any]]:
        """Get async database connection."""
        return await psycopg.AsyncConnection.connect(
            self._db_url,
            row_factory=dict_row,
            autocommit=False,
        )

    async def _create_or_get_job(
        self,
        conn: psycopg.AsyncConnection[Any],
        source_batch_id: str,
        file_hash: str,
    ) -> Dict[str, Any]:
        """Create a new job record or get existing one.

        Uses INSERT ... ON CONFLICT to handle race conditions.
        """
        async with conn.cursor() as cur:
            # Try to insert; if exists, return existing
            await cur.execute(
                """
                INSERT INTO ingest.import_runs (source_batch_id, file_hash, status)
                VALUES (%(source_batch_id)s, %(file_hash)s, 'pending')
                ON CONFLICT (source_batch_id) DO UPDATE
                    SET updated_at = now()  -- Touch to show activity
                RETURNING id, source_batch_id, file_hash, status, started_at,
                          completed_at, record_count, error_details, created_at, updated_at
                """,
                {"source_batch_id": source_batch_id, "file_hash": file_hash},
            )
            row = await cur.fetchone()
            if row is None:
                raise IngestError(f"Failed to create/get job for {source_batch_id}")
            return dict(row)

    async def _try_claim_job(
        self,
        conn: psycopg.AsyncConnection[Any],
        source_batch_id: str,
    ) -> tuple[ClaimResult, Dict[str, Any] | None]:
        """Attempt to claim a job for processing.

        Uses UPDATE ... WHERE status='pending' RETURNING for atomic claim.
        Also handles stale takeover for jobs stuck in 'processing'.

        Returns:
            Tuple of (claim_result, job_record or None)
        """
        now_utc = datetime.now(timezone.utc)
        stale_threshold = now_utc - timedelta(seconds=STALE_THRESHOLD_SECONDS)

        async with conn.cursor() as cur:
            # First, try to claim pending job
            await cur.execute(
                """
                UPDATE ingest.import_runs
                SET status = 'processing',
                    started_at = now(),
                    updated_at = now()
                WHERE source_batch_id = %(source_batch_id)s
                  AND status = 'pending'
                RETURNING id, source_batch_id, file_hash, status, started_at,
                          completed_at, record_count, error_details, created_at, updated_at
                """,
                {"source_batch_id": source_batch_id},
            )
            row = await cur.fetchone()
            if row:
                await conn.commit()
                logger.info("Claimed job %s for processing", source_batch_id)
                return ClaimResult.CLAIMED, dict(row)

            # Not pending - check current status
            await cur.execute(
                """
                SELECT id, source_batch_id, file_hash, status, started_at,
                       completed_at, record_count, error_details, created_at, updated_at
                FROM ingest.import_runs
                WHERE source_batch_id = %(source_batch_id)s
                """,
                {"source_batch_id": source_batch_id},
            )
            existing = await cur.fetchone()

            if existing is None:
                # Job doesn't exist (shouldn't happen after _create_or_get_job)
                return ClaimResult.CLAIMED, None

            status = existing["status"]

            if status == "completed":
                return ClaimResult.ALREADY_COMPLETED, dict(existing)

            if status == "failed":
                return ClaimResult.ALREADY_FAILED, dict(existing)

            if status == "processing":
                # Check if stale (updated_at older than threshold)
                updated_at = existing.get("updated_at")
                if updated_at and updated_at < stale_threshold:
                    # Stale takeover
                    await cur.execute(
                        """
                        UPDATE ingest.import_runs
                        SET status = 'processing',
                            started_at = now(),
                            updated_at = now()
                        WHERE source_batch_id = %(source_batch_id)s
                          AND status = 'processing'
                          AND updated_at < %(stale_threshold)s
                        RETURNING id, source_batch_id, file_hash, status, started_at,
                                  completed_at, record_count, error_details, created_at, updated_at
                        """,
                        {"source_batch_id": source_batch_id, "stale_threshold": stale_threshold},
                    )
                    taken = await cur.fetchone()
                    if taken:
                        await conn.commit()
                        logger.warning(
                            "Stale takeover of job %s (last update: %s)",
                            source_batch_id,
                            updated_at,
                        )
                        return ClaimResult.STALE_TAKEOVER, dict(taken)

                # Still running and not stale
                return ClaimResult.ALREADY_RUNNING, dict(existing)

            # Unknown status
            logger.error("Unexpected job status: %s for %s", status, source_batch_id)
            return ClaimResult.ALREADY_RUNNING, dict(existing)

    async def _start_heartbeat(self, job_id: UUID) -> None:
        """Start background heartbeat task to update updated_at."""
        self._current_job_id = job_id
        self._stop_heartbeat.clear()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(job_id))

    async def _stop_heartbeat_task(self) -> None:
        """Stop the heartbeat task."""
        self._stop_heartbeat.set()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        self._current_job_id = None

    async def _heartbeat_loop(self, job_id: UUID) -> None:
        """Background loop to update updated_at while processing."""
        while not self._stop_heartbeat.is_set():
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if self._stop_heartbeat.is_set():
                    break

                async with await self._get_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            UPDATE ingest.import_runs
                            SET updated_at = now()
                            WHERE id = %(job_id)s AND status = 'processing'
                            """,
                            {"job_id": str(job_id)},
                        )
                        await conn.commit()
                        logger.debug("Heartbeat for job %s", job_id)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Heartbeat failed for job %s: %s", job_id, exc)

    async def _mark_completed(
        self,
        conn: psycopg.AsyncConnection[Any],
        job_id: UUID,
        record_count: int,
    ) -> None:
        """Mark job as completed."""
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE ingest.import_runs
                SET status = 'completed',
                    completed_at = now(),
                    updated_at = now(),
                    record_count = %(record_count)s
                WHERE id = %(job_id)s
                """,
                {"job_id": str(job_id), "record_count": record_count},
            )
            await conn.commit()
        logger.info("Job %s completed with %d records", job_id, record_count)

    async def _mark_failed(
        self,
        conn: psycopg.AsyncConnection[Any],
        job_id: UUID,
        error_details: Dict[str, Any],
    ) -> None:
        """Mark job as failed."""
        import json

        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE ingest.import_runs
                SET status = 'failed',
                    completed_at = now(),
                    updated_at = now(),
                    error_details = %(error_details)s::jsonb
                WHERE id = %(job_id)s
                """,
                {"job_id": str(job_id), "error_details": json.dumps(error_details)},
            )
            await conn.commit()
        logger.error("Job %s failed: %s", job_id, error_details.get("message", "unknown"))

    async def process_batch(
        self,
        source_batch_id: str,
        file_hash: str,
        processor: ProcessorFunc,
        *,
        allow_stale_takeover: bool = True,
        raise_on_duplicate: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a batch with exactly-once semantics.

        Args:
            source_batch_id: Unique identifier for the batch (e.g., filename, S3 key)
            file_hash: SHA-256 hash of the file content
            processor: Async function that processes the batch, returns record count
            allow_stale_takeover: If True, take over stale jobs stuck in processing
            raise_on_duplicate: If True, raise DuplicateBatchError for completed batches

        Returns:
            Dict with job status and metadata

        Raises:
            DuplicateBatchError: If batch already completed and raise_on_duplicate=True
            JobAlreadyRunningError: If batch is being processed by another worker
            IngestError: For other errors
        """
        logger.info("Processing batch: %s (hash: %s...)", source_batch_id, file_hash[:20])

        async with await self._get_connection() as conn:
            # Create job record if it doesn't exist
            await self._create_or_get_job(conn, source_batch_id, file_hash)
            await conn.commit()

            # Try to claim the job
            claim_result, job_record = await self._try_claim_job(conn, source_batch_id)

            if claim_result == ClaimResult.ALREADY_COMPLETED:
                if raise_on_duplicate:
                    raise DuplicateBatchError(
                        source_batch_id,
                        job_record.get("completed_at") if job_record else None,
                    )
                logger.info("Batch %s already completed, skipping", source_batch_id)
                return {
                    "status": "skipped",
                    "reason": "already_completed",
                    "job": job_record,
                }

            if claim_result == ClaimResult.ALREADY_FAILED:
                logger.warning("Batch %s previously failed, not retrying", source_batch_id)
                return {
                    "status": "skipped",
                    "reason": "already_failed",
                    "job": job_record,
                }

            if claim_result == ClaimResult.ALREADY_RUNNING:
                raise JobAlreadyRunningError(
                    source_batch_id,
                    job_record.get("started_at") if job_record else None,
                )

            if claim_result == ClaimResult.STALE_TAKEOVER and not allow_stale_takeover:
                raise JobAlreadyRunningError(source_batch_id)

            # We have the claim - process the batch
            if job_record is None:
                raise IngestError(f"Claimed job but no record for {source_batch_id}")

            job_id = UUID(str(job_record["id"]))

            try:
                # Start heartbeat
                await self._start_heartbeat(job_id)

                # Run the processor
                record_count = await processor(source_batch_id, file_hash)

                # Mark completed
                await self._mark_completed(conn, job_id, record_count)

                return {
                    "status": "completed",
                    "record_count": record_count,
                    "job_id": str(job_id),
                    "claim_result": claim_result.value,
                }

            except Exception as exc:
                # Mark failed
                error_details = {
                    "message": str(exc),
                    "type": type(exc).__name__,
                }
                await self._mark_failed(conn, job_id, error_details)
                raise IngestError(f"Processing failed for {source_batch_id}: {exc}") from exc

            finally:
                # Stop heartbeat
                await self._stop_heartbeat_task()

    async def get_job_status(self, source_batch_id: str) -> Dict[str, Any] | None:
        """Get the current status of a job by source_batch_id.

        Returns:
            Job record dict or None if not found
        """
        async with await self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT id, source_batch_id, file_hash, status, started_at,
                           completed_at, record_count, error_details, created_at, updated_at
                    FROM ingest.import_runs
                    WHERE source_batch_id = %(source_batch_id)s
                    """,
                    {"source_batch_id": source_batch_id},
                )
                row = await cur.fetchone()
                return dict(row) if row else None

    async def reset_failed_job(self, source_batch_id: str) -> bool:
        """Reset a failed job to pending for retry.

        Returns:
            True if reset, False if job not found or not in failed state
        """
        async with await self._get_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    UPDATE ingest.import_runs
                    SET status = 'pending',
                        started_at = NULL,
                        completed_at = NULL,
                        record_count = NULL,
                        error_details = NULL,
                        updated_at = now()
                    WHERE source_batch_id = %(source_batch_id)s
                      AND status = 'failed'
                    RETURNING id
                    """,
                    {"source_batch_id": source_batch_id},
                )
                row = await cur.fetchone()
                await conn.commit()
                if row:
                    logger.info("Reset failed job %s to pending", source_batch_id)
                    return True
                return False
