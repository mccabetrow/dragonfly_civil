"""
Dragonfly Engine - Portfolio Router

Provides portfolio-level statistics for the CEO Portfolio page.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.security import AuthContext, get_current_user
from ...db import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/portfolio", tags=["Portfolio"])


# =============================================================================
# Response Models
# =============================================================================


class ScoreTierAllocation(BaseModel):
    """Breakdown by collectability score tier."""

    tier: str = Field(..., description="Tier label (A, B, C)")
    label: str = Field(..., description="Human-readable label")
    amount: float = Field(..., description="Total judgment amount in tier")
    count: int = Field(..., description="Number of judgments in tier")
    color: str = Field(..., description="UI color for the tier")


class CountyBreakdown(BaseModel):
    """Breakdown by county."""

    county: str = Field(..., description="County name")
    amount: float = Field(..., description="Total judgment amount")
    count: int = Field(..., description="Number of judgments")


class JudgmentRow(BaseModel):
    """Single judgment row for the Portfolio Explorer grid."""

    id: str = Field(..., description="Judgment UUID")
    case_number: Optional[str] = Field(None, description="Court case number")
    plaintiff_name: str = Field(..., description="Plaintiff name")
    defendant_name: str = Field(..., description="Defendant name")
    judgment_amount: float = Field(..., description="Judgment amount in dollars")
    collectability_score: int = Field(..., description="Collectability score 0-100")
    status: str = Field(..., description="Current status")
    county: str = Field(..., description="County name")
    judgment_date: Optional[str] = Field(None, description="Date judgment was entered")
    tier: str = Field(..., description="Tier letter (A, B, C)")
    tier_label: str = Field(..., description="Tier display label")


class PortfolioJudgmentsResponse(BaseModel):
    """Paginated portfolio judgments response."""

    items: list[JudgmentRow] = Field(..., description="Judgment rows for current page")
    total_count: int = Field(..., description="Total number of matching judgments")
    total_value: float = Field(..., description="Sum of matching judgment amounts")
    page: int = Field(..., description="Current page (1-indexed)")
    limit: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total number of pages")
    timestamp: str = Field(..., description="Response timestamp")


class PortfolioStatsResponse(BaseModel):
    """Portfolio-level statistics."""

    total_aum: float = Field(..., description="Sum of all judgment amounts")
    actionable_liquidity: float = Field(..., description="Sum where collectability_score > 40")
    pipeline_value: float = Field(..., description="Sum of amounts for BUY_CANDIDATE cases")
    offers_outstanding: int = Field(..., description="Count of pending offers")
    total_judgments: int = Field(..., description="Total judgment count")
    actionable_count: int = Field(..., description="Judgments with collectability > 40")
    tier_allocation: list[ScoreTierAllocation] = Field(..., description="Breakdown by score tier")
    top_counties: list[CountyBreakdown] = Field(..., description="Top counties by amount")
    timestamp: str = Field(..., description="Response timestamp")


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/stats",
    response_model=PortfolioStatsResponse,
    summary="Get portfolio statistics",
    description="Returns portfolio-level AUM and financial metrics for the CEO Portfolio page.",
)
async def get_portfolio_stats(
    auth: AuthContext = Depends(get_current_user),
) -> PortfolioStatsResponse:
    """
    Get portfolio-level statistics.

    Returns:
        - Total AUM (sum of all judgment amounts)
        - Actionable Liquidity (sum where score > 40)
        - Pipeline Value (sum of BUY_CANDIDATE cases)
        - Offers Outstanding
        - Tier Allocation breakdown
        - Top counties by amount
    """
    logger.info(f"Portfolio stats requested by {auth.via}")

    try:
        client = get_supabase_client()

        # Fetch all judgments with relevant fields
        result = (
            client.table("judgments")
            .select("id, judgment_amount, collectability_score, county")
            .execute()
        )
        rows: list[dict] = result.data or []  # type: ignore[assignment]

        # Calculate aggregates
        total_aum = 0.0
        actionable_liquidity = 0.0
        pipeline_value = 0.0
        actionable_count = 0
        tier_a_amount = 0.0
        tier_a_count = 0
        tier_b_amount = 0.0
        tier_b_count = 0
        tier_c_amount = 0.0
        tier_c_count = 0
        county_totals: dict[str, dict] = {}

        for row in rows:
            amount = float(row.get("judgment_amount") or 0)
            raw_score = row.get("collectability_score")
            score: Optional[int] = int(raw_score) if raw_score is not None else None
            county = row.get("county") or "Unknown"

            total_aum += amount

            # Actionable if score > 40
            if score is not None and score > 40:
                actionable_liquidity += amount
                actionable_count += 1

            # Pipeline value = BUY_CANDIDATE = score >= 70 AND amount >= 10000
            if score is not None and score >= 70 and amount >= 10000:
                pipeline_value += amount

            # Tier allocation
            if score is None:
                tier_c_amount += amount
                tier_c_count += 1
            elif score >= 80:
                tier_a_amount += amount
                tier_a_count += 1
            elif score >= 50:
                tier_b_amount += amount
                tier_b_count += 1
            else:
                tier_c_amount += amount
                tier_c_count += 1

            # County breakdown
            if county not in county_totals:
                county_totals[county] = {"amount": 0.0, "count": 0}
            county_totals[county]["amount"] += amount
            county_totals[county]["count"] += 1

        # Get offer count (pending status)
        try:
            offers_result = (
                client.table("offers")
                .select("id", count="exact")  # type: ignore[arg-type]
                .eq("status", "offered")
                .execute()
            )
            offers_outstanding = offers_result.count or 0
        except Exception:
            offers_outstanding = 0

        # Sort counties by amount and take top 5
        sorted_counties = sorted(county_totals.items(), key=lambda x: x[1]["amount"], reverse=True)[
            :5
        ]

        top_counties = [
            CountyBreakdown(county=name, amount=round(data["amount"], 2), count=data["count"])
            for name, data in sorted_counties
        ]

        tier_allocation = [
            ScoreTierAllocation(
                tier="A",
                label="Tier A (80+)",
                amount=round(tier_a_amount, 2),
                count=tier_a_count,
                color="#10b981",
            ),
            ScoreTierAllocation(
                tier="B",
                label="Tier B (50-79)",
                amount=round(tier_b_amount, 2),
                count=tier_b_count,
                color="#3b82f6",
            ),
            ScoreTierAllocation(
                tier="C",
                label="Tier C (<50)",
                amount=round(tier_c_amount, 2),
                count=tier_c_count,
                color="#6b7280",
            ),
        ]

        return PortfolioStatsResponse(
            total_aum=round(total_aum, 2),
            actionable_liquidity=round(actionable_liquidity, 2),
            pipeline_value=round(pipeline_value, 2),
            offers_outstanding=offers_outstanding,
            total_judgments=len(rows),
            actionable_count=actionable_count,
            tier_allocation=tier_allocation,
            top_counties=top_counties,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    except Exception as e:
        logger.error(f"Portfolio stats query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query portfolio stats: {e}")


@router.get(
    "/judgments",
    response_model=PortfolioJudgmentsResponse,
    summary="Get paginated portfolio judgments",
    description="Returns paginated judgment data for the Portfolio Explorer grid.",
)
async def get_portfolio_judgments(
    page: int = 1,
    limit: int = 50,
    min_score: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    county: Optional[str] = None,
    auth: AuthContext = Depends(get_current_user),
) -> PortfolioJudgmentsResponse:
    """
    Get paginated portfolio judgments with optional filters.

    Args:
        page: Page number (1-indexed)
        limit: Items per page (max 100)
        min_score: Minimum collectability score filter
        status: Filter by status (exact match)
        search: Search case_number, plaintiff_name, or defendant_name
        county: Filter by county (exact match)

    Returns:
        Paginated list of judgments with totals.
    """
    logger.info(f"Portfolio judgments requested by {auth.via} - page={page}, limit={limit}")

    # Validate and clamp params
    page = max(1, page)
    limit = max(1, min(limit, 100))

    try:
        client = get_supabase_client()

        # Call the RPC function for server-side pagination
        result = client.rpc(
            "portfolio_judgments_paginated",
            {
                "p_page": page,
                "p_limit": limit,
                "p_min_score": min_score,
                "p_status": status,
                "p_search": search,
                "p_county": county,
            },
        ).execute()

        rows: list[dict] = result.data or []  # type: ignore[assignment]

        # Extract totals from first row (all rows have same total_count/total_value)
        total_count = int(rows[0]["total_count"]) if rows else 0
        total_value = float(rows[0]["total_value"]) if rows else 0.0
        total_pages = max(1, (total_count + limit - 1) // limit)

        # Convert to response models
        items = [
            JudgmentRow(
                id=str(row["id"]),
                case_number=row.get("case_number"),
                plaintiff_name=row.get("plaintiff_name", "Unknown"),
                defendant_name=row.get("defendant_name", "Unknown"),
                judgment_amount=float(row.get("judgment_amount") or 0),
                collectability_score=int(row.get("collectability_score") or 0),
                status=row.get("status", "unknown"),
                county=row.get("county", "Unknown"),
                judgment_date=(row["judgment_date"] if row.get("judgment_date") else None),
                tier=row.get("tier", "C"),
                tier_label=row.get("tier_label", "Low Priority"),
            )
            for row in rows
        ]

        return PortfolioJudgmentsResponse(
            items=items,
            total_count=total_count,
            total_value=round(total_value, 2),
            page=page,
            limit=limit,
            total_pages=total_pages,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    except Exception as e:
        logger.error(f"Portfolio judgments query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query portfolio judgments: {e}")
