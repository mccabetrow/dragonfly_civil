"""
Dragonfly Engine - Health Check Router

Provides health check endpoints for monitoring and load balancers.
All external checks have configurable timeouts to prevent hanging probes.

Key endpoints:
- GET /health (or /api/health) - Liveness probe: returns 200 if process is up
- GET /readyz - Readiness probe: returns 200 only if DB is reachable
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
from ..db import check_db_ready, fetch_val, get_pool, get_pool_health, get_supabase_client

# Default timeouts for health checks (seconds)
HEALTH_DB_TIMEOUT = 5.0
HEALTH_SUPABASE_TIMEOUT = 8.0
READINESS_DB_TIMEOUT = 2.0  # Stricter timeout for readiness probe

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


class LivenessResponse(BaseModel):
    """Liveness probe response - indicates process is alive."""

    status: str
    timestamp: str
    version: str


class ReadinessDBResponse(BaseModel):
    """Readiness probe response - indicates service is ready to accept traffic."""

    ready: bool
    status: str
    timestamp: str
    database: str
    latency_ms: float | None = None
    error: str | None = None
    pool_initialized: bool
    pool_init_attempts: int


class SystemHealthMetric(BaseModel):
    """Individual SLO metric for system health."""

    name: str
    status: str  # "healthy", "warning", "critical"
    value: float | int | None = None
    threshold: str | None = None
    message: str


class IntakeHealthMetrics(BaseModel):
    """Intake pipeline health metrics for observability."""

    last_intake_success: str | None = None
    pending_validation: int = 0
    failed_rows_24h: int = 0
    enrichment_backlog: int = 0
    active_workers: int = 0
    batches_24h: int = 0
    success_rate_24h: float | None = None


class SystemHealthResponse(BaseModel):
    """
    Comprehensive system health response for CEO Dashboard and alerting.

    Aggregates key SLO metrics from queue, workers, and reaper.
    """

    overall_status: str  # "healthy", "degraded", "critical"
    timestamp: str
    environment: str
    metrics: list[SystemHealthMetric]
    queue_health: dict | None = None
    worker_health: dict | None = None
    reaper_health: dict | None = None
    intake_health: IntakeHealthMetrics | None = None


# ==========================================================================
# LIVENESS PROBE - /health (returns 200 if process is up)
# ==========================================================================


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


# ==========================================================================
# KUBERNETES-STYLE PROBES
# ==========================================================================


@router.get(
    "/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Returns 200 if the process is alive. Never checks external dependencies.",
)
async def liveness_check() -> LivenessResponse:
    """
    Kubernetes-style liveness probe.

    Returns 200 OK if the process is alive and can respond to requests.
    This endpoint NEVER checks the database or any external dependencies.

    Use this for container liveness checks - if this fails, restart the container.
    """
    return LivenessResponse(
        status="ok",
        timestamp=datetime.utcnow().isoformat() + "Z",
        version=__version__,
    )


@router.get(
    "/readyz",
    response_model=ReadinessDBResponse,
    responses={
        200: {"description": "Service is ready to accept traffic"},
        503: {"description": "Service is not ready - DB unreachable or unhealthy"},
    },
    summary="Readiness probe (DB-focused)",
    description="Returns 200 only if DB is reachable and SELECT 1 succeeds within 2s.",
)
async def readiness_db_check() -> JSONResponse:
    """
    Kubernetes-style readiness probe focused on database connectivity.

    Returns 200 OK only if:
    - Database pool was successfully initialized
    - SELECT 1 query succeeds within 2 seconds

    Returns 503 Service Unavailable if:
    - Pool initialization failed
    - Database is unreachable
    - Query times out (>2s)

    Use this for container readiness checks - if this fails, remove from load balancer.
    """
    pool_health = get_pool_health()
    timestamp = datetime.utcnow().isoformat() + "Z"

    # Check database readiness with strict timeout
    is_ready, db_status = await check_db_ready(timeout=READINESS_DB_TIMEOUT)

    # Extract latency if present in status
    latency_ms: float | None = None
    if "ms)" in db_status:
        try:
            latency_str = db_status.split("(")[1].rstrip("ms)")
            latency_ms = float(latency_str)
        except (IndexError, ValueError):
            pass

    response_data = ReadinessDBResponse(
        ready=is_ready,
        status="ready" if is_ready else "not_ready",
        timestamp=timestamp,
        database=db_status,
        latency_ms=latency_ms,
        error=pool_health.last_error if not is_ready else None,
        pool_initialized=pool_health.initialized,
        pool_init_attempts=pool_health.init_attempts,
    )

    if is_ready:
        return JSONResponse(
            status_code=200,
            content=response_data.model_dump(),
        )
    else:
        logger.warning(
            f"Readiness check failed: db={db_status}, "
            f"initialized={pool_health.initialized}, "
            f"error={pool_health.last_error}"
        )
        return JSONResponse(
            status_code=503,
            content=response_data.model_dump(),
        )


# ==========================================================================
# DETAILED HEALTH CHECKS
# ==========================================================================


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


# ==========================================================================
# SYSTEM HEALTH - /health/system (CEO Dashboard SLO metrics)
# ==========================================================================


@router.get(
    "/system",
    response_model=SystemHealthResponse,
    summary="System health with SLO metrics",
    description="Comprehensive system health for CEO Dashboard and alerting.",
)
async def health_check_system() -> SystemHealthResponse:
    """
    System-wide health check with SLO metrics.

    Returns:
    - Queue health (pending, stuck, failed counts)
    - Worker health (active workers, last heartbeat)
    - Reaper health (last run, stuck job count)
    - Overall status: healthy/degraded/critical

    Thresholds (configurable):
    - CRITICAL: stuck_jobs > 0 OR no worker heartbeat in 10 min
    - WARNING: pending_jobs > 50 OR failed_jobs_24h > 20
    - HEALTHY: All metrics within thresholds
    """
    from ..db import get_pool

    timestamp = datetime.utcnow().isoformat() + "Z"
    settings = get_settings()
    metrics: list[SystemHealthMetric] = []
    queue_health: dict = {}
    worker_health: dict = {}
    reaper_health: dict = {}

    try:
        pool = await get_pool()
        if pool is None:
            return SystemHealthResponse(
                overall_status="critical",
                timestamp=timestamp,
                environment=settings.environment,
                metrics=[
                    SystemHealthMetric(
                        name="database",
                        status="critical",
                        message="Database pool not initialized",
                    )
                ],
            )

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                # ----------------------------------------------------------
                # QUEUE HEALTH
                # ----------------------------------------------------------
                await cur.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                        COUNT(*) FILTER (WHERE status = 'processing') AS processing,
                        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                        COUNT(*) FILTER (
                            WHERE status = 'processing'
                            AND started_at < NOW() - INTERVAL '15 minutes'
                        ) AS stuck,
                        COUNT(*) FILTER (
                            WHERE status = 'failed'
                            AND updated_at > NOW() - INTERVAL '24 hours'
                        ) AS failed_24h
                    FROM ops.job_queue
                    """
                )
                row = await cur.fetchone()
                queue_health = {
                    "pending": row[0] or 0,
                    "processing": row[1] or 0,
                    "failed": row[2] or 0,
                    "stuck": row[3] or 0,
                    "failed_24h": row[4] or 0,
                }

                # Stuck jobs metric
                stuck_count = queue_health["stuck"]
                if stuck_count > 0:
                    metrics.append(
                        SystemHealthMetric(
                            name="stuck_jobs",
                            status="critical",
                            value=stuck_count,
                            threshold="0",
                            message=f"{stuck_count} jobs stuck in processing > 15 min",
                        )
                    )
                else:
                    metrics.append(
                        SystemHealthMetric(
                            name="stuck_jobs",
                            status="healthy",
                            value=0,
                            threshold="0",
                            message="No stuck jobs",
                        )
                    )

                # Pending jobs metric
                pending_count = queue_health["pending"]
                if pending_count > 100:
                    metrics.append(
                        SystemHealthMetric(
                            name="pending_jobs",
                            status="warning",
                            value=pending_count,
                            threshold="100",
                            message=f"{pending_count} jobs pending (queue backlog)",
                        )
                    )
                else:
                    metrics.append(
                        SystemHealthMetric(
                            name="pending_jobs",
                            status="healthy",
                            value=pending_count,
                            threshold="100",
                            message=f"{pending_count} pending jobs",
                        )
                    )

                # ----------------------------------------------------------
                # WORKER HEALTH
                # ----------------------------------------------------------
                await cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_workers,
                        COUNT(*) FILTER (
                            WHERE last_seen > NOW() - INTERVAL '5 minutes'
                        ) AS active_workers,
                        MAX(last_seen) AS last_heartbeat
                    FROM ops.worker_heartbeats
                    """
                )
                row = await cur.fetchone()
                worker_health = {
                    "total_workers": row[0] or 0,
                    "active_workers": row[1] or 0,
                    "last_heartbeat": row[2].isoformat() + "Z" if row[2] else None,
                }

                active_workers = worker_health["active_workers"]
                if active_workers == 0:
                    metrics.append(
                        SystemHealthMetric(
                            name="active_workers",
                            status="critical",
                            value=0,
                            threshold="1",
                            message="No active workers (no heartbeat in 5 min)",
                        )
                    )
                else:
                    metrics.append(
                        SystemHealthMetric(
                            name="active_workers",
                            status="healthy",
                            value=active_workers,
                            threshold="1",
                            message=f"{active_workers} active worker(s)",
                        )
                    )

                # ----------------------------------------------------------
                # REAPER HEALTH (check cron.job_run_details if available)
                # ----------------------------------------------------------
                try:
                    await cur.execute(
                        """
                        SELECT
                            jrd.status,
                            jrd.start_time,
                            jrd.return_message
                        FROM cron.job_run_details jrd
                        JOIN cron.job j ON j.jobid = jrd.jobid
                        WHERE j.jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
                        ORDER BY jrd.start_time DESC
                        LIMIT 1
                        """
                    )
                    row = await cur.fetchone()
                    if row:
                        reaper_health = {
                            "last_status": row[0],
                            "last_run": row[1].isoformat() + "Z" if row[1] else None,
                            "return_message": row[2],
                        }

                        # Check if reaper ran recently
                        if row[1]:
                            minutes_since = (
                                datetime.utcnow() - row[1].replace(tzinfo=None)
                            ).total_seconds() / 60
                            if minutes_since > 15:
                                metrics.append(
                                    SystemHealthMetric(
                                        name="reaper",
                                        status="warning",
                                        value=int(minutes_since),
                                        threshold="15",
                                        message=f"Reaper last ran {int(minutes_since)} min ago",
                                    )
                                )
                            else:
                                metrics.append(
                                    SystemHealthMetric(
                                        name="reaper",
                                        status="healthy",
                                        value=int(minutes_since),
                                        threshold="15",
                                        message=f"Reaper ran {int(minutes_since)} min ago",
                                    )
                                )
                        else:
                            metrics.append(
                                SystemHealthMetric(
                                    name="reaper",
                                    status="warning",
                                    message="Reaper has no execution history",
                                )
                            )
                    else:
                        reaper_health = {"configured": False}
                        metrics.append(
                            SystemHealthMetric(
                                name="reaper",
                                status="warning",
                                message="Reaper schedule not found in pg_cron",
                            )
                        )
                except Exception as e:
                    # pg_cron might not be accessible
                    reaper_health = {"error": str(e)}
                    metrics.append(
                        SystemHealthMetric(
                            name="reaper",
                            status="warning",
                            message=f"Cannot check reaper: {type(e).__name__}",
                        )
                    )

                # ----------------------------------------------------------
                # INTAKE HEALTH
                # ----------------------------------------------------------
                intake_health_data = IntakeHealthMetrics()
                try:
                    # Last successful intake
                    await cur.execute(
                        """
                        SELECT MAX(completed_at)
                        FROM intake.simplicity_batches
                        WHERE status = 'completed'
                        """
                    )
                    row = await cur.fetchone()
                    if row and row[0]:
                        intake_health_data.last_intake_success = row[0].isoformat() + "Z"

                    # Pending validation (raw rows not yet validated)
                    await cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM intake.simplicity_raw_rows r
                        WHERE NOT EXISTS (
                            SELECT 1 FROM intake.simplicity_validated_rows v
                            WHERE v.raw_row_id = r.id
                        )
                        AND NOT EXISTS (
                            SELECT 1 FROM intake.simplicity_failed_rows f
                            WHERE f.raw_row_id = r.id AND f.resolved_at IS NULL
                        )
                        """
                    )
                    row = await cur.fetchone()
                    intake_health_data.pending_validation = row[0] or 0

                    # Failed rows in last 24h
                    await cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM intake.simplicity_failed_rows
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                        AND resolved_at IS NULL
                        """
                    )
                    row = await cur.fetchone()
                    intake_health_data.failed_rows_24h = row[0] or 0

                    # Enrichment backlog (pending enrichment jobs)
                    await cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM ops.job_queue
                        WHERE job_type IN ('enrich_tlo', 'enrich_idicore')
                        AND status = 'pending'
                        """
                    )
                    row = await cur.fetchone()
                    intake_health_data.enrichment_backlog = row[0] or 0

                    # Active workers (from earlier query)
                    intake_health_data.active_workers = worker_health.get("active_workers", 0)

                    # Batches in last 24h with success rate
                    await cur.execute(
                        """
                        SELECT 
                            COUNT(*) AS batch_count,
                            AVG(
                                CASE WHEN row_count_total > 0 
                                THEN (row_count_valid::float / row_count_total) * 100 
                                ELSE 0 END
                            ) AS avg_success_rate
                        FROM intake.simplicity_batches
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                        """
                    )
                    row = await cur.fetchone()
                    intake_health_data.batches_24h = row[0] or 0
                    if row[1] is not None:
                        intake_health_data.success_rate_24h = round(float(row[1]), 2)

                    # Add intake metrics to SLO checks
                    if intake_health_data.pending_validation > 100:
                        metrics.append(
                            SystemHealthMetric(
                                name="intake_pending",
                                status="warning",
                                value=intake_health_data.pending_validation,
                                threshold="100",
                                message=f"{intake_health_data.pending_validation} rows pending validation",
                            )
                        )

                    if intake_health_data.failed_rows_24h > 50:
                        metrics.append(
                            SystemHealthMetric(
                                name="intake_failures",
                                status="warning",
                                value=intake_health_data.failed_rows_24h,
                                threshold="50",
                                message=f"{intake_health_data.failed_rows_24h} failed rows in 24h",
                            )
                        )

                except Exception as e:
                    logger.warning(f"Failed to collect intake health: {e}")
                    # Don't fail the whole health check

        # ----------------------------------------------------------
        # DETERMINE OVERALL STATUS
        # ----------------------------------------------------------
        has_critical = any(m.status == "critical" for m in metrics)
        has_warning = any(m.status == "warning" for m in metrics)

        if has_critical:
            overall_status = "critical"
        elif has_warning:
            overall_status = "degraded"
        else:
            overall_status = "healthy"

        return SystemHealthResponse(
            overall_status=overall_status,
            timestamp=timestamp,
            environment=settings.environment,
            metrics=metrics,
            queue_health=queue_health,
            worker_health=worker_health,
            reaper_health=reaper_health,
            intake_health=intake_health_data,
        )

    except Exception as e:
        logger.error(f"System health check failed: {e}")
        return SystemHealthResponse(
            overall_status="critical",
            timestamp=timestamp,
            environment=settings.environment,
            metrics=[
                SystemHealthMetric(
                    name="database",
                    status="critical",
                    message=f"Database error: {type(e).__name__}",
                )
            ],
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
