"""
Dragonfly Engine - Worker Heartbeat

Lightweight heartbeat mechanism for worker processes.
Workers emit periodic heartbeats to:
1. Log lines (always) - for log aggregation/alerting
2. Database table (rate-limited) - for UI/dashboard visibility

Usage in workers:
    from backend.core.heartbeat import WorkerHeartbeat

    heartbeat = WorkerHeartbeat("ingest_processor")

    while running:
        # ... do work ...
        await heartbeat.beat()  # Call frequently, internally rate-limited
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Default intervals
DEFAULT_LOG_INTERVAL_SECONDS = 60  # Log heartbeat every 60 seconds
DEFAULT_DB_INTERVAL_SECONDS = 30  # Write to DB every 30 seconds


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat behavior."""

    log_interval_seconds: float = DEFAULT_LOG_INTERVAL_SECONDS
    db_interval_seconds: float = DEFAULT_DB_INTERVAL_SECONDS
    enable_db_writes: bool = True
    hostname: str = field(default_factory=lambda: platform.node())


class WorkerHeartbeat:
    """
    Manages worker heartbeat emissions.

    Thread-safe and rate-limited to avoid log/DB spam.
    """

    def __init__(
        self,
        worker_type: str,
        worker_id: str | None = None,
        config: HeartbeatConfig | None = None,
    ):
        """
        Initialize heartbeat manager.

        Args:
            worker_type: Type of worker (e.g., "ingest_processor", "enforcement_engine")
            worker_id: Unique ID for this worker instance (auto-generated if not provided)
            config: Optional heartbeat configuration
        """
        self.worker_type = worker_type
        self.worker_id = worker_id or self._generate_worker_id()
        self.config = config or HeartbeatConfig()

        self._last_log_time: float = 0
        self._last_db_time: float = 0
        self._beat_count: int = 0
        self._start_time: float = time.monotonic()
        self._status: str = "starting"
        self._last_error: str | None = None

        # Stats for logging
        self._jobs_processed: int = 0
        self._errors_count: int = 0

    def _generate_worker_id(self) -> str:
        """Generate a unique worker ID."""
        import uuid

        short_uuid = str(uuid.uuid4())[:8]
        return f"{self.worker_type}-{short_uuid}"

    @property
    def uptime_seconds(self) -> float:
        """Get worker uptime in seconds."""
        return time.monotonic() - self._start_time

    def set_status(self, status: str) -> None:
        """Update worker status."""
        self._status = status

    def record_job_processed(self) -> None:
        """Record that a job was processed."""
        self._jobs_processed += 1

    def record_error(self, error_message: str | None = None) -> None:
        """Record an error occurrence."""
        self._errors_count += 1
        self._last_error = error_message

    async def beat(self, force: bool = False) -> None:
        """
        Emit a heartbeat if interval has elapsed.

        Args:
            force: If True, emit regardless of interval
        """
        now = time.monotonic()
        self._beat_count += 1

        # Always update status to running on beat
        if self._status == "starting":
            self._status = "running"

        # Log heartbeat (rate-limited)
        if force or (now - self._last_log_time) >= self.config.log_interval_seconds:
            self._emit_log_heartbeat()
            self._last_log_time = now

        # DB heartbeat (rate-limited)
        if self.config.enable_db_writes:
            if force or (now - self._last_db_time) >= self.config.db_interval_seconds:
                await self._emit_db_heartbeat()
                self._last_db_time = now

    def _emit_log_heartbeat(self) -> None:
        """Emit heartbeat to logs."""
        uptime_mins = int(self.uptime_seconds / 60)

        log_data = {
            "event": "worker_heartbeat",
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "status": self._status,
            "uptime_minutes": uptime_mins,
            "jobs_processed": self._jobs_processed,
            "errors_count": self._errors_count,
            "hostname": self.config.hostname,
        }

        if self._last_error:
            log_data["last_error"] = self._last_error[:200]  # Truncate

        logger.info(
            f"heartbeat worker={self.worker_type} status={self._status} "
            f"uptime={uptime_mins}m jobs={self._jobs_processed} errors={self._errors_count}",
            extra=log_data,
        )

    async def _emit_db_heartbeat(self) -> None:
        """Emit heartbeat to database using secure RPC."""
        try:
            # Import here to avoid circular imports
            from ..db import get_supabase_client

            client = get_supabase_client()

            # Use the SECURITY DEFINER RPC function for secure writes
            # Note: ops.register_heartbeat is exposed via PostgREST
            client.rpc(
                "register_heartbeat",
                {
                    "p_worker_id": self.worker_id,
                    "p_worker_type": self.worker_type,
                    "p_hostname": self.config.hostname,
                    "p_status": self._status,
                },
            ).execute()

        except Exception as e:
            # Don't fail the worker on heartbeat errors
            logger.warning(
                f"Failed to write DB heartbeat: {e}",
                extra={
                    "worker_id": self.worker_id,
                    "worker_type": self.worker_type,
                    "error": str(e),
                },
            )

    async def startup(self) -> None:
        """Called on worker startup. Emits initial heartbeat."""
        self._status = "starting"
        await self.beat(force=True)
        logger.info(
            f"Worker started: {self.worker_id}",
            extra={
                "event": "worker_startup",
                "worker_id": self.worker_id,
                "worker_type": self.worker_type,
                "hostname": self.config.hostname,
            },
        )

    async def shutdown(self, reason: str = "normal") -> None:
        """Called on worker shutdown. Emits final heartbeat."""
        self._status = "stopped"

        # Emit final DB heartbeat
        if self.config.enable_db_writes:
            await self._emit_db_heartbeat()

        logger.info(
            f"Worker stopped: {self.worker_id} reason={reason} "
            f"uptime={int(self.uptime_seconds)}s jobs={self._jobs_processed}",
            extra={
                "event": "worker_shutdown",
                "worker_id": self.worker_id,
                "worker_type": self.worker_type,
                "reason": reason,
                "uptime_seconds": self.uptime_seconds,
                "jobs_processed": self._jobs_processed,
                "errors_count": self._errors_count,
            },
        )


# =============================================================================
# SYNC VERSION (for workers that aren't fully async)
# =============================================================================


class SyncWorkerHeartbeat:
    """
    Synchronous version of WorkerHeartbeat.

    For workers that use synchronous code or psycopg (not psycopg async).
    Only emits log heartbeats (no async DB writes).
    """

    def __init__(
        self,
        worker_type: str,
        worker_id: str | None = None,
        log_interval_seconds: float = DEFAULT_LOG_INTERVAL_SECONDS,
    ):
        self.worker_type = worker_type
        self.worker_id = worker_id or self._generate_worker_id()
        self.log_interval_seconds = log_interval_seconds
        self.hostname = platform.node()

        self._last_log_time: float = 0
        self._beat_count: int = 0
        self._start_time: float = time.monotonic()
        self._status: str = "starting"
        self._jobs_processed: int = 0
        self._errors_count: int = 0
        self._last_error: str | None = None

    def _generate_worker_id(self) -> str:
        import uuid

        short_uuid = str(uuid.uuid4())[:8]
        return f"{self.worker_type}-{short_uuid}"

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def set_status(self, status: str) -> None:
        self._status = status

    def record_job_processed(self) -> None:
        self._jobs_processed += 1

    def record_error(self, error_message: str | None = None) -> None:
        self._errors_count += 1
        self._last_error = error_message

    def beat(self, force: bool = False) -> None:
        """Emit heartbeat if interval elapsed."""
        now = time.monotonic()
        self._beat_count += 1

        if self._status == "starting":
            self._status = "running"

        if force or (now - self._last_log_time) >= self.log_interval_seconds:
            self._emit_log_heartbeat()
            self._last_log_time = now

    def _emit_log_heartbeat(self) -> None:
        uptime_mins = int(self.uptime_seconds / 60)

        log_data = {
            "event": "worker_heartbeat",
            "worker_id": self.worker_id,
            "worker_type": self.worker_type,
            "status": self._status,
            "uptime_minutes": uptime_mins,
            "jobs_processed": self._jobs_processed,
            "errors_count": self._errors_count,
            "hostname": self.hostname,
        }

        if self._last_error:
            log_data["last_error"] = self._last_error[:200]

        logger.info(
            f"heartbeat worker={self.worker_type} status={self._status} "
            f"uptime={uptime_mins}m jobs={self._jobs_processed} errors={self._errors_count}",
            extra=log_data,
        )

    def startup(self) -> None:
        """Called on worker startup."""
        self._status = "starting"
        self.beat(force=True)
        logger.info(
            f"Worker started: {self.worker_id}",
            extra={
                "event": "worker_startup",
                "worker_id": self.worker_id,
                "worker_type": self.worker_type,
                "hostname": self.hostname,
            },
        )

    def shutdown(self, reason: str = "normal") -> None:
        """Called on worker shutdown."""
        self._status = "stopped"
        logger.info(
            f"Worker stopped: {self.worker_id} reason={reason} "
            f"uptime={int(self.uptime_seconds)}s jobs={self._jobs_processed}",
            extra={
                "event": "worker_shutdown",
                "worker_id": self.worker_id,
                "worker_type": self.worker_type,
                "reason": reason,
                "uptime_seconds": self.uptime_seconds,
                "jobs_processed": self._jobs_processed,
                "errors_count": self._errors_count,
            },
        )
