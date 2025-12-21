"""
Dragonfly Engine - Production Worker Bootstrap

Provides production-grade infrastructure for background workers:
- Structured startup banner with service name, env, mode, git SHA
- Enhanced preflight checks with DB connectivity test
- Signal handling (SIGTERM/SIGINT) with graceful shutdown
- Exponential backoff on transient failures
- Heartbeat status transitions (starting → running → degraded → stopped)
- Robust DB connection with retry and sslmode enforcement
- Distinct exit codes for infrastructure alerting

Usage:
    from backend.workers.bootstrap import WorkerBootstrap

    def my_worker_loop(conn, heartbeat):
        # Your business logic here
        pass

    if __name__ == "__main__":
        bootstrap = WorkerBootstrap(
            worker_type="ingest_processor",
            job_types=["ingest_csv"],
        )
        bootstrap.run(my_worker_loop)

Exit Codes:
    0 - Clean shutdown
    1 - General error / preflight failure
    2 - Database unavailable after retries (EXIT_CODE_DB_UNAVAILABLE)
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from backend.preflight import get_git_sha, run_preflight_checks
from backend.workers.backoff import (
    BACKOFF_JITTER,
    BACKOFF_MULTIPLIER,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    BackoffState,
)
from backend.workers.db_connect import (
    EXIT_CODE_DB_UNAVAILABLE,
    RetryConfig,
    ThrottledWarningLogger,
    connect_with_retry,
    db_smoke_test,
    ensure_sslmode,
    get_safe_application_name,
    log_dsn_info,
)
from backend.workers.heartbeat import WorkerHeartbeat
from backend.workers.rpc_client import RPCClient
from src.supabase_client import get_supabase_db_url

logger = logging.getLogger(__name__)

# Heartbeat status values (matches ops.worker_heartbeats.status enum)
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_DEGRADED = "degraded"
STATUS_STOPPED = "stopped"
STATUS_ERROR = "error"

# Preflight DB connectivity timeout
DB_CONNECT_TIMEOUT_SECONDS = 10


# ==============================================================================
# ENHANCED HEARTBEAT
# ==============================================================================


class EnhancedHeartbeat(WorkerHeartbeat):
    """
    Extended heartbeat with status transitions and degraded detection.

    Status transitions:
        starting → running (on first successful poll)
        running → degraded (on transient failure)
        degraded → running (on recovery)
        * → stopped (on graceful shutdown)
        * → error (on unrecoverable error)
    """

    def __init__(
        self,
        worker_type: str,
        get_db_url: Callable[[], str],
        interval: float = 30.0,
    ) -> None:
        super().__init__(worker_type, get_db_url, interval)
        self._status = STATUS_STARTING
        self._degraded_reason: Optional[str] = None
        self._lock = threading.Lock()

    def set_starting(self) -> None:
        """Mark worker as starting (initial state)."""
        with self._lock:
            self._status = STATUS_STARTING
            self._degraded_reason = None
        self._try_send_heartbeat()

    def set_running(self) -> None:
        """Mark worker as running (healthy)."""
        with self._lock:
            prev_status = self._status
            self._status = STATUS_RUNNING
            self._degraded_reason = None
        if prev_status != STATUS_RUNNING:
            logger.info(f"Worker status: {prev_status} → {STATUS_RUNNING}")
            self._try_send_heartbeat()

    def set_degraded(self, reason: str) -> None:
        """Mark worker as degraded (transient issue)."""
        with self._lock:
            prev_status = self._status
            self._status = STATUS_DEGRADED
            self._degraded_reason = reason
        if prev_status != STATUS_DEGRADED:
            logger.warning(f"Worker status: {prev_status} → {STATUS_DEGRADED} ({reason})")
            self._try_send_heartbeat()

    def set_stopped(self) -> None:
        """Mark worker as stopped (graceful shutdown)."""
        with self._lock:
            self._status = STATUS_STOPPED
        logger.info(f"Worker status: → {STATUS_STOPPED}")
        self._try_send_heartbeat()

    def set_error(self, error_msg: Optional[str] = None) -> None:
        """Mark worker as in error state (unrecoverable)."""
        with self._lock:
            self._status = STATUS_ERROR
            self._degraded_reason = error_msg
        logger.error(f"Worker status: → {STATUS_ERROR} ({error_msg})")
        self._try_send_heartbeat()

    def _try_send_heartbeat(self) -> None:
        """Attempt to send heartbeat, log on failure."""
        try:
            self._send_heartbeat(status=self._status)
        except Exception as e:
            logger.debug(f"Could not send heartbeat: {e}")

    @property
    def current_status(self) -> str:
        """Get current status string."""
        with self._lock:
            return self._status


# ==============================================================================
# SIGNAL HANDLING
# ==============================================================================


class GracefulShutdown:
    """
    Handles SIGTERM/SIGINT for graceful shutdown.

    Sets a flag that the main loop should check, allowing
    cleanup (final heartbeat, connection close) before exit.
    """

    def __init__(self) -> None:
        self._shutdown_requested = threading.Event()
        self._original_sigterm = None
        self._original_sigint = None

    def install(self) -> None:
        """Install signal handlers."""
        self._original_sigterm = signal.signal(signal.SIGTERM, self._handle_signal)
        self._original_sigint = signal.signal(signal.SIGINT, self._handle_signal)
        logger.debug("Signal handlers installed (SIGTERM, SIGINT)")

    def uninstall(self) -> None:
        """Restore original signal handlers."""
        if self._original_sigterm is not None:
            signal.signal(signal.SIGTERM, self._original_sigterm)
        if self._original_sigint is not None:
            signal.signal(signal.SIGINT, self._original_sigint)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle shutdown signal."""
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")
        self._shutdown_requested.set()

    @property
    def should_shutdown(self) -> bool:
        """Check if shutdown was requested."""
        return self._shutdown_requested.is_set()

    def wait(self, timeout: float) -> bool:
        """Wait for shutdown signal or timeout. Returns True if shutdown requested."""
        return self._shutdown_requested.wait(timeout)


# ==============================================================================
# PREFLIGHT CHECKS
# ==============================================================================


@dataclass
class PreflightCheckResult:
    """Result of enhanced preflight checks."""

    passed: bool
    env_valid: bool = True
    db_connected: bool = False
    migrations_safe: bool = True  # Read-only check
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def run_enhanced_preflight(
    worker_type: str,
    db_url: str,
) -> PreflightCheckResult:
    """
    Run enhanced preflight checks including DB connectivity.

    Checks:
    1. Environment validation (via existing preflight)
    2. Database connectivity (new)
    3. Migration safety check (read-only, new)

    Args:
        worker_type: Name of the worker for logging
        db_url: Database URL to test

    Returns:
        PreflightCheckResult with check outcomes
    """
    result = PreflightCheckResult(passed=True)

    # 1. Environment validation
    env_result = run_preflight_checks(worker_type)
    if env_result.errors:
        result.env_valid = False
        result.passed = False
        result.errors.extend(env_result.errors)
    result.warnings.extend(env_result.warnings)

    # 2. Database connectivity check
    logger.info("Checking database connectivity...")
    try:
        app_name = get_safe_application_name(worker_type)
        with psycopg.connect(
            db_url, connect_timeout=DB_CONNECT_TIMEOUT_SECONDS, application_name=app_name
        ) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            result.db_connected = True
            logger.info("Database connectivity: OK")
    except psycopg.OperationalError as e:
        result.db_connected = False
        result.passed = False
        result.errors.append(f"Database connection failed: {e}")
        logger.error(f"Database connectivity: FAILED - {e}")
    except Exception as e:
        result.db_connected = False
        result.passed = False
        result.errors.append(f"Database check error: {e}")
        logger.error(f"Database connectivity: ERROR - {e}")

    # 3. Migration safety check (read-only)
    if result.db_connected:
        logger.info("Checking migration status...")
        try:
            app_name = get_safe_application_name(worker_type)
            with psycopg.connect(db_url, application_name=app_name) as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    # Check for common required tables
                    cur.execute(
                        """
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'ops'
                            AND table_name = 'job_queue'
                        ) AS job_queue_exists,
                        EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_schema = 'ops'
                            AND table_name = 'worker_heartbeats'
                        ) AS heartbeats_exists
                    """
                    )
                    row = cur.fetchone()
                    if row:
                        if not row.get("job_queue_exists"):
                            result.warnings.append(
                                "ops.job_queue table not found - migrations may be pending"
                            )
                        if not row.get("heartbeats_exists"):
                            result.warnings.append(
                                "ops.worker_heartbeats table not found - heartbeats disabled"
                            )
            result.migrations_safe = True
            logger.info("Migration status: OK")
        except Exception as e:
            result.warnings.append(f"Could not verify migration status: {e}")
            logger.warning(f"Migration status check failed: {e}")

    return result


# ==============================================================================
# STARTUP BANNER
# ==============================================================================


def print_startup_banner(
    worker_type: str,
    job_types: list[str],
    poll_interval: float,
    worker_id: Optional[str] = None,
) -> None:
    """
    Print structured startup banner.

    No secrets are printed. Format:
    ======================================================================
      DRAGONFLY WORKER: ingest_processor
    ----------------------------------------------------------------------
      Environment:   prod
      Supabase Mode: prod
      Git SHA:       abc12345
      Worker ID:     ingest_processor-a1b2c3d4
      Job Types:     ingest_csv
      Poll Interval: 2.0s
      Startup:       2025-01-15T10:30:00Z
    ======================================================================
    """
    env = os.environ.get("ENVIRONMENT", "dev").lower()
    mode = os.environ.get("SUPABASE_MODE", "dev").lower()
    git_sha = get_git_sha() or "unknown"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z"

    width = 70
    print()
    print("=" * width)
    print(f"  DRAGONFLY WORKER: {worker_type}")
    print("-" * width)
    print(f"  Environment:   {env}")
    print(f"  Supabase Mode: {mode}")
    print(f"  Git SHA:       {git_sha}")
    if worker_id:
        print(f"  Worker ID:     {worker_id}")
    print(f"  Job Types:     {', '.join(job_types)}")
    print(f"  Poll Interval: {poll_interval}s")
    print(f"  Startup:       {now}")
    print("=" * width)
    print()


# ==============================================================================
# WORKER BOOTSTRAP
# ==============================================================================


@dataclass
class WorkerConfig:
    """Configuration for a production worker."""

    worker_type: str
    job_types: list[str]
    poll_interval: float = 5.0
    heartbeat_interval: float = 30.0
    lock_timeout_minutes: int = 30
    max_consecutive_failures: int = 10  # Before considering crash loop
    max_job_attempts: int = 5  # Max attempts before DLQ
    base_backoff_seconds: float = 30.0  # Base for exponential backoff
    max_backoff_seconds: float = 3600.0  # Cap backoff at 1 hour


class WorkerBootstrap:
    """
    Production-grade worker bootstrap.

    Provides:
    - Structured startup banner
    - Enhanced preflight checks
    - Signal handling for graceful shutdown
    - Exponential backoff on transient failures
    - Heartbeat status transitions
    """

    def __init__(
        self,
        worker_type: str,
        job_types: list[str],
        poll_interval: float = 5.0,
        heartbeat_interval: float = 30.0,
        lock_timeout_minutes: int = 30,
    ) -> None:
        self.config = WorkerConfig(
            worker_type=worker_type,
            job_types=job_types,
            poll_interval=poll_interval,
            heartbeat_interval=heartbeat_interval,
            lock_timeout_minutes=lock_timeout_minutes,
        )
        self._shutdown = GracefulShutdown()
        self._backoff = BackoffState()
        self._heartbeat: Optional[EnhancedHeartbeat] = None
        self._db_url: Optional[str] = None

    def run(
        self,
        job_processor: Callable[[psycopg.Connection, dict[str, Any]], None],
        job_claimer: Optional[Callable[[psycopg.Connection], Optional[dict[str, Any]]]] = None,
    ) -> int:
        """
        Run the worker with full production infrastructure.

        Args:
            job_processor: Function that processes a single job.
                           Signature: (conn, job_dict) -> None
            job_claimer: Optional custom job claim function.
                         Signature: (conn) -> Optional[job_dict]
                         If not provided, uses default claim_pending_job.

        Returns:
            Exit code:
            - 0 for clean shutdown
            - 1 for general errors
            - 2 for database unavailable (EXIT_CODE_DB_UNAVAILABLE)
        """
        # 1. Validate environment (call preflight first)
        from backend.preflight import validate_worker_env

        validate_worker_env(self.config.worker_type)

        # 2. Get DB URL and validate
        raw_db_url = get_supabase_db_url()
        if not raw_db_url:
            logger.critical(f"[{self.config.worker_type}] SUPABASE_DB_URL not configured")
            return 1

        # 3. Parse and validate DSN (logs host/port/user/dbname, never password)
        dsn_info = log_dsn_info(raw_db_url, self.config.worker_type)
        if not dsn_info.is_valid:
            logger.critical(f"[{self.config.worker_type}] Invalid DSN: {dsn_info.validation_error}")
            return 1

        # 4. Enforce sslmode=require
        self._db_url = ensure_sslmode(raw_db_url, required_mode="require")

        # 5. Run enhanced preflight (uses basic DB connectivity check)
        preflight = run_enhanced_preflight(self.config.worker_type, self._db_url)
        if not preflight.passed:
            logger.critical(f"Preflight failed: {preflight.errors}")
            return 1

        # 6. Initialize heartbeat with throttled logging
        db_url_for_heartbeat: str = self._db_url
        self._heartbeat = EnhancedHeartbeat(
            worker_type=self.config.worker_type,
            get_db_url=lambda: db_url_for_heartbeat,
            interval=self.config.heartbeat_interval,
        )

        # 7. Print startup banner
        print_startup_banner(
            worker_type=self.config.worker_type,
            job_types=self.config.job_types,
            poll_interval=self.config.poll_interval,
            worker_id=self._heartbeat.worker_id,
        )

        # 8. Install signal handlers
        self._shutdown.install()

        # 9. Start heartbeat with "starting" status
        self._heartbeat.set_starting()
        self._heartbeat.start()

        # 10. Initial DB connection with robust retry
        # Uses: initial 0.5s, max 10s, 30 attempts
        retry_config = RetryConfig(
            initial_delay=0.5,
            max_delay=10.0,
            max_attempts=30,
        )
        initial_conn = connect_with_retry(
            dsn=self._db_url,
            worker_type=self.config.worker_type,
            config=retry_config,
            exit_on_failure=True,  # Exit with code 2 if DB unavailable
        )

        # 11. DB smoke test before entering job loop
        if initial_conn:
            if not db_smoke_test(initial_conn, self.config.worker_type):
                logger.critical(f"[{self.config.worker_type}] DB smoke test failed, aborting")
                initial_conn.close()
                self._heartbeat.set_error("DB smoke test failed")
                self._heartbeat.stop()
                return EXIT_CODE_DB_UNAVAILABLE

        # 12. Run main loop
        exit_code = 0
        try:
            self._run_main_loop(job_processor, job_claimer, initial_conn)
        except Exception as e:
            logger.exception(f"Fatal error in worker: {e}")
            self._heartbeat.set_error(str(e)[:200])
            exit_code = 1
        finally:
            # 13. Graceful shutdown
            logger.info("Shutting down worker...")
            self._heartbeat.set_stopped()
            self._heartbeat.stop()
            self._shutdown.uninstall()
            logger.info("Worker shutdown complete")

        return exit_code

    def _run_main_loop(
        self,
        job_processor: Callable[[psycopg.Connection, dict[str, Any]], None],
        job_claimer: Optional[Callable[[psycopg.Connection], Optional[dict[str, Any]]]],
        initial_conn: Optional[psycopg.Connection] = None,
    ) -> None:
        """Main polling loop with crash loop protection."""
        conn: Optional[psycopg.Connection] = initial_conn

        # Type assertions - these are guaranteed to be set by run() before this method
        assert self._db_url is not None, "DB URL must be set before main loop"
        assert self._heartbeat is not None, "Heartbeat must be initialized before main loop"

        # Throttled logger for transient failures (avoid log spam)
        throttled_log = ThrottledWarningLogger(logger, min_interval=60.0)

        while not self._shutdown.should_shutdown:
            try:
                # Ensure connection
                if conn is None or conn.closed:
                    # Reconnect with retry logic
                    retry_config = RetryConfig(
                        initial_delay=0.5,
                        max_delay=10.0,
                        max_attempts=30,
                    )
                    conn = connect_with_retry(
                        dsn=self._db_url,
                        worker_type=self.config.worker_type,
                        config=retry_config,
                        exit_on_failure=True,
                    )
                    if conn:
                        logger.info("Database connection re-established")

                # Mark as running once we're connected and ready
                self._heartbeat.set_running()
                self._backoff.record_success()

                # Try to claim a job
                if job_claimer:
                    job = job_claimer(conn)
                else:
                    job = self._default_claim_job(conn)

                if job:
                    job_id = job.get("id")
                    logger.info(f"Processing job: {job_id}")
                    # Process with DLQ protection - if we crash, mark job failed
                    self._process_job_with_dlq(conn, job, job_processor)
                else:
                    # No jobs - wait before next poll (check for shutdown)
                    if self._shutdown.wait(self.config.poll_interval):
                        break

            except psycopg.OperationalError as e:
                # Transient DB error - use throttled logging to avoid spam
                throttled_log.warning(
                    f"Transient DB failure ({self._backoff.consecutive_failures}): "
                    f"{type(e).__name__}: {e}",
                    key="db_transient",
                )
                self._handle_transient_failure(e, conn, throttled_log)
                conn = None  # Force reconnect

            except psycopg.errors.InFailedSqlTransaction as e:
                # Transaction left in failed state - must rollback
                logger.warning(f"Transaction in failed state, rolling back: {e}")
                if conn:
                    try:
                        conn.rollback()
                        logger.info("Transaction rolled back successfully")
                    except Exception as rollback_err:
                        logger.error(f"Rollback failed, forcing reconnect: {rollback_err}")
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = None  # Force reconnect

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break

            except Exception as e:
                # Unexpected error - try to rollback any failed transaction first
                logger.exception(f"Unexpected error in worker loop: {e}")

                # Attempt rollback to recover connection if possible
                if conn and not conn.closed:
                    try:
                        conn.rollback()
                        logger.debug("Rolled back transaction after unexpected error")
                    except Exception as rollback_err:
                        logger.warning(f"Rollback after error failed: {rollback_err}")
                        try:
                            conn.close()
                        except Exception:
                            pass
                        conn = None  # Force reconnect

                delay = self._backoff.record_failure()
                self._heartbeat.set_degraded(f"Unexpected error: {type(e).__name__}")

                if self._backoff.is_in_crash_loop():
                    logger.critical(
                        f"Crash loop detected ({self._backoff.consecutive_failures} failures)"
                    )
                    self._heartbeat.set_error("Crash loop detected")
                    raise

                logger.info(f"Backing off for {delay:.1f}s before retry")
                if self._shutdown.wait(delay):
                    break

        # Cleanup
        if conn and not conn.closed:
            conn.close()

    def _handle_transient_failure(
        self,
        error: Exception,
        conn: Optional[psycopg.Connection],
        throttled_log: Optional[ThrottledWarningLogger] = None,
    ) -> None:
        """Handle transient DB/network failure with backoff."""
        assert self._heartbeat is not None, "Heartbeat must be initialized"

        delay = self._backoff.record_failure()
        self._heartbeat.set_degraded(f"DB error: {type(error).__name__}")

        # Use throttled logging if provided
        if throttled_log:
            throttled_log.warning(
                f"Backing off for {delay:.1f}s before reconnect",
                key="db_backoff",
            )
        else:
            logger.warning(f"Transient failure: {error}")
            logger.info(f"Backing off for {delay:.1f}s before reconnect")

        # Close bad connection
        if conn:
            try:
                conn.close()
            except Exception:
                pass

        # Check for crash loop
        if self._backoff.is_in_crash_loop():
            logger.critical(
                f"Crash loop detected ({self._backoff.consecutive_failures} consecutive failures)"
            )
            self._heartbeat.set_error("Crash loop - too many consecutive failures")
            raise RuntimeError("Crash loop detected, aborting worker")

        # Wait with shutdown check
        self._shutdown.wait(delay)

    def _default_claim_job(self, conn: psycopg.Connection) -> Optional[dict[str, Any]]:
        """Default job claim using ops.claim_pending_job RPC."""
        rpc = RPCClient(conn)

        # Get worker_id from heartbeat if available
        worker_id = None
        if self._heartbeat:
            worker_id = self._heartbeat.worker_id

        claimed = rpc.claim_pending_job(
            job_types=list(self.config.job_types),
            lock_timeout_minutes=self.config.lock_timeout_minutes,
            worker_id=worker_id,
        )
        if claimed:
            logger.info(f"Job claimed via RPC: {claimed.job_id} (worker: {worker_id})")
            # Convert ClaimedJob to dict for compatibility with existing job_processor signature
            return {
                "id": claimed.job_id,
                "job_type": claimed.job_type,
                "payload": claimed.payload,
                "attempts": claimed.attempts,
            }
        return None

    def _process_job_with_dlq(
        self,
        conn: psycopg.Connection,
        job: dict[str, Any],
        job_processor: Callable[[psycopg.Connection, dict[str, Any]], None],
    ) -> None:
        """
        Process a job with Dead Letter Queue (DLQ) protection.

        Reliability Invariants:
        - If job_processor succeeds: job marked 'completed' via RPC
        - If job_processor raises AND attempts < max: reset to 'pending' with backoff
        - If job_processor raises AND attempts >= max: move to DLQ ('failed')
        - Transaction is always rolled back on error to maintain atomicity
        - Jobs never get "stuck" in processing state (zombie prevention)

        Backoff Formula: min(2^attempts * base_seconds, max_seconds)
        Example with base=30s, max=3600s:
            Attempt 1: 60s, Attempt 2: 120s, Attempt 3: 240s, ...

        Args:
            conn: Active database connection
            job: Job dict with 'id', 'job_type', 'payload', 'attempts'
            job_processor: User-provided job processing function
        """
        job_id = str(job.get("id", "unknown"))
        job_type = job.get("job_type", "unknown")
        attempts = job.get("attempts", 1)

        try:
            # Execute the job processor
            job_processor(conn, job)

            # SUCCESS: Mark job as completed via RPC
            self._mark_job_completed(conn, job_id)
            logger.info(f"Job {job_id} ({job_type}) completed successfully")

        except Exception as e:
            # Job failed - determine retry vs DLQ
            error_msg = f"{type(e).__name__}: {str(e)[:500]}"
            logger.error(f"Job {job_id} ({job_type}) failed (attempt {attempts}): {error_msg}")

            # Rollback any partial transaction from the failed job
            try:
                conn.rollback()
                logger.debug(f"Rolled back transaction for failed job {job_id}")
            except Exception as rollback_err:
                logger.warning(f"Rollback failed for job {job_id}: {rollback_err}")

            # Decide: Retry with backoff OR move to DLQ
            if attempts >= self.config.max_job_attempts:
                # DLQ: Exceeded max attempts
                self._mark_job_dlq(conn, job_id, error_msg, attempts)
            else:
                # Retry: Reset to pending with exponential backoff
                backoff_seconds = self._calculate_backoff(attempts)
                self._mark_job_retry(conn, job_id, error_msg, backoff_seconds, attempts)

            # Re-raise so the main loop continues
            raise

    def _calculate_backoff(self, attempts: int) -> int:
        """
        Calculate exponential backoff delay.

        Formula: min(2^attempts * base_seconds, max_seconds)

        Args:
            attempts: Current attempt number

        Returns:
            Backoff delay in seconds
        """
        backoff = min(
            (2**attempts) * self.config.base_backoff_seconds,
            self.config.max_backoff_seconds,
        )
        return int(backoff)

    def _mark_job_completed(self, conn: psycopg.Connection, job_id: str) -> None:
        """Mark a job as successfully completed via RPC."""
        try:
            rpc = RPCClient(conn)
            rpc.update_job_status(
                job_id=job_id,
                status="completed",
                error_message=None,
            )
        except Exception as e:
            logger.error(f"Failed to mark job {job_id} as completed: {e}")
            # Job will be reaped by stuck job reaper if this fails

    def _mark_job_retry(
        self,
        conn: psycopg.Connection,
        job_id: str,
        error_msg: str,
        backoff_seconds: int,
        attempts: int,
    ) -> None:
        """
        Reset a failed job to pending with exponential backoff.

        Args:
            conn: Database connection
            job_id: Job ID to retry
            error_msg: Error message from the failure
            backoff_seconds: Seconds to wait before retry
            attempts: Current attempt count
        """
        try:
            rpc = RPCClient(conn)
            rpc.update_job_status(
                job_id=job_id,
                status="pending",
                error_message=f"Retry scheduled (attempt {attempts}/{self.config.max_job_attempts}): {error_msg[:500]}",
                backoff_seconds=backoff_seconds,
            )
            logger.info(
                f"Job {job_id} scheduled for retry in {backoff_seconds}s "
                f"(attempt {attempts}/{self.config.max_job_attempts})"
            )
        except Exception as e:
            logger.error(f"Failed to schedule retry for job {job_id}: {e}")
            # Job will be reaped by stuck job reaper if this fails

    def _mark_job_dlq(
        self,
        conn: psycopg.Connection,
        job_id: str,
        error_msg: str,
        attempts: int,
    ) -> None:
        """
        Move a job to the Dead Letter Queue (failed status).

        This is called when a job exceeds max_job_attempts.

        Args:
            conn: Database connection
            job_id: Job ID to move to DLQ
            error_msg: Error message from the final failure
            attempts: Final attempt count
        """
        try:
            rpc = RPCClient(conn)
            rpc.update_job_status(
                job_id=job_id,
                status="failed",
                error_message=f"[DLQ] Max attempts ({attempts}) exceeded: {error_msg[:500]}",
            )
            logger.warning(f"Job {job_id} moved to DLQ after {attempts} attempts")
        except Exception as dlq_err:
            # If we can't mark the job failed, log critically
            # The job will remain in 'processing' and be picked up by
            # the stale job reaper after lock_timeout expires
            logger.critical(
                f"DLQ FAILURE: Could not mark job {job_id} as failed: {dlq_err}. "
                f"Job may be stuck in 'processing' until lock timeout."
            )

    def _mark_job_failed_dlq(
        self,
        conn: psycopg.Connection,
        job_id: str,
        error_msg: str,
    ) -> None:
        """
        Legacy method: Mark a job as failed in the Dead Letter Queue.

        Deprecated: Use _mark_job_dlq for new code.
        """
        self._mark_job_dlq(conn, job_id, error_msg, self.config.max_job_attempts)


# ==============================================================================
# CONVENIENCE CONTEXT MANAGER
# ==============================================================================


@contextmanager
def worker_context(
    worker_type: str,
    get_db_url: Callable[[], str],
    heartbeat_interval: float = 30.0,
):
    """
    Context manager for production worker infrastructure.

    Provides:
    - Signal handling
    - Enhanced heartbeat with status transitions
    - Proper cleanup on exit

    Usage:
        with worker_context("my_worker", get_supabase_db_url) as ctx:
            ctx.heartbeat.set_running()
            while not ctx.shutdown.should_shutdown:
                # ... worker loop ...
    """

    @dataclass
    class WorkerContext:
        heartbeat: EnhancedHeartbeat
        shutdown: GracefulShutdown
        backoff: BackoffState

    shutdown = GracefulShutdown()
    backoff = BackoffState()
    heartbeat = EnhancedHeartbeat(
        worker_type=worker_type,
        get_db_url=get_db_url,
        interval=heartbeat_interval,
    )

    shutdown.install()
    heartbeat.set_starting()
    heartbeat.start()

    try:
        yield WorkerContext(
            heartbeat=heartbeat,
            shutdown=shutdown,
            backoff=backoff,
        )
    finally:
        heartbeat.set_stopped()
        heartbeat.stop()
        shutdown.uninstall()
