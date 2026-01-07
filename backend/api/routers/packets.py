"""
Dragonfly Engine - Legal Packets Router

Endpoints for generating court-ready enforcement documents (DOCX).
Part of the Document Assembly Engine.
"""

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.packet_service import PacketError, generate_packet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/packets", tags=["Packets"])


# =============================================================================
# Request/Response Models
# =============================================================================


class PacketGenerateRequest(BaseModel):
    """Request body for generating a legal packet."""

    judgment_id: int = Field(..., description="ID of the judgment to generate packet for")
    type: Literal["income_execution_ny", "info_subpoena_ny"] = Field(
        ...,
        description="Type of packet: income_execution_ny (wage garnishment) or info_subpoena_ny (discovery)",
    )


class PacketGenerateResponse(BaseModel):
    """Response model for a generated packet."""

    packet_url: str = Field(..., description="URL to download the generated document")
    packet_type: str = Field(..., description="Type of packet generated")
    judgment_id: int = Field(..., description="ID of the judgment")


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "/generate",
    response_model=PacketGenerateResponse,
    responses={
        400: {
            "model": ErrorResponse,
            "description": "Invalid request or generation failed",
        },
        404: {"model": ErrorResponse, "description": "Judgment not found"},
    },
    summary="Generate a legal packet",
    description=(
        "Generate a court-ready enforcement document for a judgment. "
        "Supports Income Executions and Information Subpoenas for NY. "
        "Returns a signed URL to download the generated DOCX file."
    ),
)
async def generate_legal_packet(
    request: PacketGenerateRequest,
) -> PacketGenerateResponse:
    """
    Generate a legal packet document.

    - Validates that judgment_id exists
    - Renders the appropriate template with judgment data
    - Uploads to Supabase Storage
    - Returns download URL
    """
    logger.info(
        f"Generating packet: type={request.type}, judgment_id={request.judgment_id}",
        extra={"judgment_id": request.judgment_id, "packet_type": request.type},
    )

    try:
        packet_url = await generate_packet(
            judgment_id=request.judgment_id,
            packet_type=request.type,
        )

        return PacketGenerateResponse(
            packet_url=packet_url,
            packet_type=request.type,
            judgment_id=request.judgment_id,
        )

    except PacketError as e:
        error_msg = str(e)
        logger.warning(
            f"Packet generation failed: {error_msg}",
            extra={"judgment_id": request.judgment_id, "packet_type": request.type},
        )

        # Determine appropriate status code
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        else:
            raise HTTPException(status_code=400, detail=error_msg)

    except Exception as e:
        # Catch-all for unexpected errors - don't leak details
        logger.error(
            f"Unexpected error in packet generation: {e}",
            extra={"judgment_id": request.judgment_id, "packet_type": request.type},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again later.",
        )


@router.get(
    "/types",
    summary="List available packet types",
    description="Get a list of all available legal packet types with descriptions.",
)
async def list_packet_types() -> dict:
    """List available packet types and their descriptions."""
    return {
        "packet_types": [
            {
                "id": "income_execution_ny",
                "name": "Income Execution (NY)",
                "description": "Wage garnishment order for New York employers",
            },
            {
                "id": "info_subpoena_ny",
                "name": "Information Subpoena (NY)",
                "description": "Discovery document to obtain debtor financial information",
            },
        ]
    }
