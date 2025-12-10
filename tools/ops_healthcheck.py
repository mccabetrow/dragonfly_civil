from __future__ import annotations

"""Operations healthcheck helpers for daily monitoring runs."""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, cast

import click
import psycopg
from psycopg.abc import Query
from psycopg.rows import dict_row

from src.supabase_client import SupabaseEnv, get_supabase_db_url, get_supabase_env

UTC = timezone.utc
DEFAULT_SAMPLE_LIMIT = 15
DEFAULT_STUCK_TASK_DAYS = 5
DEFAULT_STALE_CALL_DAYS = 10
DISMISSED_CASE_STATUSES = {"closed", "dismissed", "archived"}


@dataclass
class CheckResult:
    name: str
    total: int
    samples: list[Mapping[str, Any]]


class OpsHealthcheck:
    def __init__(
        self,
        conn: psycopg.Connection,
        *,
        sample_limit: int = DEFAULT_SAMPLE_LIMIT,
        stuck_task_days: int = DEFAULT_STUCK_TASK_DAYS,
        stale_call_days: int = DEFAULT_STALE_CALL_DAYS,
    ) -> None:
        self.conn = conn
        self.sample_limit = max(1, sample_limit)
        self.stuck_task_days = max(1, stuck_task_days)
        self.stale_call_days = max(1, stale_call_days)

    def run(self) -> Dict[str, CheckResult]:
        return {
            "stuck_tasks": self._stuck_tasks(),
            "stale_call_queue": self._stale_call_queue(),
            "plaintiffs_missing_contacts": self._plaintiffs_missing_contacts(),
            "cases_missing_judgments": self._cases_missing_judgments(),
            "cases_missing_events": self._cases_missing_events(),
        }

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _stuck_tasks(self) -> CheckResult:
        params = {
            "threshold": self._now() - timedelta(days=self.stuck_task_days),
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiff_tasks "
            "WHERE status IN ('open','in_progress') "
            "AND due_at IS NOT NULL AND due_at < %(threshold)s"
        )
        sample_sql = (
            "SELECT id, plaintiff_id, kind, status, due_at, created_at, assignee, note "
            "FROM public.plaintiff_tasks "
            "WHERE status IN ('open','in_progress') "
            "AND due_at IS NOT NULL AND due_at < %(threshold)s "
            "ORDER BY due_at ASC LIMIT %(limit)s"
        )
        return self._run_check("stuck_tasks", count_sql, sample_sql, params)

    def _stale_call_queue(self) -> CheckResult:
        params = {
            "threshold": self._now() - timedelta(days=self.stale_call_days),
            "limit": self.sample_limit,
        }
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiff_tasks "
            "WHERE kind = 'call' AND status IN ('open','in_progress') "
            "AND COALESCE(due_at, created_at) < %(threshold)s"
        )
        sample_sql = (
            "SELECT id, plaintiff_id, status, due_at, created_at, assignee, note "
            "FROM public.plaintiff_tasks "
            "WHERE kind = 'call' AND status IN ('open','in_progress') "
            "AND COALESCE(due_at, created_at) < %(threshold)s "
            "ORDER BY COALESCE(due_at, created_at) ASC LIMIT %(limit)s"
        )
        return self._run_check("stale_call_queue", count_sql, sample_sql, params)

    def _plaintiffs_missing_contacts(self) -> CheckResult:
        params = {"limit": self.sample_limit}
        count_sql = (
            "SELECT COUNT(*) FROM public.plaintiffs p "
            "LEFT JOIN public.plaintiff_contacts c ON c.plaintiff_id = p.id "
            "WHERE c.id IS NULL"
        )
        sample_sql = (
            "SELECT p.id, p.name, p.status, p.created_at "
            "FROM public.plaintiffs p "
            "LEFT JOIN public.plaintiff_contacts c ON c.plaintiff_id = p.id "
            "WHERE c.id IS NULL "
            "ORDER BY p.created_at DESC LIMIT %(limit)s"
        )
        return self._run_check("plaintiffs_missing_contacts", count_sql, sample_sql, params)

    def _cases_missing_judgments(self) -> CheckResult:
        status_params = self._dismissed_status_params()
        status_placeholders = ", ".join(f"%({key})s" for key in status_params)
        case_filter = (
            "COALESCE(NULLIF(lower(ec.status), ''), 'active') NOT IN (" f"{status_placeholders})"
        )
        count_sql = (
            "SELECT COUNT(*) FROM public.enforcement_cases ec "
            "LEFT JOIN public.judgments j ON j.id = ec.judgment_id "
            f"WHERE ({case_filter}) AND (ec.judgment_id IS NULL OR j.id IS NULL)"
        )
        sample_sql = (
            "SELECT ec.id, ec.case_number, ec.status, ec.created_at "
            "FROM public.enforcement_cases ec "
            "LEFT JOIN public.judgments j ON j.id = ec.judgment_id "
            f"WHERE ({case_filter}) AND (ec.judgment_id IS NULL OR j.id IS NULL) "
            "ORDER BY ec.created_at DESC LIMIT %(limit)s"
        )
        params = {"limit": self.sample_limit, **status_params}
        return self._run_check("cases_missing_judgments", count_sql, sample_sql, params)

    def _cases_missing_events(self) -> CheckResult:
        status_params = self._dismissed_status_params()
        status_placeholders = ", ".join(f"%({key})s" for key in status_params)
        case_filter = (
            "COALESCE(NULLIF(lower(ec.status), ''), 'active') NOT IN (" f"{status_placeholders})"
        )
        count_sql = (
            "SELECT COUNT(*) FROM public.enforcement_cases ec "
            "LEFT JOIN public.enforcement_events ev ON ev.case_id = ec.id "
            f"WHERE ({case_filter}) AND ev.id IS NULL"
        )
        sample_sql = (
            "SELECT ec.id, ec.case_number, ec.status, ec.created_at "
            "FROM public.enforcement_cases ec "
            "LEFT JOIN public.enforcement_events ev ON ev.case_id = ec.id "
            f"WHERE ({case_filter}) AND ev.id IS NULL "
            "ORDER BY ec.created_at DESC LIMIT %(limit)s"
        )
        params = {"limit": self.sample_limit, **status_params}
        return self._run_check("cases_missing_events", count_sql, sample_sql, params)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_check(
        self,
        name: str,
        count_sql: str,
        sample_sql: str,
        params: Mapping[str, Any],
    ) -> CheckResult:
        total = self._fetch_value(count_sql, params)
        samples = self._fetch_rows(sample_sql, params)
        return CheckResult(name=name, total=total, samples=samples)

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

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _dismissed_status_params(self) -> Dict[str, Any]:
        return {
            f"status_{idx}": status for idx, status in enumerate(sorted(DISMISSED_CASE_STATUSES))
        }


def _json_friendly(report: Dict[str, CheckResult]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for name, result in report.items():
        payload[name] = {
            "total": result.total,
            "samples": [
                {
                    key: (value.isoformat() if isinstance(value, datetime) else value)
                    for key, value in sample.items()
                }
                for sample in result.samples
            ],
        }
    return payload


def _print_report(report: Dict[str, CheckResult]) -> None:
    for name, result in report.items():
        click.echo(f"[{name}] total={result.total} samples={len(result.samples)}")
        for sample in result.samples[:5]:
            compact = ", ".join(f"{k}={sample[k]}" for k in sample)
            click.echo(f"  - {compact}")


@click.command()
@click.option(
    "--env",
    "env_override",
    type=click.Choice(["dev", "prod", "demo"]),
    default=None,
    help="Optional Supabase environment override.",
)
@click.option("--sample-limit", default=DEFAULT_SAMPLE_LIMIT, show_default=True, type=int)
@click.option(
    "--stuck-task-days",
    default=DEFAULT_STUCK_TASK_DAYS,
    show_default=True,
    type=int,
    help="Days past due before a task is considered stuck.",
)
@click.option(
    "--stale-call-days",
    default=DEFAULT_STALE_CALL_DAYS,
    show_default=True,
    type=int,
    help="Age threshold for stale call queue tasks.",
)
@click.option("--json-output", is_flag=True, help="Emit JSON instead of text summary.")
def main(
    env_override: str | None,
    sample_limit: int,
    stuck_task_days: int,
    stale_call_days: int,
    json_output: bool,
) -> None:
    env = _resolve_env(env_override)
    db_url = get_supabase_db_url(env)
    with psycopg.connect(db_url) as conn:
        checker = OpsHealthcheck(
            conn,
            sample_limit=sample_limit,
            stuck_task_days=stuck_task_days,
            stale_call_days=stale_call_days,
        )
        report = checker.run()

    if json_output:
        click.echo(json.dumps(_json_friendly(report), indent=2))
    else:
        click.echo(f"[ops_healthcheck] env={env} sample_limit={sample_limit}")
        _print_report(report)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()


def _resolve_env(value: str | None) -> SupabaseEnv:
    if not value:
        return get_supabase_env()
    if value == "demo":
        return "dev"
    return cast(SupabaseEnv, value)
