"""
Dragonfly Engine - Enforcement Router

Provides endpoints for enforcement workflow management including the Radar.
"""

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user
from ..db import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/enforcement", tags=["Enforcement"])


# =============================================================================
# Radar Models
# =============================================================================


class RadarRow(BaseModel):
    """Single row in the Enforcement Radar."""

    id: str = Field(..., description="Judgment ID")
    case_number: str = Field(..., description="Court case number")
    plaintiff_name: str = Field(..., description="Plaintiff name")
    defendant_name: str = Field(..., description="Defendant name")
    judgment_amount: float = Field(..., description="Judgment amount in dollars")
    collectability_score: Optional[int] = Field(None, description="Collectability score 0-100")
    offer_strategy: str = Field(
        ..., description="BUY_CANDIDATE, CONTINGENCY, ENRICHMENT_PENDING, LOW_PRIORITY"
    )
    court: Optional[str] = Field(None, description="Court name")
    county: Optional[str] = Field(None, description="County")
    judgment_date: Optional[str] = Field(None, description="Judgment date ISO string")
    created_at: str = Field(..., description="Record creation timestamp")


# =============================================================================
# Wage Garnishment Candidate Models
# =============================================================================


class WageGarnishmentCandidate(BaseModel):
    """Single wage garnishment candidate from enforcement.v_candidate_wage_garnishments."""

    plaintiff_id: Optional[str] = Field(None, description="Plaintiff UUID")
    case_number: str = Field(..., description="Court case number")
    defendant_name: Optional[str] = Field(None, description="Defendant name")
    employer_name: str = Field(..., description="Known employer name")
    employer_address: Optional[str] = Field(None, description="Employer address")
    balance: float = Field(..., description="Judgment balance in dollars")
    jurisdiction: Optional[str] = Field(None, description="County/jurisdiction")
    priority_score: float = Field(..., description="Computed priority score")
    # Additional context
    judgment_id: Optional[str] = Field(None, description="Judgment ID")
    plaintiff_name: Optional[str] = Field(None, description="Plaintiff name")
    plaintiff_tier: Optional[str] = Field(None, description="Plaintiff tier")
    judgment_date: Optional[str] = Field(None, description="Judgment date")
    collectability_score: Optional[int] = Field(None, description="Collectability 0-100")
    income_band: Optional[str] = Field(None, description="Estimated income band")
    intel_source: Optional[str] = Field(None, description="Intelligence data source")
    intel_confidence: Optional[float] = Field(None, description="Intel confidence 0-100")
    intel_verified: Optional[bool] = Field(None, description="Human-verified flag")
    enforcement_stage: Optional[str] = Field(None, description="Current enforcement stage")
    status: Optional[str] = Field(None, description="Judgment status")
    created_at: Optional[str] = Field(None, description="Record creation timestamp")


class WageGarnishmentCandidatesResponse(BaseModel):
    """Paginated response for wage garnishment candidates."""

    candidates: list[WageGarnishmentCandidate]
    total: int = Field(..., description="Total matching candidates")
    page: int = Field(..., description="Current page (1-indexed)")
    page_size: int = Field(..., description="Number of items per page")
    has_more: bool = Field(..., description="Whether more pages exist")


# =============================================================================
# Request/Response Models
# =============================================================================


class EnforcementStartRequest(BaseModel):
    """Request to start an enforcement action."""

    case_id: str = Field(..., description="The case ID to start enforcement for")
    strategy: str | None = Field(
        default=None,
        description="Enforcement strategy (e.g., wage_garnishment, bank_levy)",
    )
    priority: Literal["low", "normal", "high", "urgent"] = Field(
        default="normal", description="Priority level for the enforcement action"
    )
    notes: str | None = Field(default=None, description="Optional notes for the enforcement team")


class EnforcementStartResponse(BaseModel):
    """Response from enforcement start request."""

    status: Literal["queued", "started", "rejected", "error"]
    case_id: str
    message: str
    enforcement_id: str | None = None
    estimated_start: str | None = None
    timestamp: str


class EnforcementStatusResponse(BaseModel):
    """Response for enforcement status query."""

    case_id: str
    enforcement_id: str | None
    status: str
    strategy: str | None
    started_at: str | None
    last_update: str | None
    next_action: str | None
    amount_recovered: float | None
    timestamp: str


class EnforcementAction(BaseModel):
    """Details of an enforcement action."""

    action_id: str
    case_id: str
    action_type: str
    status: str
    created_at: str
    completed_at: str | None
    result: str | None
    amount: float | None


class EnforcementHistoryResponse(BaseModel):
    """Response for enforcement history query."""

    case_id: str
    actions: list[EnforcementAction]
    total_recovered: float
    timestamp: str


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/start",
    response_model=EnforcementStartResponse,
    summary="Start enforcement workflow",
    description="Queue a case for enforcement action. Requires authentication.",
)
async def start_enforcement(
    request: EnforcementStartRequest,
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStartResponse:
    """
    Start an enforcement workflow for a case.

    TODO: Implement actual enforcement workflow start including:
    - Validate case is ready for enforcement
    - Check debtor information is complete
    - Queue appropriate enforcement actions
    - Notify enforcement team

    Requires authentication.
    """
    logger.info(
        f"Enforcement start requested by {auth.via}: "
        f"case_id={request.case_id}, strategy={request.strategy}"
    )

    # TODO: Implement actual enforcement workflow
    # For now, return a dummy queued response

    return EnforcementStartResponse(
        status="queued",
        case_id=request.case_id,
        message="TODO: Implement enforcement workflow start. Case queued for processing.",
        enforcement_id=f"ENF-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        estimated_start=datetime.utcnow().isoformat() + "Z",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/status",
    response_model=EnforcementStatusResponse,
    summary="Get enforcement status",
    description="Get the current enforcement status for a case.",
)
async def get_enforcement_status(
    case_id: str = Query(..., description="The case ID to check enforcement for"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStatusResponse:
    """
    Get the enforcement status for a case.

    TODO: Implement actual enforcement status lookup including:
    - Query enforcement actions table
    - Get current stage and progress
    - Return recovery amounts

    Requires authentication.
    """
    logger.info(f"Enforcement status requested by {auth.via}: case_id={case_id}")

    # TODO: Implement actual enforcement status lookup
    # For now, return mock data

    return EnforcementStatusResponse(
        case_id=case_id,
        enforcement_id="ENF-20251203120000",
        status="in_progress",
        strategy="wage_garnishment",
        started_at="2025-11-15T09:00:00Z",
        last_update="2025-12-02T14:30:00Z",
        next_action="Await employer response",
        amount_recovered=1250.00,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.get(
    "/history",
    response_model=EnforcementHistoryResponse,
    summary="Get enforcement history",
    description="Get the full enforcement history for a case.",
)
async def get_enforcement_history(
    case_id: str = Query(..., description="The case ID to get history for"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementHistoryResponse:
    """
    Get the enforcement action history for a case.

    TODO: Implement actual enforcement history lookup.

    Requires authentication.
    """
    logger.info(f"Enforcement history requested by {auth.via}: case_id={case_id}")

    # TODO: Implement actual enforcement history lookup
    # For now, return mock data

    return EnforcementHistoryResponse(
        case_id=case_id,
        actions=[
            EnforcementAction(
                action_id="ACT-001",
                case_id=case_id,
                action_type="wage_garnishment",
                status="active",
                created_at="2025-11-15T09:00:00Z",
                completed_at=None,
                result=None,
                amount=1250.00,
            ),
            EnforcementAction(
                action_id="ACT-002",
                case_id=case_id,
                action_type="skip_trace",
                status="completed",
                created_at="2025-11-10T10:00:00Z",
                completed_at="2025-11-12T15:30:00Z",
                result="success",
                amount=None,
            ),
        ],
        total_recovered=1250.00,
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@router.post(
    "/stop",
    response_model=EnforcementStartResponse,
    summary="Stop enforcement workflow",
    description="Stop an active enforcement action. Requires authentication.",
)
async def stop_enforcement(
    case_id: str = Query(..., description="The case ID to stop enforcement for"),
    reason: str = Query(default="", description="Reason for stopping"),
    auth: AuthContext = Depends(get_current_user),
) -> EnforcementStartResponse:
    """
    Stop an active enforcement workflow.

    TODO: Implement actual enforcement stop logic.

    Requires authentication.
    """
    logger.info(f"Enforcement stop requested by {auth.via}: case_id={case_id}, reason={reason}")

    return EnforcementStartResponse(
        status="queued",
        case_id=case_id,
        message=f"TODO: Implement enforcement stop. Reason: {reason or 'Not specified'}",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


# =============================================================================
# Radar Endpoint
# =============================================================================


def _compute_offer_strategy(score: int | None, amount: float) -> str:
    """
    Compute offer strategy based on collectability score and judgment amount.

    Logic:
      - score is None → ENRICHMENT_PENDING
      - score >= 70 AND amount >= 10000 → BUY_CANDIDATE
      - score >= 40 OR amount >= 5000 → CONTINGENCY
      - else → LOW_PRIORITY
    """
    if score is None:
        return "ENRICHMENT_PENDING"
    if score >= 70 and amount >= 10000:
        return "BUY_CANDIDATE"
    if score >= 40 or amount >= 5000:
        return "CONTINGENCY"
    return "LOW_PRIORITY"


@router.get(
    "/radar",
    response_model=list[RadarRow],
    summary="Get Enforcement Radar",
    description="Returns prioritized list of judgments for enforcement action.",
)
async def get_enforcement_radar(
    strategy: Optional[str] = Query(
        None, description="Filter by offer strategy (BUY_CANDIDATE, CONTINGENCY, etc.)"
    ),
    min_score: Optional[int] = Query(
        None, ge=0, le=100, description="Minimum collectability score"
    ),
    min_amount: Optional[float] = Query(None, ge=0, description="Minimum judgment amount"),
    auth: AuthContext = Depends(get_current_user),
) -> list[RadarRow]:
    """
    Get the Enforcement Radar – prioritized list of judgments for CEO review.

    Returns judgments sorted by collectability score and amount, with computed
    offer strategies (BUY_CANDIDATE, CONTINGENCY, ENRICHMENT_PENDING, LOW_PRIORITY).
    """
    logger.info(
        f"Enforcement radar requested by {auth.via}: "
        f"strategy={strategy}, min_score={min_score}, min_amount={min_amount}"
    )

    try:
        client = get_supabase_client()

        # Query judgments table with relevant fields
        query = client.table("judgments").select(
            "id, case_number, plaintiff_name, defendant_name, judgment_amount, "
            "collectability_score, court, county, judgment_date, created_at"
        )

        # Apply score filter if provided
        if min_score is not None:
            query = query.gte("collectability_score", min_score)

        # Apply amount filter if provided
        if min_amount is not None:
            query = query.gte("judgment_amount", min_amount)

        # Order by collectability score descending, then amount
        query = query.order("collectability_score", desc=True, nullsfirst=False)
        query = query.order("judgment_amount", desc=True)

        # Limit to top 500 for performance
        query = query.limit(500)

        result = query.execute()
        rows: list[dict] = result.data or []  # type: ignore[assignment]

        radar_rows: list[RadarRow] = []
        for row in rows:
            raw_score = row.get("collectability_score")
            score: int | None = int(raw_score) if raw_score is not None else None
            amount = float(row.get("judgment_amount") or 0)
            computed_strategy = _compute_offer_strategy(score, amount)

            # Apply strategy filter after computation
            if strategy and strategy != "ALL" and computed_strategy != strategy:
                continue

            radar_rows.append(
                RadarRow(
                    id=str(row.get("id", "")),
                    case_number=str(row.get("case_number") or ""),
                    plaintiff_name=str(row.get("plaintiff_name") or ""),
                    defendant_name=str(row.get("defendant_name") or ""),
                    judgment_amount=amount,
                    collectability_score=score,
                    offer_strategy=computed_strategy,
                    court=row.get("court"),
                    county=row.get("county"),
                    judgment_date=row.get("judgment_date"),
                    created_at=str(row.get("created_at") or datetime.utcnow().isoformat()),
                )
            )

        logger.info(f"Radar returning {len(radar_rows)} rows")
        return radar_rows

    except Exception as e:
        logger.error(f"Enforcement radar query failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query radar: {e}")


# =============================================================================
# Wage Garnishment Candidates Endpoint
# =============================================================================


@router.get(
    "/wage-candidates",
    response_model=WageGarnishmentCandidatesResponse,
    summary="Get wage garnishment candidates",
    description="Returns paginated list of judgments with known employers suitable for NY wage garnishment (CPLR 5231).",
)
async def get_wage_candidates(
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    min_balance: Optional[float] = Query(None, ge=0, description="Minimum judgment balance"),
    min_priority: Optional[float] = Query(None, ge=0, description="Minimum priority score"),
    jurisdiction: Optional[str] = Query(None, description="Filter by county/jurisdiction"),
    verified_only: bool = Query(False, description="Only include verified employer intel"),
    auth: AuthContext = Depends(get_current_user),
) -> WageGarnishmentCandidatesResponse:
    """
    Get wage garnishment candidates from enforcement.v_candidate_wage_garnishments.

    Returns judgments that meet NY wage garnishment criteria:
    - Unsatisfied status
    - Known employer (from debtor_intelligence)
    - Balance >= $2,000 (practical threshold)

    Candidates are scored by priority_score (higher = more actionable):
    - Base: collectability_score (0-100)
    - Employer verified: +20
    - Employer present: +15
    - High balance (>$10k): +10
    - Recent judgment (<2 years): +5

    Requires authentication.
    """
    logger.info(
        f"Wage candidates requested by {auth.via}: "
        f"page={page}, page_size={page_size}, min_balance={min_balance}, "
        f"min_priority={min_priority}, jurisdiction={jurisdiction}"
    )

    try:
        client = get_supabase_client()

        # Build query using the enforcement view
        # Note: Using schema-qualified name via PostgREST schema switching
        # or accessing via RPC if view is in non-public schema
        query = (
            client.schema("enforcement")
            .from_("v_candidate_wage_garnishments")
            .select(
                "*",
                count="exact",  # type: ignore[arg-type]
            )
        )

        # Apply filters
        if min_balance is not None:
            query = query.gte("balance", min_balance)

        if min_priority is not None:
            query = query.gte("priority_score", min_priority)

        if jurisdiction:
            query = query.ilike("jurisdiction", f"%{jurisdiction}%")

        if verified_only:
            query = query.eq("intel_verified", True)

        # Pagination (0-indexed for PostgREST)
        offset = (page - 1) * page_size
        query = query.range(offset, offset + page_size - 1)

        # Execute
        result = query.execute()
        rows: list[dict] = result.data or []  # type: ignore[assignment]
        total: int = result.count or 0

        # Map to response models
        candidates: list[WageGarnishmentCandidate] = []
        for row in rows:
            candidates.append(
                WageGarnishmentCandidate(
                    plaintiff_id=str(row.get("plaintiff_id")) if row.get("plaintiff_id") else None,
                    case_number=str(row.get("case_number") or ""),
                    defendant_name=row.get("defendant_name"),
                    employer_name=str(row.get("employer_name") or ""),
                    employer_address=row.get("employer_address"),
                    balance=float(row.get("balance") or 0),
                    jurisdiction=row.get("jurisdiction"),
                    priority_score=float(row.get("priority_score") or 0),
                    judgment_id=str(row.get("judgment_id")) if row.get("judgment_id") else None,
                    plaintiff_name=row.get("plaintiff_name"),
                    plaintiff_tier=row.get("plaintiff_tier"),
                    judgment_date=(
                        str(row.get("judgment_date")) if row.get("judgment_date") else None
                    ),
                    collectability_score=(
                        int(row["collectability_score"])
                        if row.get("collectability_score")
                        else None
                    ),
                    income_band=row.get("income_band"),
                    intel_source=row.get("intel_source"),
                    intel_confidence=(
                        float(row["intel_confidence"]) if row.get("intel_confidence") else None
                    ),
                    intel_verified=row.get("intel_verified"),
                    enforcement_stage=row.get("enforcement_stage"),
                    status=row.get("status"),
                    created_at=str(row.get("created_at")) if row.get("created_at") else None,
                )
            )

        has_more = (offset + len(candidates)) < total

        logger.info(f"Wage candidates returning {len(candidates)} of {total} total")

        return WageGarnishmentCandidatesResponse(
            candidates=candidates,
            total=total,
            page=page,
            page_size=page_size,
            has_more=has_more,
        )

    except Exception as e:
        logger.error(f"Wage candidates query failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to query wage candidates: {e}",
        )


# =============================================================================
# Generate Packet Models
# =============================================================================


class GeneratePacketRequest(BaseModel):
    """Request to generate an enforcement packet."""

    judgment_id: str = Field(..., description="The judgment ID to generate packet for")
    strategy: Literal["wage_garnishment", "bank_levy", "asset_seizure"] = Field(
        default="wage_garnishment",
        description="Enforcement strategy for the packet",
    )


class GeneratePacketResponse(BaseModel):
    """Response from packet generation request."""

    status: Literal["queued", "processing", "completed", "error"]
    job_id: str = Field(..., description="Background job ID for tracking")
    packet_id: Optional[str] = Field(None, description="Packet ID (available when completed)")
    message: str
    estimated_completion: Optional[str] = None


class JobStatusResponse(BaseModel):
    """Response for job status query."""

    job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    packet_id: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# =============================================================================
# Generate Packet Endpoint
# =============================================================================


@router.post(
    "/generate-packet",
    response_model=GeneratePacketResponse,
    summary="Generate enforcement packet",
    description="Generate a complete enforcement packet for a judgment including legal documents and forms.",
)
async def generate_enforcement_packet(
    request: GeneratePacketRequest,
    auth: AuthContext = Depends(get_current_user),
) -> GeneratePacketResponse:
    """
    Generate an enforcement packet for a judgment.

    This creates all necessary legal documents for the selected enforcement strategy:
    - Wage Garnishment: Writ of execution, garnishment order, employer notification
    - Bank Levy: Bank levy order, restraining notice, bank notification
    - Asset Seizure: Writ of execution, property levy, sheriff instructions

    The packet is queued for background processing and will be available for download
    once complete.

    Requires authentication.
    """
    import uuid

    logger.info(
        f"Packet generation requested by {auth.via}: "
        f"judgment_id={request.judgment_id}, strategy={request.strategy}"
    )

    client = get_supabase_client()

    # 1. Validate judgment exists
    try:
        judgment_id_int = int(request.judgment_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid judgment_id format")

    judgment_result = (
        client.table("judgments")
        .select("id, case_number")
        .eq("id", judgment_id_int)
        .limit(1)
        .execute()
    )

    if not judgment_result.data:
        raise HTTPException(status_code=404, detail=f"Judgment {request.judgment_id} not found")

    judgment_row = judgment_result.data[0]
    case_number = judgment_row["case_number"] if isinstance(judgment_row, dict) else "UNKNOWN"

    # 2. Create job in ops.job_queue
    job_id = str(uuid.uuid4())
    job_payload = {
        "judgment_id": request.judgment_id,
        "strategy": request.strategy,
        "case_number": case_number,
        "requested_by": auth.via,
    }

    try:
        job_result = (
            client.schema("ops")
            .table("job_queue")
            .insert(
                {
                    "id": job_id,
                    "job_type": "enforcement_generate_packet",
                    "status": "pending",
                    "payload": job_payload,
                }
            )
            .execute()
        )

        if not job_result.data:
            raise HTTPException(status_code=500, detail="Failed to create background job")

    except Exception as e:
        logger.error(f"Failed to queue packet generation job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to queue job: {str(e)}")

    logger.info(f"Queued packet generation job {job_id} for judgment {request.judgment_id}")

    return GeneratePacketResponse(
        status="queued",
        job_id=job_id,
        packet_id=None,
        message=f"Enforcement packet ({request.strategy}) queued for generation.",
        estimated_completion=(datetime.utcnow().isoformat() + "Z"),
    )


@router.get(
    "/job-status/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Get the status of a background job and resulting packet ID if complete.",
)
async def get_job_status(
    job_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> JobStatusResponse:
    """
    Get the status of a background enforcement job.

    Returns the current status and packet_id once the job completes.
    Frontend should poll this endpoint every 2 seconds until status is 'completed' or 'failed'.

    Requires authentication.
    """
    from typing import cast

    client = get_supabase_client()

    # Look up job in ops.job_queue
    try:
        job_result = (
            client.schema("ops")
            .table("job_queue")
            .select("id, status, payload, last_error, created_at, updated_at")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error(f"Failed to query job status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to query job: {str(e)}")

    if not job_result.data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job = cast(dict, job_result.data[0])
    raw_status = str(job.get("status", "pending"))
    # Validate status is a known value
    valid_statuses = ("pending", "processing", "completed", "failed")
    status: str = raw_status if raw_status in valid_statuses else "pending"
    payload_raw = job.get("payload")
    payload = cast(dict, payload_raw) if isinstance(payload_raw, dict) else {}

    # If completed, look for the resulting packet
    packet_id: str | None = None
    if status == "completed":
        judgment_id = payload.get("judgment_id")
        if judgment_id:
            try:
                packet_result = (
                    client.schema("enforcement")
                    .table("draft_packets")
                    .select("id")
                    .eq("job_id", job_id)
                    .limit(1)
                    .execute()
                )
                if packet_result.data:
                    packet_row = cast(dict, packet_result.data[0])
                    packet_id = str(packet_row.get("id")) if packet_row.get("id") else None
            except Exception as e:
                logger.warning(f"Could not fetch packet for job {job_id}: {e}")

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        packet_id=packet_id,
        error_message=str(job.get("last_error")) if job.get("last_error") else None,
        created_at=str(job.get("created_at")) if job.get("created_at") else None,
        updated_at=str(job.get("updated_at")) if job.get("updated_at") else None,
    )
