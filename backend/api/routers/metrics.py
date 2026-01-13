"""
Lightweight metrics endpoint for observability.

Exposes application vital signs without the complexity of Prometheus:
- System stats (uptime, request/error counts)
- Database connectivity
- Queue health (PGMQ depths and ages)
- Worker heartbeats

Requires API key authentication.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.core import metrics
from backend.core.security import AuthContext, get_current_user
from backend.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics", tags=["observability"])


# -----------------------------------------------------------------------------
# Response Models
# -----------------------------------------------------------------------------


class SystemStats(BaseModel):
    """System-level statistics."""

    uptime_seconds: int
    start_time_iso: str
    requests_total: int
    errors_total: int
    error_rate_percent: float


class QueueStats(BaseModel):
    """Stats for a single PGMQ queue."""

    depth: int
    oldest_msg_age_sec: Optional[int] = None


class WorkerHeartbeat(BaseModel):
    """Worker heartbeat info."""

    worker_id: str
    status: str
    last_heartbeat: Optional[str] = None
    age_seconds: Optional[int] = None


class IngestStats(BaseModel):
    """Ingestion engine health stats."""

    backlog_count: int
    last_failed_batch: Optional[str] = None
    last_failed_at: Optional[str] = None


class MetricsResponse(BaseModel):
    """Full metrics response."""

    ts: str
    system: SystemStats
    db_connected: bool
    queues: Dict[str, QueueStats]
    workers: List[WorkerHeartbeat]
    ingest: IngestStats


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


async def _check_db_connectivity() -> bool:
    """Check if database is reachable."""
    try:
        pool = await get_pool()
        if pool is None:
            return False
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1;")
                row = await cur.fetchone()
                return row is not None and row[0] == 1
    except Exception as e:
        logger.warning(f"DB connectivity check failed: {e}")
        return False


async def _get_queue_stats() -> Dict[str, QueueStats]:
    """Query PGMQ queue statistics."""
    result: Dict[str, QueueStats] = {}
    try:
        pool = await get_pool()
        if pool is None:
            return result

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Try workers.v_queue_stats first (our custom view)
                try:
                    await cur.execute(
                        """
                        SELECT queue_name, current_length, oldest_msg_age_sec
                        FROM workers.v_queue_stats
                        ORDER BY queue_name;
                    """
                    )
                    rows = await cur.fetchall()
                    for row in rows:
                        queue_name, depth, age = row
                        result[queue_name] = QueueStats(
                            depth=int(depth) if depth else 0,
                            oldest_msg_age_sec=int(age) if age else None,
                        )
                    return result
                except Exception:
                    pass  # View doesn't exist, try fallback

                # Fallback: query pgmq.metrics directly
                try:
                    await cur.execute(
                        """
                        SELECT queue_name, queue_length, newest_msg_age_sec
                        FROM pgmq.metrics()
                        ORDER BY queue_name;
                    """
                    )
                    rows = await cur.fetchall()
                    for row in rows:
                        queue_name, depth, age = row
                        result[queue_name] = QueueStats(
                            depth=int(depth) if depth else 0,
                            oldest_msg_age_sec=int(age) if age else None,
                        )
                except Exception as e:
                    logger.debug(f"PGMQ metrics not available: {e}")

    except Exception as e:
        logger.warning(f"Failed to get queue stats: {e}")

    return result


async def _get_worker_heartbeats() -> List[WorkerHeartbeat]:
    """Query worker heartbeat status."""
    result: List[WorkerHeartbeat] = []
    try:
        pool = await get_pool()
        if pool is None:
            return result

        now = datetime.now(timezone.utc)

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        """
                        SELECT worker_id, status, last_heartbeat_at
                        FROM workers.heartbeats
                        ORDER BY worker_id;
                    """
                    )
                    rows = await cur.fetchall()
                    for row in rows:
                        worker_id, status, last_heartbeat = row

                        age_sec: Optional[int] = None
                        heartbeat_iso: Optional[str] = None

                        if last_heartbeat:
                            # Handle timezone-aware vs naive datetimes
                            if last_heartbeat.tzinfo is None:
                                last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
                            heartbeat_iso = last_heartbeat.isoformat()
                            age_sec = int((now - last_heartbeat).total_seconds())

                        result.append(
                            WorkerHeartbeat(
                                worker_id=str(worker_id),
                                status=str(status) if status else "unknown",
                                last_heartbeat=heartbeat_iso,
                                age_seconds=age_sec,
                            )
                        )
                except Exception as e:
                    logger.debug(f"Worker heartbeats table not available: {e}")

    except Exception as e:
        logger.warning(f"Failed to get worker heartbeats: {e}")

    return result


async def _get_ingest_stats() -> IngestStats:
    """Query ingestion engine health stats."""
    backlog_count = 0
    last_failed_batch: Optional[str] = None
    last_failed_at: Optional[str] = None

    try:
        pool = await get_pool()
        if pool is None:
            return IngestStats(
                backlog_count=0,
                last_failed_batch=None,
                last_failed_at=None,
            )

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # Count pending/processing rows
                try:
                    await cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM ingest.import_runs
                        WHERE status IN ('pending', 'processing');
                    """
                    )
                    row = await cur.fetchone()
                    backlog_count = int(row[0]) if row and row[0] else 0
                except Exception as e:
                    logger.debug(f"Failed to query ingest backlog: {e}")

                # Get most recent failed import
                try:
                    await cur.execute(
                        """
                        SELECT source_batch_id, completed_at
                        FROM ingest.import_runs
                        WHERE status = 'failed'
                        ORDER BY completed_at DESC NULLS LAST
                        LIMIT 1;
                    """
                    )
                    row = await cur.fetchone()
                    if row:
                        last_failed_batch = str(row[0])
                        if row[1]:
                            # Handle timezone-aware vs naive
                            ts = row[1]
                            if ts.tzinfo is None:
                                ts = ts.replace(tzinfo=timezone.utc)
                            last_failed_at = ts.isoformat()
                except Exception as e:
                    logger.debug(f"Failed to query last failed ingest: {e}")

    except Exception as e:
        logger.warning(f"Failed to get ingest stats: {e}")

    return IngestStats(
        backlog_count=backlog_count,
        last_failed_batch=last_failed_batch,
        last_failed_at=last_failed_at,
    )


# -----------------------------------------------------------------------------
# Endpoint
# -----------------------------------------------------------------------------


@router.get("", response_model=MetricsResponse)
async def get_metrics(
    auth: AuthContext = Depends(get_current_user),
) -> MetricsResponse:
    """
    Get application metrics snapshot.

    Requires API key authentication.

    Returns:
        MetricsResponse with system stats, DB health, queue depths, and worker status
    """
    # System stats from in-memory counters
    counts = metrics.get_counts()
    uptime = metrics.get_uptime()
    start_time = metrics.get_start_time()

    error_rate = 0.0
    if counts["requests"] > 0:
        error_rate = round((counts["errors"] / counts["requests"]) * 100, 2)

    system = SystemStats(
        uptime_seconds=uptime,
        start_time_iso=datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
        requests_total=counts["requests"],
        errors_total=counts["errors"],
        error_rate_percent=error_rate,
    )

    # Gather async data
    db_connected = await _check_db_connectivity()
    queues = await _get_queue_stats()
    workers = await _get_worker_heartbeats()
    ingest = await _get_ingest_stats()

    return MetricsResponse(
        ts=datetime.now(timezone.utc).isoformat(),
        system=system,
        db_connected=db_connected,
        queues=queues,
        workers=workers,
        ingest=ingest,
    )
