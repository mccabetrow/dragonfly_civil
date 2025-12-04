"""
Dragonfly Engine - Intelligence Router

Provides endpoints for querying the Judgment Intelligence Graph.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])


# =============================================================================
# Response Models
# =============================================================================


class EntityResponse(BaseModel):
    """Entity in the intelligence graph."""

    id: str = Field(..., description="Entity UUID")
    type: str = Field(..., description="Entity type (person, company, court, etc.)")
    raw_name: str = Field(..., description="Original name from source data")
    normalized_name: str = Field(..., description="Normalized name for matching")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional entity attributes"
    )


class RelationshipResponse(BaseModel):
    """Relationship between entities."""

    id: str = Field(..., description="Relationship UUID")
    source_entity_id: str = Field(..., description="Source entity UUID")
    target_entity_id: str = Field(..., description="Target entity UUID")
    relation: str = Field(
        ..., description="Relationship type (plaintiff_in, defendant_in, sued_at, etc.)"
    )
    confidence: float = Field(..., description="Confidence score (0.0 to 1.0)")
    source_judgment_id: int | None = Field(
        None, description="Judgment ID that established this relationship"
    )


class JudgmentGraphResponse(BaseModel):
    """Graph data for a specific judgment."""

    judgment_id: int = Field(..., description="The judgment ID")
    entities: list[EntityResponse] = Field(
        default_factory=list, description="Entities involved in this judgment"
    )
    relationships: list[RelationshipResponse] = Field(
        default_factory=list, description="Relationships established by this judgment"
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/judgment/{judgment_id}",
    response_model=JudgmentGraphResponse,
    summary="Get judgment graph",
    description="Retrieve all entities and relationships for a specific judgment.",
)
async def get_judgment_graph_endpoint(judgment_id: int) -> JudgmentGraphResponse:
    """
    Get the intelligence graph for a specific judgment.

    Returns all entities (plaintiff, defendant, court) and relationships
    that were created from this judgment.

    Args:
        judgment_id: The judgment ID to query

    Returns:
        JudgmentGraphResponse with entities and relationships

    Raises:
        HTTPException: On database errors
    """
    try:
        from ..services.graph_service import get_judgment_graph

        result = await get_judgment_graph(judgment_id)

        return JudgmentGraphResponse(
            judgment_id=result["judgment_id"],
            entities=[EntityResponse(**e) for e in result["entities"]],
            relationships=[RelationshipResponse(**r) for r in result["relationships"]],
        )

    except Exception as e:
        logger.error("Failed to get graph for judgment %s: %s", judgment_id, e)
        raise HTTPException(
            status_code=500, detail=f"Failed to retrieve judgment graph: {str(e)}"
        )


@router.get(
    "/health",
    summary="Intelligence service health",
    description="Check if the intelligence graph service is operational.",
)
async def intelligence_health() -> dict[str, str]:
    """
    Health check for the intelligence service.

    Verifies that the intelligence schema and tables exist.

    Returns:
        Health status dict
    """
    try:
        from ..db import get_pool

        conn = await get_pool()
        if conn is None:
            return {
                "status": "degraded",
                "message": "Database connection not available",
            }

        async with conn.cursor() as cur:
            # Check if intelligence schema exists
            await cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = 'intelligence'
                )
                """
            )
            row = await cur.fetchone()
            schema_exists = row[0] if row else False

            if not schema_exists:
                return {
                    "status": "degraded",
                    "message": "intelligence schema not found - run migrations",
                }

            # Check entity count
            await cur.execute("SELECT COUNT(*) FROM intelligence.entities")
            entity_row = await cur.fetchone()
            entity_count = entity_row[0] if entity_row else 0

            # Check relationship count
            await cur.execute("SELECT COUNT(*) FROM intelligence.relationships")
            rel_row = await cur.fetchone()
            rel_count = rel_row[0] if rel_row else 0

            return {
                "status": "healthy",
                "message": f"Graph contains {entity_count} entities and {rel_count} relationships",
            }

    except Exception as e:
        logger.error("Intelligence health check failed: %s", e)
        return {"status": "error", "message": str(e)}
