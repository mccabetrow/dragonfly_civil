"""
Dragonfly Engine - Intake Router (Fortress Edition)

API endpoints for the hardened intake system.
Handles CSV uploads, batch management, and error reporting.

Endpoints:
    POST /api/v1/intake/upload - Upload CSV and start processing
    GET  /api/v1/intake/batches - List all batches with stats
    GET  /api/v1/intake/batch/{id} - Get batch details
    GET  /api/v1/intake/batch/{id}/errors - Get error log for batch
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any, Optional
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..core.security import AuthContext, get_current_user
from ..db import get_pool
from ..services.intake_service import IntakeService

logger = logging.getLogger(__name__)

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

        if source not in ("simplicity", "jbi", "manual", "csv_upload", "api"):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid source: {source}. Must be one of: simplicity, jbi, manual, csv_upload, api",
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
            # Clean up temp file then let exception bubble up to outer handler
            tmp_path.unlink(missing_ok=True)
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
            message=f"Processing started for {file.filename}. Check /intake/batch/{batch_id} for status.",
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


@router.get(
    "/batches",
    response_model=BatchListResponse,
    summary="List all intake batches",
    description="Returns paginated list of all intake batches with summary stats.",
)
async def list_batches(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    status: Optional[str] = Query(None, description="Filter by status"),
    auth: AuthContext = Depends(get_current_user),
) -> BatchListResponse:
    """List all intake batches with pagination."""

    pool = await get_pool()

    async with pool.connection() as conn:
        # Build query with optional status filter
        where_clause = ""
        params: list[Any] = []

        if status:
            where_clause = "WHERE status = $1"
            params.append(status)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM ops.v_intake_monitor {where_clause}"
        async with conn.cursor() as cur:
            await cur.execute(count_query, params)
            row = await cur.fetchone()
            total = row[0] if row else 0

        # Get paginated results
        offset = (page - 1) * page_size
        if status:
            params.extend([page_size, offset])
            data_query = f"""
                SELECT * FROM ops.v_intake_monitor 
                {where_clause}
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
            """
        else:
            params = [page_size, offset]
            data_query = """
                SELECT * FROM ops.v_intake_monitor 
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """

        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(data_query, params)
            rows = await cur.fetchall()

        batches = [
            BatchSummary(
                id=str(row["id"]),
                filename=row["filename"],
                source=row["source"],
                status=row["status"],
                total_rows=row["total_rows"] or 0,
                valid_rows=row["valid_rows"] or 0,
                error_rows=row["error_rows"] or 0,
                success_rate=float(row["success_rate"] or 0),
                duration_seconds=(
                    float(row["duration_seconds"]) if row["duration_seconds"] else None
                ),
                health_status=row["health_status"],
                created_at=row["created_at"].isoformat() if row["created_at"] else "",
                completed_at=(
                    row["completed_at"].isoformat() if row["completed_at"] else None
                ),
            )
            for row in rows
        ]

        return BatchListResponse(
            batches=batches,
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get(
    "/batch/{batch_id}",
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
                "SELECT * FROM ops.v_intake_monitor WHERE id = $1",
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
            success_rate=float(row["success_rate"] or 0),
            duration_seconds=(
                float(row["duration_seconds"]) if row["duration_seconds"] else None
            ),
            health_status=row["health_status"],
            created_at=row["created_at"].isoformat() if row["created_at"] else "",
            started_at=row["started_at"].isoformat() if row.get("started_at") else None,
            completed_at=(
                row["completed_at"].isoformat() if row["completed_at"] else None
            ),
            created_by=row.get("created_by"),
            worker_id=row.get("worker_id"),
            stats=stats,
            recent_errors=row.get("recent_errors") or [],
        )


@router.get(
    "/batch/{batch_id}/errors",
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
                "SELECT 1 FROM ops.ingest_batches WHERE id = $1",
                (str(batch_id),),
            )
            if not await cur.fetchone():
                raise HTTPException(status_code=404, detail="Batch not found")

        # Get total count
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) FROM ops.intake_logs 
                WHERE batch_id = $1 AND status IN ('error', 'skipped')
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
                WHERE batch_id = $1 AND status IN ('error', 'skipped')
                ORDER BY row_index
                LIMIT $2 OFFSET $3
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
