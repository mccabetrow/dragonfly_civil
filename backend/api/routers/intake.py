"""
Dragonfly Engine - Intake Router (Fortress Edition)

API endpoints for the hardened intake system.
Handles CSV uploads, batch management, and error reporting.

Endpoints:
    POST /api/v1/intake/upload - Upload CSV and start processing
    GET  /api/v1/intake/batches - List all batches with stats
    GET  /api/v1/intake/batches/{id} - Get batch details
    GET  /api/v1/intake/batches/{id}/errors - Get error log for batch
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ...api import ApiResponse, api_response, degraded_response
from ...config import get_settings
from ...core.security import AuthContext, get_current_user
from ...db import get_pool
from ...services.intake_service import IntakeService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RLS Error Detection
# ---------------------------------------------------------------------------


def is_rls_violation(error: Exception) -> bool:
    """Check if an exception is an RLS (Row Level Security) violation.

    Returns True for errors like:
    - 'new row violates row-level security policy'
    - 'permission denied for table'
    - PostgreSQL error code 42501 (insufficient_privilege)
    """
    error_str = str(error).lower()
    rls_keywords = [
        "row-level security",
        "row level security",
        "rls policy",
        "permission denied",
        "insufficient_privilege",
        "42501",  # PostgreSQL error code
    ]
    return any(kw in error_str for kw in rls_keywords)


router = APIRouter(prefix="/intake", tags=["Intake Fortress"])


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class BatchCreateResponse(BaseModel):
    """Response when a batch is created and processing starts."""

    batch_id: str = Field(..., description="UUID of the created batch")
    status: str = Field("processing", description="Current batch status")
    message: str = Field(..., description="Human-readable status message")


class BatchSummary(BaseModel):
    """Summary of a single batch."""

    id: str
    filename: str
    source: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    plaintiffs_inserted: int = 0
    plaintiffs_duplicate: int = 0
    plaintiffs_failed: int = 0
    success_rate: float
    duration_seconds: Optional[float] = None
    health_status: str
    created_at: str
    completed_at: Optional[str] = None


class BatchListResponse(BaseModel):
    """Response containing list of batches."""

    batches: list[BatchSummary]
    total: int
    page: int
    page_size: int


class BatchDetailResponse(BaseModel):
    """Detailed batch information."""

    id: str
    filename: str
    source: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    duplicate_rows: int
    skipped_rows: int
    plaintiffs_inserted: int = 0
    plaintiffs_duplicate: int = 0
    plaintiffs_failed: int = 0
    success_rate: float
    duration_seconds: Optional[float] = None
    health_status: str
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_by: Optional[str] = None
    worker_id: Optional[str] = None
    stats: dict[str, Any]
    recent_errors: list[dict[str, Any]]


class ErrorLogEntry(BaseModel):
    """Single error log entry."""

    row_index: int
    status: str
    error_code: Optional[str] = None
    error_details: Optional[str] = None
    judgment_id: Optional[str] = None
    created_at: str


class ErrorLogResponse(BaseModel):
    """Response containing error log entries."""

    batch_id: str
    errors: list[ErrorLogEntry]
    total: int
    page: int
    page_size: int


class ErrorResponse(BaseModel):
    """Standard error response."""

    status: str = "error"
    error: str
    detail: Optional[str] = None


class BatchListDegradedResponse(BaseModel):
    """Response when batch listing fails - degrade guard pattern."""

    ok: bool = Field(False, description="Always False for degraded response")
    degraded: bool = Field(True, description="Always True for degraded response")
    error: Optional[str] = Field(None, description="Error message")
    data: list[Any] = Field(default_factory=list, description="Empty list on failure")


class IntakeStateData(BaseModel):
    """
    Intake state data payload.

    This is the data field inside the ApiResponse envelope.
    """

    # Aggregate batch counts by status
    pending: int = Field(0, description="Batches waiting to start")
    processing: int = Field(0, description="Batches currently processing")
    completed: int = Field(0, description="Batches finished successfully")
    failed: int = Field(0, description="Batches that failed")

    # Recent activity
    total_batches: int = Field(0, description="Total batch count")
    last_batch_at: Optional[str] = Field(None, description="ISO timestamp of most recent batch")

    # Job queue depth
    queue_depth: int = Field(0, description="Pending jobs in ops.job_queue")

    # Metadata
    checked_at: str = Field(..., description="ISO timestamp of this check")


# Keep old response for backward compatibility during transition
class IntakeStateResponse(BaseModel):
    """
    Minimal, always-available intake state.

    Designed for UI health checks - never throws, returns partial state with flags.
    Queries base tables only (no views).
    """

    ok: bool = Field(..., description="True if data was retrieved without errors")
    degraded: bool = Field(False, description="True if partial data due to errors")
    error: Optional[str] = Field(None, description="Error message if degraded")

    # Aggregate batch counts by status
    pending: int = Field(0, description="Batches waiting to start")
    processing: int = Field(0, description="Batches currently processing")
    completed: int = Field(0, description="Batches finished successfully")
    failed: int = Field(0, description="Batches that failed")

    # Recent activity
    total_batches: int = Field(0, description="Total batch count")
    last_batch_at: Optional[str] = Field(None, description="ISO timestamp of most recent batch")

    # Job queue depth
    queue_depth: int = Field(0, description="Pending jobs in ops.job_queue")

    # Metadata
    checked_at: str = Field(..., description="ISO timestamp of this check")


# ---------------------------------------------------------------------------
# Background Task Handler
# ---------------------------------------------------------------------------


async def process_upload_background(
    file_path: Path,
    batch_id: UUID,
    source: str,
    created_by: Optional[str],
) -> None:
    """
    Background task to process an uploaded file.

    This runs asynchronously after the HTTP response is sent.
    """
    try:
        pool = await get_pool()
        service = IntakeService(pool)

        result = await service.process_simplicity_upload(
            file_path=file_path,
            batch_id=batch_id,
            source=source,
            created_by=created_by,
            worker_id=f"api-background-{batch_id}",
        )

        logger.info(
            f"Background processing complete for batch {batch_id}: "
            f"{result.valid_rows}/{result.total_rows} valid"
        )

    except Exception:
        logger.exception(f"Background processing failed for batch {batch_id}")

    finally:
        # Clean up temp file
        try:
            file_path.unlink(missing_ok=True)
        except Exception as cleanup_err:
            logger.warning(f"Failed to delete temp file {file_path}: {cleanup_err}")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    summary="Intake system health check",
    description="Returns health status of the intake fortress subsystem.",
)
async def intake_health() -> dict[str, str]:
    """Health check for the intake subsystem."""
    return {"status": "ok", "subsystem": "intake_fortress"}


@router.get(
    "/state",
    response_model=ApiResponse[IntakeStateData],
    summary="Get intake system state",
    description="""
Minimal, read-only, always-available intake state endpoint.

Returns aggregate batch counts and status wrapped in standard API envelope.
Never throws - on error, returns envelope with `degraded=True` and error message.

Designed for UI health checks and dashboard widgets that need
reliable state without complex view dependencies.
""",
)
async def intake_state() -> ApiResponse[IntakeStateData]:
    """
    Get minimal intake state from base tables only.

    Never throws - wraps all errors and returns degraded envelope.
    """
    from datetime import datetime, timezone

    checked_at = datetime.now(timezone.utc).isoformat()

    try:
        pool = await get_pool()

        async with pool.connection() as conn:
            # Simple aggregate query on base tables only - no views, no joins
            # Query batch counts from ops.ingest_batches
            batch_query = """
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'processing') AS processing,
                    COUNT(*) FILTER (WHERE status = 'completed') AS completed,
                    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
                    COUNT(*) AS total,
                    MAX(created_at) AS last_batch_at
                FROM ops.ingest_batches
            """
            async with conn.cursor() as cur:
                await cur.execute(batch_query)
                batch_row = await cur.fetchone()

            # Query job queue depth from ops.job_queue
            queue_depth = 0
            try:
                queue_query = """
                    SELECT COUNT(*) FROM ops.job_queue WHERE status = 'pending'
                """
                async with conn.cursor() as cur:
                    await cur.execute(queue_query)
                    queue_row = await cur.fetchone()
                    queue_depth = queue_row[0] if queue_row else 0
            except Exception:
                # job_queue may not exist - graceful fallback
                queue_depth = 0

            if batch_row:
                pending, processing, completed, failed, total, last_batch_at = batch_row
                data = IntakeStateData(
                    pending=pending or 0,
                    processing=processing or 0,
                    completed=completed or 0,
                    failed=failed or 0,
                    total_batches=total or 0,
                    last_batch_at=last_batch_at.isoformat() if last_batch_at else None,
                    queue_depth=queue_depth,
                    checked_at=checked_at,
                )
                return api_response(data=data)
            else:
                # No rows - empty but valid
                data = IntakeStateData(
                    queue_depth=queue_depth,
                    checked_at=checked_at,
                )
                return api_response(data=data)

    except Exception as e:
        # Never throw - return degraded envelope
        logger.warning(f"Intake state check degraded: {e}")
        data = IntakeStateData(checked_at=checked_at)
        return degraded_response(error=str(e)[:200], data=data)


@router.post(
    "/upload",
    response_model=BatchCreateResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"},
    },
    summary="Upload CSV for intake processing",
    description="""
Upload a CSV file for intake processing.

The file is saved and processing starts in the background.
Returns immediately with a batch_id that can be used to track progress.

Supported sources: simplicity, jbi, manual, csv_upload
""",
)
async def upload_csv(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="CSV file to process")],
    source: str = Query("simplicity", description="Source system identifier"),
    auth: AuthContext = Depends(get_current_user),
) -> BatchCreateResponse | JSONResponse:
    """Upload a CSV file and start background processing."""

    batch_id = None  # Track for error logging

    try:
        logger.info(f"Intake upload started by {auth.via}: {file.filename}")

        # Validate request
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        if not file.filename.lower().endswith(".csv"):
            raise HTTPException(status_code=400, detail="File must be a CSV")

        if source not in ("simplicity", "jbi", "foil", "manual", "csv_upload", "api"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Must be one of: simplicity, jbi, foil, manual, csv_upload, api",
            )

        # Save file to temp location
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".csv",
                prefix=f"intake_{source}_",
                delete=False,
            ) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = Path(tmp.name)

            logger.info(f"Saved upload to temp file: {tmp_path}")

        except Exception as e:
            logger.error(f"Failed to save uploaded file: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to save uploaded file: {e}",
            )

        # Create batch record
        try:
            pool = await get_pool()
            service = IntakeService(pool)

            batch_id = await service.create_batch(
                filename=file.filename,
                source=source,
                created_by=auth.via,
            )

            logger.info(f"Created batch {batch_id} for {file.filename}")

        except Exception as e:
            logger.error(f"Failed to create batch: {e}")
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)

            # Check for RLS violation specifically
            if is_rls_violation(e):
                logger.error(f"RLS violation during batch creation: {e}")
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied: Row-level security policy violation. "
                    "Ensure the API is using service_role credentials.",
                )
            raise

        # Start background processing
        background_tasks.add_task(
            process_upload_background,
            file_path=tmp_path,
            batch_id=batch_id,
            source=source,
            created_by=auth.via,
        )

        return BatchCreateResponse(
            batch_id=str(batch_id),
            status="processing",
            message=f"Processing started for {file.filename}. Check /intake/batches/{batch_id} for status.",
        )

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Catch any unexpected errors
        logger.exception(
            "Intake upload failed",
            extra={
                "batch_id": str(batch_id) if batch_id else None,
                "upload_filename": file.filename,
            },
        )
        return JSONResponse(
            status_code=500,
            content={"error": "intake_upload_failed", "message": str(e)},
        )


class BatchListData(BaseModel):
    """Batch list data payload for ApiResponse envelope."""

    batches: list[BatchSummary]
    total: int
    page: int
    page_size: int


@router.get(
    "/batches",
    response_model=ApiResponse[BatchListData],
    summary="List all intake batches",
    description="Returns paginated list of all intake batches with summary stats wrapped in standard API envelope. Never crashes - returns degraded response on error.",
)
async def list_batches(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    auth: AuthContext = Depends(get_current_user),
) -> ApiResponse[BatchListData]:
    """
    List all intake batches with pagination.

    PR-3: Hardened to query ONLY ops.ingest_batches base table.
    No complex view dependencies - computes derived fields in Python.

    Degrade Guard: On any error, returns 200 OK with degraded envelope.
    The UI must NEVER crash.
    """
    from ...core.trace_middleware import get_trace_id

    try:
        pool = await get_pool()

        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            # Build query with explicit parameter ordering
            params: list[Any] = []
            where_clause = ""

            if status:
                where_clause = "WHERE status = %s"
                params.append(status)

            # Get total count from base table
            count_query = f"SELECT COUNT(*) FROM ops.ingest_batches {where_clause}"
            async with conn.cursor() as cur:
                await cur.execute(count_query, params if params else None)
                row = await cur.fetchone()
                total = row[0] if row else 0

            # Get paginated results from BASE TABLE ONLY (PR-3)
            offset = (page - 1) * page_size

            # Query only required columns from ops.ingest_batches
            # No joins, no views - maximum reliability
            base_query = f"""
                SELECT
                    id,
                    source,
                    filename,
                    row_count_raw AS total_rows,
                    row_count_valid AS valid_rows,
                    row_count_invalid AS error_rows,
                    plaintiff_inserted,
                    plaintiff_duplicate,
                    plaintiff_failed,
                    status,
                    created_at,
                    completed_at,
                    started_at
                FROM ops.ingest_batches
                {where_clause}
                ORDER BY created_at DESC
            """

            # Append LIMIT/OFFSET with params in strict order
            data_query = base_query + " LIMIT %s OFFSET %s"
            data_params = params + [page_size, offset]

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(data_query, data_params)
                rows = await cur.fetchall()

            # Compute derived fields in Python (previously in view)
            batches = []
            for row in rows:
                total_rows = row["total_rows"] or 0
                valid_rows = row["valid_rows"] or 0
                error_rows = row["error_rows"] or 0

                # Compute success_rate
                success_rate = 0.0
                if total_rows > 0:
                    success_rate = round((valid_rows / total_rows) * 100, 2)

                # Compute duration_seconds
                duration_seconds: float | None = None
                if row["completed_at"] and row["started_at"]:
                    delta = row["completed_at"] - row["started_at"]
                    duration_seconds = round(delta.total_seconds(), 2)

                # Compute health_status based on success rate and status
                health_status = "healthy"
                if row["status"] == "failed":
                    health_status = "critical"
                elif error_rows > 0 and success_rate < 80:
                    health_status = "critical"
                elif error_rows > 0 and success_rate < 95:
                    health_status = "warning"

                batches.append(
                    BatchSummary(
                        id=str(row["id"]),
                        filename=row["filename"] or "unknown",
                        source=row["source"] or "unknown",
                        status=row["status"] or "pending",
                        total_rows=total_rows,
                        valid_rows=valid_rows,
                        error_rows=error_rows,
                        plaintiffs_inserted=row.get("plaintiff_inserted") or 0,
                        plaintiffs_duplicate=row.get("plaintiff_duplicate") or 0,
                        plaintiffs_failed=row.get("plaintiff_failed") or 0,
                        success_rate=success_rate,
                        duration_seconds=duration_seconds,
                        health_status=health_status,
                        created_at=row["created_at"].isoformat() if row["created_at"] else "",
                        completed_at=(
                            row["completed_at"].isoformat() if row["completed_at"] else None
                        ),
                    )
                )

            data = BatchListData(
                batches=batches,
                total=total,
                page=page,
                page_size=page_size,
            )
            return api_response(data=data)

    except Exception as e:
        # DEGRADE GUARD: Never 500 - return degraded envelope with trace_id
        trace_id = get_trace_id()
        logger.error(f"[trace:{trace_id}] list_batches failed, returning degraded response: {e}")
        data = BatchListData(batches=[], total=0, page=page, page_size=page_size)
        return degraded_response(error=str(e)[:200], data=data)


# Support both /batch/{id} (legacy) and /batches/{id} (canonical)
@router.get(
    "/batch/{batch_id}",
    response_model=BatchDetailResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Batch not found"},
    },
    summary="Get batch details (legacy alias)",
    description="Legacy alias for /batches/{batch_id}. Use /batches/{batch_id} for new integrations.",
    include_in_schema=False,  # Hide from OpenAPI docs
)
@router.get(
    "/batches/{batch_id}",
    response_model=BatchDetailResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Batch not found"},
    },
    summary="Get batch details",
    description="Returns detailed information about a specific batch.",
)
async def get_batch(
    batch_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> BatchDetailResponse:
    """Get detailed batch information."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM ops.v_intake_monitor WHERE id = %s",
                (str(batch_id),),
            )
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Batch not found")

        # Parse stats
        stats = row.get("stats") or {}

        return BatchDetailResponse(
            id=str(row["id"]),
            filename=row["filename"],
            source=row["source"],
            status=row["status"],
            total_rows=row["total_rows"] or 0,
            valid_rows=row["valid_rows"] or 0,
            error_rows=row["error_rows"] or 0,
            duplicate_rows=stats.get("duplicates", 0),
            skipped_rows=stats.get("skipped", 0),
            plaintiffs_inserted=row.get("plaintiff_inserted", 0) or 0,
            plaintiffs_duplicate=row.get("plaintiff_duplicate", 0) or 0,
            plaintiffs_failed=row.get("plaintiff_failed", 0) or 0,
            success_rate=float(row["success_rate"] or 0),
            duration_seconds=(float(row["duration_seconds"]) if row["duration_seconds"] else None),
            health_status=row["health_status"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
            started_at=row["started_at"].isoformat() if row.get("started_at") else None,
            completed_at=(row["completed_at"].isoformat() if row["completed_at"] else None),
            created_by=row.get("created_by"),
            worker_id=row.get("worker_id"),
            stats=stats,
            recent_errors=row.get("recent_errors") or [],
        )


# Support both /batch/{id}/errors (legacy) and /batches/{id}/errors (canonical)
@router.get(
    "/batch/{batch_id}/errors",
    response_model=ErrorLogResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Batch not found"},
    },
    summary="Get batch error log (legacy alias)",
    description="Legacy alias for /batches/{batch_id}/errors.",
    include_in_schema=False,
)
@router.get(
    "/batches/{batch_id}/errors",
    response_model=ErrorLogResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Batch not found"},
    },
    summary="Get batch error log",
    description="Returns paginated error log for a specific batch.",
)
async def get_batch_errors(
    batch_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page"),
    auth: AuthContext = Depends(get_current_user),
) -> ErrorLogResponse:
    """Get error log entries for a batch."""

    pool = await get_pool()

    async with pool.connection() as conn:
        # Verify batch exists
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM ops.ingest_batches WHERE id = %s",
                (str(batch_id),),
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Batch not found")

        # Get total count
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM ops.intake_logs
                WHERE batch_id = %s AND status IN ('error', 'skipped')
                """,
                (str(batch_id),),
            )
            row = await cur.fetchone()
            total = row[0] if row else 0

        # Get paginated errors
        offset = (page - 1) * page_size
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    row_index,
                    status,
                    error_code,
                    error_details,
                    judgment_id,
                    created_at
                FROM ops.intake_logs
                WHERE batch_id = %s AND status IN ('error', 'skipped')
                ORDER BY row_index
                LIMIT %s OFFSET %s
                """,
                (str(batch_id), page_size, offset),
            )
            rows = await cur.fetchall()

        errors = [
            ErrorLogEntry(
                row_index=row["row_index"],
                status=row["status"],
                error_code=row["error_code"],
                error_details=row["error_details"],
                judgment_id=str(row["judgment_id"]) if row["judgment_id"] else None,
                created_at=row["created_at"].isoformat() if row["created_at"] else "",
            )
            for row in rows
        ]

        return ErrorLogResponse(
            batch_id=str(batch_id),
            errors=errors,
            total=total,
            page=page,
            page_size=page_size,
        )


# ---------------------------------------------------------------------------
# V1 Endpoints - Using intake.view_batch_progress
# Ops-Grade Observability endpoints for detailed batch inspection
# ---------------------------------------------------------------------------


class SimplicitBatchProgress(BaseModel):
    """Progress details for a Simplicity batch from intake.view_batch_progress."""

    batch_id: str
    filename: str | None = None
    source_reference: str | None = None
    status: str
    total_rows: int = 0
    processed_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    job_count: int = 0
    progress_pct: float = 0.0
    success_rate_pct: float = 0.0
    error_summary: str | None = None
    created_at: str | None = None


class SimplicityBatchError(BaseModel):
    """Error entry for a Simplicity batch."""

    row_index: int
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_data_preview: str | None = None  # Truncated/masked for security
    retryable: bool = True
    created_at: str | None = None


class SimplicityBatchErrorsResponse(BaseModel):
    """Paginated errors response for a Simplicity batch."""

    batch_id: str
    errors: list[SimplicityBatchError]
    total: int
    page: int
    page_size: int


@router.get(
    "/v1/batches/{batch_id}",
    response_model=ApiResponse[SimplicitBatchProgress],
    summary="Get Simplicity batch progress (v1)",
    description="""
Get detailed progress for a Simplicity intake batch.

Uses `intake.view_batch_progress` for real-time progress tracking.
Returns counts for total, staged, success, failed, and job queue.
""",
)
async def get_simplicity_batch_progress(
    batch_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> ApiResponse[SimplicitBatchProgress]:
    """Get batch progress from intake.view_batch_progress."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    batch_id,
                    filename,
                    source_reference,
                    status,
                    total_rows,
                    processed_count,
                    success_count,
                    failed_count,
                    job_count,
                    progress_pct,
                    success_rate_pct,
                    error_summary,
                    created_at
                FROM intake.view_batch_progress
                WHERE batch_id = %s
                """,
                (batch_id,),
            )
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Batch not found")

        data = SimplicitBatchProgress(
            batch_id=str(row["batch_id"]),
            filename=row["filename"],
            source_reference=row["source_reference"],
            status=row["status"],
            total_rows=row["total_rows"] or 0,
            processed_count=row["processed_count"] or 0,
            success_count=row["success_count"] or 0,
            failed_count=row["failed_count"] or 0,
            job_count=row["job_count"] or 0,
            progress_pct=float(row["progress_pct"] or 0),
            success_rate_pct=float(row["success_rate_pct"] or 0),
            error_summary=row["error_summary"],
            created_at=row["created_at"].isoformat() if row["created_at"] else None,
        )
        return api_response(data=data)


@router.get(
    "/v1/batches/{batch_id}/errors",
    response_model=ApiResponse[SimplicityBatchErrorsResponse],
    summary="Get Simplicity batch errors (v1)",
    description="""
Get paginated error log for a Simplicity intake batch.

Returns error details including row_index, error_code, error_message,
and a truncated preview of the raw_data (masked for security).
""",
)
async def get_simplicity_batch_errors(
    batch_id: UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page"),
    auth: AuthContext = Depends(get_current_user),
) -> ApiResponse[SimplicityBatchErrorsResponse]:
    """Get error log entries for a Simplicity batch."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        # Verify batch exists
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT 1 FROM intake.simplicity_batches WHERE id = %s",
                (batch_id,),
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Batch not found")

        # Get total count of unresolved errors
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM intake.simplicity_failed_rows
                WHERE batch_id = %s AND resolved_at IS NULL
                """,
                (batch_id,),
            )
            row = await cur.fetchone()
            total = row[0] if row else 0

        # Get paginated errors
        offset = (page - 1) * page_size

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT
                    row_index,
                    error_stage,
                    error_code,
                    error_message,
                    raw_data,
                    retryable,
                    created_at
                FROM intake.simplicity_failed_rows
                WHERE batch_id = %s AND resolved_at IS NULL
                ORDER BY row_index
                LIMIT %s OFFSET %s
                """,
                (batch_id, page_size, offset),
            )
            rows = await cur.fetchall()

        import json

        errors = []
        for row in rows:
            # Truncate/mask raw_data for security
            raw_data_preview = None
            if row["raw_data"]:
                try:
                    raw_str = json.dumps(row["raw_data"])
                    # Truncate to 200 chars
                    if len(raw_str) > 200:
                        raw_data_preview = raw_str[:200] + "..."
                    else:
                        raw_data_preview = raw_str
                except Exception:
                    raw_data_preview = "[unable to serialize]"

            errors.append(
                SimplicityBatchError(
                    row_index=row["row_index"],
                    error_stage=row["error_stage"],
                    error_code=row["error_code"],
                    error_message=row["error_message"],
                    raw_data_preview=raw_data_preview,
                    retryable=row["retryable"] if row["retryable"] is not None else True,
                    created_at=row["created_at"].isoformat() if row["created_at"] else None,
                )
            )

        data = SimplicityBatchErrorsResponse(
            batch_id=str(batch_id),
            errors=errors,
            total=total,
            page=page,
            page_size=page_size,
        )
        return api_response(data=data)


# ---------------------------------------------------------------------------
# Intake Trace Endpoint - Timeline view for a batch
# ---------------------------------------------------------------------------


class IntakeTraceEvent(BaseModel):
    """Single event in an intake trace timeline."""

    timestamp: str
    stage: str
    event: str
    details: dict | None = None
    row_index: int | None = None
    correlation_id: str | None = None


class IntakeTraceResponse(BaseModel):
    """Full timeline trace for a batch."""

    batch_id: str
    filename: str | None = None
    status: str
    total_rows: int = 0
    success_count: int = 0
    failed_count: int = 0
    events: list[IntakeTraceEvent]
    job_summary: dict | None = None


@router.get(
    "/v1/batches/{batch_id}/trace",
    response_model=ApiResponse[IntakeTraceResponse],
    summary="Get intake trace timeline for a batch",
    description="""
Get a detailed timeline of all events for an intake batch.

This endpoint provides a chronological view of:
- Batch lifecycle events (created, processing, completed)
- Validation events (row validated, row failed)
- Job queue events (enqueued, processing, completed, failed)
- Audit log events from ops.ingest_event_log

Useful for debugging batch processing issues and understanding
the complete lifecycle of an intake operation.
""",
)
async def get_batch_trace(
    batch_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> ApiResponse[IntakeTraceResponse]:
    """Get timeline trace for a batch."""
    import json

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        # Get batch details
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT id, filename, status, row_count_total, row_count_valid, row_count_failed, created_at, completed_at
                FROM intake.simplicity_batches
                WHERE id = %s
                """,
                (batch_id,),
            )
            batch = await cur.fetchone()

            if not batch:
                raise HTTPException(status_code=404, detail="Batch not found")

        events: list[IntakeTraceEvent] = []

        # Event 1: Batch created
        events.append(
            IntakeTraceEvent(
                timestamp=batch["created_at"].isoformat() if batch["created_at"] else "",
                stage="batch",
                event="created",
                details={"filename": batch["filename"]},
            )
        )

        # Gather events from ops.ingest_event_log if exists
        async with conn.cursor(row_factory=dict_row) as cur:
            try:
                await cur.execute(
                    """
                    SELECT stage, event, metadata, created_at, correlation_id
                    FROM ops.ingest_event_log
                    WHERE batch_id = %s
                    ORDER BY created_at
                    LIMIT 100
                    """,
                    (batch_id,),
                )
                audit_rows = await cur.fetchall()
                for row in audit_rows:
                    events.append(
                        IntakeTraceEvent(
                            timestamp=row["created_at"].isoformat() if row["created_at"] else "",
                            stage=row["stage"] or "audit",
                            event=row["event"] or "log",
                            details=row["metadata"] if isinstance(row["metadata"], dict) else None,
                            correlation_id=(
                                str(row["correlation_id"]) if row["correlation_id"] else None
                            ),
                        )
                    )
            except Exception:
                # Table may not exist yet
                pass

        # Gather validation failure events (sample)
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT row_index, error_stage, error_code, error_message, created_at, correlation_id
                FROM intake.simplicity_failed_rows
                WHERE batch_id = %s
                ORDER BY created_at
                LIMIT 20
                """,
                (batch_id,),
            )
            failed_rows = await cur.fetchall()
            for row in failed_rows:
                events.append(
                    IntakeTraceEvent(
                        timestamp=row["created_at"].isoformat() if row["created_at"] else "",
                        stage=row["error_stage"] or "validate",
                        event="row_failed",
                        details={
                            "error_code": row["error_code"],
                            "message": row["error_message"][:100] if row["error_message"] else None,
                        },
                        row_index=row["row_index"],
                        correlation_id=(
                            str(row["correlation_id"]) if row["correlation_id"] else None
                        ),
                    )
                )

        # Gather job queue events
        job_summary = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT status, COUNT(*) as cnt
                FROM ops.job_queue
                WHERE payload->>'batch_id' = %s OR payload->>'simplicity_batch_id' = %s
                GROUP BY status
                """,
                (str(batch_id), str(batch_id)),
            )
            for row in await cur.fetchall():
                if row["status"] in job_summary:
                    job_summary[row["status"]] = row["cnt"]

        # Event: Batch completed (if applicable)
        if batch["completed_at"]:
            events.append(
                IntakeTraceEvent(
                    timestamp=batch["completed_at"].isoformat(),
                    stage="batch",
                    event="completed",
                    details={
                        "status": batch["status"],
                        "total": batch["row_count_total"],
                        "valid": batch["row_count_valid"],
                        "failed": batch["row_count_failed"],
                    },
                )
            )

        # Sort events by timestamp
        events.sort(key=lambda e: e.timestamp)

        data = IntakeTraceResponse(
            batch_id=str(batch_id),
            filename=batch["filename"],
            status=batch["status"],
            total_rows=batch["row_count_total"] or 0,
            success_count=batch["row_count_valid"] or 0,
            failed_count=batch["row_count_failed"] or 0,
            events=events,
            job_summary=job_summary,
        )
        return api_response(data=data)
