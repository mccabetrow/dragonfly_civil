"""
Dragonfly Engine - Offers Router

Endpoints for managing offers on judgments (purchase and contingency offers).
Part of the Transaction Engine.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..db import get_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/offers", tags=["Offers"])


# =============================================================================
# Request/Response Models
# =============================================================================


class CreateOfferRequest(BaseModel):
    """Request body for creating a new offer."""

    judgment_id: int = Field(..., description="ID of the judgment to make an offer on")
    offer_amount: Decimal = Field(..., description="Dollar amount of the offer")
    offer_type: Literal["purchase", "contingency"] = Field(
        ...,
        description="Type of offer: purchase (buy outright) or contingency (collection fee)",
    )
    operator_notes: Optional[str] = Field(
        default="", description="Internal notes from the operator"
    )

    @field_validator("offer_amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("offer_amount must be greater than 0")
        return v


class UpdateOfferStatusRequest(BaseModel):
    """Request body for updating an offer's status."""

    status: Literal["offered", "negotiation", "accepted", "rejected", "expired"] = Field(
        ..., description="New status for the offer"
    )
    operator_notes: Optional[str] = Field(default=None, description="Optional notes to append")


class OfferResponse(BaseModel):
    """Response model for a single offer."""

    id: str = Field(..., description="Offer UUID")
    judgment_id: int = Field(..., description="ID of the judgment")
    offer_amount: Decimal = Field(..., description="Dollar amount of the offer")
    offer_type: str = Field(..., description="Type of offer")
    status: str = Field(..., description="Current status of the offer")
    operator_notes: str = Field(..., description="Operator notes")
    created_at: str = Field(..., description="ISO timestamp of creation")


class OfferStatsResponse(BaseModel):
    """Response model for aggregated offer statistics."""

    total_offers: int = Field(..., description="Total number of offers")
    accepted: int = Field(..., description="Number of accepted offers")
    rejected: int = Field(..., description="Number of rejected offers")
    negotiation: int = Field(..., description="Number of offers in negotiation")
    conversion_rate: float = Field(..., description="Acceptance rate (accepted / total)")


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str


# =============================================================================
# Endpoints
# =============================================================================


@router.post(
    "",
    response_model=OfferResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        404: {"model": ErrorResponse, "description": "Judgment not found"},
    },
    summary="Create a new offer",
    description="Create a new offer on a judgment. Validates that the judgment exists and offer amount is positive.",
)
async def create_offer(request: CreateOfferRequest) -> OfferResponse:
    """
    Create a new offer on a judgment.

    - Validates that judgment_id exists in public.judgments
    - Validates offer_amount > 0
    - Inserts a new row into enforcement.offers with status='offered'
    - Returns the created offer
    """
    async with get_connection() as conn:
        # Validate judgment exists
        row = await conn.fetchrow(
            "SELECT id FROM public.judgments WHERE id = %s",
            request.judgment_id,
        )

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Judgment with id {request.judgment_id} not found",
            )

        # Insert the offer
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO enforcement.offers (
                    judgment_id,
                    offer_amount,
                    offer_type,
                    status,
                    operator_notes
                ) VALUES (
                    %s,
                    %s,
                    %s::enforcement.offer_type,
                    'offered'::enforcement.offer_status,
                    %s
                )
                RETURNING id, judgment_id, offer_amount, offer_type, status, operator_notes, created_at
                """,
                request.judgment_id,
                float(request.offer_amount),
                request.offer_type,
                request.operator_notes or "",
            )

            if row is None:
                raise HTTPException(
                    status_code=500, detail="Failed to create offer - no row returned"
                )

            offer_id = row["id"]
            judgment_id = row["judgment_id"]
            offer_amount = row["offer_amount"]
            offer_type = row["offer_type"]
            status = row["status"]
            notes = row["operator_notes"]
            created_at = row["created_at"]

            logger.info(
                "Offer created: offer_id=%s judgment_id=%s type=%s amount=%.2f",
                offer_id,
                judgment_id,
                offer_type,
                float(offer_amount),
                extra={
                    "offer_id": str(offer_id),
                    "judgment_id": judgment_id,
                    "offer_type": offer_type,
                    "offer_amount": float(offer_amount),
                    "action": "offer_created",
                },
            )

            # Emit offer_made event (best-effort, after transaction commits)
            try:
                from ..services.event_service import emit_event_for_judgment

                # Calculate cents on the dollar if we have judgment amount
                cents_on_dollar = None
                try:
                    jrow = await conn.fetchrow(
                        "SELECT judgment_amount FROM public.judgments WHERE id = %s",
                        judgment_id,
                    )
                    if jrow and jrow.get("judgment_amount"):
                        judgment_amount_val = float(jrow["judgment_amount"])
                        if judgment_amount_val > 0:
                            cents_on_dollar = round(
                                (float(offer_amount) / judgment_amount_val) * 100, 1
                            )
                except Exception:
                    pass

                await emit_event_for_judgment(
                    judgment_id=judgment_id,
                    event_type="offer_made",
                    payload={
                        "judgment_id": judgment_id,
                        "amount": str(offer_amount),
                        "type": offer_type,
                        "cents_on_dollar": cents_on_dollar,
                        "offer_id": str(offer_id),
                    },
                )
            except Exception as event_err:
                # Never fail offer creation due to event emission
                logger.debug(
                    "Event emission skipped for offer %s: %s",
                    offer_id,
                    event_err,
                )

            return OfferResponse(
                id=str(offer_id),
                judgment_id=judgment_id,
                offer_amount=Decimal(str(offer_amount)),
                offer_type=offer_type,
                status=status,
                operator_notes=notes,
                created_at=created_at.isoformat(),
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Failed to create offer: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to create offer: {str(e)}")


@router.get(
    "/stats",
    response_model=OfferStatsResponse,
    summary="Get offer statistics",
    description="Get aggregated offer statistics, optionally filtered by date range.",
)
async def get_offer_stats(
    from_date: Optional[date] = Query(
        default=None, description="Start date for filtering (inclusive)"
    ),
    to_date: Optional[date] = Query(default=None, description="End date for filtering (inclusive)"),
) -> OfferStatsResponse:
    """
    Get aggregated offer statistics.

    Optionally filter by date range based on created_at.
    Returns counts by status and conversion rate.
    """
    # Build query with optional date filters
    query = """
        SELECT
            COUNT(*) AS total_offers,
            COUNT(*) FILTER (WHERE status = 'accepted') AS accepted,
            COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
            COUNT(*) FILTER (WHERE status = 'negotiation') AS negotiation
        FROM enforcement.offers
        WHERE 1=1
    """
    params: list = []

    if from_date:
        query += " AND created_at >= %s"
        params.append(from_date)

    if to_date:
        query += " AND created_at < %s + INTERVAL '1 day'"
        params.append(to_date)

    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(query, *params)

            if row is None:
                return OfferStatsResponse(
                    total_offers=0,
                    accepted=0,
                    rejected=0,
                    negotiation=0,
                    conversion_rate=0.0,
                )

            total = row["total_offers"]
            accepted = row["accepted"]
            rejected = row["rejected"]
            negotiation = row["negotiation"]

            # Calculate conversion rate
            conversion_rate = 0.0
            if total > 0:
                conversion_rate = round(accepted / total, 4)

            return OfferStatsResponse(
                total_offers=total,
                accepted=accepted,
                rejected=rejected,
                negotiation=negotiation,
                conversion_rate=conversion_rate,
            )

    except Exception as e:
        logger.error("Failed to get offer stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get offer stats: {str(e)}")


@router.get(
    "/{offer_id}",
    response_model=OfferResponse,
    responses={404: {"model": ErrorResponse, "description": "Offer not found"}},
    summary="Get offer by ID",
    description="Retrieve a single offer by its UUID.",
)
async def get_offer(offer_id: UUID) -> OfferResponse:
    """Get a single offer by ID."""
    try:
        async with get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, judgment_id, offer_amount, offer_type, status, operator_notes, created_at
                FROM enforcement.offers
                WHERE id = %s
                """,
                offer_id,
            )

            if row is None:
                raise HTTPException(status_code=404, detail=f"Offer with id {offer_id} not found")

            return OfferResponse(
                id=str(row["id"]),
                judgment_id=row["judgment_id"],
                offer_amount=Decimal(str(row["offer_amount"])),
                offer_type=row["offer_type"],
                status=row["status"],
                operator_notes=row["operator_notes"],
                created_at=row["created_at"].isoformat(),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get offer: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get offer: {str(e)}")


@router.get(
    "/judgment/{judgment_id}",
    response_model=list[OfferResponse],
    summary="Get offers for a judgment",
    description="Retrieve all offers made on a specific judgment.",
)
async def get_offers_for_judgment(judgment_id: int) -> list[OfferResponse]:
    """Get all offers for a specific judgment."""
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, judgment_id, offer_amount, offer_type, status, operator_notes, created_at
                FROM enforcement.offers
                WHERE judgment_id = %s
                ORDER BY created_at DESC
                """,
                judgment_id,
            )

            return [
                OfferResponse(
                    id=str(row["id"]),
                    judgment_id=row["judgment_id"],
                    offer_amount=Decimal(str(row["offer_amount"])),
                    offer_type=row["offer_type"],
                    status=row["status"],
                    operator_notes=row["operator_notes"],
                    created_at=row["created_at"].isoformat(),
                )
                for row in rows
            ]

    except Exception as e:
        logger.error("Failed to get offers for judgment: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get offers: {str(e)}")


@router.patch(
    "/{offer_id}/status",
    response_model=OfferResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Offer not found"},
    },
    summary="Update offer status",
    description="Update the status of an offer. Emits offer_accepted event when status changes to accepted.",
)
async def update_offer_status(
    offer_id: UUID,
    request: UpdateOfferStatusRequest,
) -> OfferResponse:
    """
    Update an offer's status.

    - Validates that the offer exists
    - Updates the status
    - Emits offer_accepted event if status changes to 'accepted'
    """
    try:
        async with get_connection() as conn:
            # First, get the current offer to check it exists and get judgment_id
            row = await conn.fetchrow(
                """
                SELECT id, judgment_id, offer_amount, offer_type, status, operator_notes, created_at
                FROM enforcement.offers
                WHERE id = %s
                """,
                offer_id,
            )

            if row is None:
                raise HTTPException(status_code=404, detail=f"Offer with id {offer_id} not found")

            old_status = row["status"]

            # Update the status
            new_notes = row["operator_notes"]
            if request.operator_notes:
                new_notes = (
                    f"{row['operator_notes']}\n{request.operator_notes}"
                    if row["operator_notes"]
                    else request.operator_notes
                )

            updated_row = await conn.fetchrow(
                """
                UPDATE enforcement.offers
                SET status = %s::enforcement.offer_status,
                    operator_notes = %s
                WHERE id = %s
                RETURNING id, judgment_id, offer_amount, offer_type, status, operator_notes, created_at
                """,
                request.status,
                new_notes,
                offer_id,
            )

            if updated_row is None:
                raise HTTPException(
                    status_code=500, detail="Failed to update offer - no row returned"
                )

            oid = updated_row["id"]
            jid = updated_row["judgment_id"]
            amount = updated_row["offer_amount"]
            otype = updated_row["offer_type"]
            status = updated_row["status"]
            notes = updated_row["operator_notes"]
            created_at = updated_row["created_at"]

            logger.info(
                "Offer status updated: offer_id=%s judgment_id=%s old_status=%s new_status=%s",
                offer_id,
                jid,
                old_status,
                request.status,
                extra={
                    "offer_id": str(offer_id),
                    "judgment_id": jid,
                    "old_status": old_status,
                    "new_status": request.status,
                    "action": "offer_status_updated",
                },
            )

            # Emit offer_accepted event if status changed to accepted
            if request.status == "accepted" and old_status != "accepted":
                logger.info(
                    "Offer ACCEPTED: offer_id=%s judgment_id=%s amount=%.2f",
                    oid,
                    jid,
                    float(amount),
                    extra={
                        "offer_id": str(oid),
                        "judgment_id": jid,
                        "offer_amount": float(amount),
                        "action": "offer_accepted",
                    },
                )
                try:
                    from ..services.event_service import emit_event_for_judgment

                    await emit_event_for_judgment(
                        judgment_id=jid,
                        event_type="offer_accepted",
                        payload={
                            "judgment_id": jid,
                            "amount": str(amount),
                            "type": otype,
                            "offer_id": str(oid),
                        },
                    )
                except Exception as event_err:
                    # Never fail status update due to event emission
                    logger.debug(
                        "Event emission skipped for offer %s: %s",
                        offer_id,
                        event_err,
                    )
            elif request.status == "rejected" and old_status != "rejected":
                logger.info(
                    "Offer REJECTED: offer_id=%s judgment_id=%s",
                    oid,
                    jid,
                    extra={
                        "offer_id": str(oid),
                        "judgment_id": jid,
                        "action": "offer_rejected",
                    },
                )

            return OfferResponse(
                id=str(oid),
                judgment_id=jid,
                offer_amount=Decimal(str(amount)),
                offer_type=otype,
                status=status,
                operator_notes=notes,
                created_at=created_at.isoformat(),
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to update offer status: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to update offer status: {str(e)}")
