"""
Dragonfly Engine - Webhooks Router

Handles incoming webhooks from external service providers:
- Proof.com (process server dispatches)
- Future: Payment processors, court filing services, etc.
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/webhooks", tags=["Webhooks"])


# =============================================================================
# Proof.com Webhook Models
# =============================================================================


class ProofWebhookEvent(BaseModel):
    """Incoming webhook event from Proof.com."""

    event_type: str = Field(..., description="Event type (e.g., job.status_changed)")
    job_id: str = Field(..., description="Proof.com job ID")
    timestamp: str = Field(..., description="Event timestamp ISO string")
    data: dict[str, Any] = Field(default_factory=dict, description="Event payload")


class ProofJobStatusData(BaseModel):
    """Status update data from Proof.com."""

    status: str = Field(..., description="New job status")
    previous_status: str | None = Field(None, description="Previous status")
    attempts_made: int | None = Field(None, description="Number of attempts")
    served_at: str | None = Field(None, description="Service completion timestamp")
    served_to: str | None = Field(None, description="Person who received service")
    service_notes: str | None = Field(None, description="Notes from process server")
    proof_url: str | None = Field(None, description="URL to affidavit/proof document")
    actual_cost: float | None = Field(None, description="Actual service cost")
    latitude: float | None = Field(None, description="Service location latitude")
    longitude: float | None = Field(None, description="Service location longitude")
    service_address: str | None = Field(None, description="Service address")


class WebhookResponse(BaseModel):
    """Standard webhook response."""

    received: bool = True
    message: str = "Webhook processed"


# =============================================================================
# Proof.com Status Mapping
# =============================================================================

# Map Proof.com statuses to our internal statuses
PROOF_STATUS_MAP: dict[str, str] = {
    "pending": "created",
    "assigned": "assigned",
    "in_progress": "out_for_service",
    "out_for_delivery": "out_for_service",
    "attempted": "attempted",
    "completed": "served",
    "served": "served",
    "failed": "failed",
    "cancelled": "cancelled",
}


# =============================================================================
# Signature Verification
# =============================================================================


def verify_proof_signature(
    payload: bytes,
    signature: str | None,
    timestamp: str | None,
    secret: str | None,
) -> bool:
    """
    Verify Proof.com webhook signature.

    Args:
        payload: Raw request body
        signature: X-Proof-Signature header
        timestamp: X-Proof-Timestamp header
        secret: Webhook secret from settings

    Returns:
        True if signature is valid or verification is disabled
    """
    if not secret:
        logger.warning(
            "PROOF_WEBHOOK_SECRET not configured - skipping signature verification"
        )
        return True

    if not signature:
        logger.warning("Missing X-Proof-Signature header")
        return False

    # Build signed payload
    if timestamp:
        signed_payload = f"{timestamp}.".encode() + payload
    else:
        signed_payload = payload

    expected = hmac.new(
        secret.encode(),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


# =============================================================================
# Proof.com Webhook Endpoint
# =============================================================================


@router.post("/proof", response_model=WebhookResponse)
async def proof_webhook(
    request: Request,
    x_proof_signature: str | None = Header(None, alias="X-Proof-Signature"),
    x_proof_timestamp: str | None = Header(None, alias="X-Proof-Timestamp"),
) -> WebhookResponse:
    """
    Handle incoming webhooks from Proof.com.

    Updates serve_jobs status and syncs to judgments when service is completed.

    Webhook Events:
    - job.created: Job accepted by Proof
    - job.assigned: Server assigned to job
    - job.status_changed: Status update (out_for_service, attempted, served, failed)
    - job.completed: Service successfully completed
    - job.failed: All attempts exhausted
    - job.cancelled: Job was cancelled
    """
    # Read raw body for signature verification
    body = await request.body()

    # Get webhook secret from environment (via settings)
    import os

    webhook_secret = os.getenv("PROOF_WEBHOOK_SECRET")

    # Verify signature
    if not verify_proof_signature(
        body, x_proof_signature, x_proof_timestamp, webhook_secret
    ):
        logger.error("Invalid Proof.com webhook signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in Proof.com webhook")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = payload.get("event_type", "unknown")
    job_id = payload.get("job_id")
    data = payload.get("data", {})

    logger.info(
        "Received Proof.com webhook",
        extra={
            "event_type": event_type,
            "job_id": job_id,
        },
    )

    if not job_id:
        logger.warning("Proof.com webhook missing job_id")
        return WebhookResponse(message="No job_id provided")

    # Get Supabase client
    supabase = get_supabase_client()

    # Find the serve job by provider_job_id
    result = (
        supabase.table("serve_jobs")
        .select("*")
        .eq("provider_job_id", job_id)
        .eq("provider", "proof.com")
        .execute()
    )

    if not result.data:
        logger.warning(f"Serve job not found for Proof.com job_id: {job_id}")
        # Still return 200 to acknowledge receipt
        return WebhookResponse(message="Job not found in database")

    serve_job = result.data[0]
    serve_job_id = serve_job["id"]
    judgment_id = serve_job["judgment_id"]

    # Map Proof status to our status
    proof_status = data.get("status", "").lower()
    internal_status = PROOF_STATUS_MAP.get(proof_status, serve_job["status"])

    # Build update payload
    now = datetime.utcnow().isoformat()
    update_data: dict[str, Any] = {
        "status": internal_status,
        "last_webhook_at": now,
        "updated_at": now,
    }

    # Add additional fields if present
    if data.get("attempts_made") is not None:
        update_data["attempts_made"] = data["attempts_made"]

    if data.get("actual_cost") is not None:
        update_data["actual_cost"] = data["actual_cost"]

    if data.get("proof_url"):
        update_data["proof_url"] = data["proof_url"]

    if data.get("served_at"):
        update_data["served_at"] = data["served_at"]

    if data.get("served_to"):
        update_data["served_to"] = data["served_to"]

    if data.get("service_notes"):
        update_data["service_notes"] = data["service_notes"]

    if data.get("latitude") is not None:
        update_data["service_latitude"] = data["latitude"]

    if data.get("longitude") is not None:
        update_data["service_longitude"] = data["longitude"]

    if data.get("service_address"):
        update_data["service_address"] = data["service_address"]

    # Append to webhook_events array for audit trail
    webhook_event = {
        "event_type": event_type,
        "timestamp": payload.get("timestamp", now),
        "data": data,
        "received_at": now,
    }

    # Use SQL to append to JSONB array
    supabase.rpc(
        "jsonb_array_append",
        {
            "table_name": "enforcement.serve_jobs",
            "id": serve_job_id,
            "column_name": "webhook_events",
            "new_element": json.dumps(webhook_event),
        },
    ).execute()

    # Update serve_jobs record
    supabase.schema("enforcement").table("serve_jobs").update(update_data).eq(
        "id", serve_job_id
    ).execute()

    logger.info(
        f"Updated serve job {serve_job_id}",
        extra={
            "old_status": serve_job["status"],
            "new_status": internal_status,
            "judgment_id": judgment_id,
        },
    )

    # If status is 'served', update the judgment status
    if internal_status == "served":
        supabase.table("judgments").update(
            {
                "status": "served",
                "updated_at": now,
            }
        ).eq("id", judgment_id).execute()

        logger.info(
            f"Updated judgment {judgment_id} status to 'served'",
            extra={"serve_job_id": serve_job_id},
        )

    return WebhookResponse(message=f"Processed {event_type} for job {job_id}")


# =============================================================================
# Health Check for Webhook Endpoint
# =============================================================================


@router.get("/proof/health")
async def proof_webhook_health() -> dict[str, str]:
    """Health check for Proof.com webhook endpoint."""
    return {
        "status": "ok",
        "endpoint": "/api/v1/webhooks/proof",
        "method": "POST",
    }
