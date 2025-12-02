from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg
import typer
from fastapi import FastAPI, HTTPException
from typer.core import TyperGroup

from src.supabase_client import get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)

DEFAULT_STALE_DAYS = 3
RECENT_FAILURE_WINDOW_HOURS = 24
MAX_FAILED_IMPORTS = 50

app = FastAPI(title="Dragonfly Alerts Export", version="0.1.0")
cli = typer.Typer(
    cls=TyperGroup,
    add_completion=False,
    invoke_without_command=False,
    help="Emit alert summaries for n8n automations.",
)


@cli.callback()
def cli_root() -> None:
    """Root CLI entry point placeholder."""
    return None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_env(env: str | None) -> str:
    if env is None:
        return get_supabase_env()
    normalized = env.strip().lower()
    if normalized in {"dev", "development", "demo"}:
        return "dev"
    if normalized in {"prod", "production"}:
        return "prod"
    raise ValueError(f"Unsupported Supabase env: {env}")


def _connect(env: str) -> psycopg.Connection[Any]:
    db_url = get_supabase_db_url(env)
    return psycopg.connect(db_url, autocommit=True, connect_timeout=10)


def _serialize_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        target = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return target.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _fetch_failed_imports(
    conn: psycopg.Connection[Any], since: datetime
) -> List[Dict[str, Any]]:
    sql = """
        SELECT id::text,
               import_kind,
               source_system,
               status,
               file_name,
               started_at,
               finished_at,
               error_count,
               COALESCE(metadata->>'batch_name', '') AS batch_name
        FROM public.import_runs
        WHERE status = 'failed'
          AND COALESCE(finished_at, started_at, created_at) >= %s
        ORDER BY COALESCE(finished_at, started_at, created_at) DESC
        LIMIT %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (since, MAX_FAILED_IMPORTS))
        rows = cur.fetchall()

    failures: List[Dict[str, Any]] = []
    for row in rows:
        (
            run_id,
            import_kind,
            source_system,
            status,
            file_name,
            started_at,
            finished_at,
            error_count,
            batch_name,
        ) = row
        failures.append(
            {
                "id": run_id,
                "import_kind": import_kind,
                "source_system": source_system,
                "status": status,
                "file_name": file_name,
                "started_at": _serialize_ts(started_at),
                "finished_at": _serialize_ts(finished_at),
                "error_count": int(error_count or 0),
                "batch_name": batch_name or None,
            }
        )
    return failures


def _fetch_stale_call_task_count(
    conn: psycopg.Connection[Any], threshold: datetime
) -> int:
    sql = """
        SELECT COUNT(*)
        FROM public.plaintiff_tasks
        WHERE kind = 'call'
          AND status IN ('open', 'in_progress')
          AND COALESCE(due_at, created_at) <= %s;
    """
    with conn.cursor() as cur:
        cur.execute(sql, (threshold,))
        result = cur.fetchone()
    return int(result[0] if result and result[0] is not None else 0)


def build_alert_summary(
    *, env: str | None = None, stale_days: int = DEFAULT_STALE_DAYS
) -> Dict[str, Any]:
    if stale_days <= 0:
        raise ValueError("stale_days must be positive")

    supabase_env = _coerce_env(env)
    now = _utcnow()
    since = now - timedelta(hours=RECENT_FAILURE_WINDOW_HOURS)
    stale_threshold = now - timedelta(days=stale_days)

    try:
        with _connect(supabase_env) as conn:
            failures = _fetch_failed_imports(conn, since)
            stale_call_count = _fetch_stale_call_task_count(conn, stale_threshold)
    except psycopg.Error as exc:  # pragma: no cover - network/database failures
        logger.exception("alerts_export query failed: env=%s", supabase_env)
        raise RuntimeError(f"Database query failed: {exc}") from exc

    summary = {
        "env": supabase_env,
        "generated_at": now.isoformat(timespec="seconds"),
        "failed_imports": failures,
        "open_call_tasks": {
            "stale_days_threshold": stale_days,
            "reference_timestamp": stale_threshold.isoformat(timespec="seconds"),
            "stale_count": stale_call_count,
        },
    }
    return summary


@cli.command("export")
def export_command(
    env: Optional[str] = typer.Option(
        None,
        "--env",
        help="Override Supabase env (dev/prod). Defaults to SUPABASE_MODE.",
    ),
    stale_days: int = typer.Option(
        DEFAULT_STALE_DAYS,
        "--stale-days",
        min=1,
        help="Count open call tasks older than this many days.",
    ),
    output_json: bool = typer.Option(
        False,
        "--json/--no-json",
        help="Emit machine-readable JSON for n8n instead of a human summary.",
        show_default=False,
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty/--no-pretty",
        help="Pretty-print JSON output (implies --json).",
        show_default=False,
    ),
) -> None:
    summary = build_alert_summary(env=env, stale_days=stale_days)

    if output_json or pretty:
        indent = 2 if pretty else None
        typer.echo(json.dumps(summary, indent=indent, default=str))
        return

    typer.echo(
        "[alerts_export] env={env} failed_imports={failures} stale_calls={stale_count}".format(
            env=summary["env"],
            failures=len(summary["failed_imports"]),
            stale_count=summary["open_call_tasks"]["stale_count"],
        )
    )
    if summary["failed_imports"]:
        typer.echo("  recent failures:")
        for failure in summary["failed_imports"]:
            typer.echo(
                "    {id} kind={import_kind} batch={batch_name} finished={finished_at} errors={error_count}".format(
                    **{**failure, "batch_name": failure.get("batch_name") or "-"}
                )
            )


@app.get("/alerts")
def get_alerts(
    env: str | None = None, stale_days: int = DEFAULT_STALE_DAYS
) -> Dict[str, Any]:
    try:
        return build_alert_summary(env=env, stale_days=stale_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/healthz")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


def main() -> None:
    cli()


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
