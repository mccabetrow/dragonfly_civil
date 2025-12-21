"""
Dragonfly Engine - Worker Heartbeat Mixin

Provides heartbeat functionality for background workers.
Workers spawn a background thread that upserts to ops.worker_heartbeats
every HEARTBEAT_INTERVAL_SECONDS (default: 30s).

Features:
- Uses ops.register_heartbeat RPC for least-privilege security
- Throttled warning logs when DB is unavailable (avoids log spam)
- Circuit breaker for missing heartbeat function
- Clean shutdown with final status update

Usage:
    from backend.workers.heartbeat import WorkerHeartbeat

    # In worker main loop:
    heartbeat = WorkerHeartbeat(
        worker_type="ingest_processor",
        get_db_url=lambda: get_supabase_db_url()
    )
    heartbeat.start()

    try:
        # ... main worker loop ...
    finally:
        heartbeat.stop()
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable, Optional
from uuid import uuid4

import psycopg
import psycopg.errors

from backend.workers.backoff import BackoffState
from backend.workers.rpc_client import RPCClient

logger = logging.getLogger(__name__)

# Heartbeat configuration
HEARTBEAT_INTERVAL_SECONDS = 30.0
HEARTBEAT_WARNING_INTERVAL = 60.0  # Throttle warnings to once per minute


def _generate_worker_id(worker_type: str) -> str:
    """Generate a unique worker ID for this instance."""
    short_uuid = str(uuid4())[:8]
    return f"{worker_type}-{short_uuid}"


def _get_hostname() -> str:
    """Get the hostname for this machine."""
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


class WorkerHeartbeat:
    """
    Background heartbeat thread for worker processes.

    Spawns a daemon thread that upserts to ops.worker_heartbeats
    every HEARTBEAT_INTERVAL_SECONDS while the worker is running.

    Attributes:
        worker_id: Unique identifier for this worker instance
        worker_type: Type of worker (e.g., "ingest_processor")
        hostname: Machine hostname
    """

    def __init__(
        self,
        worker_type: str,
        get_db_url: Callable[[], str],
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        """
        Initialize the heartbeat manager.

        Args:
            worker_type: Type identifier (e.g., "ingest_processor", "enforcement_engine")
            get_db_url: Callable that returns the database connection URL
            interval: Seconds between heartbeats (default: 30)
        """
        self.worker_type = worker_type
        self.worker_id = _generate_worker_id(worker_type)
        self.hostname = _get_hostname()
        self._get_db_url = get_db_url
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._status = "running"
        self._disabled = False  # Circuit breaker: True if heartbeat table missing

        # Backoff state for transient failure handling
        self._backoff = BackoffState()

        # Throttled warning state to avoid log spam when DB is down
        self._last_warning_time: float = 0.0
        self._warning_suppress_count: int = 0

    def start(self) -> None:
        """Start the background heartbeat thread."""
        if self._disabled:
            logger.debug("Heartbeat disabled (table missing), not starting thread")
            return

        if self._thread is not None and self._thread.is_alive():
            logger.warning("Heartbeat thread already running")
            return

        self._stop_event.clear()
        self._status = "running"
        self._thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"heartbeat-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"Started heartbeat thread for {self.worker_type} "
            f"(id={self.worker_id}, interval={self._interval}s)"
        )

    def stop(self) -> None:
        """Stop the heartbeat thread and send final 'stopped' heartbeat."""
        if self._thread is None:
            return

        self._stop_event.set()
        self._status = "stopped"

        # Send final heartbeat with stopped status
        try:
            self._send_heartbeat(status="stopped")
            logger.info(f"Sent final 'stopped' heartbeat for {self.worker_id}")
        except Exception as e:
            logger.warning(f"Failed to send final heartbeat: {e}")

        # Wait for thread to finish
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info(f"Heartbeat thread stopped for {self.worker_id}")

    def set_error(self, error_msg: Optional[str] = None) -> None:
        """Mark worker as in error state."""
        self._status = "error"
        try:
            self._send_heartbeat(status="error")
        except Exception as e:
            logger.warning(f"Failed to send error heartbeat: {e}")

    def _heartbeat_loop(self) -> None:
        """Background thread loop that sends heartbeats with exponential backoff."""
        # Send initial heartbeat immediately
        try:
            self._send_heartbeat()
            self._backoff.record_success()
        except psycopg.errors.UndefinedTable:
            self._disable_heartbeats("ops.worker_heartbeats")
            return
        except Exception as e:
            logger.error(f"Failed to send initial heartbeat: {e}")
            self._backoff.record_failure()

        while not self._stop_event.is_set():
            # Circuit breaker: stop loop if disabled
            if self._disabled:
                break

            # Wait for interval or stop signal
            if self._stop_event.wait(timeout=self._interval):
                break  # Stop event was set

            try:
                self._send_heartbeat()
                self._backoff.record_success()
            except psycopg.errors.UndefinedTable:
                self._disable_heartbeats("ops.worker_heartbeats")
                break
            except psycopg.OperationalError as e:
                # Network blips - use exponential backoff
                delay = self._backoff.record_failure()
                self._log_throttled_warning(
                    f"Heartbeat DB connection error: {type(e).__name__}: {e} (backoff: {delay:.1f}s)"
                )
                # Wait for backoff delay or stop signal
                if self._stop_event.wait(timeout=delay):
                    break
            except psycopg.errors.InFailedSqlTransaction as e:
                # Transaction in failed state - log and wait
                delay = self._backoff.record_failure()
                self._log_throttled_warning(
                    f"Heartbeat InFailedSqlTransaction: {e} (backoff: {delay:.1f}s)"
                )
                if self._stop_event.wait(timeout=delay):
                    break
            except Exception as e:
                delay = self._backoff.record_failure()
                self._log_throttled_warning(
                    f"Heartbeat error: {type(e).__name__}: {e} (backoff: {delay:.1f}s)"
                )

    def _log_throttled_warning(self, message: str) -> None:
        """Log a warning with throttling to avoid spam when DB is down."""
        now = time.monotonic()
        if now - self._last_warning_time >= HEARTBEAT_WARNING_INTERVAL:
            if self._warning_suppress_count > 0:
                message = f"{message} (suppressed {self._warning_suppress_count} similar warnings)"
            logger.warning(message)
            self._last_warning_time = now
            self._warning_suppress_count = 0
        else:
            self._warning_suppress_count += 1

    def _disable_heartbeats(self, table_name: str) -> None:
        """Circuit breaker: permanently disable heartbeats for this process."""
        if not self._disabled:
            logger.warning(
                f"Heartbeat table missing ({table_name}), disabling heartbeats for this process"
            )
            self._disabled = True

    def _send_heartbeat(self, status: Optional[str] = None) -> None:
        """Send a single heartbeat to the database via RPC."""
        if self._disabled:
            return

        status = status or self._status
        db_url = self._get_db_url()

        with psycopg.connect(db_url) as conn:
            rpc = RPCClient(conn)
            rpc.register_heartbeat(
                worker_id=self.worker_id,
                worker_type=self.worker_type,
                hostname=self.hostname,
                status=status,
            )

        logger.debug(f"Heartbeat sent: {self.worker_id} ({self.worker_type}) status={status}")


# =============================================================================
# Convenience context manager for workers
# =============================================================================


class HeartbeatContext:
    """
    Context manager for worker heartbeats.

    Usage:
        with HeartbeatContext("ingest_processor", get_supabase_db_url) as hb:
            # hb.worker_id is the unique worker ID
            # ... run worker loop ...
    """

    def __init__(
        self,
        worker_type: str,
        get_db_url: Callable[[], str],
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._heartbeat = WorkerHeartbeat(worker_type, get_db_url, interval)

    def __enter__(self) -> WorkerHeartbeat:
        self._heartbeat.start()
        return self._heartbeat

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self._heartbeat.set_error()
        self._heartbeat.stop()
        return False  # Don't suppress exceptions
