"""
Dragonfly Engine - Compliance Service

Spend guards and risk controls for automated enforcement actions.
Prevents automated spending on low-ROI cases before dispatching
to external services (e.g., Proof.com process servers).

Guards:
1. ROI Guard: Blocks service dispatch for judgments < $1,500
2. Confidence Guard: Blocks dispatch if collectability score < 40
3. Gig Bypass: Overrides Confidence Guard if gig activity detected

These guards protect against wasted spend on cases unlikely to yield
returns that justify the cost of physical service (~$100-150/attempt).
"""

import logging
from dataclasses import dataclass
from typing import Optional

from backend.db import get_pool

logger = logging.getLogger(__name__)


# =============================================================================
# Constants - Guard Thresholds
# =============================================================================

# Minimum judgment amount to justify service costs (~$100-150)
MIN_JUDGMENT_AMOUNT = 1500.0

# Minimum collectability score to proceed automatically
MIN_SCORE_THRESHOLD = 40

# Task type for manual review queue
MANUAL_REVIEW_TASK_TYPE = "manual_review_service"


# =============================================================================
# Exceptions
# =============================================================================


class ComplianceError(Exception):
    """
    Raised when a compliance check fails.

    Attributes:
        rule: The rule that triggered the error (e.g., 'roi', 'confidence')
        judgment_id: The judgment ID that failed the check
        details: Additional context about the failure
    """

    def __init__(
        self,
        message: str,
        rule: str = "unknown",
        judgment_id: Optional[int] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.rule = rule
        self.judgment_id = judgment_id
        self.details = details or {}


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ComplianceResult:
    """Result of a compliance validation check."""

    judgment_id: int
    passed: bool
    rule_triggered: Optional[str] = None
    message: Optional[str] = None
    judgment_amount: Optional[float] = None
    score: Optional[int] = None
    gig_detected: bool = False
    gig_bypass_applied: bool = False


@dataclass
class JudgmentComplianceData:
    """Data fetched for compliance validation."""

    judgment_id: int
    judgment_amount: float
    collectability_score: Optional[int]
    gig_detected: bool


# =============================================================================
# Core Functions
# =============================================================================


async def fetch_compliance_data(judgment_id: int) -> JudgmentComplianceData:
    """
    Fetch judgment data needed for compliance validation.

    Args:
        judgment_id: The judgment ID to fetch

    Returns:
        JudgmentComplianceData with amount, score, and gig status

    Raises:
        ComplianceError: If judgment not found or data unavailable
    """
    conn = await get_pool()
    if conn is None:
        raise ComplianceError(
            "Database connection not available",
            rule="system",
            judgment_id=judgment_id,
        )

    try:
        async with conn.cursor() as cur:
            # Fetch judgment amount and score
            await cur.execute(
                """
                SELECT
                    j.id,
                    COALESCE(j.judgment_amount, 0) AS judgment_amount,
                    j.collectability_score,
                    EXISTS(
                        SELECT 1 FROM intelligence.gig_detections gd
                        WHERE gd.judgment_id = j.id
                    ) AS gig_detected
                FROM public.judgments j
                WHERE j.id = %s
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()

            if row is None:
                raise ComplianceError(
                    f"Judgment {judgment_id} not found",
                    rule="system",
                    judgment_id=judgment_id,
                )

            return JudgmentComplianceData(
                judgment_id=row[0],
                judgment_amount=float(row[1]) if row[1] else 0.0,
                collectability_score=int(row[2]) if row[2] is not None else None,
                gig_detected=bool(row[3]),
            )

    except ComplianceError:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch compliance data for judgment {judgment_id}: {e}")
        raise ComplianceError(
            f"Failed to fetch compliance data: {e}",
            rule="system",
            judgment_id=judgment_id,
        ) from e


async def validate_service_dispatch(judgment_id: int) -> ComplianceResult:
    """
    Validate whether a judgment qualifies for automated physical service dispatch.

    Applies the following rules in order:

    1. ROI Guard: If judgment_amount < $1,500, BLOCK
       Rationale: Service costs ~$100-150, low amounts don't justify spend

    2. Confidence Guard: If collectability_score < 40, BLOCK
       Rationale: Low confidence means we're unlikely to collect

    3. Gig Bypass: If gig_detected is True, BYPASS the Confidence Guard
       Rationale: Gig garnishment is highly effective; worth the service cost

    Args:
        judgment_id: The judgment ID to validate

    Returns:
        ComplianceResult with validation outcome

    Raises:
        ComplianceError: If validation fails (case should not proceed)
    """
    data = await fetch_compliance_data(judgment_id)

    # Rule 1: ROI Guard - Minimum Amount Check
    if data.judgment_amount < MIN_JUDGMENT_AMOUNT:
        raise ComplianceError(
            f"Amount too low for physical service (${data.judgment_amount:.2f} < ${MIN_JUDGMENT_AMOUNT:.2f})",
            rule="roi",
            judgment_id=judgment_id,
            details={
                "judgment_amount": data.judgment_amount,
                "threshold": MIN_JUDGMENT_AMOUNT,
            },
        )

    # Rule 2 & 3: Confidence Guard with Gig Bypass
    score = data.collectability_score

    # If we have gig detection, bypass the score check entirely
    if data.gig_detected:
        logger.info(
            f"Judgment {judgment_id}: Gig detected - bypassing score check "
            f"(score={score}, threshold={MIN_SCORE_THRESHOLD})"
        )
        return ComplianceResult(
            judgment_id=judgment_id,
            passed=True,
            judgment_amount=data.judgment_amount,
            score=score,
            gig_detected=True,
            gig_bypass_applied=True,
            message="Approved via gig bypass",
        )

    # No gig detection - apply standard score check
    if score is None:
        raise ComplianceError(
            "Score not available - cannot assess risk",
            rule="confidence",
            judgment_id=judgment_id,
            details={"score": None, "threshold": MIN_SCORE_THRESHOLD},
        )

    if score < MIN_SCORE_THRESHOLD:
        raise ComplianceError(
            f"Score too low to risk service costs (score={score} < {MIN_SCORE_THRESHOLD})",
            rule="confidence",
            judgment_id=judgment_id,
            details={"score": score, "threshold": MIN_SCORE_THRESHOLD},
        )

    # All checks passed
    logger.info(
        f"Judgment {judgment_id}: Compliance passed "
        f"(amount=${data.judgment_amount:.2f}, score={score})"
    )

    return ComplianceResult(
        judgment_id=judgment_id,
        passed=True,
        judgment_amount=data.judgment_amount,
        score=score,
        gig_detected=data.gig_detected,
        gig_bypass_applied=False,
        message="All compliance checks passed",
    )


async def create_manual_review_task(
    judgment_id: int,
    compliance_error: ComplianceError,
    plaintiff_id: Optional[str] = None,
) -> str:
    """
    Create a manual review task when automated dispatch is blocked.

    Args:
        judgment_id: The judgment ID that failed compliance
        compliance_error: The ComplianceError that triggered the review
        plaintiff_id: Optional plaintiff ID (will be looked up if not provided)

    Returns:
        Task ID (UUID string)

    Raises:
        RuntimeError: If task creation fails
    """
    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection not available")

    # Look up plaintiff_id if not provided
    if plaintiff_id is None:
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT p.id
                    FROM public.plaintiffs p
                    JOIN public.judgments j ON j.plaintiff_id = p.id
                    WHERE j.id = %s
                    """,
                    (judgment_id,),
                )
                row = await cur.fetchone()
                if row:
                    plaintiff_id = str(row[0])
        except Exception as e:
            logger.warning(
                f"Could not look up plaintiff for judgment {judgment_id}: {e}"
            )

    # Build metadata
    metadata = {
        "judgment_id": judgment_id,
        "compliance_rule": compliance_error.rule,
        "compliance_message": str(compliance_error),
        "compliance_details": compliance_error.details,
        "action_blocked": "physical_service_dispatch",
    }

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO public.plaintiff_tasks (
                    plaintiff_id,
                    task_type,
                    priority,
                    status,
                    metadata,
                    created_at,
                    updated_at
                )
                VALUES (
                    %s::uuid,
                    %s,
                    10,  -- High priority for blocked actions
                    'pending',
                    %s::jsonb,
                    NOW(),
                    NOW()
                )
                RETURNING id
                """,
                (plaintiff_id, MANUAL_REVIEW_TASK_TYPE, metadata),
            )
            row = await cur.fetchone()

            if row is None:
                raise RuntimeError("Task insert returned no ID")

            task_id = str(row[0])
            logger.info(
                f"Created manual review task {task_id} for judgment {judgment_id} "
                f"(rule={compliance_error.rule})"
            )
            return task_id

    except Exception as e:
        logger.error(
            f"Failed to create manual review task for judgment {judgment_id}: {e}"
        )
        raise RuntimeError(f"Failed to create manual review task: {e}") from e
