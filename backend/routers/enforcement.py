"""
Dragonfly Engine - Enforcement Router

Provides endpoints for enforcement workflow management including the Radar.
"""

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user
from ..db import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/enforcement", tags=["Enforcement"])


# =============================================================================
# Radar Models
# =============================================================================


class RadarRow(BaseModel):
    """Single row in the Enforcement Radar."""

    id: str = Field(..., description="Judgment ID")
    case_number: str = Field(..., description="Court case number")
    plaintiff_name: str = Field(..., description="Plaintiff name")
    defendant_name: str = Field(..., description="Defendant name")
    judgment_amount: float = Field(..., description="Judgment amount in dollars")
    collectability_score: Optional[int] = Field(
        None, description="Collectability score 0-100"
    )
    offer_strategy: str = Field(
        ..., description="BUY_CANDIDATE, CONTINGENCY, ENRICHMENT_PENDING, LOW_PRIORITY"
    )
    court: Optional[str] = Field(None, description="Court name")
    county: Optional[str] = Field(None, description="County")
    judgment_date: Optional[str] = Field(None, description="Judgment date ISO string")
    created_at: str = Field(..., description="Record creation timestamp")


# =============================================================================
# Request/Response Models
# =============================================================================


class EnforcementStartRequest(BaseModel):
    """Request to start an enforcement action."""

    case_id: str = Field(..., description="The case ID to start enforcement for")
    strategy: str | None = Field(
        default=None,
        description="Enforcement strategy (e.g., wage_garnishment, bank_levy)",
    )
    priority: Literal["low", "normal", "high", "urgent"] = Field(
        default="normal", description="Priority level for the enforcement action"
    )
    notes: str | None = Field(
        default=None, description="Optional notes for the enforcement team"
    )


class EnforcementStartResponse(BaseModel):
    """Response from enforcement start request."""

    status: Literal["queued", "started", "rejected", "error"]
    case_id: str
    message: str
    enforcement_id: str | None = None
    estimated_start: str | None = None
    timestamp: str


class EnforcementStatusResponse(BaseModel):
    """Response for enforcement status query."""

    case_id: str
    enforcement_id: str | None
    status: str
    strategy: str | None
    started_at: str | None
    last_update: str | None
    next_action: str | None
    amount_recovered: float | None
    timestamp: str


class EnforcementAction(BaseModel):
    """Details of an enforcement action."""

    action_id: str
    case_id: str
    action_type: str
    status: str
    created_at: str
    completed_at: str | None
    result: str | None
    amount: float | None


class EnforcementHistoryResponse(BaseModel):
    """Response for enforcement history query."""

    case_id: str
    actions: list[EnforcementAction]
    total_recovered: float
    timestamp: str


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/start",
    response_model=EnforcementStartResponse,
    summary="Start enforcement workflow",
    description="Queue a case for enforcement action. Requires authentication.",
)
async def start_enforcement(
    request: EnforcementStartRequest,
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStartResponse:
    """
    Start an enforcement workflow for a case.

    TODO: Implement actual enforcement workflow start including:
    - Validate case is ready for enforcement
    - Check debtor information is complete
    - Queue appropriate enforcement actions
    - Notify enforcement team

    Requires authentication.
    """
    logger.info(
        f"Enforcement start requested by {auth.via}: "
        f"case_id={request.case_id}, strategy={request.strategy}"
    )

    # TODO: Implement actual enforcement workflow
    # For now, return a dummy queued response

    return EnforcementStartResponse(
        status="queued",
        case_id=request.case_id,
        message="TODO: Implement enforcement workflow start. Case queued for processing.",
        enforcement_id=f"ENF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        estimated_start=datetime.utcnow().isoformat() + "Z",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/status",
    response_model=EnforcementStatusResponse,
    summary="Get enforcement status",
    description="Get the current enforcement status for a case.",
)
async def get_enforcement_status(
    case_id: str = Query(..., description="The case ID to check enforcement for"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStatusResponse:
    """
    Get the enforcement status for a case.

    TODO: Implement actual enforcement status lookup including:
    - Query enforcement actions table
    - Get current stage and progress
    - Return recovery amounts

    Requires authentication.
    """
    logger.info(f"Enforcement status requested by {auth.via}: case_id={case_id}")

    # TODO: Implement actual enforcement status lookup
    # For now, return mock data

    return EnforcementStatusResponse(
        case_id=case_id,
        enforcement_id="ENF-20251203120000",
        status="in_progress",
        strategy="wage_garnishment",
        started_at="2025-11-15T09:00:00Z",
        last_update="2025-12-02T14:30:00Z",
        next_action="Await employer response",
        amount_recovered=1250.00,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/history",
    response_model=EnforcementHistoryResponse,
    summary="Get enforcement history",
    description="Get the full enforcement history for a case.",
)
async def get_enforcement_history(
    case_id: str = Query(..., description="The case ID to get history for"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementHistoryResponse:
    """
    Get the enforcement action history for a case.

    TODO: Implement actual enforcement history lookup.

    Requires authentication.
    """
    logger.info(f"Enforcement history requested by {auth.via}: case_id={case_id}")

    # TODO: Implement actual enforcement history lookup
    # For now, return mock data

    return EnforcementHistoryResponse(
        case_id=case_id,
        actions=[
            EnforcementAction(
                action_id="ACT-001",
                case_id=case_id,
                action_type="wage_garnishment",
                status="active",
                created_at="2025-11-15T09:00:00Z",
                completed_at=None,
                result=None,
                amount=1250.00,
            ),
            EnforcementAction(
                action_id="ACT-002",
                case_id=case_id,
                action_type="skip_trace",
                status="completed",
                created_at="2025-11-10T10:00:00Z",
                completed_at="2025-11-12T15:30:00Z",
                result="success",
                amount=None,
            ),
        ],
        total_recovered=1250.00,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.post(
    "/stop",
    response_model=EnforcementStartResponse,
    summary="Stop enforcement workflow",
    description="Stop an active enforcement action. Requires authentication.",
)
async def stop_enforcement(
    case_id: str = Query(..., description="The case ID to stop enforcement for"),
    reason: str = Query(default="", description="Reason for stopping"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStartResponse:
    """
    Stop an active enforcement workflow.

    TODO: Implement actual enforcement stop logic.

    Requires authentication.
    """
    logger.info(
        f"Enforcement stop requested by {auth.via}: case_id={case_id}, reason={reason}"
    )

    return EnforcementStartResponse(
        status="queued",
        case_id=case_id,
        message=f"TODO: Implement enforcement stop. Reason: {reason or 'Not specified'}",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


# =============================================================================
# Radar Endpoint
# =============================================================================


def _compute_offer_strategy(score: int | None, amount: float) -> str:
    """
    Compute offer strategy based on collectability score and judgment amount.

    Logic:
      - score is None → ENRICHMENT_PENDING
      - score >= 70 AND amount >= 10000 → BUY_CANDIDATE
      - score >= 40 OR amount >= 5000 → CONTINGENCY
      - else → LOW_PRIORITY
    """
    if score is None:
        return "ENRICHMENT_PENDING"
    if score >= 70 and amount >= 10000:
        return "BUY_CANDIDATE"
    if score >= 40 or amount >= 5000:
        return "CONTINGENCY"
    return "LOW_PRIORITY"


@router.get(
    "/radar",
    response_model=list[RadarRow],
    summary="Get Enforcement Radar",
    description="Returns prioritized list of judgments for enforcement action.",
)
async def get_enforcement_radar(
    strategy: Optional[str] = Query(
        None, description="Filter by offer strategy (BUY_CANDIDATE, CONTINGENCY, etc.)"
    ),
    min_score: Optional[int] = Query(
        None, ge=0, le=100, description="Minimum collectability score"
    ),
    min_amount: Optional[float] = Query(
        None, ge=0, description="Minimum judgment amount"
    ),
    auth: AuthContext = Depends(get_current_user),
) -> list[RadarRow]:
    """
    Get the Enforcement Radar – prioritized list of judgments for CEO review.

    Returns judgments sorted by collectability score and amount, with computed
    offer strategies (BUY_CANDIDATE, CONTINGENCY, ENRICHMENT_PENDING, LOW_PRIORITY).
    """
    logger.info(
        f"Enforcement radar requested by {auth.via}: "
        f"strategy={strategy}, min_score={min_score}, min_amount={min_amount}"
    )

    try:
        client = get_supabase_client()

        # Query judgments table with relevant fields
        query = client.table("judgments").select(
            "id, case_number, plaintiff_name, defendant_name, judgment_amount, "
            "collectability_score, court, county, judgment_date, created_at"
        )

        # Apply score filter if provided
        if min_score is not None:
            query = query.gte("collectability_score", min_score)

        # Apply amount filter if provided
        if min_amount is not None:
            query = query.gte("judgment_amount", min_amount)

        # Order by collectability score descending, then amount
        query = query.order("collectability_score", desc=True, nullsfirst=False)
        query = query.order("judgment_amount", desc=True)

        # Limit to top 500 for performance
        query = query.limit(500)

        result = query.execute()
        rows: list[dict] = result.data or []  # type: ignore[assignment]

        radar_rows: list[RadarRow] = []
        for row in rows:
            raw_score = row.get("collectability_score")
            score: int | None = int(raw_score) if raw_score is not None else None
            amount = float(row.get("judgment_amount") or 0)
            computed_strategy = _compute_offer_strategy(score, amount)

            # Apply strategy filter after computation
            if strategy and strategy != "ALL" and computed_strategy != strategy:
                continue

            radar_rows.append(
                RadarRow(
                    id=str(row.get("id", "")),
                    case_number=str(row.get("case_number") or ""),
                    plaintiff_name=str(row.get("plaintiff_name") or ""),
                    defendant_name=str(row.get("defendant_name") or ""),
                    judgment_amount=amount,
                    collectability_score=score,
                    offer_strategy=computed_strategy,
                    court=row.get("court"),
                    county=row.get("county"),
                    judgment_date=row.get("judgment_date"),
                    created_at=str(
                        row.get("created_at") or datetime.utcnow().isoformat()
                    ),
                )
            )

        logger.info(f"Radar returning {len(radar_rows)} rows")
        return radar_rows

    except Exception as e:
        logger.error(f"Enforcement radar query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query radar: {e}")
