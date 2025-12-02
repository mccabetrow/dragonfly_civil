"""Tier assignment handler for PGMQ workers.

This handler processes tier_assignment jobs from the PGMQ queue. It evaluates
each judgment's collectability_score, principal_amount, and debtor_intelligence
to assign an enforcement tier (0-3) per docs/enforcement_tiers.md.

The handler:
1. Fetches the judgment and its debtor intelligence
2. Computes the appropriate tier based on policy rules
3. Updates core_judgments with tier, tier_reason, tier_as_of

Tier Policy Summary (from docs/enforcement_tiers.md):
  - Tier 0 (Monitor): collectability_score < 35 OR (balance < $5k AND no assets)
  - Tier 1 (Warm): 35 <= score < 60, balance $5k-$15k
  - Tier 2 (Active): 60 <= score < 80 OR balance $15k-$50k with assets
  - Tier 3 (Strategic): score >= 80 OR balance >= $50k with multiple assets

Job Payload Format:
    {
        "judgment_id": "<uuid>"  # Required: core_judgments.id
    }

Queue Kind: tier_assignment
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from src.supabase_client import create_supabase_client

logger = logging.getLogger(__name__)

# Balance thresholds (in dollars)
BALANCE_TIER_0_MAX = Decimal("5000")
BALANCE_TIER_1_MAX = Decimal("15000")
BALANCE_TIER_2_MAX = Decimal("50000")

# Collectability score thresholds
SCORE_TIER_0_MAX = 35
SCORE_TIER_1_MAX = 60
SCORE_TIER_2_MAX = 80


def _extract_judgment_id(job: Dict[str, Any]) -> Optional[str]:
    """Extract judgment_id from job payload.

    Handles nested payload structure from PGMQ.
    """
    if not isinstance(job, dict):
        return None

    # Try direct access first
    judgment_id = job.get("judgment_id")
    if judgment_id:
        return str(judgment_id).strip()

    # Check nested payload
    payload = job.get("payload")
    if isinstance(payload, dict):
        # Double-nested payload (from queue_job RPC)
        nested = payload.get("payload")
        if isinstance(nested, dict):
            judgment_id = nested.get("judgment_id")
            if judgment_id:
                return str(judgment_id).strip()

        # Single-nested payload
        judgment_id = payload.get("judgment_id")
        if judgment_id:
            return str(judgment_id).strip()

    return None


def _has_asset_hints(intelligence: Optional[Dict[str, Any]]) -> bool:
    """Check if debtor intelligence contains asset hints (bank or employer)."""
    if not intelligence:
        return False

    has_employer = bool(intelligence.get("employer_name"))
    has_bank = bool(intelligence.get("bank_name"))

    return has_employer or has_bank


def _count_asset_signals(intelligence: Optional[Dict[str, Any]]) -> int:
    """Count the number of asset signals present in intelligence."""
    if not intelligence:
        return 0

    count = 0
    if intelligence.get("employer_name"):
        count += 1
    if intelligence.get("bank_name"):
        count += 1
    if intelligence.get("real_property_lead"):
        count += 1
    if intelligence.get("vehicle_lead"):
        count += 1

    return count


def compute_tier(
    collectability_score: Optional[float],
    principal_amount: Optional[Decimal],
    intelligence: Optional[Dict[str, Any]],
) -> Tuple[int, str]:
    """Compute enforcement tier based on judgment data and intelligence.

    Returns:
        Tuple of (tier: int 0-3, reason: str explaining assignment)

    Tier Policy (docs/enforcement_tiers.md) - uses OR logic for each tier:
        Tier 3: score >= 80 OR (balance >= $50k with 2+ asset signals)
        Tier 2: score in [60,80) OR (balance $15k-$50k with assets)
        Tier 1: score in [35,60) OR balance $5k-$15k
        Tier 0: score < 35 OR (balance < $5k with no assets)

    Logic: Check each tier from highest (3) to lowest (0).
    Within each tier, check score-based criteria first, then balance-based.
    This ensures balance can PROMOTE to a higher tier (OR logic).
    """
    score = collectability_score if collectability_score is not None else 0
    balance = principal_amount if principal_amount is not None else Decimal("0")
    has_assets = _has_asset_hints(intelligence)
    asset_count = _count_asset_signals(intelligence)

    reasons = []

    # === TIER 3 - Strategic / Priority ===
    # score >= 80 OR (balance >= $50k with 2+ assets)
    if score >= SCORE_TIER_2_MAX:
        reasons.append(f"collectability_score={score:.0f}>=80")
        return 3, "; ".join(reasons)

    if balance >= BALANCE_TIER_2_MAX and asset_count >= 2:
        reasons.append(f"balance=${balance:,.0f}>=50k")
        reasons.append(f"asset_signals={asset_count}")
        return 3, "; ".join(reasons)

    # === TIER 2 - Active Enforcement ===
    # score in [60,80) OR (balance $15k-$50k with assets)
    if SCORE_TIER_1_MAX <= score < SCORE_TIER_2_MAX:
        reasons.append(f"collectability_score={score:.0f} in [60,80)")
        if has_assets:
            reasons.append("has_asset_hints")
        return 2, "; ".join(reasons)

    if BALANCE_TIER_1_MAX <= balance < BALANCE_TIER_2_MAX and has_assets:
        reasons.append(f"balance=${balance:,.0f} in [15k,50k)")
        reasons.append("has_asset_hints")
        return 2, "; ".join(reasons)

    # === TIER 1 - Warm Prospects ===
    # score in [35,60) OR balance $5k-$15k
    if SCORE_TIER_0_MAX <= score < SCORE_TIER_1_MAX:
        reasons.append(f"collectability_score={score:.0f} in [35,60)")
        return 1, "; ".join(reasons)

    if BALANCE_TIER_0_MAX <= balance < BALANCE_TIER_1_MAX:
        reasons.append(f"balance=${balance:,.0f} in [5k,15k)")
        return 1, "; ".join(reasons)

    # === TIER 0 - Monitor (default/lowest) ===
    # score < 35 OR (balance < $5k with no assets)
    if score < SCORE_TIER_0_MAX:
        reasons.append(f"collectability_score={score:.0f}<35")

    if balance < BALANCE_TIER_0_MAX and not has_assets:
        if reasons:  # Already have score reason
            reasons.append(f"balance=${balance:,.0f}<5k; no_asset_hints")
        else:
            reasons.append(f"balance=${balance:,.0f}<5k")
            reasons.append("no_asset_hints")

    if not reasons:
        reasons.append("default_tier_0")

    return 0, "; ".join(reasons)


async def handle_tier_assignment(job: Dict[str, Any]) -> bool:
    """Handle a tier_assignment job from the PGMQ queue.

    Args:
        job: The job dict from dequeue_job RPC containing judgment_id

    Returns:
        True if job processed successfully (delete from queue)
        False if job should be retried

    Raises:
        Exception: On unrecoverable errors (will be logged, job deleted)
    """
    msg_id = job.get("msg_id", "?")

    judgment_id = _extract_judgment_id(job)
    if not judgment_id:
        logger.error(
            "tier_assignment_invalid_payload kind=tier_assignment msg_id=%s",
            msg_id,
        )
        return True  # Don't retry invalid payloads

    logger.info(
        "tier_assignment_start kind=tier_assignment msg_id=%s judgment_id=%s",
        msg_id,
        judgment_id,
    )

    client = create_supabase_client()

    try:
        # 1. Fetch the judgment
        response = (
            client.table("core_judgments")
            .select(
                "id, case_index_number, status, collectability_score, principal_amount, tier"
            )
            .eq("id", judgment_id)
            .execute()
        )

        if not response.data:
            logger.warning(
                "tier_assignment_judgment_not_found kind=tier_assignment msg_id=%s judgment_id=%s",
                msg_id,
                judgment_id,
            )
            return True  # Don't retry for missing judgments

        judgment = response.data[0]

        # Skip closed statuses
        status = judgment.get("status")
        if status in ("satisfied", "vacated", "expired"):
            logger.info(
                "tier_assignment_skipped_closed kind=tier_assignment msg_id=%s judgment_id=%s status=%s",
                msg_id,
                judgment_id,
                status,
            )
            return True

        # 2. Fetch debtor intelligence (if any)
        intel_response = (
            client.table("debtor_intelligence")
            .select("*")
            .eq("judgment_id", judgment_id)
            .order("last_updated", desc=True)
            .limit(1)
            .execute()
        )

        intelligence = intel_response.data[0] if intel_response.data else None

        # 3. Compute tier
        collectability_score = judgment.get("collectability_score")
        principal_amount = judgment.get("principal_amount")
        if principal_amount is not None:
            principal_amount = Decimal(str(principal_amount))

        new_tier, tier_reason = compute_tier(
            collectability_score, principal_amount, intelligence
        )

        old_tier = judgment.get("tier")

        # 4. Update judgment with new tier (idempotent - always updates)
        now = datetime.now(timezone.utc).isoformat()

        update_response = (
            client.table("core_judgments")
            .update(
                {
                    "tier": new_tier,
                    "tier_reason": tier_reason,
                    "tier_as_of": now,
                }
            )
            .eq("id", judgment_id)
            .execute()
        )

        if not update_response.data:
            logger.error(
                "tier_assignment_update_failed kind=tier_assignment msg_id=%s judgment_id=%s",
                msg_id,
                judgment_id,
            )
            return False  # Retry

        # Log tier change vs tier refresh
        if old_tier is None or old_tier != new_tier:
            logger.info(
                "tier_assignment_changed kind=tier_assignment msg_id=%s judgment_id=%s old_tier=%s new_tier=%s reason=%s",
                msg_id,
                judgment_id,
                old_tier,
                new_tier,
                tier_reason,
            )
        else:
            logger.debug(
                "tier_assignment_refreshed kind=tier_assignment msg_id=%s judgment_id=%s tier=%s",
                msg_id,
                judgment_id,
                new_tier,
            )

        logger.info(
            "tier_assignment_complete kind=tier_assignment msg_id=%s judgment_id=%s tier=%s",
            msg_id,
            judgment_id,
            new_tier,
        )

        return True

    except Exception as e:
        logger.exception(
            "tier_assignment_failed kind=tier_assignment msg_id=%s judgment_id=%s",
            msg_id,
            judgment_id,
        )
        raise
