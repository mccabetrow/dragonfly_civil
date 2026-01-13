"""
Dragonfly Engine - Platform Router

Top-level platform endpoints for version and readiness checks.
These endpoints are mounted directly at /api without additional prefix.

Endpoints:
    GET /api/version - Version info (no DB touch)
    GET /api/ready   - Full readiness probe with DB/views/auth validation
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import __version__
from ...config import get_settings
from ...core.trace_middleware import get_trace_id
from ...db import fetch_val, get_pool, get_supabase_client
from ...maintenance.schema_guard import get_schema_guard

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Platform"])

# Views that must exist for the system to be operational
REQUIRED_VIEWS = [
    "v_plaintiffs_overview",
    "v_judgment_pipeline",
    "v_enforcement_overview",
]

# Hard fail reason shared across readiness probes
FAILURE_REASON = "not_ready"
SCHEMA_GUARD_TIMEOUT_SECONDS = 5.0


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class VersionResponse(BaseModel):
    """Version endpoint response - never touches database."""

    git_sha: str = Field(..., description="Git commit SHA (from GIT_SHA or RENDER_GIT_COMMIT)")
    environment: str = Field(..., description="Deployment environment (dev/staging/prod)")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Application version")
    timestamp: str = Field(..., description="ISO timestamp of response")


class ReadinessResponse(BaseModel):
    """Readiness probe response."""

    ready: bool = Field(..., description="True if all checks pass")
    checks: dict[str, bool] = Field(..., description="Individual check results")
    timestamp: str = Field(..., description="ISO timestamp of check")
    trace_id: str = Field(..., description="Request trace identifier")
    # Only included on failure - redacted details
    failure_reason: str | None = Field(
        None, description="High-level failure reason (redacted for security)"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Get API version and environment",
    description=(
        "Returns version info including git SHA, environment, and service name. "
        "Never queries the database - safe for frequent polling."
    ),
)
async def get_version() -> VersionResponse:
    """
    Get platform version information.

    This endpoint never touches the database, making it suitable for
    high-frequency health polling by load balancers and monitoring tools.

    Returns:
        Version info including git_sha, environment, service name, and timestamp
    """
    settings = get_settings()

    # Get git SHA from environment (Railway sets RENDER_GIT_COMMIT, Railway also sets GIT_SHA)
    git_sha = os.environ.get("GIT_SHA") or os.environ.get("RENDER_GIT_COMMIT") or "unknown"

    return VersionResponse(
        git_sha=git_sha[:8] if len(git_sha) > 8 else git_sha,
        environment=settings.ENVIRONMENT,
        service="DragonflyAPI",
        version=__version__,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={
        200: {"description": "Service is ready to accept traffic"},
        503: {"description": "Service is not ready - see failure_reason"},
    },
    summary="Readiness probe",
    description=(
        "Full readiness check validating database connectivity, required views, "
        "and Supabase authentication. Returns 200 if ready, 503 if not."
    ),
)
async def readiness_check() -> ReadinessResponse | JSONResponse:
    """
    Kubernetes-style readiness probe with comprehensive checks.

    Validates:
    1. Database connectivity (psycopg pool)
    2. Required views exist (v_plaintiffs_overview, v_judgment_pipeline, etc.)
    3. Supabase client can authenticate

    Returns 200 OK if all checks pass, 503 Service Unavailable with
    redacted failure reason otherwise.
    """
    trace_id = get_trace_id()
    checks: dict[str, bool] = {}
    failure_details: list[str] = []

    # Check 1: Database connectivity
    try:
        pool = await get_pool()
        if pool:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    await cur.fetchone()
            checks["database"] = True
        else:
            checks["database"] = False
            failure_details.append("database_pool_unavailable")
    except Exception as e:
        logger.warning(f"Readiness: DB connectivity failed - {type(e).__name__}")
        checks["database"] = False
        failure_details.append("database_connection_failed")

    # Check 2: Required views exist
    if checks.get("database"):
        try:
            pool = await get_pool()
            if pool:
                async with pool.connection() as conn:
                    async with conn.cursor() as cur:
                        # Check if required views exist in information_schema
                        await cur.execute(
                            """
                            SELECT table_name
                            FROM information_schema.views
                            WHERE table_schema = 'public'
                              AND table_name = ANY(%s)
                            """,
                            (REQUIRED_VIEWS,),
                        )
                        found_views = {row[0] for row in await cur.fetchall()}
                        missing_views = set(REQUIRED_VIEWS) - found_views

                        if missing_views:
                            checks["views"] = False
                            failure_details.append("required_views_missing")
                            logger.warning(f"Readiness: Missing views - {missing_views}")
                        else:
                            checks["views"] = True
        except Exception as e:
            logger.warning(f"Readiness: View check failed - {type(e).__name__}")
            checks["views"] = False
            failure_details.append("view_check_failed")
    else:
        checks["views"] = False
        failure_details.append("skipped_view_check_no_db")

    # Check 3: Supabase client authentication
    try:
        client = get_supabase_client()
        # Lightweight check - just verify the client can make an authenticated request
        # Query a system table with limit 1 to minimize overhead
        client.table("plaintiffs").select("id").limit(1).execute()
        checks["supabase_auth"] = True
    except Exception as e:
        logger.warning(f"Readiness: Supabase auth failed - {type(e).__name__}")
        checks["supabase_auth"] = False
        failure_details.append("supabase_auth_failed")

    # Check 4: Schema Guard (skip if database already unhealthy)
    schema_guard_ready = False
    if checks.get("database"):
        guard = get_schema_guard()
        try:
            drift_detected = await asyncio.wait_for(
                guard.check_schema_drift(), timeout=SCHEMA_GUARD_TIMEOUT_SECONDS
            )
            schema_guard_ready = not drift_detected
            if drift_detected:
                failure_details.append("schema_guard_drift_detected")
                logger.warning("Readiness: Schema guard detected drift")
        except asyncio.TimeoutError:
            failure_details.append("schema_guard_timeout")
            logger.warning("Readiness: Schema guard check timed out")
        except Exception as exc:
            failure_details.append("schema_guard_error")
            logger.warning(f"Readiness: Schema guard check failed - {type(exc).__name__}")
    checks["schema_guard"] = schema_guard_ready if checks.get("database") else False
    if not checks.get("database"):
        failure_details.append("schema_guard_skipped_no_db")

    # Build response
    is_ready = all(checks.values()) and len(checks) > 0
    timestamp = datetime.now(timezone.utc).isoformat()

    if is_ready:
        return ReadinessResponse(
            ready=True,
            checks=checks,
            timestamp=timestamp,
            trace_id=trace_id,
            failure_reason=None,
        )
    else:
        # Return 503 with redacted failure reason
        response = ReadinessResponse(
            ready=False,
            checks=checks,
            timestamp=timestamp,
            trace_id=trace_id,
            failure_reason=FAILURE_REASON,
        )
        logger.warning(
            "Readiness: failing checks=%s details=%s",
            {k: v for k, v in checks.items() if not v},
            failure_details,
        )
        return JSONResponse(status_code=503, content=response.model_dump())
