from __future__ import annotations

"""FastAPI wrapper around TaskPlanner for n8n-triggered runs."""

from collections import Counter
from typing import Literal, Optional

import uvicorn
from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, Field

from src.supabase_client import get_supabase_env
from tools.task_planner import DatabaseTaskPlannerRepository, PlannerConfig, TaskPlanner

DEFAULT_TIER_TARGETS: dict[str, int] = {"tier_a": 10, "tier_b": 5}
DEFAULT_FOLLOWUP_DAYS = 21
DEFAULT_ENV: Literal["dev", "prod"] = "prod"

app = FastAPI(
    title="Dragonfly Task Planner API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


class PlannerRequest(BaseModel):
    env: Optional[Literal["dev", "prod"]] = Field(
        DEFAULT_ENV,
        description="Supabase environment for planner run.",
    )


class PlannerResponse(BaseModel):
    env: Literal["dev", "prod"]
    planned_total: int
    planned_call: int
    planned_follow_up: int
    backlog: int
    summary: str


def _resolve_env(candidate: Optional[str]) -> Literal["dev", "prod"]:
    if candidate in {"dev", "prod"}:
        return candidate  # type: ignore[return-value]
    # Fall back to existing SUPABASE_MODE (dev/prod) before defaulting to prod.
    fallback = get_supabase_env()
    if fallback in {"dev", "prod"}:
        return fallback  # type: ignore[return-value]
    return DEFAULT_ENV


def _run_planner(env: Literal["dev", "prod"]) -> PlannerResponse:
    config_kwargs: dict[str, object] = {
        "tier_targets": DEFAULT_TIER_TARGETS,
        "enable_followups": True,
        "followup_threshold_days": DEFAULT_FOLLOWUP_DAYS,
    }
    config = PlannerConfig(**config_kwargs)  # type: ignore[arg-type]

    with DatabaseTaskPlannerRepository(env) as repo:
        planner = TaskPlanner(repo=repo, config=config, dry_run=False)
        outcome = planner.run()

    kind_counts = Counter(task.kind for task in outcome.planned_tasks)
    planned_total = len(outcome.planned_tasks)
    planned_call = kind_counts.get("call", 0)
    planned_follow_up = kind_counts.get("follow_up", 0)
    summary = "Planned {total} tasks (call={call}, follow_up={followup}); backlog now {backlog}.".format(
        total=planned_total,
        call=planned_call,
        followup=planned_follow_up,
        backlog=outcome.backlog_count,
    )

    return PlannerResponse(
        env=env,
        planned_total=planned_total,
        planned_call=planned_call,
        planned_follow_up=planned_follow_up,
        backlog=outcome.backlog_count,
        summary=summary,
    )


@app.post("/run-task-planner", response_model=PlannerResponse)
async def run_task_planner_endpoint(
    payload: PlannerRequest | None = Body(default=None),
) -> PlannerResponse:
    try:
        resolved = payload or PlannerRequest(env=DEFAULT_ENV)
        env = _resolve_env(resolved.env)
        return _run_planner(env)
    except Exception as exc:  # pragma: no cover - surfaced via FastAPI
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def main() -> None:
    uvicorn.run(
        "tools.planner_api:app",
        host="0.0.0.0",
        port=8085,
        reload=False,
    )


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
