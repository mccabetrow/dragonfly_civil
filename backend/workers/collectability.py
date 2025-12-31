"""
Dragonfly Engine - Collectability Scorer Worker

This worker scores judgments for collectability after ingestion.
It runs after batch ingestion completes and assigns tier-based
collectability scores to enable prioritization.

Scoring Logic (docs/enforcement_tiers.md):
  - Tier A (Score 80-100): >$10k judgment AND <5 years old
  - Tier B (Score 50-79): >$5k judgment OR (>$2k AND <3 years old)
  - Tier C (Score 0-49): All other judgments

Usage:
    # Run as standalone worker
    python -m backend.workers.collectability

    # Or import and use directly
    from backend.workers.collectability import score_batch_judgments
    await score_batch_judgments(batch_id)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

# =============================================================================
# SCORING THRESHOLDS
# =============================================================================

# Amount thresholds (in dollars)
TIER_A_MIN_AMOUNT = Decimal("10000")  # $10k+
TIER_B_MIN_AMOUNT = Decimal("5000")  # $5k+
TIER_B_ALT_AMOUNT = Decimal("2000")  # $2k+ (with age bonus)

# Age thresholds (in years)
TIER_A_MAX_AGE_YEARS = 5
TIER_B_ALT_MAX_AGE_YEARS = 3

# Score ranges
TIER_A_BASE_SCORE = 85
TIER_B_BASE_SCORE = 65
TIER_C_BASE_SCORE = 30


# =============================================================================
# SCORING FUNCTIONS
# =============================================================================


def compute_judgment_age_years(judgment_date: date | datetime | None) -> float | None:
    """Compute the age of a judgment in years from today."""
    if judgment_date is None:
        return None

    if isinstance(judgment_date, datetime):
        judgment_date = judgment_date.date()

    today = date.today()
    delta = today - judgment_date
    return delta.days / 365.25


def compute_collectability_score(
    judgment_amount: Decimal | float | None,
    judgment_date: date | datetime | None,
) -> tuple[int, str, str]:
    """
    Compute collectability score based on judgment amount and age.

    Returns:
        tuple of (score: int 0-100, tier: str, reason: str)

    Scoring Logic:
        Tier A (80-100): >$10k AND <5 years old
        Tier B (50-79):  >$5k OR (>$2k AND <3 years old)
        Tier C (0-49):   Everything else
    """
    amount = Decimal(str(judgment_amount)) if judgment_amount else Decimal("0")
    age_years = compute_judgment_age_years(judgment_date)

    reasons: list[str] = []

    # === TIER A: High Value + Recent ===
    if amount >= TIER_A_MIN_AMOUNT and age_years is not None and age_years < TIER_A_MAX_AGE_YEARS:
        base_score = TIER_A_BASE_SCORE

        # Bonus for higher amounts (up to +10)
        if amount >= Decimal("50000"):
            base_score += 10
            reasons.append(f"amount=${amount:,.0f}>=50k")
        elif amount >= Decimal("25000"):
            base_score += 5
            reasons.append(f"amount=${amount:,.0f}>=25k")
        else:
            reasons.append(f"amount=${amount:,.0f}>=10k")

        # Bonus for newer judgments (up to +5)
        if age_years < 1:
            base_score += 5
            reasons.append(f"age={age_years:.1f}y<1y")
        elif age_years < 2:
            base_score += 3
            reasons.append(f"age={age_years:.1f}y<2y")
        else:
            reasons.append(f"age={age_years:.1f}y<5y")

        score = min(base_score, 100)  # Cap at 100
        return (score, "A", "; ".join(reasons))

    # === TIER B: Medium Value OR Younger + Moderate Value ===
    if amount >= TIER_B_MIN_AMOUNT:
        # Standard Tier B: >$5k
        base_score = TIER_B_BASE_SCORE
        reasons.append(f"amount=${amount:,.0f}>=5k")

        # Age bonus
        if age_years is not None and age_years < 3:
            base_score += 10
            reasons.append(f"age={age_years:.1f}y<3y")
        elif age_years is not None and age_years < 5:
            base_score += 5
            reasons.append(f"age={age_years:.1f}y<5y")

        score = min(base_score, 79)  # Cap at Tier B max
        return (score, "B", "; ".join(reasons))

    if (
        amount >= TIER_B_ALT_AMOUNT
        and age_years is not None
        and age_years < TIER_B_ALT_MAX_AGE_YEARS
    ):
        # Alternative Tier B: >$2k AND <3 years
        base_score = 55
        reasons.append(f"amount=${amount:,.0f}>=2k")
        reasons.append(f"age={age_years:.1f}y<3y")

        return (base_score, "B", "; ".join(reasons))

    # === TIER C: Everything else ===
    base_score = TIER_C_BASE_SCORE

    if amount > 0:
        reasons.append(f"amount=${amount:,.0f}")
    else:
        reasons.append("amount=0")

    if age_years is not None:
        reasons.append(f"age={age_years:.1f}y")
        # Penalty for old judgments
        if age_years > 10:
            base_score = max(base_score - 20, 5)
            reasons.append("old_penalty")
        elif age_years > 7:
            base_score = max(base_score - 10, 10)

    return (base_score, "C", "; ".join(reasons))


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================


async def get_unscored_judgments(
    conn: Any,
    batch_id: UUID | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """
    Fetch judgments that need collectability scoring.

    Args:
        conn: asyncpg connection
        batch_id: Optional - limit to judgments from a specific batch
        limit: Max rows to fetch (default 500)

    Returns:
        List of judgment dicts with id, judgment_amount, judgment_date
    """
    if batch_id:
        # Fetch from specific batch
        rows = await conn.fetch(
            """
            SELECT
                j.id,
                j.case_number,
                j.judgment_amount,
                j.judgment_date,
                j.collectability_score,
                j.tier
            FROM public.judgments j
            WHERE j.source_reference LIKE $1
              AND j.collectability_score IS NULL
            ORDER BY j.judgment_amount DESC NULLS LAST
            LIMIT $2
            """,
            f"batch:{batch_id}%",
            limit,
        )
    else:
        # Fetch any unscored judgments
        rows = await conn.fetch(
            """
            SELECT
                j.id,
                j.case_number,
                j.judgment_amount,
                j.judgment_date,
                j.collectability_score,
                j.tier
            FROM public.judgments j
            WHERE j.collectability_score IS NULL
            ORDER BY j.judgment_amount DESC NULLS LAST
            LIMIT $1
            """,
            limit,
        )

    return [dict(row) for row in rows]


async def update_judgment_score(
    conn: Any,
    judgment_id: UUID,
    score: int,
    tier: str,
    reason: str,
) -> None:
    """
    Update a judgment with its collectability score and tier.

    Args:
        conn: asyncpg connection
        judgment_id: UUID of the judgment
        score: Collectability score (0-100)
        tier: Tier classification (A, B, or C)
        reason: Human-readable reason for the score
    """
    await conn.execute(
        """
        UPDATE public.judgments
        SET collectability_score = $2,
            tier = $3,
            tier_reason = $4,
            tier_as_of = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        str(judgment_id),
        score,
        tier,
        reason,
    )


# =============================================================================
# BATCH SCORING
# =============================================================================


async def score_batch_judgments(
    batch_id: UUID,
    limit: int = 1000,
) -> dict[str, int]:
    """
    Score all unscored judgments from a specific batch.

    Args:
        batch_id: UUID of the intake batch
        limit: Max judgments to score

    Returns:
        dict with counts: {"scored": N, "tier_a": N, "tier_b": N, "tier_c": N}
    """
    from ..db import get_connection

    logger.info(f"[COLLECTABILITY] Scoring judgments for batch {batch_id}")

    counts = {"scored": 0, "tier_a": 0, "tier_b": 0, "tier_c": 0}

    async with get_connection() as conn:
        judgments = await get_unscored_judgments(conn, batch_id, limit)

        if not judgments:
            logger.info(f"[COLLECTABILITY] No unscored judgments for batch {batch_id}")
            return counts

        logger.info(f"[COLLECTABILITY] Found {len(judgments)} judgments to score")

        for j in judgments:
            try:
                score, tier, reason = compute_collectability_score(
                    j.get("judgment_amount"),
                    j.get("judgment_date"),
                )

                await update_judgment_score(
                    conn,
                    UUID(str(j["id"])),
                    score,
                    tier,
                    reason,
                )

                counts["scored"] += 1
                counts[f"tier_{tier.lower()}"] += 1

                logger.debug(
                    f"[COLLECTABILITY] Scored {j['case_number']}: "
                    f"score={score}, tier={tier}, reason={reason}"
                )

            except Exception as e:
                logger.warning(f"[COLLECTABILITY] Failed to score judgment {j['id']}: {e}")
                continue

    logger.info(
        f"[COLLECTABILITY] Batch {batch_id} complete: "
        f"{counts['scored']} scored (A={counts['tier_a']}, B={counts['tier_b']}, C={counts['tier_c']})"
    )

    return counts


async def score_all_unscored(limit: int = 500) -> dict[str, int]:
    """
    Score all unscored judgments across all batches.

    Args:
        limit: Max judgments to score per run

    Returns:
        dict with counts
    """
    from ..db import get_connection

    logger.info("[COLLECTABILITY] Scoring all unscored judgments")

    counts = {"scored": 0, "tier_a": 0, "tier_b": 0, "tier_c": 0}

    async with get_connection() as conn:
        judgments = await get_unscored_judgments(conn, batch_id=None, limit=limit)

        if not judgments:
            logger.info("[COLLECTABILITY] No unscored judgments found")
            return counts

        logger.info(f"[COLLECTABILITY] Found {len(judgments)} judgments to score")

        for j in judgments:
            try:
                score, tier, reason = compute_collectability_score(
                    j.get("judgment_amount"),
                    j.get("judgment_date"),
                )

                await update_judgment_score(
                    conn,
                    UUID(str(j["id"])),
                    score,
                    tier,
                    reason,
                )

                counts["scored"] += 1
                counts[f"tier_{tier.lower()}"] += 1

            except Exception as e:
                logger.warning(f"[COLLECTABILITY] Failed to score judgment {j['id']}: {e}")
                continue

    logger.info(
        f"[COLLECTABILITY] Run complete: "
        f"{counts['scored']} scored (A={counts['tier_a']}, B={counts['tier_b']}, C={counts['tier_c']})"
    )

    return counts


# =============================================================================
# JOB HANDLER (for PGMQ/job_queue integration)
# =============================================================================


async def handle_collectability_batch(job: dict[str, Any]) -> bool:
    """
    Handle a collectability_batch job from the job queue.

    Job payload format:
        {
            "batch_id": "<uuid>",
            "rows_inserted": <int>,
            "trigger": "batch_complete"
        }

    Returns:
        True if job completed successfully
    """
    # Extract batch_id from potentially nested payload
    payload = job.get("payload", job)
    if isinstance(payload, dict) and "payload" in payload:
        payload = payload["payload"]

    batch_id_raw = payload.get("batch_id")
    if not batch_id_raw:
        logger.error("[COLLECTABILITY] Job missing batch_id")
        return False

    batch_id = UUID(str(batch_id_raw))
    rows_expected = payload.get("rows_inserted", 0)

    logger.info(f"[COLLECTABILITY] Processing batch {batch_id} (expected: {rows_expected} rows)")

    try:
        counts = await score_batch_judgments(batch_id, limit=rows_expected + 100)

        if counts["scored"] > 0:
            logger.info(
                f"[COLLECTABILITY] Job complete: batch={batch_id}, "
                f"scored={counts['scored']}/{rows_expected}"
            )
            return True
        else:
            logger.warning(f"[COLLECTABILITY] No judgments scored for batch {batch_id}")
            return True  # Still consider job complete (nothing to do)

    except Exception as e:
        logger.exception(f"[COLLECTABILITY] Job failed for batch {batch_id}: {e}")
        raise


# =============================================================================
# WORKER LOOP
# =============================================================================


async def worker_loop(poll_interval: int = 10) -> None:
    """
    Main worker loop - poll for unscored judgments and process them.

    This runs continuously, scoring any judgments with NULL collectability_score.
    """
    logger.info("[COLLECTABILITY] Worker starting...")

    while True:
        try:
            counts = await score_all_unscored(limit=100)

            if counts["scored"] > 0:
                logger.info(f"[COLLECTABILITY] Scored {counts['scored']} judgments")
            else:
                logger.debug("[COLLECTABILITY] No work, sleeping...")

        except Exception as e:
            logger.error(f"[COLLECTABILITY] Worker error: {e}")

        await asyncio.sleep(poll_interval)


# =============================================================================
# CLI ENTRY POINT
# =============================================================================


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    # Parse args
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # Single run mode
        async def run_once():
            counts = await score_all_unscored(limit=500)
            print(
                f"Scored: {counts['scored']} (A={counts['tier_a']}, B={counts['tier_b']}, C={counts['tier_c']})"
            )

        asyncio.run(run_once())
    else:
        # Continuous worker mode
        asyncio.run(worker_loop())
