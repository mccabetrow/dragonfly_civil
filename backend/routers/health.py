"""
Dragonfly Engine - Health Check Router

Provides health check endpoints for monitoring and load balancers.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..api import ApiResponse, api_response, degraded_response
from ..config import get_settings
from ..db import fetch_val, get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


class HealthData(BaseModel):
    """Health check data payload for ApiResponse envelope."""

    status: str
    timestamp: str
    environment: str


# Keep legacy model for backward compatibility
class HealthResponse(BaseModel):
    """Basic health check response."""

    status: str
    timestamp: str
    environment: str


class HealthDetailResponse(BaseModel):
    """Detailed health check response."""

    status: str
    timestamp: str
    environment: str
    database: str
    scheduler: str
    version: str


class DBHealthResponse(BaseModel):
    """Database health check response."""

    status: str
    timestamp: str
    latency_ms: float
    pool_size: int
    pool_free: int


@router.get(
    "",
    response_model=ApiResponse[HealthData],
    summary="Basic health check",
    description="Returns OK if the service is running. No authentication required.",
)
async def health_check() -> ApiResponse[HealthData]:
    """
    Canonical health probe for the Dragonfly system.

    This endpoint is the primary health check for:
    - Vercel console (SystemDiagnostic component)
    - n8n workflow health monitors
    - Railway load balancer
    - Uptime monitoring services

    Returns standard API envelope with:
        data.status: "ok" if service is running
        data.timestamp: ISO 8601 UTC timestamp
        data.environment: Current environment (dev/staging/prod)
        meta.trace_id: Request trace ID for debugging

    No authentication required - this endpoint is public.
    """
    settings = get_settings()
    data = HealthData(
        status="ok",
        timestamp=datetime.utcnow().isoformat() + "Z",
        environment=settings.environment,
    )
    return api_response(data=data)


@router.get(
    "/db",
    response_model=DBHealthResponse,
    summary="Database health check",
    description="Checks database connectivity and pool status.",
)
async def health_check_db() -> DBHealthResponse:
    """
    Database health check endpoint.

    Executes a simple query to verify database connectivity.
    Returns pool statistics for monitoring.
    """
    import time

    try:
        pool = get_pool()

        # Time the query
        start = time.perf_counter()
        result = await fetch_val("SELECT 1")
        latency = (time.perf_counter() - start) * 1000  # Convert to ms

        if result != 1:
            raise ValueError(f"Unexpected result from SELECT 1: {result}")

        return DBHealthResponse(
            status="ok",
            timestamp=datetime.utcnow().isoformat() + "Z",
            latency_ms=round(latency, 2),
            pool_size=pool.get_size(),
            pool_free=pool.get_idle_size(),
        )
    except RuntimeError as e:
        # Pool not initialized
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database pool not initialized")
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)}")


@router.get(
    "/detail",
    response_model=HealthDetailResponse,
    summary="Detailed health check",
    description="Returns detailed status of all service components.",
)
async def health_check_detail() -> HealthDetailResponse:
    """
    Detailed health check endpoint.

    Checks all service components and returns their status.
    Useful for debugging and monitoring dashboards.
    """
    from .. import __version__

    settings = get_settings()

    # Check database
    db_status = "ok"
    try:
        result = await fetch_val("SELECT 1")
        if result != 1:
            db_status = "error"
    except Exception as e:
        logger.warning(f"DB check failed: {e}")
        db_status = "error"

    # Check scheduler
    scheduler_status = "ok"
    try:
        from ..scheduler import get_scheduler

        scheduler = get_scheduler()
        if not scheduler.running:
            scheduler_status = "stopped"
    except RuntimeError:
        scheduler_status = "not_initialized"
    except Exception as e:
        logger.warning(f"Scheduler check failed: {e}")
        scheduler_status = "error"

    # Determine overall status
    overall_status = "ok"
    if db_status != "ok" or scheduler_status not in ("ok", "not_initialized"):
        overall_status = "degraded"

    return HealthDetailResponse(
        status=overall_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
        environment=settings.environment,
        database=db_status,
        scheduler=scheduler_status,
        version=__version__,
    )


class OperationalHealthResponse(BaseModel):
    """Operational health metrics for observability."""

    status: str
    timestamp: str
    database_ok: bool
    pending_jobs: int
    failed_jobs_24h: int
    last_event_at: str | None
    events_24h: int


@router.get(
    "/ops",
    response_model=OperationalHealthResponse,
    summary="Operational health metrics",
    description="Returns operational metrics: pending jobs, recent events, failures.",
)
async def health_ops() -> OperationalHealthResponse:
    """
    Operational health endpoint for production monitoring.

    Reports:
    - Database connectivity
    - Number of pending jobs in the queue
    - Failed jobs in the last 24 hours
    - Last event timestamp
    - Events in the last 24 hours

    Use this endpoint for alerting and dashboards.
    """
    from ..db import get_pool

    timestamp = datetime.utcnow().isoformat() + "Z"

    try:
        pool = await get_pool()
        if pool is None:
            return OperationalHealthResponse(
                status="degraded",
                timestamp=timestamp,
                database_ok=False,
                pending_jobs=0,
                failed_jobs_24h=0,
                last_event_at=None,
                events_24h=0,
            )

        async with pool.cursor() as cur:
            # Count pending jobs
            await cur.execute("SELECT COUNT(*) FROM ops.job_queue WHERE status = 'pending'")
            row = await cur.fetchone()
            pending_jobs = row[0] if row else 0

            # Count failed jobs in last 24h
            await cur.execute(
                """
                SELECT COUNT(*) FROM ops.job_queue
                WHERE status = 'failed'
                AND updated_at > now() - interval '24 hours'
            """
            )
            row = await cur.fetchone()
            failed_jobs = row[0] if row else 0

            # Get last event timestamp and 24h count
            await cur.execute(
                """
                SELECT
                    MAX(created_at) as last_event,
                    COUNT(*) FILTER (WHERE created_at > now() - interval '24 hours') as events_24h
                FROM intelligence.events
            """
            )
            row = await cur.fetchone()
            last_event_at = row[0].isoformat() + "Z" if row and row[0] else None
            events_24h = row[1] if row else 0

        # Determine status
        status = "ok"
        if failed_jobs > 10:
            status = "degraded"
        elif pending_jobs > 100:
            status = "warning"

        return OperationalHealthResponse(
            status=status,
            timestamp=timestamp,
            database_ok=True,
            pending_jobs=pending_jobs,
            failed_jobs_24h=failed_jobs,
            last_event_at=last_event_at,
            events_24h=events_24h,
        )

    except Exception as e:
        logger.error(f"Ops health check failed: {e}")
        return OperationalHealthResponse(
            status="error",
            timestamp=timestamp,
            database_ok=False,
            pending_jobs=0,
            failed_jobs_24h=0,
            last_event_at=None,
            events_24h=0,
        )


@router.get(
    "/jobs",
    summary="List scheduled jobs",
    description="Returns a list of all scheduled jobs.",
)
async def list_scheduled_jobs() -> dict[str, Any]:
    """
    List all scheduled jobs.

    Returns job IDs, triggers, and next run times.
    """
    try:
        from ..scheduler import list_jobs

        jobs = list_jobs()
        return {
            "status": "ok",
            "jobs": jobs,
            "count": len(jobs),
        }
    except RuntimeError:
        return {
            "status": "ok",
            "jobs": [],
            "count": 0,
            "note": "Scheduler not initialized",
        }


@router.get(
    "/daily",
    summary="Trigger daily health broadcast",
    description="Manually triggers the daily health broadcast for testing.",
)
async def trigger_daily_health() -> dict[str, Any]:
    """
    Manually trigger the daily health broadcast.

    This endpoint is useful for testing the health broadcast
    without waiting for the scheduled 5 PM run.
    """
    from ..services.health_service import broadcast_daily_health

    result = await broadcast_daily_health()

    if result.get("status") == "error":
        raise HTTPException(
            status_code=500,
            detail={"error": result.get("error"), "status": "error"},
        )

    return result
