from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Sequence, Tuple

import click
import psycopg
from psycopg import abc as psycopg_abc

from scripts import check_prod_schema
from src.supabase_client import describe_db_url, get_supabase_db_url

from . import (
    check_api_health,
    check_storage,
    config_check,
    doctor,
    security_audit,
    smoke_enforcement,
    smoke_plaintiffs,
)

RunResult = Tuple[str, int, str]
Runner = Callable[[], None]

# Track whether a check passed with tolerated warnings
_tolerated_warnings: List[str] = []


def _run_step(name: str, runner: Runner) -> RunResult:
    try:
        runner()
        return (name, 0, f"{name} passed")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return (name, code, f"{name} exited with code {code}")
    except Exception as exc:  # pragma: no cover - unexpected failure path
        return (name, 1, f"{name} raised unexpected error: {exc}")


def _bootstrap_env(requested: str | None) -> str:
    actual_env = "prod" if requested == "prod" else "dev"
    os.environ["SUPABASE_MODE"] = actual_env

    try:
        db_url = get_supabase_db_url(actual_env)
    except RuntimeError as exc:
        click.echo(
            f"[doctor_all] database URL unavailable for env '{actual_env}': {exc}",
            err=True,
        )
        raise SystemExit(2)

    host, dbname, user = describe_db_url(db_url)
    click.echo(f"[doctor_all] env={actual_env} host={host} db={dbname} user={user}")
    return actual_env


def _run_sequence(actions: Sequence[Tuple[str, Runner]]) -> List[RunResult]:
    results: List[RunResult] = []
    for name, runner in actions:
        click.echo(f"[doctor_all] Running {name}...")
        outcome = _run_step(name, runner)
        if name == "security_audit" and outcome[1] != 0:
            click.echo("[doctor_all] SECURITY AUDIT FAILED")
        click.echo(f"[doctor_all] {outcome[2]}")
        results.append(outcome)
    return results


def _doctor_runner(env: str) -> Runner:
    def _runner() -> None:
        doctor.main.main(("--env", env), prog_name="doctor", standalone_mode=False)

    return _runner


def _config_check_runner(env: str, tolerant: bool = False) -> Runner:
    def _runner() -> None:
        results = config_check.check_environment(env)
        if config_check.has_failures(results, tolerant=tolerant):
            raise SystemExit(1)
        # Track if warnings were tolerated
        if tolerant and any(r.status == "FAIL" for r in results):
            _tolerated_warnings.append("config_check")

    return _runner


def _security_audit_runner(env: str) -> Runner:
    def _runner() -> None:
        security_audit.main.main(
            ("--env", env),
            prog_name="security_audit",
            standalone_mode=False,
        )

    return _runner


def _check_storage_runner(env: str, tolerant: bool = False) -> Runner:
    """Run storage bucket check with optional tolerance for transient errors."""

    def _runner() -> None:
        result = check_storage.check_storage_buckets(env, tolerant=tolerant)
        if result.status == "OK":
            click.echo(f"[doctor_all] ✅ Storage: {result.message}")
        elif result.status == "WARN":
            click.echo(f"[doctor_all] {result.message}")
            _tolerated_warnings.append("check_storage")
        else:
            click.echo(f"[doctor_all] ❌ Storage: {result.message}", err=True)
            raise SystemExit(1)

    return _runner


def _check_api_health_runner(env: str, tolerant: bool = False) -> Runner:
    """Run API health check with optional tolerance for transient errors."""

    def _runner() -> None:
        result = check_api_health.check_api_health(env, tolerant=tolerant)
        if result.status == "OK":
            click.echo(f"[doctor_all] ✅ API: {result.message}")
        elif result.status == "WARN":
            click.echo(f"[doctor_all] {result.message}")
            _tolerated_warnings.append("check_api_health")
        else:
            click.echo(f"[doctor_all] ❌ API: {result.message}", err=True)
            raise SystemExit(1)

    return _runner


def _prod_schema_guard_runner(env: str, tolerant: bool = False) -> Runner:
    def _runner() -> None:
        args = ["--env", env]
        if tolerant:
            args.append("--tolerant")
        exit_code = check_prod_schema.main(args)
        if exit_code != 0:
            raise SystemExit(exit_code)

    return _runner


def _run_query(
    env: str, query: psycopg_abc.Query, params: Sequence[object] | None = None
) -> List[tuple]:
    db_url = get_supabase_db_url(env)
    try:
        with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params or [])
                return cur.fetchall()
    except psycopg.errors.UndefinedTable as exc:
        click.echo(f"[doctor_all] required relation missing: {exc}", err=True)
        raise SystemExit(2) from exc


def _fmt_ts(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="minutes")
    if value is None:
        return "-"
    return str(value)


def _recent_import_failures_runner(env: str) -> Runner:
    def _runner() -> None:
        window_start = datetime.now(timezone.utc) - timedelta(hours=24)
        query = """
            SELECT id, import_kind, source_system, status, started_at, finished_at,
                   COALESCE(metadata->>'batch_name', '') AS batch_name
            FROM public.import_runs
            WHERE status = 'failed'
              AND COALESCE(finished_at, started_at, created_at) >= %s
            ORDER BY COALESCE(finished_at, started_at, created_at) DESC
            LIMIT 25;
        """
        rows = _run_query(env, query, (window_start,))
        if not rows:
            click.echo("[doctor_all] import_runs: no failed jobs in the last 24h.")
            return

        click.echo("[doctor_all] import_runs: failed jobs detected in the last 24h:")
        for row in rows:
            (
                run_id,
                import_kind,
                source_system,
                status,
                started_at,
                finished_at,
                batch_name,
            ) = row
            click.echo(
                f"    id={run_id} kind={import_kind} source={source_system} status={status} "
                f"start={_fmt_ts(started_at)} finish={_fmt_ts(finished_at)} batch={batch_name or '-'}"
            )
        raise SystemExit(1)

    return _runner


def _plaintiff_task_integrity_runner(env: str) -> Runner:
    def _runner() -> None:
        query = """
            SELECT t.id, t.plaintiff_id, t.kind, t.status, t.due_at
            FROM public.plaintiff_tasks t
            LEFT JOIN public.plaintiffs p ON p.id = t.plaintiff_id
            WHERE t.plaintiff_id IS NOT NULL
              AND p.id IS NULL
            ORDER BY t.created_at DESC
            LIMIT 25;
        """
        rows = _run_query(env, query)
        if not rows:
            click.echo("[doctor_all] plaintiff_tasks: no orphaned tasks detected.")
            return

        click.echo("[doctor_all] plaintiff_tasks: orphaned tasks detected:")
        for row in rows:
            task_id, plaintiff_id, kind, status, due_at = row
            click.echo(
                f"    task_id={task_id} plaintiff_id={plaintiff_id} kind={kind} status={status} "
                f"due={_fmt_ts(due_at)}"
            )
        raise SystemExit(1)

    return _runner


def _enforcement_case_integrity_runner(env: str) -> Runner:
    def _runner() -> None:
        query = """
            SELECT ec.id, ec.judgment_id, ec.case_number, ec.status, ec.current_stage
            FROM public.enforcement_cases ec
            LEFT JOIN public.judgments j ON j.id = ec.judgment_id
            WHERE ec.judgment_id IS NOT NULL
              AND j.id IS NULL
            ORDER BY ec.updated_at DESC NULLS LAST
            LIMIT 25;
        """
        rows = _run_query(env, query)
        if not rows:
            click.echo("[doctor_all] enforcement_cases: all rows reference valid judgments.")
            return

        click.echo("[doctor_all] enforcement_cases: invalid judgment references detected:")
        for row in rows:
            case_id, judgment_id, case_number, status, current_stage = row
            click.echo(
                f"    case_id={case_id} judgment_id={judgment_id} case={case_number or '-'} "
                f"status={status or '-'} stage={current_stage or '-'}"
            )
        raise SystemExit(1)

    return _runner


@click.command()
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod", "demo"]),
    default=None,
    help="Override Supabase environment (default reads SUPABASE_MODE).",
)
@click.option(
    "--tolerant",
    is_flag=True,
    default=False,
    help="Downgrade non-critical failures to warnings (for initial deploys).",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Alias for --tolerant (demo mode with resilient checks).",
)
def main(
    requested_env: str | None = None,
    tolerant: bool = False,
    demo: bool = False,
) -> None:
    global _tolerated_warnings
    _tolerated_warnings = []

    # --demo implies --tolerant
    tolerant = tolerant or demo

    env = _bootstrap_env(requested_env)

    if tolerant:
        click.echo("[doctor_all] Running in TOLERANT mode (Demo/Initial Deploy)")

    actions: List[Tuple[str, Runner]] = [
        ("config_check", _config_check_runner(env, tolerant=tolerant)),
        ("check_storage", _check_storage_runner(env, tolerant=tolerant)),
        ("check_api_health", _check_api_health_runner(env, tolerant=tolerant)),
        ("security_audit", _security_audit_runner(env)),  # Security ALWAYS strict
        ("doctor", _doctor_runner(env)),
        ("smoke_plaintiffs", smoke_plaintiffs.main),
        ("smoke_enforcement", smoke_enforcement.main),
        ("import_runs_recent_failures", _recent_import_failures_runner(env)),
        ("plaintiff_task_integrity", _plaintiff_task_integrity_runner(env)),
        ("enforcement_case_integrity", _enforcement_case_integrity_runner(env)),
    ]

    if env == "prod":
        actions.insert(0, ("prod_schema_guard", _prod_schema_guard_runner(env, tolerant=tolerant)))

    results = _run_sequence(actions)

    failures = [(name, code) for name, code, _ in results if code != 0]
    if not failures:
        if _tolerated_warnings:
            click.echo(
                f"[doctor_all] ✅ PASSED (With Tolerated Warnings: {', '.join(_tolerated_warnings)})"
            )
        else:
            click.echo("[doctor_all] All checks passed.")
        raise SystemExit(0)

    summary = ", ".join(f"{name} (exit {code})" for name, code in failures)
    click.echo(f"[doctor_all] Failures detected: {summary}", err=True)
    raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive guard
        click.echo(f"[doctor_all] unexpected error: {exc}", err=True)
        sys.exit(1)
