"""
Dragonfly Engine - Finance Router

API endpoints for the Securitization Engine:
- Pool management (create, list, assign judgments)
- Performance tracking
- NAV calculations

All endpoints are prefixed with /v1/finance when mounted.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.finance_service import (
    FinanceServiceError,
    assign_pool,
    calculate_nav,
    create_pool,
    get_pool_performance,
    list_pools,
    record_transaction,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/finance", tags=["finance"])


# =============================================================================
# Request/Response Models
# =============================================================================


class PoolCreateRequest(BaseModel):
    """Request to create a new pool."""

    name: str = Field(..., description="Pool name (e.g., 'Queens 2025-A')")
    target_irr: Optional[float] = Field(None, description="Target IRR (%)")
    management_fee_percent: float = Field(0.015, description="Management fee (default 1.5%)")
    description: Optional[str] = Field(None, description="Pool description")


class PoolResponse(BaseModel):
    """Pool summary response."""

    id: str
    name: str
    target_irr: Optional[float]
    management_fee_percent: float
    status: str
    inception_date: Optional[date]
    judgment_count: int
    total_face_value: float


class PoolAssignRequest(BaseModel):
    """Request to assign judgments to a pool."""

    judgment_ids: list[int] = Field(..., description="Judgment IDs to assign")
    pool_name: str = Field(..., description="Pool name (created if missing)")


class PoolAssignResponse(BaseModel):
    """Response from pool assignment."""

    pool_id: str
    pool_name: str
    requested_count: int
    assigned_count: int
    assigned_ids: list[int]


class PoolPerformanceResponse(BaseModel):
    """Pool performance metrics."""

    pool_id: str
    pool_name: str
    status: str
    inception_date: Optional[date]
    target_irr: Optional[float]
    management_fee_percent: float

    # Judgment counts
    judgment_count: int
    pre_enforcement_count: int
    discovery_count: int
    enforcement_count: int
    collecting_count: int
    closed_count: int

    # Financials
    total_face_value: float
    projected_value: float
    total_collected: float
    total_expenses: float
    total_fees: float
    net_income: float
    current_roi_percent: float
    collection_rate_percent: float
    nav_estimate: float
    days_active: int


class NAVResponse(BaseModel):
    """NAV calculation result."""

    pool_id: str
    pool_name: str
    nav: float
    total_collected: float
    projected_future_value: float
    total_expenses: float
    as_of_date: date


class TransactionRequest(BaseModel):
    """Request to record a transaction."""

    pool_id: str = Field(..., description="Pool UUID")
    txn_type: str = Field(
        ...,
        description="Transaction type: collection, expense, management_fee, write_off, distribution",
    )
    amount: float = Field(..., description="Transaction amount")
    judgment_id: Optional[int] = Field(None, description="Associated judgment ID")
    description: Optional[str] = Field(None, description="Transaction description")


class TransactionResponse(BaseModel):
    """Response from recording a transaction."""

    transaction_id: int
    message: str


# =============================================================================
# Helper Functions
# =============================================================================


def _decimal_to_float(val: Decimal | None) -> float:
    """Convert Decimal to float for JSON serialization."""
    if val is None:
        return 0.0
    return float(val)


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/pools", response_model=list[PoolResponse])
async def get_pools() -> list[PoolResponse]:
    """
    List all pools with summary metrics.

    Returns:
        List of pools with judgment counts and face values
    """
    try:
        pools = await list_pools()
    except FinanceServiceError as e:
        logger.error(f"Failed to list pools: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return [
        PoolResponse(
            id=p.id,
            name=p.name,
            target_irr=_decimal_to_float(p.target_irr),
            management_fee_percent=_decimal_to_float(p.management_fee_percent),
            status=p.status,
            inception_date=p.inception_date,
            judgment_count=p.judgment_count,
            total_face_value=_decimal_to_float(p.total_face_value),
        )
        for p in pools
    ]


@router.post("/pools", response_model=PoolResponse, status_code=201)
async def create_new_pool(request: PoolCreateRequest) -> PoolResponse:
    """
    Create a new pool.

    Args:
        request: Pool creation parameters

    Returns:
        Created pool details
    """
    try:
        pool = await create_pool(
            name=request.name,
            target_irr=request.target_irr,
            management_fee_percent=request.management_fee_percent,
            description=request.description,
        )
    except FinanceServiceError as e:
        if "already exists" in str(e):
            raise HTTPException(status_code=409, detail=str(e)) from e
        logger.error(f"Failed to create pool: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return PoolResponse(
        id=pool.id,
        name=pool.name,
        target_irr=_decimal_to_float(pool.target_irr),
        management_fee_percent=_decimal_to_float(pool.management_fee_percent),
        status=pool.status,
        inception_date=pool.inception_date,
        judgment_count=pool.judgment_count,
        total_face_value=_decimal_to_float(pool.total_face_value),
    )


@router.post("/pools/assign", response_model=PoolAssignResponse)
async def assign_judgments_to_pool(request: PoolAssignRequest) -> PoolAssignResponse:
    """
    Assign judgments to a pool.

    Creates the pool if it doesn't exist.

    Args:
        request: Judgment IDs and pool name

    Returns:
        Assignment results
    """
    try:
        result = await assign_pool(
            judgment_ids=request.judgment_ids,
            pool_name=request.pool_name,
            create_if_missing=True,
        )
    except FinanceServiceError as e:
        logger.error(f"Failed to assign judgments: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return PoolAssignResponse(**result)


@router.get("/pools/performance", response_model=list[PoolPerformanceResponse])
async def get_pools_performance() -> list[PoolPerformanceResponse]:
    """
    Get performance metrics for all pools.

    Includes:
    - Judgment counts by stage
    - Financial metrics (collected, expenses, fees)
    - ROI and collection rate calculations
    - NAV estimates

    Returns:
        List of pool performance metrics
    """
    try:
        performance = await get_pool_performance()
    except FinanceServiceError as e:
        logger.error(f"Failed to get pool performance: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return [
        PoolPerformanceResponse(
            pool_id=p.pool_id,
            pool_name=p.pool_name,
            status=p.status,
            inception_date=p.inception_date,
            target_irr=_decimal_to_float(p.target_irr),
            management_fee_percent=_decimal_to_float(p.management_fee_percent),
            judgment_count=p.judgment_count,
            pre_enforcement_count=p.pre_enforcement_count,
            discovery_count=p.discovery_count,
            enforcement_count=p.enforcement_count,
            collecting_count=p.collecting_count,
            closed_count=p.closed_count,
            total_face_value=_decimal_to_float(p.total_face_value),
            projected_value=_decimal_to_float(p.projected_value),
            total_collected=_decimal_to_float(p.total_collected),
            total_expenses=_decimal_to_float(p.total_expenses),
            total_fees=_decimal_to_float(p.total_fees),
            net_income=_decimal_to_float(p.net_income),
            current_roi_percent=_decimal_to_float(p.current_roi_percent),
            collection_rate_percent=_decimal_to_float(p.collection_rate_percent),
            nav_estimate=_decimal_to_float(p.nav_estimate),
            days_active=p.days_active,
        )
        for p in performance
    ]


@router.get("/pools/{pool_id}/nav", response_model=NAVResponse)
async def get_pool_nav(pool_id: str) -> NAVResponse:
    """
    Calculate Net Asset Value for a pool.

    NAV = Total Collected + Projected Future Value - Total Expenses

    Args:
        pool_id: Pool UUID

    Returns:
        NAV calculation result
    """
    try:
        result = await calculate_nav(pool_id)
    except FinanceServiceError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e)) from e
        logger.error(f"Failed to calculate NAV: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return NAVResponse(
        pool_id=result.pool_id,
        pool_name=result.pool_name,
        nav=_decimal_to_float(result.nav),
        total_collected=_decimal_to_float(result.total_collected),
        projected_future_value=_decimal_to_float(result.projected_future_value),
        total_expenses=_decimal_to_float(result.total_expenses),
        as_of_date=result.as_of_date,
    )


@router.post("/transactions", response_model=TransactionResponse, status_code=201)
async def create_transaction(request: TransactionRequest) -> TransactionResponse:
    """
    Record a financial transaction for a pool.

    Transaction types:
    - collection: Cash received from debtor
    - expense: Operating cost (skip trace, service, etc.)
    - management_fee: Fee charged to pool
    - write_off: Written off judgment
    - distribution: Paid out to investors

    Args:
        request: Transaction details

    Returns:
        Created transaction ID
    """
    try:
        txn_id = await record_transaction(
            pool_id=request.pool_id,
            txn_type=request.txn_type,
            amount=request.amount,
            judgment_id=request.judgment_id,
            description=request.description,
        )
    except FinanceServiceError as e:
        if "invalid transaction type" in str(e).lower():
            raise HTTPException(status_code=400, detail=str(e)) from e
        logger.error(f"Failed to record transaction: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

    return TransactionResponse(
        transaction_id=txn_id,
        message=f"Transaction recorded: {request.txn_type} ${request.amount:,.2f}",
    )
