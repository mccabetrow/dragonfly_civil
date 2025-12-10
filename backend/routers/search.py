"""
Dragonfly Engine - Semantic Search Router

API endpoints for semantic (vector-based) search across judgments.
Uses pgvector for fast approximate nearest-neighbor queries.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..db import get_connection
from ..services.ai_service import generate_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------


class SemanticSearchRequest(BaseModel):
    """Request body for semantic search."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language search query",
        examples=["construction company in Queens", "unpaid rent Brooklyn"],
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of results to return",
    )


class JudgmentSearchResult(BaseModel):
    """A single judgment search result."""

    id: int
    plaintiff_name: str | None
    defendant_name: str | None
    judgment_amount: float | None
    county: str | None
    case_number: str | None
    score: float = Field(description="Similarity score (0-1, higher is better)")


class SemanticSearchResponse(BaseModel):
    """Response from semantic search."""

    query: str
    results: list[JudgmentSearchResult]
    count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/semantic",
    response_model=SemanticSearchResponse,
    summary="Semantic search across judgments",
    description="""
    Search for judgments using natural language queries.

    Uses OpenAI embeddings and pgvector for semantic similarity matching.
    Returns judgments ranked by relevance to the query.

    Example queries:
    - "construction company that didn't pay"
    - "restaurant in Manhattan"
    - "contractor Queens unpaid invoice"
    """,
)
async def semantic_search(body: SemanticSearchRequest) -> SemanticSearchResponse:
    """
    Perform semantic search across judgments.

    Args:
        body: Search request with query and limit

    Returns:
        List of matching judgments ranked by similarity
    """
    logger.info(f"Semantic search: query='{body.query}', limit={body.limit}")

    # Generate embedding for the search query
    query_embedding = await generate_embedding(body.query)

    if query_embedding is None:
        logger.warning("Failed to generate query embedding, returning empty results")
        return SemanticSearchResponse(
            query=body.query,
            results=[],
            count=0,
        )

    # Query database using cosine similarity
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    source_file as county,
                    case_number,
                    1 - (description_embedding <=> $1::vector) as score
                FROM public.judgments
                WHERE description_embedding IS NOT NULL
                ORDER BY description_embedding <=> $1::vector
                LIMIT $2
                """,
                str(query_embedding),
                body.limit,
            )

    except Exception as e:
        logger.error(f"Semantic search query failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Search query failed. Please try again.",
        )

    # Transform results
    results = []
    for row in rows:
        # Extract county from source_file if it contains pipe separator
        county = row.get("county")
        if county and "|" in county:
            county = county.split("|")[0]

        results.append(
            JudgmentSearchResult(
                id=row["id"],
                plaintiff_name=row.get("plaintiff_name"),
                defendant_name=row.get("defendant_name"),
                judgment_amount=row.get("judgment_amount"),
                county=county,
                case_number=row.get("case_number"),
                score=round(float(row.get("score", 0)), 4),
            )
        )

    logger.info(f"Semantic search returned {len(results)} results")

    return SemanticSearchResponse(
        query=body.query,
        results=results,
        count=len(results),
    )


@router.get(
    "/health",
    summary="Check search service health",
    description="Verify that embedding generation and vector search are operational.",
)
async def search_health() -> dict[str, Any]:
    """
    Health check for search functionality.

    Tests:
    1. OpenAI embedding generation
    2. pgvector query execution
    """
    status = {"embedding": "unknown", "vector_search": "unknown"}

    # Test embedding generation
    try:
        test_embedding = await generate_embedding("test query for health check")
        if test_embedding and len(test_embedding) == 1536:
            status["embedding"] = "ok"
        else:
            status["embedding"] = "failed"
    except Exception as e:
        status["embedding"] = f"error: {str(e)}"

    # Test vector search capability
    try:
        async with get_connection() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM public.judgments WHERE description_embedding IS NOT NULL"
            )
            status["vector_search"] = "ok"
            status["indexed_judgments"] = result or 0
    except Exception as e:
        status["vector_search"] = f"error: {str(e)}"

    is_healthy = status["embedding"] == "ok" and status["vector_search"] == "ok"
    status["healthy"] = is_healthy

    return status


# ---------------------------------------------------------------------------
# Quick Text Search (for Global Search in UI)
# ---------------------------------------------------------------------------


class QuickSearchResult(BaseModel):
    """A single result from quick text search."""

    id: str
    type: str = "judgment"
    title: str
    subtitle: str
    path: str


class QuickSearchResponse(BaseModel):
    """Response from quick text search."""

    items: list[QuickSearchResult]


@router.get(
    "/judgments",
    response_model=QuickSearchResponse,
    summary="Quick text search for judgments",
    description="""
    Fast text-based search for the global search UI.

    Searches by case number, defendant name, or plaintiff name.
    Uses ILIKE for substring matching.
    """,
)
async def quick_search_judgments(
    q: str = "",
    limit: int = 8,
) -> QuickSearchResponse:
    """
    Quick text search for global search modal.

    Matches case_number, defendant_name, plaintiff_name using ILIKE.
    Returns results formatted for the command palette UI.
    """
    if not q or len(q) < 2:
        return QuickSearchResponse(items=[])

    search_term = f"%{q}%"

    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    id,
                    case_number,
                    defendant_name,
                    plaintiff_name,
                    judgment_amount,
                    tier
                FROM public.judgments
                WHERE
                    case_number ILIKE $1
                    OR defendant_name ILIKE $1
                    OR plaintiff_name ILIKE $1
                ORDER BY
                    CASE
                        WHEN case_number ILIKE $1 THEN 1
                        WHEN defendant_name ILIKE $1 THEN 2
                        ELSE 3
                    END,
                    created_at DESC
                LIMIT $2
                """,
                search_term,
                min(limit, 20),
            )
    except Exception as e:
        logger.error(f"Quick search failed: {e}")
        return QuickSearchResponse(items=[])

    items = []
    for row in rows:
        judgment_id = str(row["id"])
        case_number = row.get("case_number") or "Unknown"
        defendant = row.get("defendant_name") or "Unknown Defendant"
        plaintiff = row.get("plaintiff_name") or ""
        amount = row.get("judgment_amount")
        tier = row.get("tier") or ""

        # Format amount
        amount_str = f"${amount:,.2f}" if amount else ""
        tier_str = f"[{tier}]" if tier else ""

        # Build subtitle
        subtitle_parts = []
        if plaintiff:
            subtitle_parts.append(f"v. {plaintiff}")
        if amount_str:
            subtitle_parts.append(amount_str)
        if tier_str:
            subtitle_parts.append(tier_str)

        items.append(
            QuickSearchResult(
                id=judgment_id,
                type="judgment",
                title=f"{case_number} — {defendant}",
                subtitle=" • ".join(subtitle_parts) if subtitle_parts else "No details",
                path=f"/cases?id={judgment_id}",
            )
        )

    logger.info(f"Quick search '{q}' returned {len(items)} results")
    return QuickSearchResponse(items=items)
