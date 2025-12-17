"""
Dragonfly Engine - CEO Metrics Router

Provides the canonical 12 CEO Metrics endpoint for executive dashboard.

Metrics by Category:
    PIPELINE (3):
        1. pipeline_total_aum - Total Assets Under Management
        2. pipeline_active_cases - Active cases not closed/collected
        3. pipeline_intake_velocity_7d - New judgments in last 7 days

    QUALITY (2):
        4. quality_batch_success_rate - CSV batch success rate (30d)
        5. quality_data_integrity_score - Records with complete data

    ENFORCEMENT (3):
        6. enforcement_active_cases - Active enforcement cases
        7. enforcement_stalled_cases - Stalled 14+ days
        8. enforcement_actions_7d - Actions completed in 7 days

    REVENUE (2):
        9. revenue_collected_30d - Amount collected last 30 days
        10. revenue_recovery_rate - Historical recovery rate

    RISK (2):
        11. risk_queue_failures - Failed jobs in queue
        12. risk_aging_90d - Cases older than 90 days unresolved
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user
from ..db import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/ceo", tags=["CEO Metrics"])


# =============================================================================
# Response Models
# =============================================================================

AlertStatus = Literal["green", "yellow", "red"]


class PipelineMetrics(BaseModel):
    """Pipeline category metrics."""

    total_aum: float = Field(..., description="Total Assets Under Management ($)")
    active_cases: int = Field(..., description="Active cases not closed/collected")
    intake_velocity_7d: int = Field(..., description="New judgments in last 7 days")

    # Alert statuses
    aum_alert: AlertStatus = Field(default="green")
    velocity_alert: AlertStatus = Field(default="green")


class QualityMetrics(BaseModel):
    """Quality category metrics."""

    batch_success_rate: float = Field(..., description="CSV batch success rate % (30d)")
    data_integrity_score: float = Field(..., description="% records with complete data")

    # Alert statuses
    batch_alert: AlertStatus = Field(default="green")
    integrity_alert: AlertStatus = Field(default="green")


class EnforcementMetrics(BaseModel):
    """Enforcement category metrics."""

    active_cases: int = Field(..., description="Active enforcement cases")
    stalled_cases: int = Field(..., description="Cases stalled 14+ days")
    actions_7d: int = Field(..., description="Actions completed in 7 days")

    # Alert statuses
    stalled_alert: AlertStatus = Field(default="green")
    actions_alert: AlertStatus = Field(default="green")


class RevenueMetrics(BaseModel):
    """Revenue category metrics."""

    collected_30d: float = Field(..., description="Amount collected last 30 days ($)")
    recovery_rate: float = Field(..., description="Historical recovery rate %")

    # Alert statuses
    recovery_alert: AlertStatus = Field(default="green")


class RiskMetrics(BaseModel):
    """Risk category metrics."""

    queue_failures: int = Field(..., description="Failed jobs in queue")
    aging_90d: int = Field(..., description="Cases older than 90 days unresolved")

    # Alert statuses
    queue_alert: AlertStatus = Field(default="green")
    aging_alert: AlertStatus = Field(default="green")


class CEO12Metrics(BaseModel):
    """
    The canonical 12 CEO Metrics for Dragonfly Civil.

    Grouped by category: Pipeline (3), Quality (2), Enforcement (3),
    Revenue (2), Risk (2). Each metric includes value and alert status.
    """

    pipeline: PipelineMetrics
    quality: QualityMetrics
    enforcement: EnforcementMetrics
    revenue: RevenueMetrics
    risk: RiskMetrics

    generated_at: str = Field(..., description="ISO timestamp when metrics were generated")
    metric_version: str = Field(default="1.0", description="Metric schema version")


class MetricDefinition(BaseModel):
    """Definition of a single CEO metric."""

    metric_key: str
    category: str
    display_name: str
    description: str
    unit: str
    refresh_rate: str
    warning_threshold: Optional[str] = None
    critical_threshold: Optional[str] = None
    dashboard_card_position: int


class MetricDefinitionsResponse(BaseModel):
    """Response containing all metric definitions."""

    metrics: list[MetricDefinition]
    count: int


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/metrics",
    response_model=CEO12Metrics,
    summary="Get 12 CEO Metrics",
    description="Returns the canonical 12 CEO metrics with values and alert statuses.",
)
async def get_ceo_12_metrics(
    auth: AuthContext = Depends(get_current_user),
) -> CEO12Metrics:
    """
    Get the canonical 12 CEO metrics for executive dashboard.

    Returns metrics grouped by category (Pipeline, Quality, Enforcement,
    Revenue, Risk) with current values and alert status (green/yellow/red).

    Requires authentication.
    """
    logger.info(f"CEO metrics requested by {auth.via}")

    try:
        client = get_supabase_client()

        # Call the RPC function
        result = client.rpc("ceo_12_metrics").execute()

        if not result.data:
            logger.warning("No data returned from ceo_12_metrics RPC")
            return _fallback_metrics()

        row = result.data[0] if isinstance(result.data, list) else result.data

        return CEO12Metrics(
            pipeline=PipelineMetrics(
                total_aum=float(row.get("pipeline_total_aum", 0)),
                active_cases=int(row.get("pipeline_active_cases", 0)),
                intake_velocity_7d=int(row.get("pipeline_intake_velocity_7d", 0)),
                aum_alert=row.get("pipeline_aum_alert", "green"),
                velocity_alert=row.get("intake_velocity_alert", "green"),
            ),
            quality=QualityMetrics(
                batch_success_rate=float(row.get("quality_batch_success_rate", 100)),
                data_integrity_score=float(row.get("quality_data_integrity_score", 100)),
                batch_alert=row.get("batch_success_alert", "green"),
                integrity_alert=row.get("data_integrity_alert", "green"),
            ),
            enforcement=EnforcementMetrics(
                active_cases=int(row.get("enforcement_active_cases", 0)),
                stalled_cases=int(row.get("enforcement_stalled_cases", 0)),
                actions_7d=int(row.get("enforcement_actions_7d", 0)),
                stalled_alert=row.get("stalled_cases_alert", "green"),
                actions_alert=row.get("actions_7d_alert", "green"),
            ),
            revenue=RevenueMetrics(
                collected_30d=float(row.get("revenue_collected_30d", 0)),
                recovery_rate=float(row.get("revenue_recovery_rate", 0)),
                recovery_alert=row.get("recovery_rate_alert", "green"),
            ),
            risk=RiskMetrics(
                queue_failures=int(row.get("risk_queue_failures", 0)),
                aging_90d=int(row.get("risk_aging_90d", 0)),
                queue_alert=row.get("queue_failures_alert", "green"),
                aging_alert=row.get("aging_90d_alert", "green"),
            ),
            generated_at=row.get("generated_at", datetime.utcnow().isoformat()),
            metric_version=row.get("metric_version", "1.0"),
        )

    except Exception as e:
        logger.exception(f"Error fetching CEO metrics: {e}")
        return _fallback_metrics()


@router.get(
    "/metrics/definitions",
    response_model=MetricDefinitionsResponse,
    summary="Get CEO Metric Definitions",
    description="Returns definitions for all 12 CEO metrics including thresholds.",
)
async def get_metric_definitions(
    auth: AuthContext = Depends(get_current_user),
) -> MetricDefinitionsResponse:
    """
    Get definitions for all 12 CEO metrics.

    Returns metric key, display name, description, unit, refresh rate,
    and alert thresholds for dashboard configuration.

    Requires authentication.
    """
    logger.info(f"CEO metric definitions requested by {auth.via}")

    try:
        client = get_supabase_client()

        result = (
            client.schema("analytics")
            .from_("ceo_metric_definitions")
            .select("*")
            .order("dashboard_card_position")
            .execute()
        )

        metrics = [
            MetricDefinition(
                metric_key=row["metric_key"],
                category=row["category"],
                display_name=row["display_name"],
                description=row["description"],
                unit=row["unit"],
                refresh_rate=row["refresh_rate"],
                warning_threshold=row.get("warning_threshold"),
                critical_threshold=row.get("critical_threshold"),
                dashboard_card_position=row["dashboard_card_position"],
            )
            for row in (result.data or [])
        ]

        return MetricDefinitionsResponse(metrics=metrics, count=len(metrics))

    except Exception as e:
        logger.exception(f"Error fetching metric definitions: {e}")
        # Return static definitions as fallback
        return _static_definitions()


@router.get(
    "/metrics/{category}",
    summary="Get metrics by category",
    description="Returns metrics for a specific category.",
)
async def get_metrics_by_category(
    category: Literal["pipeline", "quality", "enforcement", "revenue", "risk"],
    auth: AuthContext = Depends(get_current_user),
):
    """
    Get metrics for a specific category.

    Categories: pipeline, quality, enforcement, revenue, risk
    """
    logger.info(f"CEO {category} metrics requested by {auth.via}")

    full_metrics = await get_ceo_12_metrics(auth)

    category_map = {
        "pipeline": full_metrics.pipeline,
        "quality": full_metrics.quality,
        "enforcement": full_metrics.enforcement,
        "revenue": full_metrics.revenue,
        "risk": full_metrics.risk,
    }

    return category_map[category]


# =============================================================================
# Fallback / Static Data
# =============================================================================


def _fallback_metrics() -> CEO12Metrics:
    """Return fallback metrics when database is unavailable."""
    return CEO12Metrics(
        pipeline=PipelineMetrics(
            total_aum=0,
            active_cases=0,
            intake_velocity_7d=0,
            aum_alert="yellow",
            velocity_alert="yellow",
        ),
        quality=QualityMetrics(
            batch_success_rate=100,
            data_integrity_score=100,
            batch_alert="green",
            integrity_alert="green",
        ),
        enforcement=EnforcementMetrics(
            active_cases=0,
            stalled_cases=0,
            actions_7d=0,
            stalled_alert="green",
            actions_alert="yellow",
        ),
        revenue=RevenueMetrics(
            collected_30d=0,
            recovery_rate=0,
            recovery_alert="yellow",
        ),
        risk=RiskMetrics(
            queue_failures=0,
            aging_90d=0,
            queue_alert="green",
            aging_alert="green",
        ),
        generated_at=datetime.utcnow().isoformat(),
        metric_version="1.0-fallback",
    )


def _static_definitions() -> MetricDefinitionsResponse:
    """Return static metric definitions when database is unavailable."""
    definitions = [
        MetricDefinition(
            metric_key="pipeline_total_aum",
            category="Pipeline",
            display_name="Total AUM",
            description="Total Assets Under Management",
            unit="currency",
            refresh_rate="real-time",
            warning_threshold="< $100,000",
            critical_threshold="< $50,000",
            dashboard_card_position=1,
        ),
        MetricDefinition(
            metric_key="pipeline_active_cases",
            category="Pipeline",
            display_name="Active Cases",
            description="Cases not closed/collected",
            unit="count",
            refresh_rate="real-time",
            dashboard_card_position=2,
        ),
        MetricDefinition(
            metric_key="pipeline_intake_velocity_7d",
            category="Pipeline",
            display_name="Intake Velocity",
            description="New judgments in 7 days",
            unit="count",
            refresh_rate="real-time",
            warning_threshold="< 10",
            critical_threshold="< 5",
            dashboard_card_position=3,
        ),
        MetricDefinition(
            metric_key="quality_batch_success_rate",
            category="Quality",
            display_name="Batch Success Rate",
            description="CSV import success rate",
            unit="percentage",
            refresh_rate="real-time",
            warning_threshold="< 95%",
            critical_threshold="< 90%",
            dashboard_card_position=4,
        ),
        MetricDefinition(
            metric_key="quality_data_integrity_score",
            category="Quality",
            display_name="Data Integrity",
            description="Records with complete data",
            unit="percentage",
            refresh_rate="real-time",
            warning_threshold="< 98%",
            critical_threshold="< 95%",
            dashboard_card_position=5,
        ),
        MetricDefinition(
            metric_key="enforcement_active_cases",
            category="Enforcement",
            display_name="Active Enforcement",
            description="Enforcement cases in progress",
            unit="count",
            refresh_rate="real-time",
            dashboard_card_position=6,
        ),
        MetricDefinition(
            metric_key="enforcement_stalled_cases",
            category="Enforcement",
            display_name="Stalled Cases",
            description="Cases stalled 14+ days",
            unit="count",
            refresh_rate="real-time",
            warning_threshold="> 10",
            critical_threshold="> 25",
            dashboard_card_position=7,
        ),
        MetricDefinition(
            metric_key="enforcement_actions_7d",
            category="Enforcement",
            display_name="Actions (7d)",
            description="Actions completed in 7 days",
            unit="count",
            refresh_rate="real-time",
            warning_threshold="< 5",
            critical_threshold="< 2",
            dashboard_card_position=8,
        ),
        MetricDefinition(
            metric_key="revenue_collected_30d",
            category="Revenue",
            display_name="Collections (30d)",
            description="Amount collected last 30 days",
            unit="currency",
            refresh_rate="real-time",
            dashboard_card_position=9,
        ),
        MetricDefinition(
            metric_key="revenue_recovery_rate",
            category="Revenue",
            display_name="Recovery Rate",
            description="Historical recovery percentage",
            unit="percentage",
            refresh_rate="real-time",
            warning_threshold="< 5%",
            critical_threshold="< 2%",
            dashboard_card_position=10,
        ),
        MetricDefinition(
            metric_key="risk_queue_failures",
            category="Risk",
            display_name="Queue Failures",
            description="Failed jobs in queue",
            unit="count",
            refresh_rate="real-time",
            warning_threshold="> 5",
            critical_threshold="> 10",
            dashboard_card_position=11,
        ),
        MetricDefinition(
            metric_key="risk_aging_90d",
            category="Risk",
            display_name="Aging Cases",
            description="Cases 90+ days unresolved",
            unit="count",
            refresh_rate="real-time",
            warning_threshold="> 50",
            critical_threshold="> 100",
            dashboard_card_position=12,
        ),
    ]
    return MetricDefinitionsResponse(metrics=definitions, count=len(definitions))
