"""
Enforcement API endpoints for Mom's Console.

These endpoints wrap Supabase RPCs and provide a clean interface
for the frontend to call when logging enforcement actions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.api.app import _get_supabase_client_cached, _normalize_env, require_api_key

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enforcement", tags=["enforcement"])


class MarkSignedRequest(BaseModel):
    """Request to mark an enforcement action as signed."""

    action_id: str = Field(..., min_length=1, description="UUID of the enforcement_action")
    notes: Optional[str] = Field(default=None, description="Optional notes about the signature")
    signed_at: Optional[datetime] = Field(default=None, description="When the document was signed")


class MarkSignedResponse(BaseModel):
    """Response after marking an action as signed."""

    action_id: str
    status: str
    updated_at: str


class LogCallOutcomeRequest(BaseModel):
    """Request to log a call outcome from the call queue."""

    plaintiff_id: str = Field(..., min_length=1)
    task_id: str = Field(..., min_length=1)
    outcome: str = Field(..., description="reached|left_voicemail|no_answer|bad_number|do_not_call")
    interest: Optional[str] = Field(default="none", description="hot|warm|cold|none")
    notes: Optional[str] = Field(default=None)
    follow_up_at: Optional[datetime] = Field(default=None)


class LogCallOutcomeResponse(BaseModel):
    """Response after logging a call outcome."""

    task_id: str
    plaintiff_id: str
    status: str


class CreateEnforcementActionRequest(BaseModel):
    """Request to create a new enforcement action."""

    judgment_id: str = Field(..., min_length=1)
    action_type: str = Field(
        ...,
        description="wage_garnishment|bank_levy|property_lien|information_subpoena|restraining_notice|other",
    )
    requires_attorney_signature: bool = Field(default=True)
    notes: Optional[str] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class CreateEnforcementActionResponse(BaseModel):
    """Response after creating an enforcement action."""

    action_id: str
    judgment_id: str
    action_type: str
    status: str


@router.post("/mark_signed", response_model=MarkSignedResponse)
async def mark_action_signed(
    body: MarkSignedRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
) -> MarkSignedResponse:
    """
    Mark an enforcement action as signed by the attorney.

    This updates the action status to 'completed' and records the signature.
    Called from Mom's Enforcement Console when she clicks "Signed & Sent".
    """
    env = _normalize_env(env_override)
    client = _get_supabase_client_cached(env)

    try:
        # Call the update_enforcement_action_status RPC
        result = client.rpc(
            "update_enforcement_action_status",
            {
                "_action_id": body.action_id,
                "_status": "completed",
                "_notes": body.notes or "Signed and sent by attorney",
            },
        ).execute()

        if result.data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Enforcement action {body.action_id} not found",
            )

        return MarkSignedResponse(
            action_id=body.action_id,
            status="completed",
            updated_at=datetime.utcnow().isoformat(),
        )

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Failed to mark action as signed: %s", body.action_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to mark action as signed: {exc}",
        ) from exc


@router.post("/log_call_outcome", response_model=LogCallOutcomeResponse)
async def log_call_outcome(
    body: LogCallOutcomeRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
) -> LogCallOutcomeResponse:
    """
    Log a call outcome from the call queue.

    This is called when Mom logs the result of a plaintiff call.
    Wraps the log_call_outcome RPC.
    """
    env = _normalize_env(env_override)
    client = _get_supabase_client_cached(env)

    try:
        result = client.rpc(
            "log_call_outcome",
            {
                "_plaintiff_id": body.plaintiff_id,
                "_task_id": body.task_id,
                "_outcome": body.outcome,
                "_interest": body.interest or "none",
                "_notes": body.notes,
                "_follow_up_at": (body.follow_up_at.isoformat() if body.follow_up_at else None),
            },
        ).execute()

        if result.data is None:
            LOGGER.warning("log_call_outcome returned no data for task %s", body.task_id)

        return LogCallOutcomeResponse(
            task_id=body.task_id,
            plaintiff_id=body.plaintiff_id,
            status="logged",
        )

    except Exception as exc:
        LOGGER.exception("Failed to log call outcome: %s", body.task_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to log call outcome: {exc}",
        ) from exc


@router.post("/create_action", response_model=CreateEnforcementActionResponse)
async def create_enforcement_action(
    body: CreateEnforcementActionRequest,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
) -> CreateEnforcementActionResponse:
    """
    Create a new enforcement action for a judgment.

    This is typically called by the enforcement planner worker,
    but can also be triggered manually for ad-hoc actions.
    """
    env = _normalize_env(env_override)
    client = _get_supabase_client_cached(env)

    try:
        # Direct insert into enforcement_actions table
        insert_data = {
            "judgment_id": body.judgment_id,
            "action_type": body.action_type,
            "status": "planned",
            "requires_attorney_signature": body.requires_attorney_signature,
            "notes": body.notes,
        }
        if body.metadata:
            insert_data["metadata"] = body.metadata

        result = client.table("enforcement_actions").insert(insert_data).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create enforcement action",
            )

        action_data = result.data[0]
        return CreateEnforcementActionResponse(
            action_id=action_data["id"],
            judgment_id=body.judgment_id,
            action_type=body.action_type,
            status="planned",
        )

    except HTTPException:
        raise
    except Exception as exc:
        LOGGER.exception("Failed to create enforcement action for judgment %s", body.judgment_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create enforcement action: {exc}",
        ) from exc


@router.get("/pending_signatures")
async def get_pending_signatures(
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
    limit: int = 100,
) -> Dict[str, Any]:
    """
    Get all enforcement actions pending attorney signature.

    This is a convenience endpoint that mirrors the v_enforcement_actions_pending_signature view.
    """
    env = _normalize_env(env_override)
    client = _get_supabase_client_cached(env)

    try:
        result = (
            client.table("v_enforcement_actions_pending_signature")
            .select("*")
            .limit(limit)
            .execute()
        )

        return {
            "count": len(result.data or []),
            "actions": result.data or [],
        }

    except Exception as exc:
        LOGGER.exception("Failed to fetch pending signatures")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch pending signatures: {exc}",
        ) from exc


@router.get("/pipeline_status")
async def get_pipeline_status(
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
    limit: int = 200,
) -> Dict[str, Any]:
    """
    Get the current enforcement pipeline status.

    Returns judgments grouped by pipeline stage with counts.
    """
    env = _normalize_env(env_override)
    client = _get_supabase_client_cached(env)

    try:
        result = client.table("v_enforcement_pipeline_status").select("*").limit(limit).execute()

        rows = result.data or []

        # Calculate stage counts
        stage_counts: Dict[str, int] = {}
        for row in rows:
            stage = row.get("pipeline_stage", "unknown")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

        return {
            "total_count": len(rows),
            "stage_counts": stage_counts,
            "judgments": rows,
        }

    except Exception as exc:
        LOGGER.exception("Failed to fetch pipeline status")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch pipeline status: {exc}",
        ) from exc
