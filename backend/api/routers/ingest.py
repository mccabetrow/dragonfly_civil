"""
Dragonfly Engine - Ingest Router

Endpoints for ingesting judgment data from various sources (Simplicity, etc.).
"""

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from ...core.security import AuthContext, get_current_user
from ...services.discord_service import DiscordService
from ...services.ingest_service import ingest_simplicity_csv, log_ingest_result

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["Ingest"])


class PathIngestRequest(BaseModel):
    """Request body for path-based ingestion."""

    path: str


class IngestResponse(BaseModel):
    """Response from ingest operations."""

    status: str
    rows: int
    inserted: int
    failed: int
    source: str
    message: str


class IngestErrorResponse(BaseModel):
    """Error response from ingest operations."""

    status: str = "error"
    error: str
    detail: str | None = None


@router.post(
    "/simplicity/upload",
    response_model=IngestResponse,
    responses={
        500: {"model": IngestErrorResponse, "description": "Ingest failed"},
    },
)
async def upload_simplicity_csv(
    file: Annotated[UploadFile, File(description="Simplicity CSV export file")],
    auth: AuthContext = Depends(get_current_user),
) -> IngestResponse:
    """
    Upload a Simplicity CSV file for ingestion.

    Accepts a CSV file via multipart/form-data, saves it to a temp directory,
    then processes it for insertion into the staging_judgments table.

    Requires authentication via API key or JWT token.
    """
    logger.info(f"Ingest upload started by {auth.via}: {file.filename}")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    logger.info(f"Received Simplicity CSV upload: {file.filename}")

    # Save to temp directory
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".csv",
            prefix="simplicity_",
            delete=False,
        ) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        logger.info(f"Saved upload to temp file: {tmp_path}")

    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": str(e),
                "detail": "Failed to save uploaded file",
            },
        )

    # Process the CSV
    try:
        summary = await ingest_simplicity_csv(tmp_path)
        source = f"upload:{file.filename}"

        # Log the result
        await log_ingest_result(summary, source)

        # Notify Discord on success
        async with DiscordService() as discord:
            await discord.send_message(
                f"✅ Simplicity ingest complete: {summary['inserted']}/{summary['rows']} "
                f"rows inserted from {source}."
            )

        return IngestResponse(
            status="success",
            rows=summary["rows"],
            inserted=summary["inserted"],
            failed=summary["failed"],
            source=source,
            message=f"Successfully processed {file.filename}",
        )

    except Exception as e:
        logger.exception(f"Ingest failed for {file.filename}: {e}")

        # Notify Discord on failure
        async with DiscordService() as discord:
            await discord.send_message(
                f"❌ Simplicity ingest FAILED for upload:{file.filename}: {str(e)[:200]}"
            )

        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": str(e),
                "detail": f"Ingest failed for {file.filename}",
            },
        )

    finally:
        # Clean up temp file
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass


@router.post(
    "/simplicity/path",
    response_model=IngestResponse,
    responses={
        500: {"model": IngestErrorResponse, "description": "Ingest failed"},
    },
)
async def ingest_simplicity_from_path(
    request: PathIngestRequest,
    auth: AuthContext = Depends(get_current_user),
) -> IngestResponse:
    """
    Ingest a Simplicity CSV from a path.

    Accepts a JSON body with a path field. Supported path schemes:
    - Local filesystem: /path/to/file.csv
    - S3: s3://bucket/key.csv (not yet implemented)
    - Supabase Storage: supabase://storage/bucket/key.csv (not yet implemented)

    Requires authentication via API key or JWT token.
    """
    path = request.path

    logger.info(f"Ingest from path started by {auth.via}: {path}")

    # Validate path scheme
    if path.startswith("s3://"):
        raise HTTPException(
            status_code=501,
            detail={"status": "error", "error": "S3 paths not yet implemented"},
        )

    if path.startswith("supabase://"):
        raise HTTPException(
            status_code=501,
            detail={
                "status": "error",
                "error": "Supabase Storage paths not yet implemented",
            },
        )

    # For now, assume local filesystem path
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": f"File not found: {path}"},
        )

    if not file_path.suffix.lower() == ".csv":
        raise HTTPException(
            status_code=400,
            detail={"status": "error", "error": "File must be a CSV"},
        )

    try:
        summary = await ingest_simplicity_csv(str(file_path))
        source = f"path:{path}"

        # Log the result
        await log_ingest_result(summary, source)

        # Notify Discord on success
        async with DiscordService() as discord:
            await discord.send_message(
                f"✅ Simplicity ingest complete: {summary['inserted']}/{summary['rows']} "
                f"rows inserted from {source}."
            )

        return IngestResponse(
            status="success",
            rows=summary["rows"],
            inserted=summary["inserted"],
            failed=summary["failed"],
            source=source,
            message=f"Successfully processed {path}",
        )

    except Exception as e:
        logger.exception(f"Ingest failed for {path}: {e}")

        # Notify Discord on failure
        async with DiscordService() as discord:
            await discord.send_message(
                f"❌ Simplicity ingest FAILED for path:{path}: {str(e)[:200]}"
            )

        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "error": str(e),
                "detail": f"Ingest failed for {path}",
            },
        )
