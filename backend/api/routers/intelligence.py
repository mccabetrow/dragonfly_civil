"""
Dragonfly Engine - Intelligence Router

Provides endpoints for:
- Judgment Intelligence Graph queries
- RAG-based semantic search with citations
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/intelligence", tags=["Intelligence"])


# =============================================================================
# RAG Search Models
# =============================================================================


class RAGSearchRequest(BaseModel):
    """Request body for RAG search."""

    query: str = Field(..., description="Natural language question", min_length=3, max_length=1000)
    match_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for chunk retrieval",
    )
    match_count: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Maximum number of chunks to retrieve",
    )


class CitationResponse(BaseModel):
    """A citation linking an answer to source evidence."""

    document_id: str = Field(..., description="RAG document UUID")
    evidence_id: str = Field(..., description="Evidence file UUID (immutable source)")
    page_number: Optional[int] = Field(None, description="Page number in source document")
    chunk_index: int = Field(..., description="Chunk position within document")
    quote_snippet: str = Field(..., description="Relevant excerpt from source")
    similarity: float = Field(..., description="Cosine similarity score")


class RAGSearchResponse(BaseModel):
    """Response from RAG search with mandatory citations."""

    answer: str = Field(..., description="Generated answer with inline citations")
    citations: list[CitationResponse] = Field(
        default_factory=list, description="Structured citations for verification"
    )
    query: str = Field(..., description="Original query")
    chunks_retrieved: int = Field(..., description="Number of context chunks used")
    model_used: str = Field(..., description="LLM model used for synthesis")
    insufficient_evidence: bool = Field(
        default=False, description="True if context was insufficient to answer"
    )


# =============================================================================
# Graph Response Models
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
# RAG Search Endpoints
# =============================================================================


@router.post(
    "/search",
    response_model=RAGSearchResponse,
    summary="RAG semantic search with citations",
    description="Search evidence documents using natural language. Returns answers grounded in source documents with mandatory citations.",
)
async def rag_search_endpoint(
    request: RAGSearchRequest,
    org_id: str = "00000000-0000-0000-0000-000000000000",  # TODO: Extract from JWT
) -> RAGSearchResponse:
    """
    Execute RAG search with citations enforcement.

    This endpoint:
    1. Embeds the query using text-embedding-3-small
    2. Retrieves relevant document chunks from the vector store
    3. Synthesizes an answer using GPT-4o with strict citation requirements
    4. Returns structured citations linking to evidence.files

    Args:
        request: Search query and parameters
        org_id: Organization ID for RLS filtering (will be extracted from JWT)

    Returns:
        RAGSearchResponse with answer, citations, and metadata

    Raises:
        HTTPException: On service errors
    """
    try:
        from ...services.rag import get_rag_service

        service = get_rag_service()

        result = await service.search(
            query=request.query,
            org_id=org_id,
            match_threshold=request.match_threshold,
            match_count=request.match_count,
        )

        return RAGSearchResponse(
            answer=result.answer,
            citations=[
                CitationResponse(
                    document_id=c.document_id,
                    evidence_id=c.evidence_id,
                    page_number=c.page_number,
                    chunk_index=c.chunk_index,
                    quote_snippet=c.quote_snippet,
                    similarity=c.similarity,
                )
                for c in result.citations
            ],
            query=result.query,
            chunks_retrieved=result.chunks_retrieved,
            model_used=result.model_used,
            insufficient_evidence=result.insufficient_evidence,
        )

    except ValueError as e:
        logger.warning("RAG search validation error: %s", e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("RAG search failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.get(
    "/search/health",
    summary="RAG service health",
    description="Check if the RAG search service is operational.",
)
async def rag_health_endpoint() -> dict[str, Any]:
    """
    Health check for RAG service.

    Verifies OpenAI and Supabase configuration.

    Returns:
        Health status dict
    """
    try:
        from ...services.rag import get_rag_service

        service = get_rag_service()
        return await service.health_check()
    except Exception as e:
        logger.error("RAG health check failed: %s", e)
        return {"status": "error", "message": str(e)}


# =============================================================================
# Graph Endpoints
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
        from ...services.graph_service import get_judgment_graph

        result = await get_judgment_graph(judgment_id)

        return JudgmentGraphResponse(
            judgment_id=result["judgment_id"],
            entities=[EntityResponse(**e) for e in result["entities"]],
            relationships=[RelationshipResponse(**r) for r in result["relationships"]],
        )

    except Exception as e:
        logger.error("Failed to get graph for judgment %s: %s", judgment_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve judgment graph: {str(e)}")


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
        from ...db import get_pool

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
