"""
Dragonfly Engine - Budget Router

Provides endpoints for litigation budget management and approvals.
"""

import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/budget", tags=["Budget"])


# =============================================================================
# Request/Response Models
# =============================================================================


class BudgetApprovalRequest(BaseModel):
    """Request to approve a litigation budget item."""

    case_id: str = Field(..., description="The case ID to approve budget for")
    amount: float = Field(..., gt=0, description="Amount to approve in dollars")
    category: str = Field(
        default="general", description="Budget category (e.g., filing, skip_trace)"
    )
    approver: str | None = Field(default=None, description="Name or ID of the approver")
    notes: str | None = Field(default=None, description="Optional approval notes")


class BudgetApprovalResponse(BaseModel):
    """Response from budget approval request."""

    status: Literal["approved", "rejected", "pending"]
    case_id: str
    amount: float
    message: str
    approval_id: str | None = None
    timestamp: str


class BudgetStatusResponse(BaseModel):
    """Response for budget status query."""

    case_id: str
    status: str
    approved_amount: float | None
    spent_amount: float | None
    remaining_amount: float | None
    last_approval: str | None
    timestamp: str


class BudgetSummaryResponse(BaseModel):
    """Summary of budget allocations."""

    total_approved: float
    total_spent: float
    total_pending: float
    case_count: int
    timestamp: str


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/approve",
    response_model=BudgetApprovalResponse,
    summary="Approve a budget request",
    description="Submit a budget approval for a case. Requires authentication.",
)
async def approve_budget(
    request: BudgetApprovalRequest,
    auth: AuthContext = Depends(get_current_user),
) -> BudgetApprovalResponse:
    """
    Approve a litigation budget item.

    TODO: Implement actual budget approval logic including:
    - Validate case exists
    - Check budget limits and rules
    - Record approval in database
    - Trigger notifications

    Requires authentication.
    """
    logger.info(
        f"Budget approval requested by {auth.via}: "
        f"case_id={request.case_id}, amount=${request.amount}"
    )

    # TODO: Implement actual budget approval logic
    # For now, return a dummy approved response

    return BudgetApprovalResponse(
        status="approved",
        case_id=request.case_id,
        amount=request.amount,
        message="TODO: Implement budget approval logic. Auto-approved for now.",
        approval_id=f"BUD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/status",
    response_model=BudgetStatusResponse,
    summary="Get budget status for a case",
    description="Retrieve current budget status for a specific case.",
)
async def get_budget_status(
    case_id: str = Query(..., description="The case ID to check budget for"),
    auth: AuthContext = Depends(get_current_user),
) -> BudgetStatusResponse:
    """
    Get the budget status for a case.

    TODO: Implement actual budget status lookup including:
    - Query budget allocations table
    - Calculate spent vs remaining
    - Return approval history

    Requires authentication.
    """
    logger.info(f"Budget status requested by {auth.via}: case_id={case_id}")

    # TODO: Implement actual budget status lookup
    # For now, return mock data

    return BudgetStatusResponse(
        case_id=case_id,
        status="active",
        approved_amount=2500.00,
        spent_amount=750.00,
        remaining_amount=1750.00,
        last_approval="2025-12-01T10:30:00Z",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/summary",
    response_model=BudgetSummaryResponse,
    summary="Get overall budget summary",
    description="Get a summary of all budget allocations across cases.",
)
async def get_budget_summary(
    auth: AuthContext = Depends(get_current_user),
) -> BudgetSummaryResponse:
    """
    Get overall budget summary.

    TODO: Implement actual budget summary aggregation.

    Requires authentication.
    """
    logger.info(f"Budget summary requested by {auth.via}")

    # TODO: Implement actual budget summary
    # For now, return mock data

    return BudgetSummaryResponse(
        total_approved=125_000.00,
        total_spent=48_750.00,
        total_pending=15_000.00,
        case_count=47,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.post(
    "/reject",
    response_model=BudgetApprovalResponse,
    summary="Reject a budget request",
    description="Reject a pending budget request. Requires authentication.",
)
async def reject_budget(
    request: BudgetApprovalRequest,
    reason: str = Query(default="", description="Reason for rejection"),
    auth: AuthContext = Depends(get_current_user),
) -> BudgetApprovalResponse:
    """
    Reject a budget request.

    TODO: Implement actual budget rejection logic.

    Requires authentication.
    """
    logger.info(
        f"Budget rejection requested by {auth.via}: case_id={request.case_id}, reason={reason}"
    )

    return BudgetApprovalResponse(
        status="rejected",
        case_id=request.case_id,
        amount=request.amount,
        message=f"TODO: Implement budget rejection. Reason: {reason or 'Not specified'}",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )
