"""
backend/routers/dashboard.py - Dashboard Router with Resilient Data Access

Provides dashboard data endpoints using the centralized DataService.
Implements "Try REST -> Heal -> Failover to DB" pattern transparently.

Endpoints:
    GET /api/v1/dashboard/overview      - Enforcement overview stats
    GET /api/v1/dashboard/radar         - Enforcement radar metrics
    GET /api/v1/dashboard/collectability - Collectability tier distribution
    GET /api/v1/dashboard/pipeline      - Judgment pipeline data
    GET /api/v1/dashboard/plaintiffs    - Plaintiffs overview
    GET /api/v1/dashboard/activity      - Recent enforcement activity
    GET /api/v1/dashboard/batch-performance - Batch ingestion metrics
    GET /api/v1/dashboard/health        - Service health check

Design:
    - All endpoints use DataService for automatic failover
    - Frontend gets consistent JSON regardless of data source
    - Never blocks user-critical operations on PostgREST health
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services.data_service import get_data_service

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class DashboardResponse(BaseModel):
    """Standard dashboard response envelope."""

    success: bool
    data: list[dict[str, Any]]
    count: int
    source: str = "auto"  # 'rest', 'direct_db', or 'auto'
    timestamp: str


class HealthCheckResponse(BaseModel):
    """Health check response."""

    is_healthy: bool
    latency_ms: float
    source: str
    timestamp: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def make_response(data: list[dict[str, Any]], source: str = "auto") -> DashboardResponse:
    """Wrap data in standard response envelope."""
    return DashboardResponse(
        success=True,
        data=data,
        count=len(data),
        source=source,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/overview",
    response_model=DashboardResponse,
    summary="Enforcement Overview Stats",
    description="Returns aggregated enforcement stats by stage and collectability tier. "
    "View: public.v_enforcement_overview",
)
async def get_overview() -> DashboardResponse:
    """
    Fetch enforcement overview statistics.

    Returns aggregated case counts and amounts grouped by:
    - enforcement_stage (e.g., 'intake', 'discovery', 'collection')
    - collectability_tier (e.g., 'high', 'medium', 'low')

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        result = await service.fetch_view_with_metadata("v_enforcement_overview")
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch overview: {e}")


@router.get(
    "/radar",
    response_model=DashboardResponse,
    summary="Enforcement Radar Metrics",
    description="Returns key enforcement metrics for monitoring.",
)
async def get_radar() -> DashboardResponse:
    """
    Fetch enforcement radar/metrics data.

    Returns key metrics including:
    - active_cases: Current open case count and amount
    - week_new: Cases opened in last 7 days
    - week_closed: Cases closed in last 7 days

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        result = await service.fetch_view_with_metadata("v_metrics_enforcement")
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch radar: {e}")


@router.get(
    "/collectability",
    response_model=DashboardResponse,
    summary="Collectability Tier Distribution",
    description="Returns collectability tier distribution with counts and percentages.",
)
async def get_collectability() -> DashboardResponse:
    """
    Fetch collectability tier distribution.

    Returns tier breakdown:
    - A: High value, recent judgments
    - B: Medium value/age
    - C: Low value or aged out

    Each tier includes case_count, total_amount, and percentage.

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        # Fetch from judgments and aggregate by tier
        result = await service.fetch_view_with_metadata("v_collectability_tiers", limit=10)
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch collectability: {e}")


@router.get(
    "/pipeline",
    response_model=DashboardResponse,
    summary="Judgment Pipeline",
    description="Returns judgment pipeline data with enforcement status. "
    "View: public.v_judgment_pipeline",
)
async def get_pipeline(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum rows to return"),
) -> DashboardResponse:
    """
    Fetch judgment pipeline data.

    Returns recent judgments with:
    - case_number, plaintiff, defendant
    - judgment_amount
    - enforcement_stage and last update time
    - collectability_tier and enrichment status

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        result = await service.fetch_view_with_metadata("v_judgment_pipeline", limit=limit)
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch pipeline: {e}")


@router.get(
    "/plaintiffs",
    response_model=DashboardResponse,
    summary="Plaintiffs Overview",
    description="Returns plaintiffs summary with case counts and exposure. "
    "View: public.v_plaintiffs_overview",
)
async def get_plaintiffs(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum rows to return"),
) -> DashboardResponse:
    """
    Fetch plaintiffs overview data.

    Returns per-plaintiff summary:
    - plaintiff_id, plaintiff_name, firm_name
    - status
    - total_judgment_amount (exposure)
    - case_count

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        result = await service.fetch_view_with_metadata("v_plaintiffs_overview", limit=limit)
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch plaintiffs: {e}")


@router.get(
    "/activity",
    response_model=DashboardResponse,
    summary="Recent Enforcement Activity",
    description="Returns recently updated enforcement cases. View: public.v_enforcement_recent",
)
async def get_activity(
    limit: int = Query(default=50, ge=1, le=500, description="Maximum rows to return"),
) -> DashboardResponse:
    """
    Fetch recent enforcement activity.

    Returns recently updated cases sorted by enforcement_stage_updated_at DESC.
    Useful for activity feeds and recent changes widgets.

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        result = await service.fetch_view_with_metadata("v_enforcement_recent", limit=limit)
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch activity: {e}")


@router.get(
    "/batch-performance",
    response_model=DashboardResponse,
    summary="Batch Ingestion Performance",
    description="Returns ingestion performance metrics. View: ops.v_batch_performance",
)
async def get_batch_performance(
    limit: int = Query(default=24, ge=1, le=168, description="Number of recent batches"),
) -> DashboardResponse:
    """
    Fetch batch ingestion performance metrics.

    Returns recent batch stats including:
    - batch_count, total_rows_ingested, total_rows_failed
    - avg/max processing time
    - dedupe_rate, error_rate

    Uses DataService with automatic REST/DB failover.
    """
    try:
        service = get_data_service()
        # Note: ops schema prefix handled by DataService
        result = await service.fetch_view_with_metadata("ops.v_batch_performance", limit=limit)
        return make_response(result.data, source=result.metadata.source)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch batch performance: {e}")


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    summary="Dashboard Service Health",
    description="Checks if the DataService can access data via REST and/or direct DB.",
)
async def health_check() -> HealthCheckResponse:
    """
    Check dashboard service health.

    Performs a test fetch to verify data access.
    Returns source used (rest or direct_db) and latency.

    Use this to verify the failover mechanism is working.
    """
    import time

    start = time.monotonic()

    try:
        service = get_data_service()
        # Simple test query - fetch 1 row from any view
        result = await service.fetch_view_with_metadata("v_plaintiffs_overview", limit=1)
        latency_ms = (time.monotonic() - start) * 1000

        return HealthCheckResponse(
            is_healthy=True,
            latency_ms=latency_ms,
            source=result.metadata.source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=result.metadata.rest_error,
        )

    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return HealthCheckResponse(
            is_healthy=False,
            latency_ms=latency_ms,
            source="error",
            timestamp=datetime.now(timezone.utc).isoformat(),
            error=str(e),
        )
