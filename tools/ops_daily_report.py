from __future__ import annotations

"""Generate a daily operations report for intake + enforcement queues."""

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Mapping, cast

import click
import psycopg
from psycopg.abc import Query
from psycopg.rows import dict_row

from src.supabase_client import SupabaseEnv, get_supabase_db_url, get_supabase_env

UTC = timezone.utc
DEFAULT_SAMPLE_LIMIT = 10
OPS_METADATA_CATEGORY = "daily_report"
CLOSED_CASE_STATUSES = {"closed", "dismissed", "archived"}


@dataclass
class DailyMetric:
    name: str
    total: int
    samples: list[Mapping[str, Any]]


class OpsDailyReport:
    def __init__(
        self,
        conn: psycopg.Connection,
        *,
        day_start: datetime,
        now: datetime,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
    ) -> None:
        self.conn = conn
        self.day_start = day_start
        self.day_end = day_start + timedelta(days=1)
        self.now = now
        self.sample_limit = max(1, sample_limit)

    def run(self) -> Dict[str, DailyMetric]:
        return {
            "new_plaintiffs": self._new_plaintiffs(),
            "new_judgments": self._new_judgments(),
            "tasks_completed": self._tasks_completed(),
            "tasks_overdue": self._tasks_overdue(),
            "active_enforcement_cases": self._active_enforcement_cases(),
        }

    # ------------------------------------------------------------------
    def _new_plaintiffs(self) -> DailyMetric:
        params = {
            "start": self.day_start,
            "end": self.day_end,
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiffs "
            "WHERE created_at >= %(start)s AND created_at < %(end)s"
        )
        sample_sql = (
            "SELECT id, name, status, created_at FROM public.plaintiffs "
            "WHERE created_at >= %(start)s AND created_at < %(end)s "
            "ORDER BY created_at DESC LIMIT %(limit)s"
        )
        return self._run_metric("new_plaintiffs", count_sql, sample_sql, params)

    def _new_judgments(self) -> DailyMetric:
        params = {
            "start": self.day_start,
            "end": self.day_end,
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.judgments "
            "WHERE created_at >= %(start)s AND created_at < %(end)s"
        )
        sample_sql = (
            "SELECT id, case_number, plaintiff_name, judgment_amount, created_at "
            "FROM public.judgments "
            "WHERE created_at >= %(start)s AND created_at < %(end)s "
            "ORDER BY created_at DESC LIMIT %(limit)s"
        )
        return self._run_metric("new_judgments", count_sql, sample_sql, params)

    def _tasks_completed(self) -> DailyMetric:
        params = {
            "start": self.day_start,
            "end": self.day_end,
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiff_tasks "
            "WHERE status = 'closed' AND closed_at >= %(start)s AND closed_at < %(end)s"
        )
        sample_sql = (
            "SELECT id, plaintiff_id, kind, result, closed_at FROM public.plaintiff_tasks "
            "WHERE status = 'closed' AND closed_at >= %(start)s AND closed_at < %(end)s "
            "ORDER BY closed_at DESC LIMIT %(limit)s"
        )
        return self._run_metric("tasks_completed", count_sql, sample_sql, params)

    def _tasks_overdue(self) -> DailyMetric:
        params = {
            "cutoff": self.now,
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiff_tasks "
            "WHERE status IN ('open','in_progress') AND due_at IS NOT NULL AND due_at < %(cutoff)s"
        )
        sample_sql = (
            "SELECT id, plaintiff_id, kind, due_at, assignee FROM public.plaintiff_tasks "
            "WHERE status IN ('open','in_progress') AND due_at IS NOT NULL AND due_at < %(cutoff)s "
            "ORDER BY due_at ASC LIMIT %(limit)s"
        )
        return self._run_metric("tasks_overdue", count_sql, sample_sql, params)

    def _active_enforcement_cases(self) -> DailyMetric:
        params = {
            **self._status_params(),
            "limit": self.sample_limit,
        }
        status_placeholders = ", ".join(f"%({key})s" for key in self._status_params())
        case_filter = (
            "COALESCE(NULLIF(lower(status), ''), 'active') NOT IN (" f"{status_placeholders})"
        )
        count_sql = "SELECT COUNT(*) FROM public.enforcement_cases " f"WHERE {case_filter}"
        sample_sql = (
            "SELECT id, case_number, status, opened_at, created_at "
            "FROM public.enforcement_cases "
            f"WHERE {case_filter} "
            "ORDER BY COALESCE(updated_at, created_at) DESC LIMIT %(limit)s"
        )
        return self._run_metric("active_enforcement_cases", count_sql, sample_sql, params)

    # ------------------------------------------------------------------
    def _run_metric(
        self,
        name: str,
        count_sql: str,
        sample_sql: str,
        params: Mapping[str, Any],
    ) -> DailyMetric:
        total = self._fetch_value(count_sql, params)
        samples = self._fetch_rows(sample_sql, params)
        return DailyMetric(name=name, total=total, samples=samples)

    def _fetch_value(self, sql: str, params: Mapping[str, Any]) -> int:
        with self.conn.cursor() as cur:
            cur.execute(cast(Query, sql), params)
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def _fetch_rows(self, sql: str, params: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(cast(Query, sql), params)
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def _status_params(self) -> Dict[str, str]:
        return {f"status_{idx}": status for idx, status in enumerate(sorted(CLOSED_CASE_STATUSES))}

    def snapshot_payload(self, report: Dict[str, DailyMetric]) -> Dict[str, Any]:
        return {
            name: {
                "total": metric.total,
                "samples": [
                    {
                        key: (value.isoformat() if isinstance(value, datetime) else value)
                        for key, value in sample.items()
                    }
                    for sample in metric.samples
                ],
            }
            for name, metric in report.items()
        }

    def upsert_snapshot(self, payload: Dict[str, Any]) -> None:
        sql = (
            "INSERT INTO public.ops_metadata (snapshot_date, category, metrics) "
            "VALUES (%(date)s, %(category)s, %(metrics)s) "
            "ON CONFLICT (snapshot_date, category) DO UPDATE "
            "SET metrics = EXCLUDED.metrics, updated_at = timezone('utc', now())"
        )
        params = {
            "date": self.day_start.date(),
            "category": OPS_METADATA_CATEGORY,
            "metrics": json.dumps(payload),
        }
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
        self.conn.commit()


def _json_friendly(report: Dict[str, DailyMetric]) -> Dict[str, Any]:
    converted: Dict[str, Any] = {}
    for name, metric in report.items():
        converted[name] = {
            "total": metric.total,
            "samples": [
                {
                    key: (value.isoformat() if isinstance(value, datetime) else value)
                    for key, value in sample.items()
                }
                for sample in metric.samples
            ],
        }
    return converted


def _print_report(report: Dict[str, DailyMetric], day_start: datetime) -> None:
    click.echo(f"[ops_daily_report] date={day_start.date().isoformat()} metrics={len(report)}")
    for name, metric in report.items():
        click.echo(f"[{name}] total={metric.total} samples={len(metric.samples)}")
        for sample in metric.samples[:5]:
            compact = ", ".join(f"{k}={sample[k]}" for k in sample)
            click.echo(f"  - {compact}")


def _parse_report_date(value: str | None) -> datetime:
    if not value:
        today = datetime.now(UTC).date()
    else:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
        today = parsed
    return datetime.combine(today, time.min, tzinfo=UTC)


def _resolve_env(value: str | None) -> SupabaseEnv:
    if not value:
        return get_supabase_env()
    if value == "demo":
        return "dev"
    return cast(SupabaseEnv, value)


@click.command()
@click.option(
    "--env",
    "env_override",
    type=click.Choice(["dev", "prod", "demo"]),
    default=None,
    help="Optional Supabase environment override.",
)
@click.option(
    "--date",
    "report_date",
    default=None,
    help="ISO date (YYYY-MM-DD) to report on (default: today UTC).",
)
@click.option("--sample-limit", default=DEFAULT_SAMPLE_LIMIT, show_default=True, type=int)
@click.option("--json-output", is_flag=True, help="Emit JSON payload instead of text summary.")
@click.option(
    "--record/--no-record",
    default=False,
    help="Persist snapshot to ops_metadata (default: no-record)",
)
def main(
    env_override: str | None,
    report_date: str | None,
    sample_limit: int,
    json_output: bool,
    record: bool,
) -> None:
    env = _resolve_env(env_override)
    db_url = get_supabase_db_url(env)
    day_start = _parse_report_date(report_date)
    now = datetime.now(UTC)

    with psycopg.connect(db_url) as conn:
        report_runner = OpsDailyReport(
            conn,
            day_start=day_start,
            now=now,
            sample_limit=sample_limit,
        )
        report = report_runner.run()
        payload = report_runner.snapshot_payload(report)
        if record:
            report_runner.upsert_snapshot(payload)

    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        _print_report(report, day_start)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
