"""
Dragonfly Engine - Cases Router

API endpoints for case management and pipeline views.
Provides access to judgment case data with pipeline-oriented aggregations.

Endpoints:
    GET  /api/v1/cases/pipeline - Get pipeline summary statistics
    GET  /api/v1/cases/list     - List all cases with pagination
    GET  /api/v1/cases/{id}     - Get single case details
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...core.security import AuthContext, get_current_user
from ...db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/cases", tags=["Cases"])


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class PipelineStageSummary(BaseModel):
    """Summary for a single pipeline stage."""

    stage: str = Field(..., description="Name of the enforcement stage")
    case_count: int = Field(0, description="Number of cases in this stage")
    total_amount: float = Field(0, description="Total judgment amount in stage")
    avg_score: Optional[float] = Field(None, description="Average collectability score")


class PipelineResponse(BaseModel):
    """Response for pipeline summary."""

    stages: list[PipelineStageSummary] = Field(
        default_factory=list, description="Summary by enforcement stage"
    )
    total_cases: int = Field(0, description="Total cases in pipeline")
    total_amount: float = Field(0, description="Total judgment amount")
    generated_at: str = Field(..., description="Timestamp when data was generated")


class CaseSummary(BaseModel):
    """Summary of a single case."""

    id: int
    case_number: str
    plaintiff_name: Optional[str] = None
    defendant_name: Optional[str] = None
    judgment_amount: Optional[float] = None
    collectability_score: Optional[int] = None
    enforcement_stage: Optional[str] = None
    offer_strategy: Optional[str] = None
    court: Optional[str] = None
    county: Optional[str] = None
    judgment_date: Optional[str] = None
    status: Optional[str] = None
    created_at: str


class CaseListResponse(BaseModel):
    """Response for case listing."""

    cases: list[CaseSummary]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/pipeline",
    response_model=PipelineResponse,
    summary="Get pipeline summary",
    description="""
Returns aggregated statistics about the enforcement pipeline.

Groups cases by enforcement stage and provides:
- Case count per stage
- Total judgment amount per stage
- Average collectability score per stage

Used by the CEO dashboard and Pipeline view.
""",
)
async def get_pipeline_summary(
    auth: AuthContext = Depends(get_current_user),
) -> PipelineResponse:
    """Get pipeline summary statistics grouped by enforcement stage."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        # Try to use the enforcement.v_enforcement_pipeline_status view first
        # Fall back to direct query if view doesn't exist
        query = """
        SELECT
            COALESCE(enforcement_stage, 'unassigned') AS stage,
            COUNT(*) AS case_count,
            COALESCE(SUM(judgment_amount), 0) AS total_amount,
            AVG(collectability_score) AS avg_score
        FROM public.judgments
        WHERE status IS NULL OR status NOT IN ('closed', 'collected', 'satisfied')
        GROUP BY COALESCE(enforcement_stage, 'unassigned')
        ORDER BY
            CASE COALESCE(enforcement_stage, 'unassigned')
                WHEN 'discovery' THEN 1
                WHEN 'filed' THEN 2
                WHEN 'served' THEN 3
                WHEN 'judgment' THEN 4
                WHEN 'execution' THEN 5
                WHEN 'collection' THEN 6
                WHEN 'unassigned' THEN 99
                ELSE 50
            END
        """

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query)
            rows = await cur.fetchall()

        stages = []
        total_cases = 0
        total_amount = 0.0

        for row in rows:
            stage_summary = PipelineStageSummary(
                stage=row["stage"],
                case_count=row["case_count"],
                total_amount=float(row["total_amount"] or 0),
                avg_score=float(row["avg_score"]) if row["avg_score"] else None,
            )
            stages.append(stage_summary)
            total_cases += row["case_count"]
            total_amount += float(row["total_amount"] or 0)

        from datetime import datetime, timezone

        return PipelineResponse(
            stages=stages,
            total_cases=total_cases,
            total_amount=total_amount,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


@router.get(
    "/list",
    response_model=CaseListResponse,
    summary="List all cases",
    description="Returns paginated list of all cases with summary information.",
)
async def list_cases(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Results per page"),
    stage: Optional[str] = Query(None, description="Filter by enforcement stage"),
    offer_strategy: Optional[str] = Query(None, description="Filter by offer strategy"),
    auth: AuthContext = Depends(get_current_user),
) -> CaseListResponse:
    """List all cases with pagination and optional filters."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        # Build WHERE clause - use %s placeholders for psycopg3
        conditions = ["(status IS NULL OR status NOT IN ('closed', 'collected', 'satisfied'))"]
        params: list[Any] = []

        if stage:
            conditions.append("enforcement_stage = %s")
            params.append(stage)

        where_clause = " AND ".join(conditions)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM public.judgments WHERE {where_clause}"
        async with conn.cursor() as cur:
            await cur.execute(count_query, params if params else None)
            row = await cur.fetchone()
            total = row[0] if row else 0

        # Get paginated data
        offset = (page - 1) * page_size

        data_query = f"""
        SELECT
            id,
            case_number,
            plaintiff_name,
            defendant_name,
            judgment_amount,
            collectability_score,
            enforcement_stage,
            court,
            county,
            judgment_date,
            status,
            created_at,
            CASE
                WHEN collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
                WHEN collectability_score >= 70 AND judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
                WHEN collectability_score >= 40 OR judgment_amount >= 5000 THEN 'CONTINGENCY'
                ELSE 'LOW_PRIORITY'
            END AS offer_strategy
        FROM public.judgments
        WHERE {where_clause}
        ORDER BY collectability_score DESC NULLS LAST, judgment_amount DESC
        LIMIT %s OFFSET %s
        """

        # Build params list with pagination at the end
        data_params = params + [page_size, offset]

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(data_query, data_params)
            rows = await cur.fetchall()

        cases = [
            CaseSummary(
                id=row["id"],
                case_number=row["case_number"] or f"J-{row['id']}",
                plaintiff_name=row["plaintiff_name"],
                defendant_name=row["defendant_name"],
                judgment_amount=float(row["judgment_amount"]) if row["judgment_amount"] else None,
                collectability_score=row["collectability_score"],
                enforcement_stage=row["enforcement_stage"],
                offer_strategy=row["offer_strategy"],
                court=row["court"],
                county=row["county"],
                judgment_date=str(row["judgment_date"]) if row["judgment_date"] else None,
                status=row["status"],
                created_at=row["created_at"].isoformat() if row["created_at"] else "",
            )
            for row in rows
        ]

        return CaseListResponse(
            cases=cases,
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get(
    "/{case_id}",
    summary="Get case details",
    description="Returns detailed information for a single case.",
)
async def get_case(
    case_id: int,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Get details for a single case."""

    pool = await get_pool()

    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        query = """
        SELECT
            j.*,
            CASE
                WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
                WHEN j.collectability_score >= 70 AND j.judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
                WHEN j.collectability_score >= 40 OR j.judgment_amount >= 5000 THEN 'CONTINGENCY'
                ELSE 'LOW_PRIORITY'
            END AS offer_strategy,
            p.name AS plaintiff_display_name,
            p.firm_name,
            p.email AS plaintiff_email,
            p.phone AS plaintiff_phone,
            p.tier AS plaintiff_tier
        FROM public.judgments j
        LEFT JOIN public.plaintiffs p ON j.plaintiff_id = p.id
        WHERE j.id = %s
        """

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (case_id,))
            row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

        # Convert to serializable dict
        result = dict(row)
        for key, value in result.items():
            if hasattr(value, "isoformat"):
                result[key] = value.isoformat()
            elif isinstance(value, (int, float, str, bool, type(None))):
                pass
            else:
                result[key] = str(value)

        return result
