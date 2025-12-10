"""
Dragonfly Engine - Telemetry Router

Endpoints for capturing UI telemetry events from the dashboard.
Provides a lightweight, fire-and-forget API for tracking user interactions.
"""

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ..core.security import AuthContext, get_current_user
from ..db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/telemetry", tags=["Telemetry"])


# ═══════════════════════════════════════════════════════════════════════════
# REQUEST/RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════


class UiActionRequest(BaseModel):
    """Request body for logging a UI action."""

    event_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Event type identifier (e.g., 'intake.upload_submitted')",
        examples=["intake.upload_submitted", "enforcement.generate_packet_clicked"],
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific metadata",
        examples=[{"batch_id": "abc-123", "row_count": 50}],
    )
    session_id: str | None = Field(
        default=None,
        max_length=255,
        description="Optional client-side session identifier for event correlation",
    )

    @field_validator("event_name")
    @classmethod
    def validate_event_name(cls, v: str) -> str:
        """Ensure event_name follows naming conventions."""
        v = v.strip()
        if not v:
            raise ValueError("event_name cannot be empty")
        # Allow alphanumeric, dots, underscores, and hyphens
        allowed_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
        if not all(c in allowed_chars for c in v):
            raise ValueError(
                "event_name can only contain letters, numbers, dots, underscores, and hyphens"
            )
        return v


class UiActionResponse(BaseModel):
    """Response confirming the UI action was logged."""

    status: str = "ok"
    event_id: str = Field(..., description="The generated UUID for this event")


class UiActionErrorResponse(BaseModel):
    """Error response for telemetry operations."""

    status: str = "error"
    error: str
    detail: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post(
    "/ui-action",
    response_model=UiActionResponse,
    responses={
        400: {"model": UiActionErrorResponse, "description": "Invalid request payload"},
        500: {"model": UiActionErrorResponse, "description": "Database insert failed"},
    },
    summary="Log a UI action",
    description=(
        "Captures a UI interaction event from the dashboard. "
        "Events are stored in ops.ui_actions for analytics and debugging. "
        "This is a fire-and-forget endpoint - errors are logged but should not block UI."
    ),
)
async def log_ui_action(
    request: UiActionRequest,
    auth: AuthContext = Depends(get_current_user),
) -> UiActionResponse:
    """
    Log a UI action event to the telemetry table.

    Args:
        request: The UI action event data
        auth: Authentication context (provides user_id if available)

    Returns:
        UiActionResponse with the generated event ID
    """
    logger.debug(
        f"UI action received: event={request.event_name}, "
        f"session={request.session_id}, auth={auth.via}"
    )

    try:
        # Extract user_id if authenticated with a real user (JWT auth)
        user_id: UUID | None = None
        if auth.subject and auth.via == "jwt":
            try:
                user_id = UUID(auth.subject)
            except ValueError:
                # Invalid UUID format - log and continue without user_id
                logger.warning(f"Invalid user_id format: {auth.subject}")

        # Insert into ops.ui_actions
        sql = """
            INSERT INTO ops.ui_actions (user_id, session_id, event_name, context)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
        """

        async with get_connection() as conn:
            row = await conn.fetchrow(
                sql,
                user_id,
                request.session_id,
                request.event_name,
                json.dumps(request.context),
            )

        if not row:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "status": "error",
                    "error": "telemetry_insert_failed",
                    "detail": "Failed to insert telemetry event",
                },
            )

        event_id = str(row["id"])
        logger.info(f"UI action logged: id={event_id}, event={request.event_name}")

        return UiActionResponse(status="ok", event_id=event_id)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to log UI action: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "status": "error",
                "error": "telemetry_insert_failed",
                "detail": str(e),
            },
        )


@router.get(
    "/health",
    response_model=dict[str, str],
    summary="Telemetry health check",
    description="Verifies the telemetry subsystem is operational.",
)
async def telemetry_health() -> dict[str, str]:
    """
    Health check for telemetry endpoint.

    Returns:
        Status dict indicating telemetry is operational
    """
    return {"status": "ok", "subsystem": "telemetry"}
