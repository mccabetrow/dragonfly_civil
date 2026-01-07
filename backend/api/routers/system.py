"""
Dragonfly Engine - System Router

API endpoints for system health and status monitoring.
Provides worker heartbeat status and queue depth information.

Endpoints:
    GET /api/v1/system/status - System health status from v_system_health
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...api import ApiResponse, api_response, degraded_response
from ...core.security import AuthContext, get_current_user
from ...db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/system", tags=["System"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class WorkerStatus(BaseModel):
    """Status of a single worker type."""

    status: str = Field(..., description="'online' or 'offline'")
    last_heartbeat: Optional[str] = Field(None, description="ISO timestamp of last heartbeat")


class SystemStatusData(BaseModel):
    """
    System health status data.

    This is the data field inside the ApiResponse envelope.
    """

    ingest_worker: WorkerStatus = Field(..., description="Ingest processor worker status")
    enforcement_worker: WorkerStatus = Field(..., description="Enforcement engine worker status")
    queue_depth: int = Field(0, description="Number of pending jobs in queue")
    queue_processing: int = Field(0, description="Number of jobs currently processing")
    checked_at: str = Field(..., description="ISO timestamp when status was checked")
    all_workers_online: bool = Field(..., description="True if all workers are online")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=ApiResponse[SystemStatusData],
    summary="Get system health status",
    description="Returns worker heartbeat status and queue depth from ops.v_system_health.",
)
async def system_status(
    auth: AuthContext = Depends(get_current_user),
) -> ApiResponse[SystemStatusData]:
    """
    Get current system health status.

    Returns:
        - Worker status (online/offline) based on heartbeat freshness
        - Queue depth (pending and processing jobs)
        - Whether all workers are online

    Workers are considered 'online' if they sent a heartbeat within the last 60 seconds.
    """
    pool = get_pool()

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM ops.v_system_health")
                row = await cur.fetchone()

                if row is None:
                    # View returned no rows (shouldn't happen, but handle gracefully)
                    return degraded_response(
                        error="System health view returned no data",
                        data=SystemStatusData(
                            ingest_worker=WorkerStatus(status="unknown", last_heartbeat=None),
                            enforcement_worker=WorkerStatus(status="unknown", last_heartbeat=None),
                            queue_depth=0,
                            queue_processing=0,
                            checked_at=datetime.utcnow().isoformat() + "Z",
                            all_workers_online=False,
                        ),
                    )

                # Parse row (column order from view definition)
                (
                    ingest_status,
                    ingest_last_heartbeat,
                    enforcement_status,
                    enforcement_last_heartbeat,
                    queue_depth,
                    queue_processing,
                    checked_at,
                ) = row

                ingest_worker = WorkerStatus(
                    status=ingest_status or "offline",
                    last_heartbeat=(
                        ingest_last_heartbeat.isoformat() if ingest_last_heartbeat else None
                    ),
                )
                enforcement_worker = WorkerStatus(
                    status=enforcement_status or "offline",
                    last_heartbeat=(
                        enforcement_last_heartbeat.isoformat()
                        if enforcement_last_heartbeat
                        else None
                    ),
                )

                all_online = ingest_status == "online" and enforcement_status == "online"

                data = SystemStatusData(
                    ingest_worker=ingest_worker,
                    enforcement_worker=enforcement_worker,
                    queue_depth=queue_depth or 0,
                    queue_processing=queue_processing or 0,
                    checked_at=(
                        checked_at.isoformat()
                        if checked_at
                        else datetime.utcnow().isoformat() + "Z"
                    ),
                    all_workers_online=all_online,
                )

                return api_response(data=data)

    except Exception as e:
        logger.exception(f"Error fetching system status: {e}")
        # Return degraded response with fallback data
        return degraded_response(
            error=f"Failed to fetch system status: {type(e).__name__}",
            data=SystemStatusData(
                ingest_worker=WorkerStatus(status="unknown", last_heartbeat=None),
                enforcement_worker=WorkerStatus(status="unknown", last_heartbeat=None),
                queue_depth=0,
                queue_processing=0,
                checked_at=datetime.utcnow().isoformat() + "Z",
                all_workers_online=False,
            ),
        )


@router.get(
    "/health",
    response_model=dict,
    summary="System health check",
    description="Simple health check endpoint for system router.",
)
async def system_health() -> dict:
    """Simple health check for the system router."""
    return {"status": "ok", "subsystem": "system"}
