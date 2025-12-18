"""
Dragonfly Engine - Health Check Router

Provides health check endpoints for monitoring and load balancers.
All external checks have configurable timeouts to prevent hanging probes.
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import __version__
from ..api import ApiResponse, api_response, degraded_response
from ..config import get_settings
from ..db import fetch_val, get_pool, get_supabase_client

# Default timeouts for health checks (seconds)
HEALTH_DB_TIMEOUT = 5.0
HEALTH_SUPABASE_TIMEOUT = 8.0

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
    description="Checks database connectivity and pool status with timeout.",
)
async def health_check_db() -> DBHealthResponse:
    """
    Database health check endpoint.

    Executes a simple query to verify database connectivity.
    Returns pool statistics for monitoring.
    Timeout: 5 seconds (configurable via HEALTH_DB_TIMEOUT).
    """
    try:
        pool = await get_pool()
        if pool is None:
            raise RuntimeError("Database pool not initialized")

        # Time the query with timeout
        start = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                fetch_val("SELECT 1"),
                timeout=HEALTH_DB_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=503,
                detail=f"Database check timed out after {HEALTH_DB_TIMEOUT}s",
            )
        latency = (time.perf_counter() - start) * 1000  # Convert to ms

        if result != 1:
            raise ValueError(f"Unexpected result from SELECT 1: {result}")

        # Get pool stats
        stats = pool.get_stats()
        pool_size = stats.get("pool_size", pool.min_size)
        pool_available = stats.get("pool_available", 0)

        return DBHealthResponse(
            status="ok",
            timestamp=datetime.utcnow().isoformat() + "Z",
            latency_ms=round(latency, 2),
            pool_size=pool_size,
            pool_free=pool_available,
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

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
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


# =========================================================================
# VERSION & READINESS ENDPOINTS
# =========================================================================


class VersionResponse(BaseModel):
    """Version information response."""

    version: str
    environment: str
    timestamp: str


class SupabaseHealthResponse(BaseModel):
    """Supabase REST API health check response."""

    status: str
    timestamp: str
    latency_ms: float
    endpoint: str


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    database: str
    supabase: str
    timestamp: str
    checks: dict[str, bool]


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Get API version",
    description="Returns the current API version and environment. No authentication required. Never queries the database.",
)
async def get_version() -> VersionResponse:
    """
    Get the current API version.

    This is a cheap endpoint that never queries the database.
    Suitable for frequent polling by monitoring tools.
    """
    settings = get_settings()
    return VersionResponse(
        version=__version__,
        environment=settings.environment,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/supabase",
    response_model=SupabaseHealthResponse,
    responses={
        200: {"description": "Supabase is reachable"},
        503: {"description": "Supabase is unreachable or timed out"},
    },
    summary="Supabase health check",
    description="Validates Supabase REST API connectivity with timeout.",
)
async def health_check_supabase() -> SupabaseHealthResponse:
    """
    Supabase REST API health check endpoint.

    Executes a lightweight query to verify Supabase connectivity.
    Timeout: 8 seconds (configurable via HEALTH_SUPABASE_TIMEOUT).
    """
    settings = get_settings()

    async def _check_supabase() -> tuple[bool, float]:
        """Run Supabase check in thread pool (sync client)."""
        import concurrent.futures

        def sync_check() -> float:
            start = time.perf_counter()
            client = get_supabase_client()
            # Lightweight query - just verify we can reach the API
            client.table("plaintiffs").select("id").limit(1).execute()
            return (time.perf_counter() - start) * 1000

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            latency = await loop.run_in_executor(executor, sync_check)
        return True, latency

    try:
        _, latency = await asyncio.wait_for(
            _check_supabase(),
            timeout=HEALTH_SUPABASE_TIMEOUT,
        )
        return SupabaseHealthResponse(
            status="ok",
            timestamp=datetime.utcnow().isoformat() + "Z",
            latency_ms=round(latency, 2),
            endpoint=settings.supabase_url or "not_configured",
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail=f"Supabase check timed out after {HEALTH_SUPABASE_TIMEOUT}s",
        )
    except Exception as e:
        logger.error(f"Supabase health check failed: {e}")
        raise HTTPException(
            status_code=503,
            detail=f"Supabase error: {type(e).__name__}",
        )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"description": "Service is ready"},
        503: {"description": "Service is not ready"},
    },
    summary="Readiness probe",
    description="Validates DB and Supabase connectivity with timeouts. Returns 200 if ready, 503 if not.",
)
async def readiness_check() -> ReadinessResponse | JSONResponse:
    """
    Kubernetes-style readiness probe.

    Validates with timeouts:
    - Database connectivity (psycopg pool) - 5s timeout
    - Supabase REST API connectivity - 8s timeout

    Returns 200 OK if all checks pass, 503 Service Unavailable otherwise.
    """
    import concurrent.futures

    checks: dict[str, bool] = {}
    db_status = "unknown"
    supabase_status = "unknown"

    # Check database connectivity with timeout
    async def _check_db() -> tuple[str, bool]:
        try:
            pool = await get_pool()
            if pool:
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                        await cur.fetchone()
                return "ok", True
            else:
                return "no_pool", False
        except Exception as e:
            logger.warning(f"Readiness check: DB failed - {e}")
            return f"error: {type(e).__name__}", False

    try:
        db_status, db_ok = await asyncio.wait_for(
            _check_db(),
            timeout=HEALTH_DB_TIMEOUT,
        )
        checks["database"] = db_ok
    except asyncio.TimeoutError:
        logger.warning(f"Readiness check: DB timed out after {HEALTH_DB_TIMEOUT}s")
        db_status = f"timeout: {HEALTH_DB_TIMEOUT}s"
        checks["database"] = False

    # Check Supabase REST API connectivity with timeout
    def _sync_supabase_check() -> tuple[str, bool]:
        try:
            client = get_supabase_client()
            client.table("plaintiffs").select("id").limit(1).execute()
            return "ok", True
        except Exception as e:
            logger.warning(f"Readiness check: Supabase failed - {e}")
            return f"error: {type(e).__name__}", False

    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = loop.run_in_executor(executor, _sync_supabase_check)
            supabase_status, supabase_ok = await asyncio.wait_for(
                future,
                timeout=HEALTH_SUPABASE_TIMEOUT,
            )
        checks["supabase"] = supabase_ok
    except asyncio.TimeoutError:
        logger.warning(f"Readiness check: Supabase timed out after {HEALTH_SUPABASE_TIMEOUT}s")
        supabase_status = f"timeout: {HEALTH_SUPABASE_TIMEOUT}s"
        checks["supabase"] = False

    is_ready = all(checks.values())
    response = ReadinessResponse(
        ready=is_ready,
        database=db_status,
        supabase=supabase_status,
        timestamp=datetime.utcnow().isoformat() + "Z",
        checks=checks,
    )

    if is_ready:
        return response
    else:
        return JSONResponse(
            status_code=503,
            content=response.model_dump(),
        )
