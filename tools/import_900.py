from __future__ import annotations

"""One-click pipeline for the 900-case plaintiff intake."""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import click
import psycopg
from psycopg import sql

from etl.src.importers.jbi_900 import (
    JBI_LAST_PARSE_ERRORS,
    parse_jbi_900_csv,
    run_jbi_900_import,
)
from etl.src.importers.pipeline_support import QueueJobManager
from etl.src.importers.simplicity_plaintiffs import (
    LAST_PARSE_ERRORS,
    parse_simplicity_csv,
    run_simplicity_import,
)
from etl.src.worker_enrich import JobResult, process_once
from src.supabase_client import get_supabase_db_url, get_supabase_env
from tools import check_schema_consistency
from tools.ops_daily_report import OpsDailyReport, UTC as OPS_UTC
from tools.task_planner import DatabaseTaskPlannerRepository, PlannerConfig, TaskPlanner
from workers.queue_client import QueueClient, QueueRpcNotFound

logger = logging.getLogger(__name__)

DEFAULT_SIMPLICITY_CANDIDATES = (
    Path("data_in/simplicity_sample.csv"),
    Path("data/simplicity_sample.csv"),
    Path("data/simplicity_export.csv"),
    Path("run/plaintiffs_canonical.csv"),
)
DEFAULT_JBI_CANDIDATES = (
    Path("data/jbi_export_valid_sample.csv"),
    Path("data/jbi_export.csv"),
    Path("run/plaintiffs_canonical.csv"),
)
DASHBOARD_VIEWS = (
    ("public", "v_plaintiffs_overview"),
    ("public", "v_judgment_pipeline"),
    ("public", "v_enforcement_overview"),
    ("public", "v_enforcement_recent"),
    ("public", "v_plaintiff_call_queue"),
    ("public", "v_collectability_snapshot"),
)


@dataclass
class StageResult:
    id: int
    name: str
    status: str
    started_at: datetime
    finished_at: datetime
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "details": self.details,
            "error": self.error,
        }


@dataclass
class PipelineStage:
    id: int
    name: str
    description: str
    runner: Callable[["PipelineContext", "PipelineStage"], StageResult]


@dataclass
class PipelineContext:
    env: str
    db_url: str
    conn: psycopg.Connection
    dry_run: bool
    enqueue_jobs: bool
    batch_name: str
    source_reference: str
    simplicity_csv: Optional[Path]
    jbi_csv: Optional[Path]
    collectability_limit: int
    collectability_idle: int
    import_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    queued_jobs: List[Dict[str, Any]] = field(default_factory=list)
    queue_expectations: Dict[str, int] = field(default_factory=dict)
    inserted_plaintiffs: set[str] = field(default_factory=set)
    inserted_judgments: set[str] = field(default_factory=set)

    def source_map(self) -> Dict[str, Optional[str]]:
        return {
            "simplicity": str(self.simplicity_csv) if self.simplicity_csv else None,
            "jbi": str(self.jbi_csv) if self.jbi_csv else None,
        }

    def track_import(self, source: str, result: Dict[str, Any]) -> None:
        self.import_results[source] = result
        metadata = result.get("metadata") or {}
        for op in metadata.get("row_operations", []) or []:
            plaintiff_id = op.get("plaintiff_id")
            judgment_id = op.get("judgment_id")
            if plaintiff_id:
                self.inserted_plaintiffs.add(str(plaintiff_id))
            if judgment_id:
                self.inserted_judgments.add(str(judgment_id))
        jobs = metadata.get("queued_jobs") or []
        for job in jobs:
            if isinstance(job, dict):
                self.queued_jobs.append(job)
                if (job.get("status") or "").lower() == "queued":
                    kind = str(job.get("kind") or "unknown")
                    self.queue_expectations[kind] = (
                        self.queue_expectations.get(kind, 0) + 1
                    )

    def expected_enrich_jobs(self) -> int:
        return self.queue_expectations.get("enrich", 0)

    def serialize(self, stages: List[StageResult]) -> Dict[str, Any]:
        return {
            "env": self.env,
            "batch_name": self.batch_name,
            "dry_run": self.dry_run,
            "source_reference": self.source_reference,
            "source_files": self.source_map(),
            "imports": {
                key: {
                    "rows": value.get("row_count"),
                    "inserted": value.get("insert_count"),
                    "errors": value.get("error_count"),
                }
                for key, value in self.import_results.items()
            },
            "plaintiff_ids": sorted(self.inserted_plaintiffs),
            "judgment_ids": sorted(self.inserted_judgments),
            "queue_expectations": dict(self.queue_expectations),
            "stages": [stage.to_dict() for stage in stages],
        }


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _resolve_csv_path(
    explicit: Optional[Path],
    *,
    candidates: Iterable[Path],
) -> Optional[Path]:
    if explicit is not None:
        if explicit.is_file():
            return explicit
        raise click.ClickException(f"CSV file not found: {explicit}")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _stage_result(
    stage: PipelineStage,
    *,
    status: str,
    started: datetime,
    details: Mapping[str, Any],
    error: Optional[str] = None,
) -> StageResult:
    return StageResult(
        id=stage.id,
        name=stage.name,
        status=status,
        started_at=started,
        finished_at=_utcnow(),
        details=dict(details),
        error=error,
    )


def _run_preflight(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    schema_code = check_schema_consistency.run_checks(ctx.env)
    queue_probe = QueueJobManager(ctx.conn)
    details = {
        "schema_exit_code": schema_code,
        "queue_job_available": queue_probe.available,
    }
    status = "success" if schema_code == 0 and queue_probe.available else "error"
    error = None if status == "success" else "Schema or queue checks failed"
    return _stage_result(
        stage, status=status, started=started, details=details, error=error
    )


def _run_validation(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    details: Dict[str, Any] = {}

    if ctx.simplicity_csv:
        rows = parse_simplicity_csv(str(ctx.simplicity_csv))
        details["simplicity"] = {
            "path": str(ctx.simplicity_csv),
            "rows": len(rows),
            "parse_errors": [
                {"row": issue.row_number, "error": issue.error}
                for issue in LAST_PARSE_ERRORS
            ],
        }
    if ctx.jbi_csv:
        rows = parse_jbi_900_csv(str(ctx.jbi_csv))
        details["jbi"] = {
            "path": str(ctx.jbi_csv),
            "rows": len(rows),
            "parse_errors": [
                {"row": issue.row_number, "error": issue.error}
                for issue in JBI_LAST_PARSE_ERRORS
            ],
        }

    if not details:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "No CSV sources configured"},
        )

    parse_failures = sum(
        len(entry.get("parse_errors", [])) for entry in details.values()
    )
    status = "success" if parse_failures == 0 else "error"
    error = None
    if parse_failures and not ctx.dry_run:
        error = f"{parse_failures} row(s) failed validation"
    elif parse_failures:
        status = "success"
    return _stage_result(
        stage, status=status, started=started, details=details, error=error
    )


def _import_source(
    ctx: PipelineContext,
    *,
    source: str,
    csv_path: Path,
) -> Dict[str, Any]:
    batch_suffix = f"{ctx.batch_name}_{source}"
    reference = f"{ctx.source_reference}:{source}"
    runner: Callable[..., Dict[str, Any]]
    if source == "simplicity":
        runner = run_simplicity_import
    else:
        runner = run_jbi_900_import
    result = runner(
        str(csv_path),
        batch_name=batch_suffix,
        dry_run=ctx.dry_run,
        source_reference=reference,
        connection=ctx.conn,
        enqueue_jobs=ctx.enqueue_jobs,
    )
    ctx.track_import(source, result)
    return result


def _run_imports(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    if ctx.simplicity_csv is None and ctx.jbi_csv is None:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "No CSV files available"},
        )

    details: Dict[str, Any] = {}
    try:
        if ctx.simplicity_csv:
            result = _import_source(
                ctx, source="simplicity", csv_path=ctx.simplicity_csv
            )
            details["simplicity"] = {
                "rows": result.get("row_count"),
                "inserted": result.get("insert_count"),
                "errors": result.get("error_count"),
                "dry_run": ctx.dry_run,
            }
        if ctx.jbi_csv:
            result = _import_source(ctx, source="jbi", csv_path=ctx.jbi_csv)
            details["jbi"] = {
                "rows": result.get("row_count"),
                "inserted": result.get("insert_count"),
                "errors": result.get("error_count"),
                "dry_run": ctx.dry_run,
            }
    except Exception as exc:  # pragma: no cover - pipeline guard
        return _stage_result(
            stage,
            status="error",
            started=started,
            details=details,
            error=str(exc),
        )

    status = "success"
    if not ctx.dry_run and any(
        (info.get("errors") or 0) > 0 for info in details.values()
    ):
        status = "error"
    return _stage_result(stage, status=status, started=started, details=details)


def _run_queue_audit(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    if ctx.dry_run or not ctx.import_results:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "dry-run or no import results"},
        )

    status_counts: Dict[str, int] = {}
    for job in ctx.queued_jobs:
        status = str(job.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    details = {
        "jobs_logged": len(ctx.queued_jobs),
        "status_counts": status_counts,
        "expected_enrich": ctx.expected_enrich_jobs(),
    }
    return _stage_result(stage, status="success", started=started, details=details)


def _run_collectability(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    if ctx.dry_run:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "dry-run"},
        )
    expected = ctx.expected_enrich_jobs()
    if expected == 0:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "No enrichment jobs queued"},
        )

    processed = 0
    successes = 0
    errors = 0
    idle_streak = 0
    max_attempts = expected * 2 if expected else ctx.collectability_limit
    max_attempts = max_attempts or ctx.collectability_limit
    max_attempts = min(ctx.collectability_limit, max_attempts)

    try:
        with QueueClient() as queue:
            while processed < max_attempts:
                result = process_once(queue)
                if result is JobResult.EMPTY:
                    idle_streak += 1
                    if idle_streak >= ctx.collectability_idle:
                        break
                    continue
                processed += 1
                idle_streak = 0
                if result is JobResult.SUCCESS:
                    successes += 1
                    if successes >= expected:
                        break
                elif result is JobResult.ERROR:
                    errors += 1
    except QueueRpcNotFound as exc:
        return _stage_result(
            stage,
            status="error",
            started=started,
            details={"processed": processed, "successes": successes},
            error=str(exc),
        )

    status = "success" if successes >= min(expected, 1) else "error"
    details = {
        "expected": expected,
        "processed": processed,
        "successes": successes,
        "errors": errors,
        "idle_loops": idle_streak,
    }
    error = None if status == "success" else "Collectability jobs did not finish"
    return _stage_result(
        stage, status=status, started=started, details=details, error=error
    )


def _run_task_planner(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    if ctx.dry_run:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "dry-run"},
        )

    config = PlannerConfig(tier_targets={"tier_a": 10, "tier_b": 7, "tier_c": 4})
    with DatabaseTaskPlannerRepository(ctx.env) as repo:
        planner = TaskPlanner(repo=repo, config=config, dry_run=False)
        outcome = planner.run()
    details = {
        "planned_tasks": len(outcome.planned_tasks),
        "inserted": outcome.inserted_tasks,
        "warnings": outcome.warnings,
        "backlog": outcome.backlog_count,
    }
    return _stage_result(stage, status="success", started=started, details=details)


def _fetch_view_counts(conn: psycopg.Connection) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    with conn.cursor() as cur:
        for schema, name in DASHBOARD_VIEWS:
            stmt = sql.SQL("select count(*) from {}.{}").format(
                sql.Identifier(schema),
                sql.Identifier(name),
            )
            cur.execute(stmt)
            row = cur.fetchone()
            counts[f"{schema}.{name}"] = int(row[0]) if row else 0
    return counts


def _run_reporting(ctx: PipelineContext, stage: PipelineStage) -> StageResult:
    started = _utcnow()
    if ctx.dry_run:
        return _stage_result(
            stage,
            status="skipped",
            started=started,
            details={"reason": "dry-run"},
        )

    day_start = datetime.now(OPS_UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    now = datetime.now(OPS_UTC)
    report_runner = OpsDailyReport(ctx.conn, day_start=day_start, now=now)
    report = report_runner.run()
    ops_payload = report_runner.snapshot_payload(report)
    view_counts = _fetch_view_counts(ctx.conn)
    details = {
        "ops_metrics": ops_payload,
        "view_counts": view_counts,
    }
    return _stage_result(stage, status="success", started=started, details=details)


STAGES: List[PipelineStage] = [
    PipelineStage(0, "Preflight", "Schema + queue checks", _run_preflight),
    PipelineStage(1, "Validate CSV", "Parse vendor exports", _run_validation),
    PipelineStage(2, "Apply Imports", "Insert plaintiffs + judgments", _run_imports),
    PipelineStage(3, "Queue Audit", "Summarize downstream jobs", _run_queue_audit),
    PipelineStage(4, "Collectability", "Run enrichment bundle", _run_collectability),
    PipelineStage(5, "Task Planner", "Seed outreach tasks", _run_task_planner),
    PipelineStage(6, "Ops Snapshot", "Refresh ops + dashboard stats", _run_reporting),
]


def _run_pipeline(
    ctx: PipelineContext,
    *,
    start_stage: int,
    end_stage: int,
) -> List[StageResult]:
    results: List[StageResult] = []
    for stage in STAGES:
        if stage.id < start_stage or stage.id > end_stage:
            results.append(
                _stage_result(
                    stage,
                    status="skipped",
                    started=_utcnow(),
                    details={"reason": "filtered"},
                )
            )
            continue
        click.echo(f"[{stage.id}] {stage.name}…", err=True)
        try:
            result = stage.runner(ctx, stage)
        except Exception as exc:  # pragma: no cover - pipeline safety net
            result = _stage_result(
                stage,
                status="error",
                started=_utcnow(),
                details={},
                error=str(exc),
            )
        results.append(result)
        if result.status == "error":
            click.echo(f"[{stage.id}] FAILED: {result.error}", err=True)
            break
        click.echo(
            f"[{stage.id}] {result.status.upper()} ({(result.finished_at - result.started_at).total_seconds():.1f}s)",
            err=True,
        )
    return results


def _default_batch_name() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"oneclick_900_{timestamp}"


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Supabase environment override",
)
@click.option(
    "--simplicity-csv",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the Simplicity export",
)
@click.option(
    "--jbi-csv",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to the JBI export",
)
@click.option("--batch-name", default=None, help="Batch label (defaults to timestamp)")
@click.option(
    "--source-reference",
    default=None,
    help="Optional external reference recorded in import_runs",
)
@click.option("--commit/--dry-run", default=False, help="Apply changes to Supabase")
@click.option(
    "--skip-jobs", is_flag=True, help="Skip queue_job RPC submissions during import"
)
@click.option(
    "--start-stage",
    type=int,
    default=0,
    show_default=True,
    help="First stage to execute",
)
@click.option(
    "--end-stage", type=int, default=6, show_default=True, help="Last stage to execute"
)
@click.option(
    "--collectability-limit",
    type=int,
    default=2500,
    show_default=True,
    help="Max enrichment jobs to process",
)
@click.option(
    "--collectability-idle",
    type=int,
    default=3,
    show_default=True,
    help="Empty dequeues tolerated before stopping",
)
@click.option(
    "--summary-path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional path to write the JSON summary",
)
@click.option("--pretty", is_flag=True, help="Pretty-print JSON summary to stdout")
def main(
    env: Optional[str],
    simplicity_csv: Optional[Path],
    jbi_csv: Optional[Path],
    batch_name: Optional[str],
    source_reference: Optional[str],
    commit: bool,
    skip_jobs: bool,
    start_stage: int,
    end_stage: int,
    collectability_limit: int,
    collectability_idle: int,
    summary_path: Optional[Path],
    pretty: bool,
) -> None:
    target_env = env or get_supabase_env()
    db_url = get_supabase_db_url(target_env)

    resolved_simplicity = _resolve_csv_path(
        simplicity_csv, candidates=DEFAULT_SIMPLICITY_CANDIDATES
    )
    resolved_jbi = _resolve_csv_path(jbi_csv, candidates=DEFAULT_JBI_CANDIDATES)
    if resolved_simplicity is None and resolved_jbi is None:
        raise click.ClickException(
            "No CSV sources found; provide --simplicity-csv or --jbi-csv"
        )

    label = batch_name or _default_batch_name()
    source_ref = source_reference or label

    with psycopg.connect(db_url, autocommit=False) as conn:
        ctx = PipelineContext(
            env=target_env,
            db_url=db_url,
            conn=conn,
            dry_run=not commit,
            enqueue_jobs=not skip_jobs,
            batch_name=label,
            source_reference=source_ref,
            simplicity_csv=resolved_simplicity,
            jbi_csv=resolved_jbi,
            collectability_limit=max(collectability_limit, 1),
            collectability_idle=max(collectability_idle, 1),
        )
        stages = _run_pipeline(ctx, start_stage=start_stage, end_stage=end_stage)
        summary = ctx.serialize(stages)

    if summary_path:
        summary_path.write_text(
            json.dumps(summary, indent=2 if pretty else None), encoding="utf-8"
        )

    payload = json.dumps(summary, indent=2 if pretty else None)
    click.echo(payload)


if __name__ == "__main__":  # pragma: no cover
    main()
