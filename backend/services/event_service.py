"""
Dragonfly Engine - Event Service

Append-only event log for enforcement lifecycle tracking.
Records events like new_judgment, job_found, asset_found, offer_made, packet_sent
to build a timeline for each defendant entity.

All event emission is best-effort: if the DB call fails, we log and continue.
Events should NEVER break the main enforcement workflow.
"""

import logging
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from ..db import get_pool

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

# Valid event types (must match intelligence.event_type enum in DB)
EVENT_TYPES = frozenset(
    [
        "new_judgment",
        "job_found",
        "asset_found",
        "offer_made",
        "offer_accepted",
        "packet_sent",
    ]
)

EventType = Literal[
    "new_judgment",
    "job_found",
    "asset_found",
    "offer_made",
    "offer_accepted",
    "packet_sent",
]


# =============================================================================
# DTOs
# =============================================================================


class EventDTO(BaseModel):
    """Data transfer object for events."""

    id: str = Field(..., description="Event UUID")
    event_type: str = Field(..., description="Type of event")
    created_at: datetime = Field(..., description="When the event occurred")
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Event-specific data"
    )


# =============================================================================
# Core Functions
# =============================================================================


async def emit_event(
    entity_id: UUID | str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Emit an event to the append-only event log.

    This is a best-effort operation: if the database call fails,
    we log the error and return. The main workflow should NEVER
    be interrupted by event logging failures.

    Args:
        entity_id: UUID of the entity (typically the defendant) this event relates to
        event_type: Type of event (must be one of EVENT_TYPES)
        payload: Optional event-specific data (will be stored as JSONB)

    Returns:
        None

    Raises:
        Nothing - all errors are caught and logged
    """
    # Validate event_type
    if event_type not in EVENT_TYPES:
        logger.warning(
            "Invalid event_type '%s' - must be one of %s. Skipping.",
            event_type,
            EVENT_TYPES,
        )
        return

    # Normalize entity_id to string
    entity_id_str = str(entity_id)

    # Default empty payload
    if payload is None:
        payload = {}

    try:
        conn = await get_pool()
        if conn is None:
            logger.warning(
                "Database connection not available - skipping event emission for %s",
                event_type,
            )
            return

        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO intelligence.events (entity_id, event_type, payload)
                VALUES (%s::uuid, %s::intelligence.event_type, %s::jsonb)
                """,
                (entity_id_str, event_type, payload),
            )

        logger.debug(
            "Emitted event: type=%s, entity_id=%s, payload_keys=%s",
            event_type,
            entity_id_str,
            list(payload.keys()) if payload else [],
        )

    except Exception as e:
        # Best-effort: log and continue
        logger.warning(
            "Failed to emit event (non-fatal): type=%s, entity_id=%s, error=%s",
            event_type,
            entity_id_str,
            str(e),
        )


async def get_timeline_for_entity(
    entity_id: UUID | str,
    limit: int = 100,
) -> list[EventDTO]:
    """
    Get the event timeline for an entity.

    Returns events ordered by created_at ascending (oldest first),
    which is natural for timeline display.

    Args:
        entity_id: UUID of the entity to get timeline for
        limit: Maximum number of events to return (default 100)

    Returns:
        List of EventDTO objects, ordered by created_at ascending

    Raises:
        Nothing - returns empty list on error
    """
    entity_id_str = str(entity_id)

    try:
        conn = await get_pool()
        if conn is None:
            logger.warning(
                "Database connection not available - returning empty timeline"
            )
            return []

        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, event_type, created_at, payload
                FROM intelligence.events
                WHERE entity_id = %s::uuid
                ORDER BY created_at ASC
                LIMIT %s
                """,
                (entity_id_str, limit),
            )
            rows = await cur.fetchall()

        events = []
        for row in rows:
            event_id, event_type, created_at, payload = row
            events.append(
                EventDTO(
                    id=str(event_id),
                    event_type=event_type,
                    created_at=created_at,
                    payload=payload or {},
                )
            )

        return events

    except Exception as e:
        logger.error(
            "Failed to get timeline for entity %s: %s",
            entity_id_str,
            str(e),
        )
        return []


async def get_entity_id_for_judgment(judgment_id: int) -> Optional[UUID]:
    """
    Get the defendant entity ID for a judgment.

    Looks up the defendant entity via the intelligence graph relationships.

    Args:
        judgment_id: The judgment ID to look up

    Returns:
        UUID of the defendant entity, or None if not found
    """
    try:
        conn = await get_pool()
        if conn is None:
            return None

        async with conn.cursor() as cur:
            # Use the helper function we created in the migration
            await cur.execute(
                """
                SELECT intelligence.get_defendant_entity_for_judgment(%s)
                """,
                (judgment_id,),
            )
            row = await cur.fetchone()

            if row and row[0]:
                return UUID(str(row[0]))

            return None

    except Exception as e:
        logger.warning(
            "Failed to get entity_id for judgment %s: %s",
            judgment_id,
            str(e),
        )
        return None


async def get_timeline_for_judgment(
    judgment_id: int,
    limit: int = 100,
) -> list[EventDTO]:
    """
    Get the event timeline for a judgment.

    Convenience wrapper that first looks up the defendant entity,
    then returns the timeline for that entity.

    Args:
        judgment_id: The judgment ID to get timeline for
        limit: Maximum number of events to return (default 100)

    Returns:
        List of EventDTO objects, or empty list if no entity found
    """
    entity_id = await get_entity_id_for_judgment(judgment_id)

    if entity_id is None:
        logger.debug(
            "No defendant entity found for judgment %s - returning empty timeline",
            judgment_id,
        )
        return []

    return await get_timeline_for_entity(entity_id, limit=limit)


# =============================================================================
# Helper: Emit with entity lookup
# =============================================================================


async def emit_event_for_judgment(
    judgment_id: int,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
) -> None:
    """
    Emit an event for a judgment by looking up its defendant entity.

    This is a convenience wrapper for emit_event that first looks up
    the defendant entity for the judgment.

    Args:
        judgment_id: The judgment ID
        event_type: Type of event
        payload: Optional event-specific data

    Returns:
        None (best-effort, never raises)
    """
    try:
        entity_id = await get_entity_id_for_judgment(judgment_id)

        if entity_id is None:
            logger.debug(
                "No defendant entity found for judgment %s - skipping event emission",
                judgment_id,
            )
            return

        await emit_event(entity_id, event_type, payload)

    except Exception as e:
        logger.warning(
            "Failed to emit event for judgment %s: %s",
            judgment_id,
            str(e),
        )
