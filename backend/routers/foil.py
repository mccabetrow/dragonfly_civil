"""
Dragonfly Engine - FOIL Router

Endpoints for FOIL (Freedom of Information Law) request management.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.foil_service import (
    broadcast_foil_followup_result,
    get_foil_stats,
    process_foil_followups,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/foil", tags=["FOIL"])


class FOILFollowupResponse(BaseModel):
    """Response from FOIL follow-up processing."""

    status: str
    processed: int
    message: str


class FOILStatsResponse(BaseModel):
    """FOIL statistics response."""

    pending_count: int
    followup_sent_count: int
    responded_count: int
    completed_count: int
    total_count: int
    needs_followup_count: int


@router.post(
    "/run-followups",
    response_model=FOILFollowupResponse,
    summary="Trigger FOIL follow-ups",
    description="Manually trigger processing of pending FOIL requests that need follow-up.",
)
async def run_foil_followups() -> FOILFollowupResponse:
    """
    Manually trigger FOIL follow-up processing.

    This endpoint processes all pending FOIL requests older than 20 days
    and sends follow-up messages. Useful for testing or manual runs.
    """
    logger.info("Manual FOIL follow-up triggered via API")

    try:
        processed = await process_foil_followups()

        # Broadcast to Discord
        await broadcast_foil_followup_result(processed)

        if processed == 0:
            message = "No pending FOIL requests required follow-up"
        else:
            message = f"Successfully processed {processed} FOIL follow-up(s)"

        return FOILFollowupResponse(
            status="success",
            processed=processed,
            message=message,
        )

    except Exception as e:
        logger.exception(f"FOIL follow-up processing failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": str(e)},
        )


@router.get(
    "/stats",
    response_model=FOILStatsResponse,
    summary="Get FOIL statistics",
    description="Returns statistics about FOIL requests in the system.",
)
async def foil_stats() -> FOILStatsResponse:
    """
    Get FOIL request statistics.

    Returns counts of requests by status and how many need follow-up.
    """
    try:
        stats = await get_foil_stats()

        return FOILStatsResponse(
            pending_count=stats.get("pending_count", 0) or 0,
            followup_sent_count=stats.get("followup_sent_count", 0) or 0,
            responded_count=stats.get("responded_count", 0) or 0,
            completed_count=stats.get("completed_count", 0) or 0,
            total_count=stats.get("total_count", 0) or 0,
            needs_followup_count=stats.get("needs_followup_count", 0) or 0,
        )

    except Exception as e:
        logger.exception(f"Failed to get FOIL stats: {e}")
        raise HTTPException(
            status_code=500,
            detail={"status": "error", "error": str(e)},
        )
