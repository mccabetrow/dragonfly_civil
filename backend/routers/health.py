"""
Dragonfly Engine - Health Check Router

Provides health check endpoints for monitoring and load balancers.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings
from ..db import fetch_val, get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])


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
    response_model=HealthResponse,
    summary="Basic health check",
    description="Returns OK if the service is running.",
)
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint.

    Returns a simple status indicating the service is alive.
    Used by load balancers and uptime monitors.
    """
    settings = get_settings()
    return HealthResponse(
        status="ok",
        timestamp=datetime.utcnow().isoformat() + "Z",
        environment=settings.environment,
    )


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
