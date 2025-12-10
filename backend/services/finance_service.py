"""
Dragonfly Engine - Finance Service

Securitization engine for managing judgment pools and calculating NAV.

Pools group individual judgments into fund-like structures with:
- Target IRR and management fee parameters
- Aggregate performance tracking
- NAV (Net Asset Value) calculations

Depends on:
- finance.pools table
- finance.pool_transactions table
- finance.v_pool_performance view
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from backend.db import get_pool

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class Pool:
    """Pool entity from finance.pools."""

    id: str
    name: str
    target_irr: Optional[Decimal]
    management_fee_percent: Decimal
    status: str
    inception_date: Optional[date]
    judgment_count: int = 0
    total_face_value: Decimal = Decimal("0")


@dataclass
class PoolPerformance:
    """Pool performance metrics from v_pool_performance."""

    pool_id: str
    pool_name: str
    status: str
    inception_date: Optional[date]
    target_irr: Optional[Decimal]
    management_fee_percent: Decimal

    # Judgment counts
    judgment_count: int
    pre_enforcement_count: int
    discovery_count: int
    enforcement_count: int
    collecting_count: int
    closed_count: int

    # Financials
    total_face_value: Decimal
    projected_value: Decimal
    total_collected: Decimal
    total_expenses: Decimal
    total_fees: Decimal
    total_distributions: Decimal
    total_write_offs: Decimal
    net_income: Decimal
    current_roi_percent: Decimal
    collection_rate_percent: Decimal
    nav_estimate: Decimal
    days_active: int


@dataclass
class NAVResult:
    """NAV calculation result."""

    pool_id: str
    pool_name: str
    nav: Decimal
    total_collected: Decimal
    projected_future_value: Decimal
    total_expenses: Decimal
    as_of_date: date


# =============================================================================
# Exceptions
# =============================================================================


class FinanceServiceError(Exception):
    """Raised when finance operations fail."""

    pass


# =============================================================================
# Pool Management
# =============================================================================


async def list_pools() -> list[Pool]:
    """
    List all pools.

    Returns:
        List of Pool objects
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    query = """
        SELECT
            p.id,
            p.name,
            p.target_irr,
            p.management_fee_percent,
            p.status,
            p.inception_date,
            COUNT(j.id) AS judgment_count,
            COALESCE(SUM(j.judgment_amount), 0) AS total_face_value
        FROM finance.pools p
        LEFT JOIN public.judgments j ON j.pool_id = p.id
        GROUP BY p.id, p.name, p.target_irr, p.management_fee_percent, p.status, p.inception_date
        ORDER BY p.name
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query)
            rows = await cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to list pools: {e}")
        raise FinanceServiceError(f"Failed to list pools: {e}") from e

    pools = []
    for row in rows:
        pools.append(
            Pool(
                id=str(row[0]),
                name=row[1],
                target_irr=row[2],
                management_fee_percent=row[3] or Decimal("0.015"),
                status=row[4],
                inception_date=row[5],
                judgment_count=row[6],
                total_face_value=row[7] or Decimal("0"),
            )
        )

    return pools


async def get_pool_by_name(pool_name: str) -> Optional[Pool]:
    """
    Get a pool by name.

    Args:
        pool_name: The pool name to find

    Returns:
        Pool object or None if not found
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    query = """
        SELECT
            p.id,
            p.name,
            p.target_irr,
            p.management_fee_percent,
            p.status,
            p.inception_date,
            COUNT(j.id) AS judgment_count,
            COALESCE(SUM(j.judgment_amount), 0) AS total_face_value
        FROM finance.pools p
        LEFT JOIN public.judgments j ON j.pool_id = p.id
        WHERE p.name = %s
        GROUP BY p.id, p.name, p.target_irr, p.management_fee_percent, p.status, p.inception_date
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query, (pool_name,))
            row = await cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to get pool {pool_name}: {e}")
        raise FinanceServiceError(f"Failed to get pool: {e}") from e

    if row is None:
        return None

    return Pool(
        id=str(row[0]),
        name=row[1],
        target_irr=row[2],
        management_fee_percent=row[3] or Decimal("0.015"),
        status=row[4],
        inception_date=row[5],
        judgment_count=row[6],
        total_face_value=row[7] or Decimal("0"),
    )


async def create_pool(
    name: str,
    target_irr: Optional[float] = None,
    management_fee_percent: float = 0.015,
    description: Optional[str] = None,
) -> Pool:
    """
    Create a new pool.

    Args:
        name: Pool name (e.g., 'Queens 2025-A')
        target_irr: Target internal rate of return (%)
        management_fee_percent: Management fee (default 1.5%)
        description: Optional description

    Returns:
        Created Pool object

    Raises:
        FinanceServiceError: If creation fails
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    query = """
        INSERT INTO finance.pools (name, target_irr, management_fee_percent, description)
        VALUES (%s, %s, %s, %s)
        RETURNING id, name, target_irr, management_fee_percent, status, inception_date
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query, (name, target_irr, management_fee_percent, description))
            row = await cur.fetchone()
    except Exception as e:
        if "unique" in str(e).lower():
            raise FinanceServiceError(f"Pool '{name}' already exists") from e
        logger.error(f"Failed to create pool {name}: {e}")
        raise FinanceServiceError(f"Failed to create pool: {e}") from e

    if row is None:
        raise FinanceServiceError("Pool creation returned no data")

    logger.info(f"Created pool: {name} (id={row[0]})")

    return Pool(
        id=str(row[0]),
        name=row[1],
        target_irr=row[2],
        management_fee_percent=row[3] or Decimal("0.015"),
        status=row[4],
        inception_date=row[5],
        judgment_count=0,
        total_face_value=Decimal("0"),
    )


async def assign_pool(
    judgment_ids: list[int],
    pool_name: str,
    create_if_missing: bool = True,
) -> dict:
    """
    Assign judgments to a pool.

    Creates the pool if it doesn't exist (when create_if_missing=True).

    Args:
        judgment_ids: List of judgment IDs to assign
        pool_name: Name of the pool
        create_if_missing: Create pool if it doesn't exist

    Returns:
        Dict with pool info and assignment results

    Raises:
        FinanceServiceError: If assignment fails
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    # Get or create pool
    pool = await get_pool_by_name(pool_name)

    if pool is None:
        if create_if_missing:
            pool = await create_pool(name=pool_name)
            logger.info(f"Created new pool: {pool_name}")
        else:
            raise FinanceServiceError(f"Pool '{pool_name}' does not exist")

    # Assign judgments
    query = """
        UPDATE public.judgments
        SET pool_id = %s::uuid, updated_at = NOW()
        WHERE id = ANY(%s)
        RETURNING id
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query, (pool.id, judgment_ids))
            updated_rows = await cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to assign judgments to pool {pool_name}: {e}")
        raise FinanceServiceError(f"Failed to assign judgments: {e}") from e

    assigned_count = len(updated_rows)
    assigned_ids = [row[0] for row in updated_rows]

    logger.info(f"Assigned {assigned_count}/{len(judgment_ids)} judgments to pool {pool_name}")

    return {
        "pool_id": pool.id,
        "pool_name": pool.name,
        "requested_count": len(judgment_ids),
        "assigned_count": assigned_count,
        "assigned_ids": assigned_ids,
    }


# =============================================================================
# Performance Tracking
# =============================================================================


async def get_pool_performance() -> list[PoolPerformance]:
    """
    Get performance metrics for all pools.

    Returns:
        List of PoolPerformance objects
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    query = """
        SELECT
            pool_id,
            pool_name,
            status,
            inception_date,
            target_irr,
            management_fee_percent,
            judgment_count,
            pre_enforcement_count,
            discovery_count,
            enforcement_count,
            collecting_count,
            closed_count,
            total_face_value,
            projected_value,
            total_collected,
            total_expenses,
            total_fees,
            total_distributions,
            total_write_offs,
            net_income,
            current_roi_percent,
            collection_rate_percent,
            nav_estimate,
            days_active
        FROM finance.v_pool_performance
        ORDER BY pool_name
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query)
            rows = await cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to get pool performance: {e}")
        raise FinanceServiceError(f"Failed to get pool performance: {e}") from e

    results = []
    for row in rows:
        results.append(
            PoolPerformance(
                pool_id=str(row[0]),
                pool_name=row[1],
                status=row[2],
                inception_date=row[3],
                target_irr=row[4],
                management_fee_percent=row[5] or Decimal("0.015"),
                judgment_count=row[6] or 0,
                pre_enforcement_count=row[7] or 0,
                discovery_count=row[8] or 0,
                enforcement_count=row[9] or 0,
                collecting_count=row[10] or 0,
                closed_count=row[11] or 0,
                total_face_value=row[12] or Decimal("0"),
                projected_value=row[13] or Decimal("0"),
                total_collected=row[14] or Decimal("0"),
                total_expenses=row[15] or Decimal("0"),
                total_fees=row[16] or Decimal("0"),
                total_distributions=row[17] or Decimal("0"),
                total_write_offs=row[18] or Decimal("0"),
                net_income=row[19] or Decimal("0"),
                current_roi_percent=row[20] or Decimal("0"),
                collection_rate_percent=row[21] or Decimal("0"),
                nav_estimate=row[22] or Decimal("0"),
                days_active=row[23] or 0,
            )
        )

    return results


# =============================================================================
# NAV Calculation
# =============================================================================


async def calculate_nav(pool_id: str) -> NAVResult:
    """
    Calculate Net Asset Value for a pool.

    NAV = Total Collected + Projected Future Value - Total Expenses

    Projected Future Value is estimated based on:
    - Active garnishments (collecting stage): 50% of face value
    - Enforcement stage: 30% of face value
    - Discovery stage: 20% of face value
    - Pre-enforcement: 15% of face value

    Args:
        pool_id: UUID of the pool

    Returns:
        NAVResult with calculated values

    Raises:
        FinanceServiceError: If calculation fails
    """
    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    # Get pool name
    pool_query = "SELECT name FROM finance.pools WHERE id = %s::uuid"

    # Get financials from transactions
    txn_query = """
        SELECT
            COALESCE(SUM(CASE WHEN txn_type = 'collection' THEN amount ELSE 0 END), 0) AS total_collected,
            COALESCE(SUM(CASE WHEN txn_type = 'expense' THEN amount ELSE 0 END), 0) AS total_expenses,
            COALESCE(SUM(CASE WHEN txn_type = 'management_fee' THEN amount ELSE 0 END), 0) AS total_fees
        FROM finance.pool_transactions
        WHERE pool_id = %s::uuid
    """

    # Get projected value from judgments
    projected_query = """
        SELECT
            COALESCE(SUM(
                CASE
                    WHEN enforcement_stage = 'collecting' THEN judgment_amount * 0.5
                    WHEN enforcement_stage = 'enforcement' THEN judgment_amount * 0.3
                    WHEN enforcement_stage = 'discovery' THEN judgment_amount * 0.2
                    ELSE judgment_amount * 0.15
                END
            ), 0) AS projected_value
        FROM public.judgments
        WHERE pool_id = %s::uuid
          AND enforcement_stage != 'closed'
    """

    try:
        async with conn.cursor() as cur:
            # Get pool name
            await cur.execute(pool_query, (pool_id,))
            pool_row = await cur.fetchone()
            if pool_row is None:
                raise FinanceServiceError(f"Pool {pool_id} not found")
            pool_name = pool_row[0]

            # Get financials
            await cur.execute(txn_query, (pool_id,))
            txn_row = await cur.fetchone()
            total_collected = txn_row[0] if txn_row else Decimal("0")
            total_expenses = (txn_row[1] if txn_row else Decimal("0")) + (
                txn_row[2] if txn_row else Decimal("0")
            )

            # Get projected value
            await cur.execute(projected_query, (pool_id,))
            proj_row = await cur.fetchone()
            projected_future_value = proj_row[0] if proj_row else Decimal("0")

    except FinanceServiceError:
        raise
    except Exception as e:
        logger.error(f"Failed to calculate NAV for pool {pool_id}: {e}")
        raise FinanceServiceError(f"Failed to calculate NAV: {e}") from e

    # NAV = collected + projected - expenses
    nav = total_collected + projected_future_value - total_expenses

    logger.info(f"Calculated NAV for {pool_name}: ${nav:,.2f}")

    return NAVResult(
        pool_id=pool_id,
        pool_name=pool_name,
        nav=nav,
        total_collected=total_collected,
        projected_future_value=projected_future_value,
        total_expenses=total_expenses,
        as_of_date=date.today(),
    )


# =============================================================================
# Transaction Recording
# =============================================================================


async def record_transaction(
    pool_id: str,
    txn_type: str,
    amount: float,
    judgment_id: Optional[int] = None,
    description: Optional[str] = None,
) -> int:
    """
    Record a financial transaction for a pool.

    Args:
        pool_id: Pool UUID
        txn_type: Transaction type (collection, expense, management_fee, write_off, distribution)
        amount: Transaction amount
        judgment_id: Optional associated judgment
        description: Optional description

    Returns:
        Transaction ID

    Raises:
        FinanceServiceError: If recording fails
    """
    valid_types = {
        "collection",
        "expense",
        "management_fee",
        "write_off",
        "distribution",
    }
    if txn_type not in valid_types:
        raise FinanceServiceError(
            f"Invalid transaction type: {txn_type}. Must be one of {valid_types}"
        )

    conn = await get_pool()
    if conn is None:
        raise FinanceServiceError("Database connection not available")

    query = """
        INSERT INTO finance.pool_transactions (pool_id, judgment_id, txn_type, amount, description)
        VALUES (%s::uuid, %s, %s, %s, %s)
        RETURNING id
    """

    try:
        async with conn.cursor() as cur:
            await cur.execute(query, (pool_id, judgment_id, txn_type, amount, description))
            row = await cur.fetchone()
    except Exception as e:
        logger.error(f"Failed to record transaction: {e}")
        raise FinanceServiceError(f"Failed to record transaction: {e}") from e

    txn_id = row[0] if row else 0
    logger.info(f"Recorded {txn_type} transaction: ${amount:,.2f} for pool {pool_id}")

    return txn_id
