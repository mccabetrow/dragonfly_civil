from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
import typer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.supabase_client import (
    SupabaseEnv,
    create_supabase_client,
    get_supabase_db_url,
    get_supabase_env,
)

app = typer.Typer(help="Manage enforcement cases, events, and evidence.")

EVIDENCE_BUCKET = "enforcement_evidence"


def _load_metadata(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - argument validation
        raise typer.BadParameter(f"Invalid metadata JSON: {exc}") from exc
    if not isinstance(data, dict):  # pragma: no cover - argument validation
        raise typer.BadParameter("Metadata JSON must decode into an object")
    return data


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:  # pragma: no cover - argument validation
        raise typer.BadParameter(f"Invalid ISO timestamp: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _connect(env: SupabaseEnv | str | None) -> psycopg.Connection:
    supabase_env = env or get_supabase_env()
    db_url = get_supabase_db_url(supabase_env)
    return psycopg.connect(db_url, autocommit=True, row_factory=dict_row)


def _ensure_case_exists(conn: psycopg.Connection, case_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM public.enforcement_cases WHERE id = %s", (case_id,))
        if cur.fetchone() is None:
            raise typer.BadParameter(f"Enforcement case {case_id} was not found")


def _fetch_judgment(conn: psycopg.Connection, judgment_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, case_number FROM public.judgments WHERE id = %s",
            (judgment_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise typer.BadParameter(f"Judgment {judgment_id} was not found")
    return row


@app.command("create-case")
def create_case(
    judgment_id: int = typer.Argument(..., help="ID of the judgment to link"),
    stage: str | None = typer.Option(
        None, "--stage", help="Optional starting stage label"
    ),
    status: str = typer.Option("open", "--status", help="Case status (default: open)"),
    assigned_to: str | None = typer.Option(
        None, "--assigned-to", help="Who owns the case now"
    ),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON metadata blob"),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
) -> None:
    meta = _load_metadata(metadata)
    with _connect(env) as conn, conn.cursor() as cur:
        judgment = _fetch_judgment(conn, judgment_id)
        cur.execute(
            """
            INSERT INTO public.enforcement_cases (judgment_id, case_number, current_stage, status, assigned_to, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                judgment_id,
                judgment.get("case_number"),
                stage,
                status,
                assigned_to,
                Jsonb(meta),
            ),
        )
        case_row = cur.fetchone()
    typer.echo(
        f"[enforcement_cli] Created case {case_row['id']} for judgment {judgment_id}"
    )


@app.command("add-event")
def add_event(
    case_id: str = typer.Argument(..., help="Enforcement case UUID"),
    event_type: str = typer.Option(
        ..., "--type", help="Short label (e.g., levy_issued)"
    ),
    event_date: datetime | str | None = typer.Option(
        None, "--date", help="ISO timestamp; defaults to now"
    ),
    notes: str | None = typer.Option(None, "--notes", help="Long-form detail"),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON metadata blob"),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
) -> None:
    meta = _load_metadata(metadata)
    occurred_at = _coerce_datetime(event_date)
    with _connect(env) as conn, conn.cursor() as cur:
        _ensure_case_exists(conn, case_id)
        cur.execute(
            """
            INSERT INTO public.enforcement_events (case_id, event_type, event_date, notes, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (case_id, event_type, occurred_at, notes, Jsonb(meta)),
        )
        row = cur.fetchone()
    typer.echo(f"[enforcement_cli] Recorded event {row['id']} for case {case_id}")


@app.command("attach-evidence")
def attach_evidence(
    case_id: str = typer.Argument(..., help="Enforcement case UUID"),
    file_path: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    file_type: str | None = typer.Option(
        None, "--type", help="Optional friendly file type label"
    ),
    uploaded_by: str | None = typer.Option(
        None, "--uploaded-by", help="Who uploaded the file"
    ),
    metadata: str | None = typer.Option(None, "--metadata", help="JSON metadata blob"),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
    ttl_seconds: int = typer.Option(
        3600, "--ttl", help="Signed URL lifetime for confirmation (seconds)"
    ),
) -> None:
    supabase_env = env or get_supabase_env()
    meta = _load_metadata(metadata)
    file_bytes = file_path.read_bytes()
    file_size = file_path.stat().st_size
    content_type = (
        file_type
        or mimetypes.guess_type(file_path.name)[0]
        or "application/octet-stream"
    )
    object_key = f"cases/{case_id}/{int(datetime.now(timezone.utc).timestamp())}_{file_path.name}"

    client = create_supabase_client(supabase_env)
    storage = client.storage.from_(EVIDENCE_BUCKET)
    storage.upload(object_key, file_bytes, {"content-type": content_type})

    meta.setdefault("file_name", file_path.name)
    meta.setdefault("file_size", file_size)
    meta.setdefault("content_type", content_type)

    storage_path = f"{EVIDENCE_BUCKET}/{object_key}"

    with _connect(supabase_env) as conn, conn.cursor() as cur:
        _ensure_case_exists(conn, case_id)
        cur.execute(
            """
            INSERT INTO public.evidence_files (case_id, storage_path, file_type, uploaded_by, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                case_id,
                storage_path,
                file_type or content_type,
                uploaded_by,
                Jsonb(meta),
            ),
        )
        row = cur.fetchone()

    signed_url = storage.create_signed_url(object_key, ttl_seconds)
    typer.echo(
        "[enforcement_cli] Uploaded evidence {evidence_id} for case {case_id}\n    path={path}\n    download_url={url}".format(
            evidence_id=row["id"],
            case_id=case_id,
            path=storage_path,
            url=signed_url.get("signedURL") if isinstance(signed_url, dict) else None,
        )
    )


@app.command("list-cases")
def list_cases(
    plaintiff_id: str | None = typer.Option(
        None, "--plaintiff-id", help="Filter by plaintiff UUID"
    ),
    judgment_id: int | None = typer.Option(
        None, "--judgment-id", help="Filter by judgment ID"
    ),
    status: str | None = typer.Option(
        "open", "--status", help="Filter by case status (default: open)"
    ),
    limit: int = typer.Option(
        25, "--limit", min=1, max=200, help="Maximum rows to display"
    ),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
) -> None:
    conditions: list[str] = []
    params: list[Any] = []
    if plaintiff_id:
        conditions.append("plaintiff_id = %s")
        params.append(plaintiff_id)
    if judgment_id:
        conditions.append("judgment_id = %s")
        params.append(judgment_id)
    if status:
        conditions.append("status = %s")
        params.append(status)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"""
        SELECT case_id, case_number, plaintiff_name, status, current_stage, assigned_to,
               judgment_amount, latest_event_type, latest_event_date
        FROM public.v_enforcement_case_summary
        {where_clause}
        ORDER BY opened_at DESC
        LIMIT %s
    """
    params.append(limit)

    with _connect(env) as conn, conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        typer.echo("[enforcement_cli] No cases matched the filters provided.")
        return

    header = (
        f"{'Case ID':36}  {'Plaintiff':24}  {'Status':8}  {'Stage':18}  {'Assigned':16}"
        f"  {'Latest Event':20}  {'Judgment':10}"
    )
    typer.echo(header)
    typer.echo("-" * len(header))
    for row in rows:
        typer.echo(
            f"{row['case_id']:36}  "
            f"{(row.get('plaintiff_name') or '-')[:24]:24}  "
            f"{(row.get('status') or '-'):8}  "
            f"{(row.get('current_stage') or '-'):18}  "
            f"{(row.get('assigned_to') or '-'):16}  "
            f"{(row.get('latest_event_type') or '-'):20}  "
            f"{row.get('judgment_amount') or 0:10.0f}"
        )


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
