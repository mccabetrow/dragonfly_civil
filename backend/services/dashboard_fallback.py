"""
backend/services/dashboard_fallback.py - Direct SQL Dashboard Service

Provides dashboard data directly from PostgreSQL, bypassing PostgREST entirely.
Used as fallback when PostgREST has PGRST002 (stale schema cache) or other issues.

Endpoints Served:
    - Overview Stats: aggregated enforcement metrics
    - Radar Items: enforcement activity metrics
    - Collectability Scores: tier distribution from judgments

Connection: Uses backend.db.get_connection() for direct PostgreSQL access.
Output: Returns list[dict] (JSON serializable) for API responses.

Usage:
    from backend.services.dashboard_fallback import DashboardFallbackService

    service = DashboardFallbackService()
    stats = await service.get_overview_stats()
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from loguru import logger


@dataclass
class OverviewStats:
    """Overview statistics for the main dashboard."""

    enforcement_stage: str
    collectability_tier: str | None
    case_count: int
    total_judgment_amount: Decimal


@dataclass
class RadarItem:
    """Enforcement radar metrics item."""

    metric_name: str
    metric_value: Any
    period: str | None = None
    updated_at: datetime | None = None


@dataclass
class CollectabilityScore:
    """Collectability tier distribution."""

    tier: str
    case_count: int
    total_amount: Decimal
    percentage: float


class DashboardFallbackService:
    """
    Dashboard data service using direct PostgreSQL connection.

    Bypasses PostgREST for reliability during PGRST002 incidents.
    All methods return JSON-serializable data structures.
    """

    async def get_overview_stats(self) -> list[dict[str, Any]]:
        """
        Fetch enforcement overview statistics.

        Returns aggregated stats by enforcement_stage and collectability_tier.
        Mirrors: SELECT * FROM public.v_enforcement_overview

        Returns:
            List of dicts with keys: enforcement_stage, collectability_tier,
            case_count, total_judgment_amount
        """
        from backend.db import get_connection

        query = """
            SELECT
                COALESCE(NULLIF(LOWER(TRIM(enforcement_stage)), ''), 'unassigned') AS enforcement_stage,
                collectability_tier,
                case_count,
                total_judgment_amount::text AS total_judgment_amount
            FROM public.v_enforcement_overview
            ORDER BY enforcement_stage ASC, collectability_tier ASC NULLS FIRST
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} overview rows")
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_overview_stats failed: {e}")
            # Return empty list on error - frontend can handle gracefully
            return []

    async def get_plaintiffs_overview(self) -> list[dict[str, Any]]:
        """
        Fetch plaintiffs overview statistics.

        Returns summary per plaintiff including total exposure.
        Mirrors: SELECT * FROM public.v_plaintiffs_overview

        Returns:
            List of dicts with keys: plaintiff_id, plaintiff_name, firm_name,
            status, total_judgment_amount, case_count
        """
        from backend.db import get_connection

        query = """
            SELECT
                plaintiff_id::text AS plaintiff_id,
                plaintiff_name,
                firm_name,
                status,
                total_judgment_amount::text AS total_judgment_amount,
                case_count
            FROM public.v_plaintiffs_overview
            ORDER BY total_judgment_amount DESC
            LIMIT 1000
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} plaintiff rows")
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_plaintiffs_overview failed: {e}")
            return []

    async def get_judgment_pipeline(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Fetch judgment pipeline data.

        Returns recent judgments with enforcement status.
        Mirrors: SELECT * FROM public.v_judgment_pipeline

        Args:
            limit: Maximum rows to return (default: 100)

        Returns:
            List of dicts with case details including enforcement_stage
        """
        from backend.db import get_connection

        query = """
            SELECT
                judgment_id::text AS judgment_id,
                case_number,
                plaintiff_id::text AS plaintiff_id,
                plaintiff_name,
                defendant_name,
                judgment_amount::text AS judgment_amount,
                enforcement_stage,
                enforcement_stage_updated_at,
                collectability_tier,
                collectability_age_days,
                last_enriched_at,
                last_enrichment_status
            FROM public.v_judgment_pipeline
            ORDER BY enforcement_stage_updated_at DESC NULLS LAST
            LIMIT %s
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query, limit)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} pipeline rows")
            return [self._serialize_row(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_judgment_pipeline failed: {e}")
            return []

    async def get_radar_items(self) -> list[dict[str, Any]]:
        """
        Fetch enforcement radar/metrics data.

        Returns key enforcement metrics for monitoring dashboard.
        Mirrors: SELECT * FROM public.v_metrics_enforcement

        Returns:
            List of dicts with metric details
        """
        from backend.db import get_connection

        query = """
            SELECT
                active_case_count,
                active_judgment_amount::text AS active_judgment_amount,
                week_new_cases,
                week_new_judgment_amount::text AS week_new_judgment_amount,
                week_closed_cases,
                week_closed_judgment_amount::text AS week_closed_judgment_amount
            FROM public.v_metrics_enforcement
            LIMIT 1
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)

            if not rows:
                # Return sensible defaults if view is empty
                return [
                    {
                        "metric_name": "active_cases",
                        "value": 0,
                        "period": "current",
                    },
                    {
                        "metric_name": "week_new",
                        "value": 0,
                        "period": "last_7_days",
                    },
                ]

            # Transform single row into radar items
            row = rows[0]
            radar = [
                {
                    "metric_name": "active_cases",
                    "value": row.get("active_case_count", 0),
                    "amount": row.get("active_judgment_amount", "0"),
                    "period": "current",
                },
                {
                    "metric_name": "week_new",
                    "value": row.get("week_new_cases", 0),
                    "amount": row.get("week_new_judgment_amount", "0"),
                    "period": "last_7_days",
                },
                {
                    "metric_name": "week_closed",
                    "value": row.get("week_closed_cases", 0),
                    "amount": row.get("week_closed_judgment_amount", "0"),
                    "period": "last_7_days",
                },
            ]

            logger.debug(f"[DashboardFallback] Fetched {len(radar)} radar items")
            return radar

        except Exception as e:
            logger.error(f"[DashboardFallback] get_radar_items failed: {e}")
            return []

    async def get_collectability_scores(self) -> list[dict[str, Any]]:
        """
        Fetch collectability tier distribution.

        Returns tier counts from judgments table for collectability analysis.

        Returns:
            List of dicts with tier, case_count, total_amount, percentage
        """
        from backend.db import get_connection

        query = """
            WITH tier_stats AS (
                SELECT
                    CASE
                        WHEN collectability_score >= 70 THEN 'high'
                        WHEN collectability_score >= 40 THEN 'medium'
                        WHEN collectability_score IS NOT NULL THEN 'low'
                        ELSE 'unscored'
                    END AS tier,
                    COUNT(*) AS case_count,
                    COALESCE(SUM(judgment_amount), 0) AS total_amount
                FROM public.judgments
                WHERE status IS NULL OR status NOT IN ('closed', 'collected', 'satisfied')
                GROUP BY 1
            ),
            totals AS (
                SELECT SUM(case_count) AS total_cases FROM tier_stats
            )
            SELECT
                ts.tier,
                ts.case_count,
                ts.total_amount::text AS total_amount,
                CASE
                    WHEN t.total_cases > 0
                    THEN ROUND((ts.case_count::numeric / t.total_cases) * 100, 1)
                    ELSE 0
                END AS percentage
            FROM tier_stats ts
            CROSS JOIN totals t
            ORDER BY
                CASE ts.tier
                    WHEN 'high' THEN 1
                    WHEN 'medium' THEN 2
                    WHEN 'low' THEN 3
                    ELSE 4
                END
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} collectability rows")
            return [dict(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_collectability_scores failed: {e}")
            return []

    async def get_batch_performance(self, hours: int = 24) -> list[dict[str, Any]]:
        """
        Fetch batch ingestion performance metrics.

        Returns hourly rollup of ingestion performance from ops schema.
        Mirrors: SELECT * FROM ops.v_batch_performance

        Args:
            hours: How many hours to look back (default: 24)

        Returns:
            List of dicts with hourly performance metrics
        """
        from backend.db import get_connection

        query = """
            SELECT
                hour_bucket,
                batch_count,
                total_rows_ingested,
                total_rows_failed,
                avg_processing_time_ms,
                max_processing_time_ms,
                dedupe_rate,
                error_rate
            FROM ops.v_batch_performance
            ORDER BY hour_bucket DESC
            LIMIT %s
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query, hours)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} batch perf rows")
            return [self._serialize_row(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_batch_performance failed: {e}")
            return []

    async def get_recent_activity(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        Fetch recent enforcement activity.

        Returns recently updated cases from v_enforcement_recent.

        Args:
            limit: Maximum rows to return (default: 50)

        Returns:
            List of dicts with recent activity details
        """
        from backend.db import get_connection

        query = """
            SELECT
                judgment_id::text AS judgment_id,
                case_number,
                plaintiff_id::text AS plaintiff_id,
                plaintiff_name,
                judgment_amount::text AS judgment_amount,
                enforcement_stage,
                enforcement_stage_updated_at,
                collectability_tier
            FROM public.v_enforcement_recent
            LIMIT %s
        """

        try:
            async with get_connection() as conn:
                rows = await conn.fetch(query, limit)

            logger.debug(f"[DashboardFallback] Fetched {len(rows)} recent activity rows")
            return [self._serialize_row(row) for row in rows]

        except Exception as e:
            logger.error(f"[DashboardFallback] get_recent_activity failed: {e}")
            return []

    async def health_check(self) -> dict[str, Any]:
        """
        Check if fallback service can reach the database.

        Returns:
            Dict with is_healthy, latency_ms, and timestamp
        """
        import time

        from backend.db import get_connection

        start = time.monotonic()
        try:
            async with get_connection() as conn:
                result = await conn.fetchval("SELECT 1")

            latency_ms = (time.monotonic() - start) * 1000
            return {
                "is_healthy": result == 1,
                "latency_ms": round(latency_ms, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "direct_sql",
            }

        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return {
                "is_healthy": False,
                "latency_ms": round(latency_ms, 1),
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": "direct_sql",
            }

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """
        Serialize a database row to JSON-safe dict.

        Handles datetime, Decimal, and UUID conversions.
        """
        result = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif isinstance(value, Decimal):
                result[key] = str(value)
            elif hasattr(value, "hex"):  # UUID
                result[key] = str(value)
            else:
                result[key] = value
        return result


# Singleton instance for convenience
_dashboard_service: DashboardFallbackService | None = None


def get_dashboard_fallback_service() -> DashboardFallbackService:
    """Get or create the singleton dashboard fallback service."""
    global _dashboard_service
    if _dashboard_service is None:
        _dashboard_service = DashboardFallbackService()
    return _dashboard_service
