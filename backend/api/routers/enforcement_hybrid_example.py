"""
Dragonfly Engine - Enforcement Radar Example (HybridDataLayer Integration)

This file shows how to migrate an existing router endpoint from the Supabase
client to the HybridDataLayer pattern. The HybridDataLayer:

  1. Tries PostgREST first (fast, cached)
  2. On PGRST002/503 errors, fires NOTIFY pgrst to heal the cache
  3. Falls back to Direct SQL so the user never sees a crash

BEFORE (fragile):
    client = get_supabase_client()
    result = client.rpc("enforcement_radar_filtered", {...}).execute()
    # ☠️ If PostgREST returns PGRST002, the endpoint crashes

AFTER (resilient):
    data_layer = get_data_layer()
    result = await data_layer.call_rpc(
        rpc_name="enforcement_radar_filtered",
        params={...},
        fallback_sql=RADAR_FALLBACK_SQL,
        fallback_params={...},
    )
    # ✅ If PostgREST fails, we heal + fallback to direct SQL seamlessly
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ...core.security import AuthContext, get_current_user
from ...services.data_layer import get_data_layer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/enforcement-hybrid", tags=["Enforcement (Hybrid)"])


# =============================================================================
# Response Models (unchanged from original)
# =============================================================================


class RadarRow(BaseModel):
    """Single row in the enforcement radar."""

    id: str
    case_number: str
    plaintiff_name: str
    defendant_name: str
    judgment_amount: float
    collectability_score: int | None = None
    offer_strategy: str
    court: str | None = None
    county: str | None = None
    judgment_date: str | None = None
    created_at: str
    has_employer: bool = False
    has_bank: bool = False


# =============================================================================
# Fallback SQL
# =============================================================================

# This SQL mirrors the logic in the enforcement_radar_filtered RPC.
# When PostgREST is flaky, we run this directly against the database.
RADAR_FALLBACK_SQL = """
SELECT
    j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    COALESCE(j.judgment_amount, 0) AS judgment_amount,
    j.collectability_score,
    CASE
        WHEN j.collectability_score >= 80 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 50 THEN 'CONTINGENCY'
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    j.court,
    j.county,
    j.judgment_date::text,
    j.created_at::text,
    COALESCE(di.employer_name IS NOT NULL, FALSE) AS has_employer,
    COALESCE(di.bank_name IS NOT NULL, FALSE) AS has_bank
FROM public.judgments j
LEFT JOIN public.debtor_intelligence di ON di.judgment_id = j.id
WHERE
    (%(p_min_score)s IS NULL OR j.collectability_score >= %(p_min_score)s)
    AND (%(p_min_amount)s IS NULL OR j.judgment_amount >= %(p_min_amount)s)
    AND (%(p_only_employed)s = FALSE OR di.employer_name IS NOT NULL)
    AND (%(p_only_bank_assets)s = FALSE OR di.bank_name IS NOT NULL)
    AND (%(p_strategy)s IS NULL OR
         CASE
             WHEN j.collectability_score >= 80 THEN 'BUY_CANDIDATE'
             WHEN j.collectability_score >= 50 THEN 'CONTINGENCY'
             WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
             ELSE 'LOW_PRIORITY'
         END = %(p_strategy)s)
ORDER BY j.collectability_score DESC NULLS LAST, j.judgment_amount DESC
LIMIT %(p_limit)s
"""


# =============================================================================
# Hybrid Endpoint
# =============================================================================


@router.get(
    "/radar",
    response_model=list[RadarRow],
    summary="Get Enforcement Radar (Hybrid)",
    description="Returns prioritized list of judgments for enforcement action. "
    "Uses PostgREST-first with automatic fallback to direct SQL.",
)
async def get_enforcement_radar_hybrid(
    strategy: Optional[str] = Query(
        None, description="Filter by offer strategy (BUY_CANDIDATE, CONTINGENCY, etc.)"
    ),
    min_score: Optional[int] = Query(
        None, ge=0, le=100, description="Minimum collectability score"
    ),
    min_amount: Optional[float] = Query(None, ge=0, description="Minimum judgment amount"),
    only_employed: bool = Query(False, description="Only show judgments with employer intel"),
    only_bank_assets: bool = Query(False, description="Only show judgments with bank intel"),
    auth: AuthContext = Depends(get_current_user),
) -> list[RadarRow]:
    """
    Get the Enforcement Radar – prioritized list of judgments for CEO review.

    This version uses HybridDataLayer for resilience:
      - Primary: PostgREST RPC (fast, cached)
      - Fallback: Direct SQL (reliable, always works)
      - Healing: NOTIFY pgrst on PGRST002 errors
    """
    logger.info(
        f"Enforcement radar (hybrid) requested by {auth.via}: "
        f"strategy={strategy}, min_score={min_score}, min_amount={min_amount}"
    )

    # Build params for both RPC and SQL fallback
    rpc_params = {
        "p_min_score": min_score,
        "p_only_employed": only_employed,
        "p_only_bank_assets": only_bank_assets,
        "p_min_amount": min_amount,
        "p_strategy": strategy,
        "p_limit": 500,
    }

    try:
        data_layer = get_data_layer()

        # =====================================================================
        # KEY CHANGE: Use HybridDataLayer instead of direct Supabase client
        # =====================================================================
        result = await data_layer.call_rpc(
            function_name="enforcement_radar_filtered",
            params=rpc_params,
            fallback_sql=RADAR_FALLBACK_SQL,
        )

        # Log the source (rest vs direct) for observability
        logger.info(
            f"Radar data source={result.source}, "
            f"latency={result.latency_ms}ms, "
            f"cache_reload_triggered={result.cache_reload_triggered}"
        )

        # If there was an error and no data, raise
        if result.error and not result.data:
            raise HTTPException(
                status_code=500,
                detail=f"Radar query failed: {result.error}",
            )

        rows: list[dict] = result.data or []

        # Transform to response model
        radar_rows: list[RadarRow] = []
        for row in rows:
            raw_score = row.get("collectability_score")
            score: int | None = int(raw_score) if raw_score is not None else None

            radar_rows.append(
                RadarRow(
                    id=str(row.get("id", "")),
                    case_number=str(row.get("case_number") or ""),
                    plaintiff_name=str(row.get("plaintiff_name") or ""),
                    defendant_name=str(row.get("defendant_name") or ""),
                    judgment_amount=float(row.get("judgment_amount") or 0),
                    collectability_score=score,
                    offer_strategy=str(row.get("offer_strategy") or "ENRICHMENT_PENDING"),
                    court=row.get("court"),
                    county=row.get("county"),
                    judgment_date=row.get("judgment_date"),
                    created_at=str(row.get("created_at") or datetime.utcnow().isoformat()),
                    has_employer=bool(row.get("has_employer", False)),
                    has_bank=bool(row.get("has_bank", False)),
                )
            )

        logger.info(f"Radar returning {len(radar_rows)} rows via {result.source}")
        return radar_rows

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        logger.error(f"Enforcement radar query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query radar: {e}")


# =============================================================================
# Example: View Fetch (Simpler Pattern)
# =============================================================================


class PlaintiffOverviewRow(BaseModel):
    """Single row from v_plaintiffs_overview."""

    plaintiff_id: str
    plaintiff_name: str
    total_judgments: int
    total_judgment_value: float
    active_cases: int
    status: str


@router.get(
    "/plaintiffs-overview",
    response_model=list[PlaintiffOverviewRow],
    summary="Get Plaintiffs Overview (Hybrid)",
    description="Returns summary of all plaintiffs from v_plaintiffs_overview.",
)
async def get_plaintiffs_overview_hybrid(
    auth: AuthContext = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500),
) -> list[PlaintiffOverviewRow]:
    """
    Fetch plaintiffs overview using HybridDataLayer.

    This is a simpler pattern - just fetch a view with automatic fallback.
    """
    logger.info(f"Plaintiffs overview (hybrid) requested by {auth.via}")

    data_layer = get_data_layer()

    # Simple view fetch - no SQL fallback needed for canonical views
    result = await data_layer.fetch_view(
        view_name="v_plaintiffs_overview",
        limit=limit,
        order="total_judgment_value.desc",
    )

    logger.info(
        f"Plaintiffs overview: source={result.source}, "
        f"latency={result.latency_ms}ms, rows={len(result.data or [])}"
    )

    if result.error and not result.data:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch plaintiffs overview: {result.error}",
        )

    rows = result.data or []
    return [
        PlaintiffOverviewRow(
            plaintiff_id=str(row.get("plaintiff_id", "")),
            plaintiff_name=str(row.get("plaintiff_name", "")),
            total_judgments=int(row.get("total_judgments", 0)),
            total_judgment_value=float(row.get("total_judgment_value", 0)),
            active_cases=int(row.get("active_cases", 0)),
            status=str(row.get("status", "unknown")),
        )
        for row in rows
    ]
