"""
Dragonfly Engine - Allocation Service

Automatic asset allocation engine for sorting judgments into finance pools
based on collectability scores.

Pool allocation rules:
- Score > 80:  Prime 2025-A (high collectability, stable returns)
- Score 50-79: Standard 2025-A (moderate collectability)
- Score < 50:  Distressed Inventory (workout/recovery pool)

Depends on:
- enforcement.v_score_card view
- finance_service for pool management
"""

import logging
from dataclasses import dataclass
from typing import Optional

from backend.db import get_pool

logger = logging.getLogger(__name__)


# =============================================================================
# Constants - Pool Definitions
# =============================================================================

# Pool allocation thresholds
PRIME_THRESHOLD = 80
STANDARD_THRESHOLD = 50

# Pool names
POOL_PRIME = "Prime 2025-A"
POOL_STANDARD = "Standard 2025-A"
POOL_DISTRESSED = "Distressed Inventory"

# Pool IRR targets (for auto-creation)
POOL_CONFIGS = {
    POOL_PRIME: {
        "target_irr": 0.15,  # 15% target IRR
        "management_fee_percent": 0.01,  # 1% fee
        "description": "High collectability judgments (score > 80)",
    },
    POOL_STANDARD: {
        "target_irr": 0.20,  # 20% target IRR (higher risk premium)
        "management_fee_percent": 0.015,  # 1.5% fee
        "description": "Moderate collectability judgments (score 50-79)",
    },
    POOL_DISTRESSED: {
        "target_irr": 0.35,  # 35% target IRR (high risk)
        "management_fee_percent": 0.02,  # 2% fee
        "description": "Low collectability / workout judgments (score < 50)",
    },
}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AllocationResult:
    """Result of an auto-tranching operation."""

    judgment_id: int
    pool_name: str
    pool_id: str
    score: int
    previous_pool: Optional[str] = None
    was_reassigned: bool = False


# =============================================================================
# Exceptions
# =============================================================================


class AllocationError(Exception):
    """Raised when allocation operations fail."""

    pass


# =============================================================================
# Core Functions
# =============================================================================


def determine_pool_for_score(score: int) -> str:
    """
    Determine which pool a judgment should be assigned to based on score.

    Args:
        score: Collectability score (0-100)

    Returns:
        Pool name string
    """
    if score > PRIME_THRESHOLD:
        return POOL_PRIME
    elif score >= STANDARD_THRESHOLD:
        return POOL_STANDARD
    else:
        return POOL_DISTRESSED


async def get_score_for_judgment(judgment_id: int) -> Optional[int]:
    """
    Fetch the collectability score for a judgment from enforcement.v_score_card.

    Args:
        judgment_id: The judgment ID

    Returns:
        Score as integer, or None if not found/not scored
    """
    conn = await get_pool()
    if conn is None:
        raise AllocationError("Database connection not available")

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT total_score
                FROM enforcement.v_score_card
                WHERE id = %s
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()

            if row is None or row[0] is None:
                return None

            return int(row[0])

    except Exception as e:
        logger.error(f"Failed to fetch score for judgment {judgment_id}: {e}")
        raise AllocationError(f"Failed to fetch score: {e}") from e


async def ensure_pool_exists(pool_name: str) -> str:
    """
    Ensure a pool exists, creating it if necessary.

    Args:
        pool_name: Name of the pool

    Returns:
        Pool ID (UUID string)
    """
    from .finance_service import create_pool, get_pool_by_name

    pool = await get_pool_by_name(pool_name)

    if pool is not None:
        return pool.id

    # Create the pool with configured settings
    config = POOL_CONFIGS.get(pool_name, {})
    new_pool = await create_pool(
        name=pool_name,
        target_irr=config.get("target_irr"),
        management_fee_percent=config.get("management_fee_percent", 0.015),
        description=config.get("description"),
    )

    logger.info(f"Created pool '{pool_name}' with id={new_pool.id}")
    return new_pool.id


async def get_current_pool_for_judgment(judgment_id: int) -> Optional[str]:
    """
    Get the current pool assignment for a judgment.

    Args:
        judgment_id: The judgment ID

    Returns:
        Pool name or None if not assigned
    """
    conn = await get_pool()
    if conn is None:
        return None

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT p.name
                FROM public.judgments j
                LEFT JOIN finance.pools p ON p.id = j.pool_id
                WHERE j.id = %s
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None

    except Exception as e:
        logger.warning(f"Failed to get current pool for judgment {judgment_id}: {e}")
        return None


async def auto_tranche_judgment(judgment_id: int) -> Optional[AllocationResult]:
    """
    Automatically assign a judgment to a pool based on its collectability score.

    This is the main entry point for automatic asset allocation. It:
    1. Fetches the judgment's score from enforcement.v_score_card
    2. Determines the appropriate pool based on score thresholds
    3. Creates the pool if it doesn't exist
    4. Assigns the judgment to the pool

    Args:
        judgment_id: The judgment ID to allocate

    Returns:
        AllocationResult with pool assignment details, or None if judgment
        has no score (cannot be allocated)

    Raises:
        AllocationError: If allocation fails due to database error
    """
    # Step 1: Get the score
    score = await get_score_for_judgment(judgment_id)

    if score is None:
        logger.info(
            f"Judgment {judgment_id} has no collectability score - skipping allocation"
        )
        return None

    # Step 2: Determine target pool
    target_pool_name = determine_pool_for_score(score)

    # Step 3: Check current assignment
    current_pool_name = await get_current_pool_for_judgment(judgment_id)
    was_reassigned = (
        current_pool_name is not None and current_pool_name != target_pool_name
    )

    # Step 4: Ensure pool exists
    pool_id = await ensure_pool_exists(target_pool_name)

    # Step 5: Assign judgment to pool
    conn = await get_pool()
    if conn is None:
        raise AllocationError("Database connection not available")

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE public.judgments
                SET pool_id = %s::uuid, updated_at = NOW()
                WHERE id = %s
                """,
                (pool_id, judgment_id),
            )

    except Exception as e:
        logger.error(
            f"Failed to assign judgment {judgment_id} to pool {target_pool_name}: {e}"
        )
        raise AllocationError(f"Failed to assign judgment to pool: {e}") from e

    result = AllocationResult(
        judgment_id=judgment_id,
        pool_name=target_pool_name,
        pool_id=pool_id,
        score=score,
        previous_pool=current_pool_name,
        was_reassigned=was_reassigned,
    )

    logger.info(
        f"Allocated judgment {judgment_id} (score={score}) to pool '{target_pool_name}'"
        + (f" (reassigned from '{current_pool_name}')" if was_reassigned else "")
    )

    return result


async def emit_tranched_event(
    judgment_id: int,
    pool_name: str,
    score: int,
    was_reassigned: bool = False,
) -> None:
    """
    Emit a judgment_tranched event (best-effort).

    This is a best-effort operation - failures are logged but don't raise.

    Args:
        judgment_id: The judgment ID
        pool_name: Name of the assigned pool
        score: The collectability score that determined allocation
        was_reassigned: Whether this was a reassignment from another pool
    """
    try:
        # For now, emit via the public.events table (simpler than intelligence.events)
        # This allows us to track tranching without requiring the entity graph
        conn = await get_pool()
        if conn is None:
            logger.warning(
                f"Database unavailable - skipping judgment_tranched event for {judgment_id}"
            )
            return

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO public.events (judgment_id, event_type, payload)
                VALUES (%s, 'judgment_tranched', %s::jsonb)
                ON CONFLICT DO NOTHING
                """,
                (
                    judgment_id,
                    {
                        "pool_name": pool_name,
                        "score": score,
                        "was_reassigned": was_reassigned,
                    },
                ),
            )

        logger.debug(
            f"Emitted judgment_tranched event for judgment {judgment_id} -> {pool_name}"
        )

    except Exception as e:
        # Best-effort: log and continue
        logger.warning(f"Failed to emit judgment_tranched event for {judgment_id}: {e}")


async def auto_tranche_and_emit(judgment_id: int) -> Optional[AllocationResult]:
    """
    Auto-tranche a judgment and emit the judgment_tranched event.

    Convenience wrapper that combines allocation and event emission.

    Args:
        judgment_id: The judgment ID to allocate

    Returns:
        AllocationResult or None if judgment has no score
    """
    result = await auto_tranche_judgment(judgment_id)

    if result is not None:
        await emit_tranched_event(
            judgment_id=result.judgment_id,
            pool_name=result.pool_name,
            score=result.score,
            was_reassigned=result.was_reassigned,
        )

    return result
