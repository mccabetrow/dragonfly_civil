"""
Dragonfly API - Data Integrity Router

Provides endpoints for the Data Integrity & Reconciliation dashboard:
- GET /api/v1/integrity/dashboard - Vault status metrics
- GET /api/v1/integrity/batches/{batch_id}/verify - Verify batch integrity
- GET /api/v1/integrity/discrepancies - List failed rows (Dead Letter Queue)
- PATCH /api/v1/integrity/discrepancies/{id} - Update discrepancy
- POST /api/v1/integrity/discrepancies/{id}/retry - Retry failed row
- POST /api/v1/integrity/discrepancies/{id}/dismiss - Dismiss as unfixable
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.db import get_db_connection
from backend.services.reconciliation import DiscrepancyStatus, ErrorType, ReconciliationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/integrity", tags=["integrity"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class IntegrityDashboardResponse(BaseModel):
    """Vault status dashboard metrics."""

    total_rows_received: int = Field(..., description="All-time rows ingested")
    total_rows_stored: int = Field(..., description="All-time rows stored successfully")
    total_rows_failed: int = Field(..., description="All-time rows failed")
    total_batches: int = Field(..., description="Total number of batches")
    integrity_score: float = Field(..., description="Percentage of successful rows (e.g., 99.999)")
    pending_discrepancies: int = Field(..., description="Failed rows awaiting review")
    resolved_discrepancies: int = Field(..., description="Failed rows that were fixed")
    rows_received_24h: int = Field(..., description="Rows received in last 24 hours")
    rows_stored_24h: int = Field(..., description="Rows stored in last 24 hours")
    batches_pending: int = Field(..., description="Batches awaiting processing")
    batches_processing: int = Field(..., description="Batches currently processing")
    computed_at: str = Field(..., description="When metrics were computed")


class BatchVerificationResponse(BaseModel):
    """Result of batch verification."""

    batch_id: str
    csv_row_count: int = Field(..., description="Total rows in CSV")
    db_row_count: int = Field(..., description="Rows successfully stored in DB")
    failed_row_count: int = Field(..., description="Rows that failed")
    integrity_score: float = Field(..., description="Percentage match (0-100)")
    is_complete: bool = Field(..., description="Whether batch processing is finished")
    is_perfect: bool = Field(..., description="True if 100% integrity")
    status: str = Field(..., description="Batch status")
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    verified_at: str


class DiscrepancyResponse(BaseModel):
    """Single discrepancy (failed row) from Dead Letter Queue."""

    id: str
    batch_id: str
    row_index: int
    source_file: Optional[str] = None
    raw_data: Dict[str, Any]
    error_type: str
    error_code: Optional[str] = None
    error_message: str
    error_details: Optional[Dict[str, Any]] = None
    status: str
    retry_count: int
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    created_at: str


class DiscrepancyListResponse(BaseModel):
    """Paginated list of discrepancies."""

    discrepancies: List[DiscrepancyResponse]
    total: int
    limit: int
    offset: int


class UpdateDiscrepancyRequest(BaseModel):
    """Request to update a discrepancy."""

    raw_data: Optional[Dict[str, Any]] = Field(None, description="Updated row data for retry")
    status: Optional[str] = Field(None, description="New status")
    resolution_notes: Optional[str] = Field(None, description="Notes about resolution")


class DismissRequest(BaseModel):
    """Request to dismiss a discrepancy."""

    resolved_by: str = Field(..., description="User dismissing the discrepancy")
    resolution_notes: Optional[str] = Field(None, description="Reason for dismissal")


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/dashboard", response_model=IntegrityDashboardResponse)
async def get_integrity_dashboard(
    conn: psycopg.Connection = Depends(get_db_connection),
) -> IntegrityDashboardResponse:
    """
    Get Vault Status dashboard metrics.

    Returns all-time and recent integrity statistics for the data ingestion system.
    """
    service = ReconciliationService(conn)
    dashboard = service.get_dashboard()

    return IntegrityDashboardResponse(
        total_rows_received=dashboard.total_rows_received,
        total_rows_stored=dashboard.total_rows_stored,
        total_rows_failed=dashboard.total_rows_failed,
        total_batches=dashboard.total_batches,
        integrity_score=dashboard.integrity_score,
        pending_discrepancies=dashboard.pending_discrepancies,
        resolved_discrepancies=dashboard.resolved_discrepancies,
        rows_received_24h=dashboard.rows_received_24h,
        rows_stored_24h=dashboard.rows_stored_24h,
        batches_pending=dashboard.batches_pending,
        batches_processing=dashboard.batches_processing,
        computed_at=dashboard.computed_at.isoformat(),
    )


@router.get("/batches/{batch_id}/verify", response_model=BatchVerificationResponse)
async def verify_batch(
    batch_id: str,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> BatchVerificationResponse:
    """
    Verify a batch by comparing CSV row count vs DB row count.

    This is the core reconciliation function that proves data integrity.
    """
    service = ReconciliationService(conn)

    try:
        result = service.verify_batch(batch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return BatchVerificationResponse(
        batch_id=result.batch_id,
        csv_row_count=result.csv_row_count,
        db_row_count=result.db_row_count,
        failed_row_count=result.failed_row_count,
        integrity_score=result.integrity_score,
        is_complete=result.is_complete,
        is_perfect=result.is_perfect,
        status=result.status,
        discrepancies=result.discrepancies,
        verified_at=result.verified_at.isoformat(),
    )


@router.get("/discrepancies", response_model=DiscrepancyListResponse)
async def list_discrepancies(
    batch_id: Optional[str] = Query(None, description="Filter by batch ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> DiscrepancyListResponse:
    """
    List discrepancies (failed rows) from Dead Letter Queue.

    Supports filtering by batch and status, with pagination.
    """
    service = ReconciliationService(conn)

    # Convert status string to enum if provided
    status_enum = None
    if status:
        try:
            status_enum = DiscrepancyStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {[s.value for s in DiscrepancyStatus]}",
            )

    discrepancies = service.get_discrepancies(
        batch_id=batch_id,
        status=status_enum,
        limit=limit,
        offset=offset,
    )

    # Get total count for pagination (simplified - just use limit as indicator)
    total = len(discrepancies)

    return DiscrepancyListResponse(
        discrepancies=[
            DiscrepancyResponse(
                id=d.id,
                batch_id=d.batch_id,
                row_index=d.row_index,
                source_file=d.source_file,
                raw_data=d.raw_data,
                error_type=d.error_type.value,
                error_code=d.error_code,
                error_message=d.error_message,
                error_details=d.error_details,
                status=d.status.value,
                retry_count=d.retry_count,
                resolved_at=d.resolved_at.isoformat() if d.resolved_at else None,
                resolved_by=d.resolved_by,
                created_at=d.created_at.isoformat(),
            )
            for d in discrepancies
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/discrepancies/{discrepancy_id}", response_model=DiscrepancyResponse)
async def get_discrepancy(
    discrepancy_id: str,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> DiscrepancyResponse:
    """Get a single discrepancy by ID."""
    service = ReconciliationService(conn)

    service.get_discrepancies(limit=1)

    # Query directly for this ID
    with conn.cursor() as cur:
        from psycopg.rows import dict_row

        cur.row_factory = dict_row
        cur.execute(
            """
            SELECT * FROM ops.data_discrepancies WHERE id = %s::uuid
            """,
            (discrepancy_id,),
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Discrepancy not found")

    return DiscrepancyResponse(
        id=str(row["id"]),
        batch_id=str(row["batch_id"]),
        row_index=row["row_index"],
        source_file=row["source_file"],
        raw_data=row["raw_data"],
        error_type=row["error_type"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_details=row["error_details"],
        status=row["status"],
        retry_count=row["retry_count"],
        resolved_at=row["resolved_at"].isoformat() if row["resolved_at"] else None,
        resolved_by=row["resolved_by"],
        created_at=row["created_at"].isoformat(),
    )


@router.patch("/discrepancies/{discrepancy_id}")
async def update_discrepancy(
    discrepancy_id: str,
    request: UpdateDiscrepancyRequest,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> Dict[str, Any]:
    """
    Update a discrepancy (edit data before retry).

    Can update raw_data, status, and add resolution notes.
    """
    service = ReconciliationService(conn)

    # Convert status if provided
    status_enum = None
    if request.status:
        try:
            status_enum = DiscrepancyStatus(request.status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {[s.value for s in DiscrepancyStatus]}",
            )

    updated = service.update_discrepancy(
        discrepancy_id=discrepancy_id,
        raw_data=request.raw_data,
        status=status_enum,
        resolution_notes=request.resolution_notes,
    )

    if not updated:
        raise HTTPException(status_code=404, detail="Discrepancy not found")

    return {"success": True, "discrepancy_id": discrepancy_id}


@router.post("/discrepancies/{discrepancy_id}/retry")
async def retry_discrepancy(
    discrepancy_id: str,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> Dict[str, Any]:
    """
    Retry processing a failed row.

    Uses the (possibly edited) raw_data to attempt re-ingestion.
    """
    service = ReconciliationService(conn)
    result = service.retry_discrepancy(discrepancy_id)

    if not result.get("success", False):
        return {
            "success": False,
            "discrepancy_id": discrepancy_id,
            "error": result.get("error", "Retry failed"),
        }

    return {
        "success": True,
        "discrepancy_id": discrepancy_id,
        "judgment_id": result.get("judgment_id"),
    }


@router.post("/discrepancies/{discrepancy_id}/dismiss")
async def dismiss_discrepancy(
    discrepancy_id: str,
    request: DismissRequest,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> Dict[str, Any]:
    """
    Dismiss a discrepancy as not fixable.

    Marks the row as dismissed so it doesn't appear in pending queue.
    """
    service = ReconciliationService(conn)

    dismissed = service.dismiss_discrepancy(
        discrepancy_id=discrepancy_id,
        resolved_by=request.resolved_by,
        resolution_notes=request.resolution_notes,
    )

    if not dismissed:
        raise HTTPException(status_code=404, detail="Discrepancy not found")

    return {"success": True, "discrepancy_id": discrepancy_id, "status": "dismissed"}


# =============================================================================
# BATCH INTEGRITY VERIFICATION
# =============================================================================


class BatchIntegrityResponse(BaseModel):
    """Response from batch integrity check."""

    batch_id: str
    csv_row_count: int = Field(..., description="Rows in source CSV")
    db_row_count: int = Field(..., description="Rows stored in judgments")
    audit_log_count: int = Field(..., description="Audit entries for this batch")
    discrepancy_count: int = Field(..., description="Pending failed rows")
    integrity_score: float = Field(..., description="Percentage (0-100)")
    status: str = Field(..., description="verified or discrepancy")
    is_verified: bool = Field(..., description="True if integrity confirmed")
    verification_message: str = Field(..., description="Human-readable status")


class BatchIntegrityListResponse(BaseModel):
    """List of batch integrity records for the vault dashboard."""

    batches: List[Dict[str, Any]]
    total: int


@router.post("/batches/{batch_id}/check-integrity", response_model=BatchIntegrityResponse)
async def check_batch_integrity(
    batch_id: str,
    conn: psycopg.Connection = Depends(get_db_connection),
) -> BatchIntegrityResponse:
    """
    Run integrity check on a batch.

    This is the core reconciliation function that provides mathematical
    proof that no data was lost during ingestion:

    1. Compare intake raw_rows count VS public.judgments count
    2. If match → Mark batch "verified" (GREEN)
    3. If mismatch → Mark batch "discrepancy" (RED)

    Returns detailed verification results.
    """
    service = ReconciliationService(conn)

    try:
        result = service.check_batch_integrity(batch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return BatchIntegrityResponse(**result)


@router.get("/batches/integrity", response_model=BatchIntegrityListResponse)
async def list_batch_integrity(
    limit: int = Query(50, ge=1, le=200, description="Max batches"),
    status: Optional[str] = Query(None, description="Filter: verified, discrepancy, pending"),
    conn: psycopg.Connection = Depends(get_db_connection),
) -> BatchIntegrityListResponse:
    """
    Get list of batches with integrity status for the Vault dashboard.

    Returns batches with:
    - Integrity status (verified=GREEN, discrepancy=RED, pending=YELLOW)
    - Row counts (CSV vs DB)
    - Pending discrepancies
    """
    service = ReconciliationService(conn)

    batches = service.get_batch_integrity_list(limit=limit, status_filter=status)

    return BatchIntegrityListResponse(
        batches=batches,
        total=len(batches),
    )
