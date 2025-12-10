"""
Dragonfly Engine - Ingest Router v2

Enterprise-grade batch-based ingestion endpoints for Simplicity CSV uploads.
All endpoints require authentication via API key or JWT.

Version: v0.2.x
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user
from ..services.ingest_service_v2 import (
    ParsedBatchResult,
    ProcessResult,
    create_batch,
    get_batch_details,
    get_batch_errors,
    get_pending_batches,
    list_batches,
    parse_simplicity_csv,
    process_simplicity_batch,
    update_batch_counts,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/ingest",
    tags=["Ingest"],
)


# =============================================================================
# Response Models
# =============================================================================


class IngestUploadResponse(BaseModel):
    """Response from CSV upload endpoint."""

    batch_id: UUID
    filename: str
    row_count_raw: int
    row_count_valid: int
    row_count_invalid: int
    status: str
    message: str = Field(default="", description="Human-readable status message")


class BatchSummary(BaseModel):
    """Summary of an ingest batch."""

    id: str
    source: str
    filename: str
    row_count_raw: int
    row_count_valid: int
    row_count_invalid: int
    status: str
    error_summary: str | None = None
    created_at: str | None = None
    processed_at: str | None = None
    created_by: str | None = None


class BatchListResponse(BaseModel):
    """Response from batch list endpoint."""

    batches: list[BatchSummary]
    count: int


class BatchDetailResponse(BaseModel):
    """Detailed batch information."""

    id: str
    source: str
    filename: str
    row_count_raw: int
    row_count_valid: int
    row_count_invalid: int
    status: str
    error_summary: str | None = None
    created_at: str | None = None
    processed_at: str | None = None
    created_by: str | None = None
    success_rate_pct: float = Field(default=0.0)


class BatchErrorRow(BaseModel):
    """A single invalid row from a batch."""

    row_index: int
    validation_errors: list[str] | None = None
    plaintiff_name: str | None = None
    defendant_name: str | None = None
    case_number: str | None = None
    judgment_amount: float | None = None
    judgment_date: str | None = None
    court: str | None = None


class BatchErrorsResponse(BaseModel):
    """Response from batch errors endpoint."""

    batch_id: str
    errors: list[BatchErrorRow]
    count: int


class ProcessBatchResponse(BaseModel):
    """Response from process batch endpoint."""

    batch_id: str
    status: str
    rows_processed: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    error_summary: str | None = None


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/simplicity/upload",
    response_model=IngestUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Simplicity CSV",
    description="""
    Upload a Simplicity CSV file for batch ingestion.

    The file is parsed, validated, and stored in staging tables.
    By default, processing happens immediately after upload.

    **Required headers:**
    - `X-API-Key`: API key for authentication, OR
    - `Authorization: Bearer <jwt>`: Supabase JWT token

    **Returns:**
    - batch_id: UUID to track this upload
    - Counts of raw, valid, and invalid rows
    - Current batch status
    """,
    responses={
        400: {"description": "Invalid file or format"},
        401: {"description": "Authentication required"},
        500: {"description": "Processing error"},
    },
)
async def upload_simplicity_csv(
    file: Annotated[
        UploadFile,
        File(description="Simplicity CSV export file"),
    ],
    process_now: Annotated[
        bool,
        Query(description="Process batch immediately after upload"),
    ] = True,
    auth: AuthContext = Depends(get_current_user),
) -> IngestUploadResponse:
    """
    Upload and optionally process a Simplicity CSV file.
    """
    logger.info(f"Ingest upload by {auth.via}: {file.filename}")

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided",
        )

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV",
        )

    # Determine created_by from auth context
    created_by = auth.subject or f"via_{auth.via}"

    try:
        # Create batch record
        batch_id = await create_batch(
            source="simplicity",
            filename=file.filename,
            created_by=created_by,
        )

        logger.info(f"Created batch {batch_id} for {file.filename}")

        # Parse CSV into staging tables
        parse_result: ParsedBatchResult = await parse_simplicity_csv(batch_id, file)

        # Update batch with counts
        await update_batch_counts(
            batch_id,
            parse_result.row_count_raw,
            parse_result.row_count_valid,
            parse_result.row_count_invalid,
        )

        # Determine final status
        final_status = "pending"
        message = f"Parsed {parse_result.row_count_raw} rows"

        # Optionally process immediately
        if process_now and parse_result.row_count_valid > 0:
            process_result: ProcessResult = await process_simplicity_batch(batch_id)
            final_status = process_result.status
            message = (
                f"Processed: {process_result.rows_inserted} inserted, "
                f"{process_result.rows_updated} updated, "
                f"{process_result.rows_skipped} skipped"
            )

            if process_result.error_summary:
                message += f" - Error: {process_result.error_summary[:100]}"

        return IngestUploadResponse(
            batch_id=batch_id,
            filename=file.filename,
            row_count_raw=parse_result.row_count_raw,
            row_count_valid=parse_result.row_count_valid,
            row_count_invalid=parse_result.row_count_invalid,
            status=final_status,
            message=message,
        )

    except ValueError as e:
        logger.warning(f"Validation error for {file.filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.exception(f"Ingest failed for {file.filename}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingest failed: {str(e)[:200]}",
        )


@router.get(
    "/batches",
    response_model=BatchListResponse,
    summary="List Recent Batches",
    description="""
    List the most recent ingest batches, ordered by creation date descending.

    Use this to monitor ingest activity and find batch IDs for detailed queries.
    """,
)
async def list_ingest_batches(
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Maximum number of batches to return"),
    ] = 50,
    auth: AuthContext = Depends(get_current_user),
) -> BatchListResponse:
    """
    List recent ingest batches.
    """
    logger.debug(f"Listing batches (limit={limit}) for {auth.via}")

    batches = await list_batches(limit=limit)

    return BatchListResponse(
        batches=[BatchSummary(**b) for b in batches],
        count=len(batches),
    )


@router.get(
    "/batch/{batch_id}",
    response_model=BatchDetailResponse,
    summary="Get Batch Details",
    description="""
    Get detailed information about a specific ingest batch.

    Includes row counts, status, timing, and error summary if failed.
    """,
    responses={
        404: {"description": "Batch not found"},
    },
)
async def get_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> BatchDetailResponse:
    """
    Get details for a specific batch.
    """
    logger.debug(f"Getting batch {batch_id} for {auth.via}")

    batch = await get_batch_details(batch_id)

    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found",
        )

    # Calculate success rate
    raw = batch.get("row_count_raw", 0)
    valid = batch.get("row_count_valid", 0)
    success_rate = (valid / raw * 100) if raw > 0 else 0.0

    return BatchDetailResponse(
        **batch,
        success_rate_pct=round(success_rate, 1),
    )


@router.get(
    "/batch/{batch_id}/errors",
    response_model=BatchErrorsResponse,
    summary="Get Batch Errors",
    description="""
    Get the invalid rows from a batch with their validation errors.

    Use this to understand why certain rows failed validation and
    fix the source data for re-upload.
    """,
    responses={
        404: {"description": "Batch not found"},
    },
)
async def get_batch_error_rows(
    batch_id: UUID,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of error rows to return"),
    ] = 100,
    auth: AuthContext = Depends(get_current_user),
) -> BatchErrorsResponse:
    """
    Get invalid rows for a batch.
    """
    logger.debug(f"Getting errors for batch {batch_id} for {auth.via}")

    # First verify batch exists
    batch = await get_batch_details(batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found",
        )

    errors = await get_batch_errors(batch_id, limit=limit)

    return BatchErrorsResponse(
        batch_id=str(batch_id),
        errors=[BatchErrorRow(**e) for e in errors],
        count=len(errors),
    )


@router.post(
    "/batch/{batch_id}/process",
    response_model=ProcessBatchResponse,
    summary="Process Pending Batch",
    description="""
    Manually trigger processing for a pending batch.

    This upserts valid rows into the canonical imported_simplicity_cases table.
    Processing is idempotent - re-running won't duplicate data.
    """,
    responses={
        404: {"description": "Batch not found"},
        400: {"description": "Batch not in pending state"},
    },
)
async def process_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> ProcessBatchResponse:
    """
    Process a pending batch.
    """
    logger.info(f"Manual process triggered for batch {batch_id} by {auth.via}")

    # Verify batch exists and is pending
    batch = await get_batch_details(batch_id)
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Batch {batch_id} not found",
        )

    if batch["status"] not in ("pending", "failed"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Batch is already {batch['status']}, cannot reprocess",
        )

    result = await process_simplicity_batch(batch_id)

    return ProcessBatchResponse(
        batch_id=str(result.batch_id),
        status=result.status,
        rows_processed=result.rows_processed,
        rows_inserted=result.rows_inserted,
        rows_updated=result.rows_updated,
        rows_skipped=result.rows_skipped,
        error_summary=result.error_summary,
    )


@router.get(
    "/pending",
    response_model=list[str],
    summary="List Pending Batches",
    description="Get IDs of all batches awaiting processing.",
)
async def list_pending_batches(
    auth: AuthContext = Depends(get_current_user),
) -> list[str]:
    """
    List batch IDs with status='pending'.
    """
    pending = await get_pending_batches()
    return [str(b) for b in pending]


# =============================================================================
# Legacy endpoints for backwards compatibility
# =============================================================================


@router.post(
    "/simplicity/path",
    deprecated=True,
    summary="[Deprecated] Ingest from Path",
    description="Use /simplicity/upload instead. This endpoint will be removed.",
    include_in_schema=False,
)
async def ingest_from_path(
    auth: AuthContext = Depends(get_current_user),
):
    """Deprecated - use upload endpoint."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="This endpoint is deprecated. Use POST /api/v1/ingest/simplicity/upload",
    )
