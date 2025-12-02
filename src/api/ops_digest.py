"""
Ops Digest API endpoints for n8n notifications.

These endpoints provide read-only summary data for n8n workflows
to format and post to Discord/Slack without any business logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from src.api.app import require_api_key, _normalize_env, _get_supabase_client_cached

LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ops", tags=["ops"])


class PipelineStageCounts(BaseModel):
    """Counts of judgments by pipeline stage."""

    awaiting_enrichment: int = 0
    awaiting_action_plan: int = 0
    awaiting_signature: int = 0
    actions_in_progress: int = 0
    actions_complete: int = 0
    closed: int = 0
    unknown: int = 0


class CallQueueItem(BaseModel):
    """A single item in the call queue."""

    plaintiff_name: str
    tier: str
    phone: Optional[str]
    due_at: Optional[str]
    total_judgment_amount: Optional[float]


class OpsDigestResponse(BaseModel):
    """Daily ops digest summary for n8n notification."""

    generated_at: str = Field(description="ISO timestamp when digest was generated")
    pipeline_counts: PipelineStageCounts
    total_cases: int
    pending_signatures: int
    call_queue_count: int
    call_queue_top10: List[CallQueueItem]
    enforcement_stalled: int = Field(
        description="Cases >3 days in current enforcement stage"
    )


class EnrichmentCompletePayload(BaseModel):
    """Webhook payload when enrichment worker completes."""

    judgment_id: str
    case_index_number: str
    debtor_name: str
    principal_amount: float
    collectability_score: int
    employer_name: Optional[str] = None
    income_band: str = "UNKNOWN"


class WebhookResponse(BaseModel):
    """Standard webhook response."""

    status: str
    message: Optional[str] = None


@router.get("/digest", response_model=OpsDigestResponse)
async def get_ops_digest(
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
) -> OpsDigestResponse:
    """
    Get daily ops digest data for n8n notifications.

    Returns:
    - Pipeline stage counts
    - Pending signatures count
    - Top 10 call queue plaintiffs
    - Stalled enforcement case count

    n8n calls this endpoint and formats the response for Discord.
    """
    target_env = _normalize_env(env_override)
    supabase = _get_supabase_client_cached(target_env)

    # Fetch pipeline status counts
    pipeline_counts = PipelineStageCounts()
    try:
        pipeline_response = (
            supabase.table("v_enforcement_pipeline_status")
            .select("pipeline_stage")
            .execute()
        )
        rows = pipeline_response.data or []
        for row in rows:
            stage = row.get("pipeline_stage", "unknown")
            if hasattr(pipeline_counts, stage):
                setattr(pipeline_counts, stage, getattr(pipeline_counts, stage) + 1)
            else:
                pipeline_counts.unknown += 1
    except Exception as exc:
        LOGGER.warning("Failed to fetch pipeline status: %s", exc)

    total_cases = sum(
        [
            pipeline_counts.awaiting_enrichment,
            pipeline_counts.awaiting_action_plan,
            pipeline_counts.awaiting_signature,
            pipeline_counts.actions_in_progress,
            pipeline_counts.actions_complete,
            pipeline_counts.closed,
            pipeline_counts.unknown,
        ]
    )

    # Fetch pending signatures count
    pending_signatures = 0
    try:
        sig_response = (
            supabase.table("v_enforcement_actions_pending_signature")
            .select("action_id", count="exact")
            .limit(1)
            .execute()
        )
        pending_signatures = sig_response.count or 0
    except Exception as exc:
        LOGGER.warning("Failed to fetch pending signatures: %s", exc)

    # Fetch call queue top 10
    call_queue_items: List[CallQueueItem] = []
    try:
        queue_response = (
            supabase.table("v_plaintiff_call_queue")
            .select("plaintiff_name,tier,phone,due_at,total_judgment_amount")
            .order("due_at", desc=False, nullsfirst=True)
            .limit(10)
            .execute()
        )
        for row in queue_response.data or []:
            call_queue_items.append(
                CallQueueItem(
                    plaintiff_name=row.get("plaintiff_name", "Unknown"),
                    tier=row.get("tier", "?"),
                    phone=row.get("phone"),
                    due_at=row.get("due_at"),
                    total_judgment_amount=row.get("total_judgment_amount"),
                )
            )
    except Exception as exc:
        LOGGER.warning("Failed to fetch call queue: %s", exc)

    # Fetch stalled enforcement cases (>3 days in stage)
    enforcement_stalled = 0
    try:
        stalled_response = (
            supabase.table("v_enforcement_overview")
            .select("case_id", count="exact")
            .gte("days_in_stage", 3)
            .limit(1)
            .execute()
        )
        enforcement_stalled = stalled_response.count or 0
    except Exception as exc:
        LOGGER.warning("Failed to fetch stalled enforcement: %s", exc)

    return OpsDigestResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        pipeline_counts=pipeline_counts,
        total_cases=total_cases,
        pending_signatures=pending_signatures,
        call_queue_count=len(call_queue_items),
        call_queue_top10=call_queue_items,
        enforcement_stalled=enforcement_stalled,
    )


@router.post("/webhooks/enrichment-complete", response_model=WebhookResponse)
async def enrichment_complete_webhook(
    payload: EnrichmentCompletePayload,
    _: None = Depends(require_api_key),
    env_override: Optional[str] = Header(default=None, alias="X-Dragonfly-Env"),
) -> WebhookResponse:
    """
    Webhook called by enrich_worker after successful enrichment.

    This endpoint can:
    1. Trigger n8n webhook for Discord notification
    2. Or directly post to Discord (if webhook URL configured)
    3. Or queue a notification job

    For now, it just acknowledges the enrichment and logs it.
    The actual notification is handled by n8n polling or webhook.
    """
    LOGGER.info(
        "Enrichment complete for judgment %s (case %s, score %d)",
        payload.judgment_id,
        payload.case_index_number,
        payload.collectability_score,
    )

    # In the future, this could:
    # - Call n8n webhook directly
    # - Queue a notify_ops job
    # - Post directly to Discord via webhook

    return WebhookResponse(
        status="ok",
        message=f"Enrichment notification received for {payload.case_index_number}",
    )
