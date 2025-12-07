"""Lightweight environment checks for Supabase connectivity."""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path
from uuid import UUID, uuid4

import click
import httpx
import psycopg

from src.supabase_client import create_supabase_client


def _row_count(response) -> int:
    data = getattr(response, "data", None)
    if data is None:
        return 0
    if isinstance(data, (list, tuple)):
        return len(data)
    return 1


def _first_row(response):
    data = getattr(response, "data", None)
    if isinstance(data, list) and data:
        return data[0]
    return None


@click.command()
def main() -> None:
    """Run basic Supabase doctor checks."""

    client = create_supabase_client()

    res = client.table("judgments").select("*").limit(1).execute()
    click.echo(f"Judgments check OK, rows={_row_count(res)}")

    sample_case = _first_row(res)
    sample_case_id = _extract_case_id(client, sample_case)

    # Ensure the public collectability view exists before probing via PostgREST.
    try:
        _ensure_collectability_view()
    except Exception as exc:
        click.echo(f"[doctor] Unable to ensure collectability snapshot view: {exc}")
        raise SystemExit(1)

    try:
        res = client.table("enrichment_runs").select("id").limit(1).execute()
        click.echo(f"enrichment_runs check OK, rows={_row_count(res)}")
        if sample_case_id:
            ping_summary = f"doctor-check:{uuid4().hex[:8]}"
            run_id = _generate_enrichment_run_id()
            payload = {
                "id": run_id,
                "case_id": sample_case_id,
                "status": "doctor_check",
                "summary": ping_summary,
                "raw": {"source": "doctor"},
            }
            insert_res = client.table("enrichment_runs").insert(payload).execute()
            inserted_row = _first_row(insert_res)
            inserted_id = run_id
            if inserted_row and inserted_row.get("id") is not None:
                inserted_id = inserted_row["id"]
            client.table("enrichment_runs").delete().eq("id", inserted_id).execute()
            click.echo("enrichment_runs write OK")
        else:
            click.echo(
                "[doctor] Skipping enrichment_runs write test; no cases available to reference."
            )
    except Exception as exc:  # pragma: no cover - diagnostics for missing table/view
        message = str(exc)
        click.echo(f"enrichment_runs check FAILED: {exc}")
        if "PGRST" in message or "404" in message:
            click.echo(
                "[doctor] enrichment_runs table not accessible. Apply migration "
                "0053_enrichment_runs.sql and reload PostgREST."
            )
        elif "permission denied for sequence" in message:
            click.echo(
                "[doctor] service_role is missing usage on the enrichment_runs id sequence. "
                "Apply migration 0056_enrichment_runs_finalize.sql and reload PostgREST."
            )
        raise SystemExit(1)

    # Ensure PostgREST schema cache is aware of new views before verifying reachability.
    for attempt in range(2):
        try:
            snapshot_res = (
                client.table("v_collectability_snapshot").select("case_id").limit(1).execute()
            )
            click.echo(f"collectability snapshot check OK, rows={_row_count(snapshot_res)}")
            break
        except Exception as exc:
            message = str(exc)
            if attempt == 0 and ("PGRST" in message or "404" in message):
                try:
                    _trigger_postgrest_reload(client)
                    time.sleep(0.5)
                    continue
                except Exception:
                    pass
            if "PGRST" in message or "404" in message:
                click.echo(
                    "collectability snapshot check FAILED: PostgREST schema cache is missing the view. "
                    "Run `select public.pgrst_reload()` or rerun `tools.doctor` after cache refresh."
                )
            else:
                click.echo(f"collectability snapshot check FAILED: {exc}")
            raise SystemExit(1)

    try:
        foil_rows = _count_foil_responses()
        click.echo(f"foil_responses check OK, rows={foil_rows}")
    except Exception as exc:
        click.echo(f"foil_responses check FAILED: {exc}")
        raise SystemExit(1)

    try:
        client.rpc(
            "queue_job",
            {"payload": {"idempotency_key": "doctor:ping", "kind": "enrich", "payload": {}}},
        ).execute()
        click.echo("queue_job RPC OK")
    except Exception as exc:  # pragma: no cover - doctor diagnostics
        message = str(exc)
        click.echo(f"queue_job RPC FAILED: {exc}")

        if "PGRST202" in message:
            click.echo(
                "[doctor] queue_job RPC not found in PostgREST schema. "
                "Check that migration 0051_queue_job_expose.sql has been applied and PostgREST has been reloaded."
            )
        elif "42P01" in message and "pgmq.q_enrich" in message:
            click.echo(
                "[doctor] pgmq queues (q_enrich/q_outreach/q_enforce) are missing. "
                "Apply migration 0052_queue_bootstrap.sql via `supabase db push` or run "
                "`python -m tools.ensure_queues_exist` to recreate them."
            )
        elif _is_network_error(exc):
            click.echo(
                "[doctor] Supabase network/pooler error while calling queue_job. "
                "This is an infrastructure/network issue, not a local code problem."
            )
        raise SystemExit(1)


def _extract_case_id(client, sample_case):
    """Best-effort attempt to find a UUID case identifier for enrichment tests."""

    # Prefer the public case view which exposes the canonical UUID.
    try:
        case_view_res = client.table("v_cases_with_org").select("case_id").limit(1).execute()
        case_row = _first_row(case_view_res)
        candidate = None
        if isinstance(case_row, dict):
            candidate = case_row.get("case_id")
        if candidate and _looks_like_uuid(candidate):
            return str(candidate)
    except Exception:
        # Continue with fallback logic; view may be unavailable in some environments.
        pass

    if isinstance(sample_case, dict):
        # Some datasets surface "case_id" alongside other columns.
        for key in ("case_id", "id"):
            candidate = sample_case.get(key)
            if candidate and _looks_like_uuid(candidate):
                return str(candidate)

    return None


def _looks_like_uuid(value) -> bool:
    try:
        UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


def _generate_enrichment_run_id() -> int:
    return (1 << 62) | secrets.randbits(62)


def _is_network_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    cause = exc.__cause__
    if isinstance(cause, httpx.RequestError):
        return True
    context = getattr(exc, "__context__", None)
    return isinstance(context, httpx.RequestError)


def _resolve_db_url() -> str | None:
    explicit = os.getenv("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.getenv("SUPABASE_PROJECT_REF")
    password = os.getenv("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"
    return None


def _trigger_postgrest_reload(client) -> None:
    try:
        client.rpc("pgrst_reload", {}).execute()
        return
    except Exception:
        pass

    db_url = _resolve_db_url()
    if not db_url:
        raise RuntimeError(
            "Unable to reload PostgREST schema cache; SUPABASE_DB_URL not configured."
        )

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("select public.pgrst_reload()")


def _count_foil_responses() -> int:
    db_url = _resolve_db_url()
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL or project credentials not configured; cannot query foil responses."
        )

    _ensure_foil_responses_schema()

    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("select count(*) from public.foil_responses")
                row = cur.fetchone()
                return int(row[0]) if row else 0
    except psycopg.errors.UndefinedTable as exc:
        raise RuntimeError(
            "public.foil_responses missing. Apply migrations 0059_foil_responses.sql and 0060_foil_responses_agency.sql"
        ) from exc


def _ensure_foil_responses_schema() -> None:
    db_url = _resolve_db_url()
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL or project credentials not configured; cannot ensure foil_responses schema."
        )

    migration_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    migration_files = [
        migration_dir / "0059_foil_responses.sql",
        migration_dir / "0060_foil_responses_agency.sql",
    ]

    statements: list[str] = []
    for path in migration_files:
        up_sql_text = path.read_text(encoding="utf-8")
        up_sql_section = up_sql_text.split("-- migrate:down", 1)[0]
        if "-- migrate:up" in up_sql_section:
            up_sql_section = up_sql_section.split("-- migrate:up", 1)[1]
        up_sql = up_sql_section.strip()
        if up_sql:
            statements.append(up_sql)

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)  # type: ignore[arg-type]


def _ensure_collectability_view() -> None:
    db_url = _resolve_db_url()
    if not db_url:
        raise RuntimeError(
            "SUPABASE_DB_URL or project credentials not configured; cannot ensure view existence."
        )

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "supabase"
        / "migrations"
        / "0058_collectability_public_view.sql"
    )
    up_sql_text = migration_path.read_text(encoding="utf-8")
    up_sql_section = up_sql_text.split("-- migrate:down", 1)[0]
    if "-- migrate:up" in up_sql_section:
        up_sql_section = up_sql_section.split("-- migrate:up", 1)[1]
    up_sql = up_sql_section.strip()
    if not up_sql:
        raise RuntimeError("Collectability migration missing migrate:up SQL block.")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(up_sql)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
