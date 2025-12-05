"""
Dragonfly Engine - Ops Guardian Router

Manual trigger endpoints for the Intake Guardian self-healing subsystem.
Allows operators to manually run guardian checks and view status.

All endpoints require authentication via API key or JWT.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.security import AuthContext, get_current_user
from ..services.intake_guardian import IntakeGuardian, get_intake_guardian

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ops/guardian", tags=["ops"])


class GuardianRunResponse(BaseModel):
    """Response from running the guardian check."""

    status: str
    checked: int
    marked_failed: int
    errors: list[str] = []


class GuardianStatusResponse(BaseModel):
    """Response showing guardian configuration."""

    status: str
    stale_minutes: int
    max_retries: int


@router.post(
    "/run",
    response_model=GuardianRunResponse,
    summary="Manually run intake guardian check",
    description=(
        "Triggers a manual run of the Intake Guardian, which checks for "
        "stuck batches and marks them as failed. Returns counts of checked "
        "and failed batches."
    ),
)
async def run_guardian(
    auth: AuthContext = Depends(get_current_user),
) -> GuardianRunResponse:
    """
    Manually trigger the Intake Guardian check.

    This endpoint allows operators to manually run the guardian check
    instead of waiting for the scheduled interval (60 seconds).

    Requires authentication via API key or JWT.

    Returns:
        GuardianRunResponse with:
        - status: "ok" if completed successfully
        - checked: Number of batches checked
        - marked_failed: Number of batches marked as failed
        - errors: List of any errors encountered
    """
    logger.info(f"🛡️ Guardian manual run triggered by {auth.via}")

    guardian = get_intake_guardian()
    result = await guardian.check_stuck_batches()

    return GuardianRunResponse(
        status="ok",
        checked=result.checked,
        marked_failed=result.marked_failed,
        errors=result.errors,
    )


@router.get(
    "/status",
    response_model=GuardianStatusResponse,
    summary="Get guardian configuration",
    description="Returns the current Intake Guardian configuration.",
)
async def get_guardian_status(
    auth: AuthContext = Depends(get_current_user),
) -> GuardianStatusResponse:
    """
    Get the current Intake Guardian configuration.

    Returns:
        GuardianStatusResponse with current settings.
    """
    guardian = get_intake_guardian()

    return GuardianStatusResponse(
        status="ok",
        stale_minutes=guardian.stale_minutes,
        max_retries=guardian.max_retries,
    )
