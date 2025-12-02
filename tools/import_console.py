from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import psycopg
from psycopg import errors as psycopg_errors, sql
from psycopg.rows import dict_row
import typer

from etl.src.importers.jbi_900 import JBI_SOURCE_SYSTEM, run_jbi_900_import
from etl.src.importers.pipeline_support import RawImportWriter
from etl.src.importers.simplicity_plaintiffs import run_simplicity_import
from src.supabase_client import (
    SupabaseEnv,
    create_supabase_client,
    get_supabase_db_url,
    get_supabase_env,
)

app = typer.Typer(help="Simplicity and JBI-900 import operations console.")
import_app = typer.Typer(help="Run vendor imports and inspect their status.")
app.add_typer(import_app, name="import")

SIMPLICITY_SOURCE_SYSTEM = "simplicity"
IMPORT_RUN_COLUMNS = [
    "id",
    "batch_name",
    "import_kind",
    "source_system",
    "status",
    "row_count",
    "insert_count",
    "error_count",
    "started_at",
    "finished_at",
]
PLAINTIFF_COLUMNS = [
    "id",
    "name",
    "status",
    "tier",
    "source_system",
    "created_at",
]
CASE_COLUMNS = [
    "case_id",
    "case_number",
    "state",
    "county",
    "source_system",
    "created_at",
]
JUDGMENT_COLUMNS = [
    "id",
    "case_id",
    "judgment_number",
    "judgment_amount",
    "status",
    "source_system",
    "created_at",
]


@dataclass(frozen=True)
class ResumePlan:
    rows: set[int]
    table_name: str | None = None


def _resolve_env(env: SupabaseEnv | None) -> SupabaseEnv:
    return env or get_supabase_env()


def _connect_db(env: SupabaseEnv | None) -> psycopg.Connection:
    supabase_env = _resolve_env(env)
    db_url = get_supabase_db_url(supabase_env)
    return psycopg.connect(db_url, autocommit=False, row_factory=dict_row)


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def _print_table(
    title: str, columns: Sequence[str], rows: Sequence[Mapping[str, Any]]
) -> None:
    typer.echo(f"[import_console] {title}")
    if not rows:
        typer.echo("  (no rows)")
        return

    widths: dict[str, int] = {
        column: max(len(column), *(len(_format_value(row.get(column))) for row in rows))
        for column in columns
    }
    header = "  " + "  ".join(
        f"{column.upper():{widths[column]}}" for column in columns
    )
    ruler = "  " + "  ".join("-" * widths[column] for column in columns)
    typer.echo(header)
    typer.echo(ruler)
    for row in rows:
        line = "  " + "  ".join(
            f"{_format_value(row.get(column)):{widths[column]}}" for column in columns
        )
        typer.echo(line)


def _fetch_dicts(
    conn: psycopg.Connection, query: str, params: Iterable[Any]
) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(query, tuple(params))
        return cur.fetchall()


def _fetch_import_runs(
    conn: psycopg.Connection,
    *,
    limit: int,
    source_system: str | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_system:
        clauses.append("source_system = %s")
        params.append(source_system)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT id,
               COALESCE(metadata->>'batch_name', source_reference, file_name) AS batch_name,
               import_kind,
               source_system,
               status,
               row_count,
               insert_count,
               error_count,
               started_at,
               finished_at
        FROM public.import_runs
        {where}
        ORDER BY started_at DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    return _fetch_dicts(conn, query, params)


def _fetch_plaintiffs(
    conn: psycopg.Connection,
    *,
    limit: int,
    source_system: str | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_system:
        clauses.append("source_system = %s")
        params.append(source_system)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT id, name, status, tier, source_system, created_at
        FROM public.plaintiffs
        {where}
        ORDER BY created_at DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    return _fetch_dicts(conn, query, params)


def _fetch_cases(
    conn: psycopg.Connection,
    *,
    limit: int,
    source_system: str | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_system:
        clauses.append("source_system = %s")
        params.append(source_system)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query_template = """
        SELECT {case_id_expr} AS case_id,
               case_number,
               state,
               county,
               source_system,
               created_at
        FROM judgments.cases
        {where}
        ORDER BY created_at DESC NULLS LAST
        LIMIT %s
    """
    params_with_limit = params + [limit]
    try:
        query = query_template.format(case_id_expr="case_id", where=where)
        return _fetch_dicts(conn, query, params_with_limit)
    except psycopg_errors.UndefinedColumn:
        conn.rollback()
        query = query_template.format(case_id_expr="id", where=where)
        return _fetch_dicts(conn, query, params_with_limit)
    except psycopg_errors.UndefinedTable:
        conn.rollback()
        typer.echo("[import_console] cases table not available; skipping section.")
        return []


def _fetch_judgments(
    conn: psycopg.Connection,
    *,
    limit: int,
    source_system: str | None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_system:
        clauses.append("COALESCE(c.source_system, j.metadata->>'source_system') = %s")
        params.append(source_system)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    query = f"""
        SELECT j.id,
               j.case_id,
               j.judgment_number,
               j.judgment_amount,
               j.status,
               COALESCE(c.source_system, j.metadata->>'source_system') AS source_system,
               j.created_at
        FROM public.judgments j
        LEFT JOIN judgments.cases c ON c.case_id = j.case_id
        {where}
        ORDER BY j.created_at DESC NULLS LAST
        LIMIT %s
    """
    params.append(limit)
    try:
        return _fetch_dicts(conn, query, params)
    except psycopg_errors.UndefinedTable:
        conn.rollback()
        typer.echo(
            "[import_console] judgments.cases missing; falling back to metadata-only view."
        )
        fallback_where = ""
        fallback_params: list[Any] = []
        if source_system:
            fallback_where = "WHERE j.metadata->>'source_system' = %s"
            fallback_params.append(source_system)
        fallback_query = f"""
            SELECT j.id,
                   j.case_id,
                   j.judgment_number,
                   j.judgment_amount,
                   j.status,
                   j.metadata->>'source_system' AS source_system,
                   j.created_at
            FROM public.judgments j
            {fallback_where}
            ORDER BY j.created_at DESC NULLS LAST
            LIMIT %s
        """
        fallback_params.append(limit)
        return _fetch_dicts(conn, fallback_query, fallback_params)


def _collect_resume_rows(
    conn: psycopg.Connection,
    *,
    batch_name: str,
    source_system: str,
    source_reference: str | None,
) -> ResumePlan:
    writer = RawImportWriter(conn)
    table_name = getattr(writer, "table_fqn", None)
    table_info = getattr(writer, "table", None)
    if not getattr(writer, "enabled", False) or not table_info:
        return ResumePlan(rows=set(), table_name=table_name)

    schema, table = table_info
    query = sql.SQL(
        """
        select raw_data->>'row_number' as row_number, status
        from {}.{}
        where raw_data->>'batch_name' = %s
          and coalesce(raw_data->>'source_system', '') = %s
        """
    ).format(sql.Identifier(schema), sql.Identifier(table))
    params: list[Any] = [batch_name, source_system]
    if source_reference:
        query += sql.SQL(" and coalesce(raw_data->>'source_reference', '') = %s")
        params.append(source_reference)

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except psycopg_errors.UndefinedTable:
        conn.rollback()
        return ResumePlan(rows=set(), table_name=table_name)

    skip_rows: set[int] = set()
    for row_number_value, status in rows:
        try:
            row_number = int(row_number_value)
        except (TypeError, ValueError):
            continue
        status_label = (status or "").lower()
        if status_label in {"error", "parse_error"}:
            continue
        skip_rows.add(row_number)
    return ResumePlan(rows=skip_rows, table_name=table_name)


def _emit_resume_hint(plan: ResumePlan) -> None:
    if not plan.rows:
        typer.echo(
            "[import_console] resume requested but no completed raw rows were found; processing entire file."
        )
        return
    table_label = plan.table_name or "raw import log"
    typer.echo(
        f"[import_console] resume mode will skip {len(plan.rows)} row(s) recorded in {table_label}."
    )


def _summarize_result(
    source_label: str,
    batch_name: str,
    dry_run: bool,
    result: dict[str, Any],
    *,
    resume_plan: ResumePlan | None = None,
) -> None:
    metadata = result.get("metadata") or {}
    summary = metadata.get("summary") or {}
    row_count = summary.get("row_count") or len(metadata.get("row_operations") or [])
    insert_count = summary.get("insert_count") or 0
    error_count = summary.get("error_count") or 0
    run_id = result.get("import_run_id") or "-"
    mode = "dry-run" if dry_run else "applied"
    typer.echo(
        "[import_console] {source} batch '{batch}' {mode}: rows={rows} inserted={inserted} errors={errors} run_id={run}".format(
            source=source_label,
            batch=batch_name,
            mode=mode,
            rows=row_count,
            inserted=insert_count,
            errors=error_count,
            run=run_id,
        )
    )
    resume_meta = metadata.get("resume")
    if resume_meta or (resume_plan and resume_plan.rows):
        typer.echo(
            "  resume summary: requested_skip_rows={req} rows_dropped={dropped} table={table}".format(
                req=(resume_meta or {}).get("requested_skip_rows")
                or (len(resume_plan.rows) if resume_plan else 0),
                dropped=(resume_meta or {}).get("rows_dropped", "-"),
                table=(resume_plan.table_name if resume_plan else None) or "-",
            )
        )


def _run_import_command(
    *,
    source_label: str,
    csv_file: Path,
    batch_name: str | None,
    source_reference: str | None,
    dry_run: bool,
    resume: bool,
    skip_jobs: bool,
    env: SupabaseEnv | None,
    source_system: str,
    runner: Callable[..., dict[str, Any]],
) -> None:
    supabase_env = _resolve_env(env)
    csv_path = csv_file.resolve()
    batch = batch_name or csv_path.stem
    source_ref = source_reference or batch
    result: dict[str, Any]
    resume_plan = ResumePlan(rows=set())

    with _connect_db(supabase_env) as conn:
        if resume:
            resume_plan = _collect_resume_rows(
                conn,
                batch_name=batch,
                source_system=source_system,
                source_reference=source_ref,
            )
            _emit_resume_hint(resume_plan)

        storage_client = None if dry_run else create_supabase_client(supabase_env)
        result = runner(
            str(csv_path),
            batch_name=batch,
            dry_run=dry_run,
            source_reference=source_ref,
            connection=conn,
            storage_client=storage_client,
            enqueue_jobs=not skip_jobs,
            skip_row_numbers=resume_plan.rows or None,
        )
        if dry_run:
            conn.rollback()

    _summarize_result(
        source_label,
        batch,
        dry_run,
        result,
        resume_plan=resume_plan if resume else None,
    )


@import_app.command("simplicity")
def import_simplicity_command(
    csv_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False, readable=True
    ),
    batch_name: str | None = typer.Option(
        None, "--batch-name", help="Label recorded in import_runs metadata"
    ),
    source_reference: str | None = typer.Option(
        None, "--source-reference", help="External reference stored in import_runs"
    ),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--commit",
        help="Default to dry-run. Use --commit to apply changes.",
    ),
    resume: bool = typer.Option(
        False, "--resume", help="Skip rows already logged in raw import tables"
    ),
    skip_jobs: bool = typer.Option(
        False, "--skip-jobs", help="Prevent queue_job RPC dispatch"
    ),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE for this command"
    ),
) -> None:
    _run_import_command(
        source_label="simplicity",
        csv_file=csv_file,
        batch_name=batch_name,
        source_reference=source_reference,
        dry_run=dry_run,
        resume=resume,
        skip_jobs=skip_jobs,
        env=env,
        source_system=SIMPLICITY_SOURCE_SYSTEM,
        runner=run_simplicity_import,
    )


@import_app.command("jbi900")
def import_jbi_command(
    csv_file: Path = typer.Argument(
        ..., exists=True, file_okay=True, dir_okay=False, readable=True
    ),
    batch_name: str | None = typer.Option(None, "--batch-name"),
    source_reference: str | None = typer.Option(None, "--source-reference"),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--commit",
        help="Default to dry-run. Use --commit to apply changes.",
    ),
    resume: bool = typer.Option(False, "--resume"),
    skip_jobs: bool = typer.Option(False, "--skip-jobs"),
    env: SupabaseEnv | None = typer.Option(None, "--env"),
) -> None:
    _run_import_command(
        source_label="jbi_900",
        csv_file=csv_file,
        batch_name=batch_name,
        source_reference=source_reference,
        dry_run=dry_run,
        resume=resume,
        skip_jobs=skip_jobs,
        env=env,
        source_system=JBI_SOURCE_SYSTEM,
        runner=run_jbi_900_import,
    )


@import_app.command("runs")
def import_runs_command(
    count: int = typer.Argument(10, min=1, max=200, help="Number of runs to display"),
    source_system: str | None = typer.Option(None, "--source-system"),
    env: SupabaseEnv | None = typer.Option(None, "--env"),
) -> None:
    supabase_env = _resolve_env(env)
    with _connect_db(supabase_env) as conn:
        rows = _fetch_import_runs(conn, limit=count, source_system=source_system)
    typer.echo(
        f"[import_console] env={supabase_env} source_system={source_system or '-'} showing {len(rows)} run(s)."
    )
    _print_table("import_runs", IMPORT_RUN_COLUMNS, rows)


@import_app.command("status")
def import_status_command(
    limit: int = typer.Option(10, "--limit", min=1, max=200, help="Rows per table"),
    source_system: str | None = typer.Option(None, "--source-system"),
    env: SupabaseEnv | None = typer.Option(None, "--env"),
) -> None:
    supabase_env = _resolve_env(env)
    with _connect_db(supabase_env) as conn:
        runs = _fetch_import_runs(conn, limit=limit, source_system=source_system)
        plaintiffs = _fetch_plaintiffs(conn, limit=limit, source_system=source_system)
        cases = _fetch_cases(conn, limit=limit, source_system=source_system)
        judgments = _fetch_judgments(conn, limit=limit, source_system=source_system)

    typer.echo(
        f"[import_console] env={supabase_env} source_system={source_system or '-'} limit={limit}"
    )
    _print_table("import_runs", IMPORT_RUN_COLUMNS, runs)
    typer.echo()
    _print_table("plaintiffs", PLAINTIFF_COLUMNS, plaintiffs)
    typer.echo()
    _print_table("cases", CASE_COLUMNS, cases)
    typer.echo()
    _print_table("judgments", JUDGMENT_COLUMNS, judgments)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
