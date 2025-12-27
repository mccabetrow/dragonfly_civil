"""
Dragonfly Ops Dashboard API - The System Pulse

Provides a single high-level endpoint that returns the complete operational
state of the Dragonfly system. Service-role authenticated only.

Endpoint: GET /api/v1/ops/dashboard

Response includes:
- ingest: Batch/row counts, success rates, top errors
- queue: Pending jobs, age, processing count, failures
- infra: Worker status, reaper health, pooler status
- slos: Latency p95, error budget remaining

Usage:
    curl -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \\
         https://api.dragonfly.com/api/v1/ops/dashboard
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ops", tags=["Ops Dashboard"])


# =============================================================================
# Authentication
# =============================================================================


def verify_service_role(request: Request) -> None:
    """
    Verify the request has service role authentication.

    Accepts either:
    - apikey header matching SUPABASE_SERVICE_ROLE_KEY
    - Authorization: Bearer <service_role_key>
    """
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not service_key:
        raise HTTPException(status_code=500, detail="Service role key not configured")

    # Check apikey header
    apikey = request.headers.get("apikey")
    if apikey == service_key:
        return

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == service_key:
            return

    raise HTTPException(status_code=401, detail="Service role authentication required")


# =============================================================================
# Response Models
# =============================================================================


class IngestMetrics(BaseModel):
    """Ingest pipeline metrics."""

    batches_24h: int
    rows_24h: int
    success_rate: float
    top_errors: list[dict[str, Any]]


class QueueMetrics(BaseModel):
    """Job queue metrics."""

    pending: int
    oldest_age_min: float
    processing: int
    failed_24h: int


class InfraMetrics(BaseModel):
    """Infrastructure health metrics."""

    active_workers: int
    reaper_last_run: datetime | None
    reaper_status: str  # "healthy", "stale", "error"
    pooler_status: str  # "healthy", "degraded"


class SLOMetrics(BaseModel):
    """SLO compliance metrics."""

    ingest_latency_p95_ms: float | None
    queue_latency_p95_ms: float | None
    error_budget_remaining_pct: float


class BurnRateAlert(BaseModel):
    """Burn rate alert for a domain."""

    domain: str
    failures_5min: int
    burn_rate_pct: float
    alert_level: str  # "normal", "warning", "critical"


class DashboardResponse(BaseModel):
    """Complete ops dashboard response."""

    timestamp: datetime
    environment: str
    ingest: IngestMetrics
    queue: QueueMetrics
    infra: InfraMetrics
    slos: SLOMetrics
    burn_rate_alerts: list[BurnRateAlert]


# =============================================================================
# Dashboard Endpoint
# =============================================================================


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="System Pulse Dashboard",
    description="Returns complete operational state. Service role only.",
    dependencies=[Depends(verify_service_role)],
)
async def get_ops_dashboard() -> DashboardResponse:
    """
    Fetch the complete operational state of the Dragonfly system.

    This is an efficient single-query endpoint that aggregates:
    - Ingest metrics (batches, rows, success rate, errors)
    - Queue metrics (pending, processing, age)
    - Infrastructure health (workers, reaper, pooler)
    - SLO metrics (latency, error budget)
    - Burn rate alerts (failure acceleration)

    Returns:
        Complete ops dashboard payload

    Raises:
        401: Service role authentication required
        503: Database unavailable
    """
    from ...db import get_pool

    pool = await get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        async with pool.connection() as conn:
            # Use a single CTE query for efficiency
            result = await conn.execute(
                """
                WITH ingest_metrics AS (
                    SELECT
                        COUNT(DISTINCT CASE WHEN domain = 'ingest' THEN batch_id END) AS batches_24h,
                        COUNT(*) FILTER (WHERE domain = 'ingest') AS rows_24h,
                        ROUND(
                            (COUNT(*) FILTER (WHERE domain = 'ingest' AND event = 'completed')::numeric / 
                             NULLIF(COUNT(*) FILTER (WHERE domain = 'ingest'), 0)) * 100,
                            2
                        ) AS success_rate
                    FROM ops.audit_log
                    WHERE created_at >= now() - INTERVAL '24 hours'
                ),
                top_errors AS (
                    SELECT 
                        metadata->>'error_code' AS code,
                        COUNT(*) AS count
                    FROM ops.audit_log
                    WHERE created_at >= now() - INTERVAL '24 hours'
                    AND event = 'failed'
                    AND domain = 'ingest'
                    AND metadata->>'error_code' IS NOT NULL
                    GROUP BY metadata->>'error_code'
                    ORDER BY count DESC
                    LIMIT 5
                ),
                queue_metrics AS (
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                        COALESCE(
                            EXTRACT(EPOCH FROM (now() - MIN(created_at) FILTER (WHERE status = 'pending'))) / 60,
                            0
                        ) AS oldest_age_min,
                        COUNT(*) FILTER (WHERE status = 'processing') AS processing,
                        COUNT(*) FILTER (WHERE status = 'failed' AND updated_at >= now() - INTERVAL '24 hours') AS failed_24h
                    FROM ops.job_queue
                ),
                worker_metrics AS (
                    SELECT COUNT(DISTINCT worker_id) AS active_workers
                    FROM ops.worker_heartbeats
                    WHERE last_seen_at >= now() - INTERVAL '5 minutes'
                ),
                reaper_metrics AS (
                    SELECT 
                        last_run_at,
                        status,
                        EXTRACT(EPOCH FROM (now() - last_run_at)) / 60 AS minutes_since_run
                    FROM ops.reaper_heartbeat
                    WHERE id = 1
                ),
                latency_metrics AS (
                    -- Ingest latency: time from batch creation to completion
                    SELECT
                        PERCENTILE_CONT(0.95) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (
                                (metadata->>'completed_at')::timestamptz - 
                                (metadata->>'started_at')::timestamptz
                            )) * 1000
                        ) AS ingest_p95_ms
                    FROM ops.audit_log
                    WHERE domain = 'ingest'
                    AND event = 'completed'
                    AND created_at >= now() - INTERVAL '1 hour'
                    AND metadata->>'completed_at' IS NOT NULL
                    AND metadata->>'started_at' IS NOT NULL
                ),
                queue_latency AS (
                    SELECT
                        PERCENTILE_CONT(0.95) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (completed_at - created_at)) * 1000
                        ) AS queue_p95_ms
                    FROM ops.job_queue
                    WHERE status = 'completed'
                    AND completed_at >= now() - INTERVAL '1 hour'
                ),
                burn_rate AS (
                    SELECT * FROM ops.v_audit_burn_rate
                )
                SELECT
                    -- Ingest
                    (SELECT batches_24h FROM ingest_metrics) AS ingest_batches,
                    (SELECT rows_24h FROM ingest_metrics) AS ingest_rows,
                    (SELECT COALESCE(success_rate, 100.0) FROM ingest_metrics) AS ingest_success_rate,
                    (SELECT jsonb_agg(jsonb_build_object('code', code, 'count', count)) FROM top_errors) AS ingest_top_errors,
                    -- Queue
                    (SELECT pending FROM queue_metrics) AS queue_pending,
                    (SELECT oldest_age_min FROM queue_metrics) AS queue_oldest_age,
                    (SELECT processing FROM queue_metrics) AS queue_processing,
                    (SELECT failed_24h FROM queue_metrics) AS queue_failed_24h,
                    -- Workers
                    (SELECT active_workers FROM worker_metrics) AS active_workers,
                    -- Reaper
                    (SELECT last_run_at FROM reaper_metrics) AS reaper_last_run,
                    (SELECT status FROM reaper_metrics) AS reaper_status,
                    (SELECT minutes_since_run FROM reaper_metrics) AS reaper_minutes_since,
                    -- Latency
                    (SELECT ingest_p95_ms FROM latency_metrics) AS ingest_latency_p95,
                    (SELECT queue_p95_ms FROM queue_latency) AS queue_latency_p95,
                    -- Burn rate (as jsonb array)
                    (SELECT jsonb_agg(jsonb_build_object(
                        'domain', domain,
                        'failures_5min', failures_last_5min,
                        'burn_rate_pct', burn_rate_pct
                    )) FROM burn_rate WHERE failures_last_5min > 0) AS burn_rates
            """
            )

            row = await result.fetchone()

            if row is None:
                raise HTTPException(status_code=503, detail="Failed to fetch metrics")

            # Parse results
            top_errors = row[3] if row[3] else []
            burn_rates = row[14] if row[14] else []

            # Determine reaper status
            reaper_status = "unknown"
            if row[10]:  # reaper_status from heartbeat
                if row[10] == "ok" and row[11] and row[11] < 20:
                    reaper_status = "healthy"
                elif row[10] == "error":
                    reaper_status = "error"
                else:
                    reaper_status = "stale"

            # Calculate error budget (target: 99.5% success, 0.5% budget)
            success_rate = float(row[2]) if row[2] else 100.0
            error_rate = 100.0 - success_rate
            error_budget_total = 0.5  # 0.5% allowed failures
            error_budget_remaining = max(
                0, ((error_budget_total - error_rate) / error_budget_total) * 100
            )

            # Parse burn rate alerts
            burn_alerts = []
            for br in burn_rates:
                alert_level = "normal"
                if br.get("burn_rate_pct", 0) > 100:
                    alert_level = "critical"
                elif br.get("burn_rate_pct", 0) > 50:
                    alert_level = "warning"

                burn_alerts.append(
                    BurnRateAlert(
                        domain=br.get("domain", "unknown"),
                        failures_5min=br.get("failures_5min", 0),
                        burn_rate_pct=br.get("burn_rate_pct", 0),
                        alert_level=alert_level,
                    )
                )

            return DashboardResponse(
                timestamp=datetime.now(timezone.utc),
                environment=os.environ.get("SUPABASE_MODE", "unknown"),
                ingest=IngestMetrics(
                    batches_24h=row[0] or 0,
                    rows_24h=row[1] or 0,
                    success_rate=success_rate,
                    top_errors=top_errors,
                ),
                queue=QueueMetrics(
                    pending=row[4] or 0,
                    oldest_age_min=float(row[5]) if row[5] else 0.0,
                    processing=row[6] or 0,
                    failed_24h=row[7] or 0,
                ),
                infra=InfraMetrics(
                    active_workers=row[8] or 0,
                    reaper_last_run=row[9],
                    reaper_status=reaper_status,
                    pooler_status="healthy",  # Determined at connection time
                ),
                slos=SLOMetrics(
                    ingest_latency_p95_ms=float(row[12]) if row[12] else None,
                    queue_latency_p95_ms=float(row[13]) if row[13] else None,
                    error_budget_remaining_pct=round(error_budget_remaining, 2),
                ),
                burn_rate_alerts=burn_alerts,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Dashboard query failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database error: {str(e)[:100]}")


# =============================================================================
# Additional Endpoints
# =============================================================================


@router.get(
    "/burn-rate",
    summary="Get current burn rates",
    dependencies=[Depends(verify_service_role)],
)
async def get_burn_rates() -> list[BurnRateAlert]:
    """Get current failure burn rates by domain."""
    from ...db import get_pool

    pool = await get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.connection() as conn:
        result = await conn.execute(
            """
            SELECT domain, failures_last_5min, burn_rate_pct
            FROM ops.v_audit_burn_rate
            WHERE failures_last_5min > 0 OR burn_rate_pct != 0
        """
        )

        alerts = []
        async for row in result:
            alert_level = "normal"
            burn_rate = row[2] or 0
            if burn_rate > 100:
                alert_level = "critical"
            elif burn_rate > 50:
                alert_level = "warning"

            alerts.append(
                BurnRateAlert(
                    domain=row[0],
                    failures_5min=row[1] or 0,
                    burn_rate_pct=burn_rate,
                    alert_level=alert_level,
                )
            )

        return alerts


@router.get(
    "/audit-trace/{correlation_id}",
    summary="Get audit trail by correlation ID",
    dependencies=[Depends(verify_service_role)],
)
async def get_audit_trace(correlation_id: str) -> list[dict[str, Any]]:
    """Get all audit events for a correlation ID."""
    import uuid

    from ...db import get_pool

    try:
        corr_uuid = uuid.UUID(correlation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid correlation ID format")

    pool = await get_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable")

    async with pool.connection() as conn:
        result = await conn.execute(
            """
            SELECT id, domain, stage, event, metadata, created_at
            FROM ops.audit_log
            WHERE correlation_id = %s
            ORDER BY created_at ASC
        """,
            (corr_uuid,),
        )

        events = []
        async for row in result:
            events.append(
                {
                    "id": str(row[0]),
                    "domain": row[1],
                    "stage": row[2],
                    "event": row[3],
                    "metadata": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }
            )

        return events
