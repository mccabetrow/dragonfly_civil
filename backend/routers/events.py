"""
Dragonfly Engine - Events Router

Endpoints for querying the event timeline for entities and judgments.
Part of the Intelligence Graph.
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.event_service import (
    EventDTO,
    get_timeline_for_entity,
    get_timeline_for_judgment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])


# =============================================================================
# Response Models
# =============================================================================


class TimelineEventResponse(BaseModel):
    """A single event in the timeline."""

    id: str = Field(..., description="Event UUID")
    event_type: str = Field(..., description="Type of event")
    created_at: str = Field(..., description="ISO timestamp of when the event occurred")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Event-specific data"
    )
    # Human-readable summary
    summary: str = Field(..., description="Human-readable event summary")


class TimelineResponse(BaseModel):
    """Timeline response with list of events."""

    events: list[TimelineEventResponse] = Field(
        default_factory=list, description="List of events in chronological order"
    )
    total: int = Field(..., description="Total number of events returned")


# =============================================================================
# Helpers
# =============================================================================


def humanize_event(event: EventDTO) -> str:
    """
    Generate a human-readable summary of an event.

    Args:
        event: The EventDTO to summarize

    Returns:
        Human-readable string
    """
    payload = event.payload
    event_type = event.event_type

    if event_type == "new_judgment":
        amount = payload.get("amount", "?")
        county = payload.get("county", "unknown county")
        return f"Judgment created for ${amount} in {county}"

    elif event_type == "job_found":
        employer = payload.get("employer_name", "unknown employer")
        return f"Job found at {employer}"

    elif event_type == "asset_found":
        asset_type = payload.get("asset_type", "unknown asset")
        return f"Asset found: {asset_type}"

    elif event_type == "offer_made":
        amount = payload.get("amount", "?")
        cents = payload.get("cents_on_dollar")
        if cents:
            return f"Offer made: ${amount} ({cents}¢ on the dollar)"
        return f"Offer made: ${amount}"

    elif event_type == "offer_accepted":
        amount = payload.get("amount", "?")
        return f"Offer ACCEPTED for ${amount}"

    elif event_type == "packet_sent":
        packet_type = payload.get("packet_type", "unknown type")
        # Format packet type for display
        display_type = packet_type.replace("_", " ").title()
        return f"Packet sent: {display_type}"

    else:
        return event_type.replace("_", " ").title()


def event_dto_to_response(event: EventDTO) -> TimelineEventResponse:
    """Convert EventDTO to TimelineEventResponse with summary."""
    return TimelineEventResponse(
        id=event.id,
        event_type=event.event_type,
        created_at=event.created_at.isoformat(),
        payload=event.payload,
        summary=humanize_event(event),
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/entity/{entity_id}/timeline",
    response_model=TimelineResponse,
    summary="Get entity timeline",
    description=(
        "Retrieve the event timeline for a specific entity. "
        "Returns events in chronological order (oldest first)."
    ),
)
async def get_entity_timeline(
    entity_id: UUID,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of events to return (1-500)",
    ),
) -> TimelineResponse:
    """
    Get the event timeline for an entity.

    Returns events ordered chronologically (oldest first), which is
    natural for timeline display where you scroll down to see recent events.

    Args:
        entity_id: UUID of the entity to get timeline for
        limit: Maximum number of events to return (default 100, max 500)

    Returns:
        TimelineResponse with list of events
    """
    try:
        events = await get_timeline_for_entity(entity_id, limit=limit)

        return TimelineResponse(
            events=[event_dto_to_response(e) for e in events],
            total=len(events),
        )

    except Exception as e:
        logger.error("Failed to get timeline for entity %s: %s", entity_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve entity timeline: {str(e)}",
        )


@router.get(
    "/judgment/{judgment_id}/timeline",
    response_model=TimelineResponse,
    summary="Get judgment timeline",
    description=(
        "Retrieve the event timeline for a judgment by looking up its defendant entity. "
        "Returns events in chronological order (oldest first). "
        "Returns empty list if no entity is found for the judgment."
    ),
)
async def get_judgment_timeline(
    judgment_id: int,
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of events to return (1-500)",
    ),
) -> TimelineResponse:
    """
    Get the event timeline for a judgment.

    This is a convenience endpoint that first looks up the defendant entity
    for the judgment via the intelligence graph, then returns its timeline.

    If no entity is found (e.g., if graph build hasn't run yet), returns
    an empty list.

    Args:
        judgment_id: ID of the judgment to get timeline for
        limit: Maximum number of events to return (default 100, max 500)

    Returns:
        TimelineResponse with list of events (may be empty)
    """
    try:
        events = await get_timeline_for_judgment(judgment_id, limit=limit)

        return TimelineResponse(
            events=[event_dto_to_response(e) for e in events],
            total=len(events),
        )

    except Exception as e:
        logger.error("Failed to get timeline for judgment %s: %s", judgment_id, e)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve judgment timeline: {str(e)}",
        )
