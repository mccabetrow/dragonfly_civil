"""
Dragonfly Engine - BaseWorker (pgmq Queue Consumer)

Provides a standardized base class for all workers that consume from pgmq queues.
Implements "Exactly-Once" semantics through idempotency registry integration.

Lifecycle: Poll -> Lease -> Envelope Validation -> Idempotency Check -> Process -> Ack/Archive

Features:
- Strict envelope validation (JobEnvelope schema)
- Automatic idempotency via workers.processed_jobs registry
- Dead letter queue (DLQ) handling for poison messages
- Heartbeat reporting to workers.heartbeats
- Performance metrics to workers.metrics
- Configurable visibility timeout and batch size
- Graceful shutdown with signal handling
- Structured logging with job context
- Connection health monitoring

Usage:
    from backend.workers.base import BaseWorker

    class MyWorker(BaseWorker):
        queue_name = "q_ingest_raw"

        def process(self, envelope: JobEnvelope) -> dict | None:
            # Process the job envelope
            return {"processed": True}

    if __name__ == "__main__":
        worker = MyWorker()
        worker.run()
"""

from __future__ import annotations

# =============================================================================
# CRITICAL: Configuration Guard - Must run FIRST before any other imports
# =============================================================================
from backend.core.config_guard import validate_production_config

validate_production_config()  # Crashes if misconfigured in production
# =============================================================================

import hashlib
import json
import logging
import os
import platform
import signal
import sys
import threading
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Generator

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from backend.middleware.version import ENV_NAME, GIT_SHA_SHORT
from backend.workers.db_connect import (
    EXIT_CODE_DB_UNAVAILABLE,
    connect_with_retry,
    get_safe_application_name,
)
from backend.workers.envelope import InvalidEnvelopeError, JobEnvelope

if TYPE_CHECKING:
    from psycopg import Connection

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Default configuration values
DEFAULT_BATCH_SIZE = 10
DEFAULT_VISIBILITY_TIMEOUT = 30  # seconds
DEFAULT_POLL_INTERVAL = 1.0  # seconds between empty polls
DEFAULT_MAX_RETRIES = 3  # retries before DLQ
DEFAULT_SHUTDOWN_TIMEOUT = 30  # seconds to wait for graceful shutdown
DEFAULT_HEARTBEAT_INTERVAL = 30  # seconds between heartbeats

# Dead letter queue name
DLQ_QUEUE_NAME = "q_dead_letter"

# Worker version (should be set from package version in production)
WORKER_VERSION = os.environ.get("WORKER_VERSION", "0.1.0")


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class QueueMessage:
    """Represents a message read from pgmq."""

    msg_id: int
    read_ct: int
    enqueued_at: datetime
    vt: datetime  # Visibility timeout expiry
    message: dict[str, Any]

    @property
    def payload(self) -> dict[str, Any]:
        """Alias for message content."""
        return self.message

    @property
    def attempt_count(self) -> int:
        """Number of times this message has been read."""
        return self.read_ct


@dataclass
class JobContext:
    """Context for the current job being processed."""

    msg_id: int
    queue_name: str
    idempotency_key: str
    worker_id: uuid.UUID
    attempt_count: int
    enqueued_at: datetime
    envelope: JobEnvelope | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# BaseWorker Class
# =============================================================================


class BaseWorker(ABC):
    """
    Abstract base class for pgmq queue workers.

    Subclasses must:
    1. Set `queue_name` class attribute
    2. Implement `process(payload)` method
    3. Optionally override `get_idempotency_key(payload)` for custom key derivation

    The worker handles:
    - Connection management with retry logic
    - Message polling and visibility timeout
    - Idempotency checking via workers.processed_jobs
    - Automatic DLQ routing for failed jobs
    - Graceful shutdown on SIGTERM/SIGINT
    """

    # Required: Override in subclass
    queue_name: str = ""

    # Configuration: Override in subclass if needed
    batch_size: int = DEFAULT_BATCH_SIZE
    visibility_timeout: int = DEFAULT_VISIBILITY_TIMEOUT
    poll_interval: float = DEFAULT_POLL_INTERVAL
    max_retries: int = DEFAULT_MAX_RETRIES
    heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL

    def __init__(
        self,
        *,
        db_url: str | None = None,
        worker_id: uuid.UUID | None = None,
        batch_size: int | None = None,
        visibility_timeout: int | None = None,
        heartbeat_interval: int | None = None,
    ):
        """
        Initialize the worker.

        Args:
            db_url: Database connection string. If None, reads from SUPABASE_DB_URL.
            worker_id: Unique identifier for this worker instance. Auto-generated if None.
            batch_size: Number of messages to fetch per poll. Overrides class default.
            visibility_timeout: Seconds before message becomes visible again. Overrides class default.
            heartbeat_interval: Seconds between heartbeat updates. Overrides class default.
        """
        if not self.queue_name:
            raise ValueError(f"{self.__class__.__name__} must define queue_name")

        self.db_url = db_url or os.environ.get("SUPABASE_DB_URL")
        if not self.db_url:
            raise ValueError("Database URL required: set SUPABASE_DB_URL or pass db_url")

        self.worker_id = worker_id or uuid.uuid4()
        self.worker_name = get_safe_application_name(self.__class__.__name__)

        # Allow instance-level overrides
        if batch_size is not None:
            self.batch_size = batch_size
        if visibility_timeout is not None:
            self.visibility_timeout = visibility_timeout
        if heartbeat_interval is not None:
            self.heartbeat_interval = heartbeat_interval

        # Shutdown coordination
        self._shutdown_requested = False
        self._current_job: JobContext | None = None

        # Metrics
        self._jobs_processed = 0
        self._jobs_failed = 0
        self._jobs_skipped = 0
        self._jobs_invalid = 0  # Invalid envelope count

        # Heartbeat thread
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop_event = threading.Event()
        self._worker_status: str = "starting"

        # Worker metadata
        self._hostname = platform.node()
        self._pid = os.getpid()
        self._version = WORKER_VERSION
        self._start_time: float | None = None  # Set when run() starts
        self._git_sha = GIT_SHA_SHORT  # Use centralized resolver
        self._env = ENV_NAME  # Use centralized resolver

        logger.info(
            "Initialized %s worker_id=%s queue=%s batch_size=%d vt=%ds heartbeat=%ds",
            self.__class__.__name__,
            self.worker_id,
            self.queue_name,
            self.batch_size,
            self.visibility_timeout,
            self.heartbeat_interval,
        )

    # -------------------------------------------------------------------------
    # Abstract Method
    # -------------------------------------------------------------------------

    @abstractmethod
    def process(self, envelope: JobEnvelope) -> dict[str, Any] | None:
        """
        Process a single job envelope.

        Args:
            envelope: The validated JobEnvelope containing job metadata and payload.

        Returns:
            Optional result dict to store in processed_jobs.result.
            Return None if no result needs to be stored.

        Raises:
            Exception: Any exception will mark the job as failed and
                       potentially route to DLQ after max_retries.
        """
        raise NotImplementedError

    # -------------------------------------------------------------------------
    # Idempotency Key Generation
    # -------------------------------------------------------------------------

    def get_idempotency_key(self, payload: dict[str, Any]) -> str:
        """
        Generate an idempotency key for the given payload.

        Override this method to customize key generation.
        Default implementation uses payload's 'idempotency_key' field,
        or falls back to a hash of the entire payload.

        Args:
            payload: The job message payload.

        Returns:
            A unique string key for deduplication.
        """
        # Check for explicit idempotency key in payload
        if "idempotency_key" in payload:
            return str(payload["idempotency_key"])

        # Check for common unique identifiers
        for key in ("id", "job_id", "case_id", "entity_id"):
            if key in payload:
                return f"{self.queue_name}:{key}:{payload[key]}"

        # Fall back to content hash
        content = json.dumps(payload, sort_keys=True, default=str)
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return f"{self.queue_name}:hash:{content_hash}"

    # -------------------------------------------------------------------------
    # Structured Lifecycle Logging
    # -------------------------------------------------------------------------

    def _emit_boot_report(self) -> None:
        """Emit structured WORKER_BOOT event at run() start."""
        db_status = self._ping_database()
        boot_data = {
            "event": "WORKER_BOOT",
            "data": {
                "worker_name": self.queue_name or self.__class__.__name__,
                "worker_id": str(self.worker_id),
                "git_sha": self._git_sha,
                "env": self._env,
                "concurrency": 1,  # Pinned at 1 for exactly-once semantics
                "db_status": db_status,
                "hostname": self._hostname,
                "pid": self._pid,
                "version": self._version,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        logger.info(json.dumps(boot_data))

    def _emit_shutdown_report(self, reason: str) -> None:
        """Emit structured WORKER_SHUTDOWN event on graceful shutdown."""
        uptime_seconds = 0.0
        if self._start_time:
            uptime_seconds = round(time.monotonic() - self._start_time, 2)

        shutdown_data = {
            "event": "WORKER_SHUTDOWN",
            "data": {
                "worker_name": self.queue_name or self.__class__.__name__,
                "worker_id": str(self.worker_id),
                "uptime_seconds": uptime_seconds,
                "jobs_processed": self._jobs_processed,
                "jobs_failed": self._jobs_failed,
                "jobs_skipped": self._jobs_skipped,
                "jobs_invalid": self._jobs_invalid,
                "reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        logger.info(json.dumps(shutdown_data))

    def _emit_crash_report(self, error: Exception) -> None:
        """Emit structured WORKER_CRASH event on fatal error."""
        uptime_seconds = 0.0
        if self._start_time:
            uptime_seconds = round(time.monotonic() - self._start_time, 2)

        crash_data = {
            "event": "WORKER_CRASH",
            "data": {
                "worker_name": self.queue_name or self.__class__.__name__,
                "worker_id": str(self.worker_id),
                "uptime_seconds": uptime_seconds,
                "jobs_processed": self._jobs_processed,
                "jobs_failed": self._jobs_failed,
                "error": str(error),
                "error_type": type(error).__name__,
                "traceback": traceback.format_exc(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        }
        logger.critical(json.dumps(crash_data))

    # -------------------------------------------------------------------------
    # Signal Handling
    # -------------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

    def _handle_shutdown_signal(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal."""
        sig_name = signal.Signals(signum).name
        logger.info(
            "Received %s, initiating graceful shutdown (worker_id=%s)",
            sig_name,
            self.worker_id,
        )
        self._shutdown_requested = True
        self._worker_status = "draining"
        # Emit shutdown report with signal reason
        self._emit_shutdown_report(f"{sig_name} (Deployment/Scale-down)")

    # -------------------------------------------------------------------------
    # Heartbeat Management
    # -------------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        """Start the background heartbeat thread."""
        if self._heartbeat_thread is not None:
            return  # Already running

        self._heartbeat_stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"heartbeat-{self.queue_name}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.debug("Started heartbeat thread interval=%ds", self.heartbeat_interval)

    def _stop_heartbeat(self) -> None:
        """Stop the background heartbeat thread."""
        if self._heartbeat_thread is None:
            return

        self._heartbeat_stop_event.set()
        self._heartbeat_thread.join(timeout=5.0)
        self._heartbeat_thread = None
        logger.debug("Stopped heartbeat thread")

    def _heartbeat_loop(self) -> None:
        """Background thread that sends periodic heartbeats."""
        while not self._heartbeat_stop_event.is_set():
            try:
                self._send_heartbeat()
            except Exception as e:
                logger.warning("Heartbeat failed: %s", e)

            # Wait for next interval or stop signal
            self._heartbeat_stop_event.wait(self.heartbeat_interval)

    def _send_heartbeat(self) -> None:
        """Send a single heartbeat update to the database."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT workers.upsert_heartbeat(
                            %s, %s, %s, %s, %s, %s::workers.worker_status, %s, %s, %s::jsonb
                        )
                        """,
                        (
                            str(self.worker_id),
                            self.queue_name,
                            self._hostname,
                            self._version,
                            self._pid,
                            self._worker_status,
                            self._jobs_processed,
                            self._jobs_failed,
                            json.dumps(
                                {
                                    "batch_size": self.batch_size,
                                    "visibility_timeout": self.visibility_timeout,
                                    "invalid_envelopes": self._jobs_invalid,
                                }
                            ),
                        ),
                    )
                conn.commit()
                logger.debug(
                    "Heartbeat sent status=%s processed=%d failed=%d",
                    self._worker_status,
                    self._jobs_processed,
                    self._jobs_failed,
                )
        except Exception as e:
            # Don't let heartbeat failures crash the worker
            logger.warning("Failed to send heartbeat: %s", e)

    def _send_final_heartbeat(self) -> None:
        """Send a final 'stopped' heartbeat before shutdown."""
        self._worker_status = "stopped"
        try:
            self._send_heartbeat()
        except Exception as e:
            logger.warning("Failed to send final heartbeat: %s", e)

    # -------------------------------------------------------------------------
    # Metrics Reporting
    # -------------------------------------------------------------------------

    def _update_metrics(
        self,
        conn: Connection,
        job_id: uuid.UUID,
        latency_ms: int,
        success: bool = True,
    ) -> None:
        """Update queue metrics after job completion."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT workers.update_metrics(%s, %s, %s, %s)",
                    (self.queue_name, str(job_id), latency_ms, success),
                )
            # Don't commit here - let the caller handle transaction
        except Exception as e:
            # Metrics update failure should not affect job processing
            logger.warning("Failed to update metrics: %s", e)

    # -------------------------------------------------------------------------
    # Database Connection
    # -------------------------------------------------------------------------

    def _ping_database(self) -> str:
        """Quick database health check for boot report."""
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            return "ok"
        except Exception as e:
            return f"error: {type(e).__name__}"

    @contextmanager
    def _get_connection(self) -> Generator[Connection, None, None]:
        """Get a database connection with proper lifecycle management."""
        conn = connect_with_retry(
            dsn=self.db_url,
            worker_type=self.__class__.__name__,
            row_factory=dict_row,
        )
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Queue Operations
    # -------------------------------------------------------------------------

    def _poll_messages(self, conn: Connection) -> list[QueueMessage]:
        """
        Poll for messages from the queue.

        Uses pgmq.read() to fetch messages with visibility timeout.
        """
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM pgmq.read(%s, %s, %s)",
                (self.queue_name, self.visibility_timeout, self.batch_size),
            )
            rows = cur.fetchall()

        messages = []
        for row in rows:
            messages.append(
                QueueMessage(
                    msg_id=row["msg_id"],
                    read_ct=row["read_ct"],
                    enqueued_at=row["enqueued_at"],
                    vt=row["vt"],
                    message=row["message"] if isinstance(row["message"], dict) else {},
                )
            )

        return messages

    def _archive_message(self, conn: Connection, msg_id: int) -> bool:
        """Archive a successfully processed message."""
        with conn.cursor() as cur:
            cur.execute("SELECT pgmq.archive(%s, %s)", (self.queue_name, msg_id))
            result = cur.fetchone()
            return bool(result and result.get("archive", False))

    def _delete_message(self, conn: Connection, msg_id: int) -> bool:
        """Delete a message (used when moving to DLQ)."""
        with conn.cursor() as cur:
            cur.execute("SELECT pgmq.delete(%s, %s)", (self.queue_name, msg_id))
            result = cur.fetchone()
            return bool(result and result.get("delete", False))

    # -------------------------------------------------------------------------
    # Idempotency Operations
    # -------------------------------------------------------------------------

    def _check_already_processed(self, conn: Connection, idempotency_key: str) -> bool:
        """Check if a job has already been successfully processed."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM workers.processed_jobs WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = cur.fetchone()
            if row and row["status"] == "completed":
                return True
            return False

    def _claim_job(
        self,
        conn: Connection,
        idempotency_key: str,
        msg_id: int,
    ) -> bool:
        """
        Attempt to claim a job for processing.

        Returns True if claimed successfully, False if already claimed.
        """
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workers.claim_job(%s, %s, %s, %s)",
                (idempotency_key, msg_id, self.queue_name, str(self.worker_id)),
            )
            result = cur.fetchone()
            return bool(result and list(result.values())[0])

    def _complete_job(
        self,
        conn: Connection,
        idempotency_key: str,
        result: dict[str, Any] | None,
    ) -> None:
        """Mark a job as completed."""
        with conn.cursor() as cur:
            result_json = json.dumps(result) if result else None
            cur.execute(
                "SELECT workers.complete_job(%s, %s::jsonb)",
                (idempotency_key, result_json),
            )
        conn.commit()

    def _fail_job(
        self,
        conn: Connection,
        idempotency_key: str,
        error: str,
    ) -> None:
        """Mark a job as failed."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT workers.fail_job(%s, %s)",
                (idempotency_key, error),
            )
        conn.commit()

    def _get_attempt_count(self, conn: Connection, idempotency_key: str) -> int:
        """Get the current attempt count for a job."""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT attempts FROM workers.processed_jobs WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = cur.fetchone()
            return row["attempts"] if row else 0

    # -------------------------------------------------------------------------
    # Dead Letter Queue
    # -------------------------------------------------------------------------

    def _move_to_dlq(
        self,
        conn: Connection,
        msg: QueueMessage,
        idempotency_key: str,
        error_message: str,
        error_stack: str | None,
    ) -> uuid.UUID | None:
        """
        Move a failed job to the dead letter queue.

        Returns the DLQ log ID if successful.
        """
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT workers.move_to_dlq(
                    %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s
                )
                """,
                (
                    self.queue_name,  # original_queue
                    msg.msg_id,  # original_job_id
                    idempotency_key,  # idempotency_key
                    json.dumps(msg.payload),  # payload
                    error_message,  # error_message
                    error_stack,  # error_stack
                    msg.attempt_count,  # attempt_count
                    msg.enqueued_at,  # first_attempt_at
                    str(self.worker_id),  # worker_id
                ),
            )
            result = cur.fetchone()
            conn.commit()

            if result:
                dlq_id = list(result.values())[0]
                return uuid.UUID(str(dlq_id)) if dlq_id else None
            return None

    # -------------------------------------------------------------------------
    # Job Processing Wrapper
    # -------------------------------------------------------------------------

    def _send_to_dlq_invalid_envelope(
        self,
        conn: Connection,
        msg: QueueMessage,
        error: InvalidEnvelopeError,
    ) -> None:
        """
        Send a message with invalid envelope directly to DLQ.

        Invalid envelopes are NOT retried - they will never pass validation.
        """
        dlq_payload = {
            "original_queue": self.queue_name,
            "original_msg_id": msg.msg_id,
            "raw_payload": msg.payload,
            "error": "Invalid Envelope",
            "validation_errors": error.validation_errors,
            "worker_id": str(self.worker_id),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with conn.cursor() as cur:
            # Send to DLQ
            cur.execute(
                "SELECT pgmq.send(%s, %s::jsonb)",
                (DLQ_QUEUE_NAME, json.dumps(dlq_payload)),
            )
            # Delete from original queue (no retry for invalid envelopes)
            cur.execute(
                "SELECT pgmq.delete(%s, %s)",
                (self.queue_name, msg.msg_id),
            )
        conn.commit()

        logger.warning(
            "Invalid envelope sent to DLQ msg_id=%d queue=%s errors=%s",
            msg.msg_id,
            self.queue_name,
            error.validation_errors[:3] if error.validation_errors else str(error),
        )

    def _process_wrapper(self, conn: Connection, msg: QueueMessage) -> None:
        """
        Wrapper that handles the full job lifecycle:
        1. Parse and validate envelope (FATAL if invalid - no retry)
        2. Extract idempotency key from envelope
        3. Check if already processed -> skip
        4. Claim job (insert as 'processing')
        5. Execute process(envelope)
        6. On success: mark completed, archive message, update metrics
        7. On failure: mark failed, potentially move to DLQ
        """
        job_start = time.monotonic()

        # =====================================================================
        # Step 0: Validate Envelope (FATAL - no retry on failure)
        # =====================================================================
        try:
            envelope = JobEnvelope.parse(msg.payload)
        except InvalidEnvelopeError as e:
            logger.error(
                "Invalid envelope msg_id=%d - sending to DLQ (no retry)",
                msg.msg_id,
                exc_info=True,
            )
            self._jobs_invalid += 1
            self._send_to_dlq_invalid_envelope(conn, msg, e)
            return

        # Extract idempotency key from validated envelope
        idempotency_key = envelope.idempotency_key

        # Set up job context for logging
        self._current_job = JobContext(
            msg_id=msg.msg_id,
            queue_name=self.queue_name,
            idempotency_key=idempotency_key,
            worker_id=self.worker_id,
            attempt_count=msg.attempt_count,
            enqueued_at=msg.enqueued_at,
            envelope=envelope,
        )

        logger.debug(
            "Processing job job_id=%s entity=%s:%s attempt=%d",
            envelope.job_id,
            envelope.entity_type,
            envelope.entity_id,
            envelope.attempt,
        )

        try:
            # Step 1: Check if already processed
            if self._check_already_processed(conn, idempotency_key):
                logger.info(
                    "Skipping already-processed job job_id=%s key=%s",
                    envelope.job_id,
                    idempotency_key,
                )
                # Archive the duplicate message
                self._archive_message(conn, msg.msg_id)
                self._jobs_skipped += 1
                return

            # Step 2: Attempt to claim the job
            if not self._claim_job(conn, idempotency_key, msg.msg_id):
                logger.warning(
                    "Failed to claim job (concurrent worker?) job_id=%s key=%s",
                    envelope.job_id,
                    idempotency_key,
                )
                # Another worker is processing this - let visibility timeout handle it
                return

            # Step 3: Execute the process method with validated envelope
            result = self.process(envelope)

            # Step 4: Calculate latency
            latency_ms = int((time.monotonic() - job_start) * 1000)

            # Step 5: Mark as completed and archive
            self._complete_job(conn, idempotency_key, result)
            self._archive_message(conn, msg.msg_id)
            self._jobs_processed += 1

            # Step 6: Update queue metrics
            self._update_metrics(conn, envelope.job_id, latency_ms, success=True)
            conn.commit()

            logger.info(
                "Completed job job_id=%s key=%s latency=%dms",
                envelope.job_id,
                idempotency_key,
                latency_ms,
            )

        except Exception as e:
            # Handle failure
            error_message = str(e)
            error_stack = traceback.format_exc()
            latency_ms = int((time.monotonic() - job_start) * 1000)

            logger.error(
                "Job failed job_id=%s key=%s error=%s",
                envelope.job_id,
                idempotency_key,
                error_message,
                exc_info=True,
            )

            # Mark as failed in registry
            self._fail_job(conn, idempotency_key, error_message)
            self._jobs_failed += 1

            # Update metrics for failure
            self._update_metrics(conn, envelope.job_id, latency_ms, success=False)

            # Check if we should move to DLQ
            attempt_count = self._get_attempt_count(conn, idempotency_key)
            if attempt_count >= self.max_retries:
                logger.warning(
                    "Moving to DLQ after %d attempts job_id=%s key=%s",
                    attempt_count,
                    envelope.job_id,
                    idempotency_key,
                )
                dlq_id = self._move_to_dlq(conn, msg, idempotency_key, error_message, error_stack)
                # Delete from original queue (DLQ has its own copy)
                self._delete_message(conn, msg.msg_id)
                logger.info(
                    "Moved to DLQ dlq_id=%s job_id=%s key=%s",
                    dlq_id,
                    envelope.job_id,
                    idempotency_key,
                )
            else:
                # Let visibility timeout expire for retry
                logger.info(
                    "Will retry in %ds (attempt %d/%d) job_id=%s key=%s",
                    self.visibility_timeout,
                    attempt_count,
                    self.max_retries,
                    envelope.job_id,
                    idempotency_key,
                )

        finally:
            self._current_job = None

    # -------------------------------------------------------------------------
    # Main Run Loop
    # -------------------------------------------------------------------------

    def run(self) -> int:
        """
        Main worker loop.

        Polls the queue indefinitely until shutdown is requested.
        Maintains heartbeat updates throughout the lifecycle.

        Returns:
            Exit code (0 for clean shutdown, non-zero for errors).
        """
        self._setup_signal_handlers()
        self._start_time = time.monotonic()

        logger.info(
            "Starting worker loop queue=%s worker_id=%s hostname=%s pid=%d",
            self.queue_name,
            self.worker_id,
            self._hostname,
            self._pid,
        )

        # Emit structured boot report
        self._emit_boot_report()

        # Start heartbeat thread
        self._worker_status = "healthy"
        self._start_heartbeat()

        # Send initial heartbeat immediately
        self._send_heartbeat()

        try:
            while not self._shutdown_requested:
                try:
                    with self._get_connection() as conn:
                        self._run_poll_loop(conn)
                except psycopg.OperationalError as e:
                    if self._shutdown_requested:
                        break
                    logger.error(
                        "Database connection error, will retry: %s",
                        e,
                    )
                    time.sleep(self.poll_interval * 2)
                except Exception as e:
                    if self._shutdown_requested:
                        break
                    logger.error(
                        "Unexpected error in worker loop: %s",
                        e,
                        exc_info=True,
                    )
                    time.sleep(self.poll_interval * 2)

        except Exception as e:
            logger.critical("Fatal error in worker: %s", e, exc_info=True)
            # Emit structured crash report
            self._emit_crash_report(e)
            self._stop_heartbeat()
            self._send_final_heartbeat()
            return 1

        # Clean shutdown
        self._stop_heartbeat()
        self._send_final_heartbeat()

        # Emit shutdown report if not already done by signal handler
        if not self._shutdown_requested:
            self._emit_shutdown_report("Normal exit")

        logger.info(
            "Worker shutdown complete queue=%s processed=%d failed=%d skipped=%d invalid=%d",
            self.queue_name,
            self._jobs_processed,
            self._jobs_failed,
            self._jobs_skipped,
            self._jobs_invalid,
        )
        return 0

    def _run_poll_loop(self, conn: Connection) -> None:
        """
        Inner poll loop that runs while connection is healthy.

        Separated from run() to allow connection reconnection.
        """
        while not self._shutdown_requested:
            # Poll for messages
            messages = self._poll_messages(conn)

            if not messages:
                # No messages, sleep before next poll
                time.sleep(self.poll_interval)
                continue

            logger.debug(
                "Fetched %d messages from %s",
                len(messages),
                self.queue_name,
            )

            # Process each message
            for msg in messages:
                if self._shutdown_requested:
                    logger.info("Shutdown requested, stopping message processing")
                    break

                try:
                    self._process_wrapper(conn, msg)
                except Exception as e:
                    # This should not happen - _process_wrapper catches all exceptions
                    # But just in case, log and continue
                    logger.error(
                        "Unhandled error in process_wrapper: %s",
                        e,
                        exc_info=True,
                    )

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get worker statistics."""
        return {
            "worker_id": str(self.worker_id),
            "queue_name": self.queue_name,
            "hostname": self._hostname,
            "pid": self._pid,
            "version": self._version,
            "status": self._worker_status,
            "jobs_processed": self._jobs_processed,
            "jobs_failed": self._jobs_failed,
            "jobs_skipped": self._jobs_skipped,
            "jobs_invalid": self._jobs_invalid,
            "shutdown_requested": self._shutdown_requested,
        }

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"queue={self.queue_name} "
            f"worker_id={self.worker_id} "
            f"status={self._worker_status}>"
        )
