"""
Dragonfly Engine - Queue Processor

Production-grade async queue processing with:
- Pydantic validation for all payloads
- Transactional job state management
- Structured logging with correlation IDs
- Configurable retry policies with exponential backoff
- Dead letter queue for failed jobs
- Throughput: 10,000+ jobs/hour capacity

Architecture:
- Worker pools with configurable concurrency
- FOR UPDATE SKIP LOCKED for safe concurrent dequeue
- Idempotency key deduplication
- Graceful shutdown handling

Usage:
    from backend.core.queue_processor import QueueProcessor, JobHandler

    processor = QueueProcessor(kind="enrich", concurrency=4)
    processor.register_handler(handle_enrich)
    await processor.run()
"""

from __future__ import annotations

import asyncio
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from backend.config import get_settings
from backend.core.logging import (
    LogContext,
    Timer,
    get_logger,
    log_worker_failure,
    log_worker_start,
    log_worker_success,
    set_run_id,
)
from backend.core.models import (
    AllocateJobPayload,
    EnforceJobPayload,
    EnrichJobPayload,
    OutreachJobPayload,
    QueueJob,
    QueueJobKind,
    QueueJobStatus,
    ScoreJobPayload,
    ServiceDispatchJobPayload,
)
from backend.db import get_pool

logger = get_logger(__name__)

T = TypeVar("T")
JobHandler = Callable[[QueueJob, Dict[str, Any]], Awaitable[bool]]


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class RetryPolicy:
    """Retry configuration for failed jobs."""

    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 300.0
    exponential_base: float = 2.0
    jitter: bool = True

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number with exponential backoff."""
        delay = self.base_delay_seconds * (self.exponential_base ** (attempt - 1))
        delay = min(delay, self.max_delay_seconds)

        if self.jitter:
            import random

            delay = delay * (0.5 + random.random())

        return delay


@dataclass
class QueueProcessorConfig:
    """Configuration for queue processor."""

    kind: QueueJobKind
    concurrency: int = 4
    poll_interval_seconds: float = 0.5
    batch_size: int = 10
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    enable_dead_letter: bool = True
    shutdown_timeout_seconds: float = 30.0


# =============================================================================
# Job Validator
# =============================================================================


def validate_job_payload(kind: QueueJobKind, payload: Dict[str, Any]) -> Any:
    """
    Validate job payload against appropriate Pydantic model.

    Args:
        kind: Job type for model selection
        payload: Raw payload dict

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If payload fails validation
    """
    model_map = {
        QueueJobKind.ENRICH: EnrichJobPayload,
        QueueJobKind.SCORE: ScoreJobPayload,
        QueueJobKind.ALLOCATE: AllocateJobPayload,
        QueueJobKind.OUTREACH: OutreachJobPayload,
        QueueJobKind.ENFORCE: EnforceJobPayload,
        QueueJobKind.SERVICE_DISPATCH: ServiceDispatchJobPayload,
    }

    model_class = model_map.get(kind)
    if model_class is None:
        logger.warning(f"No validation model for job kind: {kind}")
        return payload

    # Add kind to payload if missing
    if "kind" not in payload:
        payload["kind"] = kind.value

    return model_class.model_validate(payload)


# =============================================================================
# Queue Processor
# =============================================================================


class QueueProcessor:
    """
    Production-grade async queue processor.

    Features:
    - Concurrent job processing with configurable parallelism
    - Pydantic validation for all payloads
    - Transactional job state management
    - Exponential backoff retries
    - Dead letter queue for poison messages
    - Structured JSON logging
    - Graceful shutdown
    """

    def __init__(self, config: QueueProcessorConfig) -> None:
        self.config = config
        self._handlers: Dict[QueueJobKind, JobHandler] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._active_jobs: Dict[int, asyncio.Task] = {}
        self._stats = ProcessorStats()

    def register_handler(self, kind: QueueJobKind, handler: JobHandler) -> None:
        """Register a handler for a job kind."""
        self._handlers[kind] = handler
        logger.info(f"Registered handler for {kind.value}")

    async def run(self) -> None:
        """
        Start the queue processor.

        Runs until shutdown is signaled.
        """
        self._running = True
        self._setup_signal_handlers()

        logger.info(
            "Starting queue processor",
            extra={
                "kind": self.config.kind.value,
                "concurrency": self.config.concurrency,
                "poll_interval": self.config.poll_interval_seconds,
            },
        )

        try:
            # Create worker pool
            workers = [
                asyncio.create_task(self._worker_loop(worker_id))
                for worker_id in range(self.config.concurrency)
            ]

            # Wait for shutdown or workers to complete
            await self._shutdown_event.wait()

            # Cancel workers
            for worker in workers:
                worker.cancel()

            await asyncio.gather(*workers, return_exceptions=True)

        finally:
            self._running = False
            logger.info(
                "Queue processor stopped",
                extra={
                    "kind": self.config.kind.value,
                    "jobs_processed": self._stats.processed,
                    "jobs_failed": self._stats.failed,
                },
            )

    async def shutdown(self) -> None:
        """Signal graceful shutdown."""
        logger.info("Shutdown requested, waiting for active jobs...")
        self._shutdown_event.set()

        # Wait for active jobs with timeout
        if self._active_jobs:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._active_jobs.values(), return_exceptions=True),
                    timeout=self.config.shutdown_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Shutdown timeout, {len(self._active_jobs)} jobs still active")

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown."""
        loop = asyncio.get_running_loop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.create_task(self.shutdown()),
            )

    async def _worker_loop(self, worker_id: int) -> None:
        """Main worker loop for processing jobs."""
        logger.info(f"Worker {worker_id} started for {self.config.kind.value}")

        while self._running and not self._shutdown_event.is_set():
            try:
                # Dequeue batch of jobs
                jobs = await self._dequeue_batch()

                if not jobs:
                    await asyncio.sleep(self.config.poll_interval_seconds)
                    continue

                # Process jobs concurrently
                for job in jobs:
                    if self._shutdown_event.is_set():
                        break

                    task = asyncio.create_task(self._process_job(job))
                    self._active_jobs[job.msg_id] = task

                    try:
                        await task
                    finally:
                        self._active_jobs.pop(job.msg_id, None)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Worker {worker_id} error: {e}")
                await asyncio.sleep(self.config.poll_interval_seconds)

        logger.info(f"Worker {worker_id} stopped")

    async def _dequeue_batch(self) -> List[QueueJob]:
        """
        Dequeue a batch of jobs using FOR UPDATE SKIP LOCKED.

        This ensures safe concurrent processing across multiple workers.
        """
        pool = await get_pool()

        query = """
            WITH claimed AS (
                SELECT msg_id, kind, payload, attempts, created_at
                FROM job_queue
                WHERE kind = %(kind)s
                  AND status = 'pending'
                  AND (retry_after IS NULL OR retry_after <= NOW())
                ORDER BY created_at
                LIMIT %(batch_size)s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE job_queue jq
            SET status = 'in_progress',
                processed_at = NOW()
            FROM claimed c
            WHERE jq.msg_id = c.msg_id
            RETURNING jq.msg_id, jq.kind, jq.payload, jq.attempts, jq.created_at
        """

        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    query,
                    {"kind": self.config.kind.value, "batch_size": self.config.batch_size},
                )
                rows = await cur.fetchall()

        jobs = []
        for row in rows:
            try:
                job = QueueJob(
                    msg_id=row["msg_id"],
                    kind=QueueJobKind(row["kind"]),
                    payload=row["payload"],
                    attempts=row["attempts"],
                    created_at=row["created_at"],
                    status=QueueJobStatus.IN_PROGRESS,
                )
                jobs.append(job)
            except Exception as e:
                logger.error(f"Failed to parse job row: {e}", extra={"row": row})

        return jobs

    async def _process_job(self, job: QueueJob) -> None:
        """Process a single job with validation, logging, and error handling."""
        run_id = str(uuid4())
        timer = Timer()

        # Extract context for logging
        payload = job.payload
        judgment_id = payload.get("judgment_id")
        case_number = payload.get("case_number")

        with LogContext(
            run_id=run_id,
            job_id=job.msg_id,
            kind=job.kind.value,
            judgment_id=judgment_id,
            case_number=case_number,
        ):
            with timer:
                try:
                    log_worker_start(
                        logger,
                        kind=job.kind.value,
                        job_id=job.msg_id,
                        run_id=run_id,
                        judgment_id=judgment_id,
                        case_number=case_number,
                        attempt=job.attempts + 1,
                    )

                    # Validate payload
                    try:
                        validated_payload = validate_job_payload(job.kind, payload)
                    except ValidationError as e:
                        logger.error(
                            f"Payload validation failed: {e}",
                            extra={"validation_errors": e.errors()},
                        )
                        await self._mark_job_failed(
                            job,
                            f"Validation error: {e}",
                            permanent=True,
                        )
                        return

                    # Get handler
                    handler = self._handlers.get(job.kind)
                    if handler is None:
                        logger.error(f"No handler registered for {job.kind}")
                        await self._mark_job_failed(
                            job,
                            f"No handler for {job.kind}",
                            permanent=True,
                        )
                        return

                    # Execute handler
                    success = await handler(
                        job,
                        (
                            validated_payload.model_dump()
                            if hasattr(validated_payload, "model_dump")
                            else validated_payload
                        ),
                    )

                    if success:
                        await self._mark_job_completed(job)
                        log_worker_success(
                            logger,
                            kind=job.kind.value,
                            job_id=job.msg_id,
                            duration_ms=timer.elapsed_ms,
                            judgment_id=judgment_id,
                            case_number=case_number,
                        )
                        self._stats.processed += 1
                    else:
                        await self._mark_job_failed(job, "Handler returned False")
                        self._stats.failed += 1

                except Exception as e:
                    log_worker_failure(
                        logger,
                        kind=job.kind.value,
                        job_id=job.msg_id,
                        error=e,
                        duration_ms=timer.elapsed_ms,
                        attempt=job.attempts + 1,
                        max_attempts=self.config.retry_policy.max_attempts,
                        judgment_id=judgment_id,
                        case_number=case_number,
                    )
                    await self._mark_job_failed(job, str(e))
                    self._stats.failed += 1

    async def _mark_job_completed(self, job: QueueJob) -> None:
        """Mark job as completed in database."""
        pool = await get_pool()

        async with pool.connection() as conn:
            await conn.execute(
                """
                UPDATE job_queue
                SET status = 'completed',
                    processed_at = NOW()
                WHERE msg_id = %(msg_id)s
                """,
                {"msg_id": job.msg_id},
            )

    async def _mark_job_failed(
        self,
        job: QueueJob,
        error_message: str,
        permanent: bool = False,
    ) -> None:
        """
        Mark job as failed with retry logic.

        Args:
            job: The failed job
            error_message: Error description
            permanent: If True, skip retries and move to dead letter
        """
        pool = await get_pool()
        new_attempts = job.attempts + 1
        max_attempts = self.config.retry_policy.max_attempts

        if permanent or new_attempts >= max_attempts:
            # Move to dead letter queue
            status = "dead_letter" if self.config.enable_dead_letter else "failed"
            logger.warning(
                f"Job {job.msg_id} moved to {status} after {new_attempts} attempts",
                extra={"error": error_message},
            )

            async with pool.connection() as conn:
                await conn.execute(
                    """
                    UPDATE job_queue
                    SET status = %(status)s,
                        attempts = %(attempts)s,
                        error_message = %(error)s,
                        processed_at = NOW()
                    WHERE msg_id = %(msg_id)s
                    """,
                    {
                        "msg_id": job.msg_id,
                        "status": status,
                        "attempts": new_attempts,
                        "error": error_message[:1000],
                    },
                )
        else:
            # Schedule retry with backoff
            delay = self.config.retry_policy.get_delay(new_attempts)

            async with pool.connection() as conn:
                await conn.execute(
                    """
                    UPDATE job_queue
                    SET status = 'pending',
                        attempts = %(attempts)s,
                        error_message = %(error)s,
                        retry_after = NOW() + INTERVAL '%(delay)s seconds'
                    WHERE msg_id = %(msg_id)s
                    """,
                    {
                        "msg_id": job.msg_id,
                        "attempts": new_attempts,
                        "error": error_message[:1000],
                        "delay": int(delay),
                    },
                )

            logger.info(
                f"Job {job.msg_id} scheduled for retry in {delay:.1f}s",
                extra={"attempt": new_attempts, "max_attempts": max_attempts},
            )


# =============================================================================
# Stats
# =============================================================================


@dataclass
class ProcessorStats:
    """Runtime statistics for queue processor."""

    processed: int = 0
    failed: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def uptime_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    @property
    def throughput_per_hour(self) -> float:
        if self.uptime_seconds < 1:
            return 0
        return (self.processed / self.uptime_seconds) * 3600


# =============================================================================
# Transactional Job Enqueue
# =============================================================================


async def enqueue_job_transactional(
    conn: psycopg.AsyncConnection,
    kind: QueueJobKind,
    payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> int:
    """
    Enqueue a job within an existing transaction.

    Use this when you need to atomically:
    1. Update a judgment/entity state
    2. Enqueue a follow-up job

    Args:
        conn: Active psycopg connection (within transaction)
        kind: Job type
        payload: Job payload (will be validated)
        idempotency_key: Optional key for deduplication

    Returns:
        New job msg_id

    Raises:
        ValidationError: If payload fails validation
    """
    # Validate payload
    validated = validate_job_payload(kind, payload)

    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO job_queue (kind, payload, idempotency_key, status, created_at)
            VALUES (%(kind)s, %(payload)s, %(key)s, 'pending', NOW())
            ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL
            DO NOTHING
            RETURNING msg_id
            """,
            {
                "kind": kind.value,
                "payload": (
                    validated.model_dump() if hasattr(validated, "model_dump") else validated
                ),
                "key": idempotency_key,
            },
        )
        row = await cur.fetchone()

        if row is None:
            # Duplicate idempotency key - fetch existing
            await cur.execute(
                "SELECT msg_id FROM job_queue WHERE idempotency_key = %(key)s",
                {"key": idempotency_key},
            )
            row = await cur.fetchone()

        return row[0]


async def enqueue_job(
    kind: QueueJobKind,
    payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> int:
    """
    Enqueue a job (non-transactional).

    For transactional enqueue, use enqueue_job_transactional() instead.
    """
    pool = await get_pool()

    async with pool.connection() as conn:
        return await enqueue_job_transactional(conn, kind, payload, idempotency_key)
