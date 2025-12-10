"""Dev-only simulator for the 900 plaintiff pipeline dry run.

This utility orchestrates a full JBI 900 style import, enriches the seeded
judgments with stub data, fabricates FOIL responses, logs call outcomes, and
checks the dashboard-critical views so the ops console can be demoed without
live plaintiffs. The script records inserted ids under ``state/`` so a follow-up
``--reset`` run can clean up the synthetic cohort safely.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import random
import re
import tempfile
import textwrap
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import click
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from etl.src.enrichment_bundle import build_stub_enrichment
from etl.src.importers.jbi_900 import run_jbi_900_import
from etl.src.importers.pipeline_support import QueueJobManager
from etl.src.importers.simplicity_plaintiffs import run_simplicity_import
from etl.src.worker_enrich import _derive_score_components
from src.supabase_client import get_supabase_db_url, get_supabase_env

logger = logging.getLogger(__name__)

STATE_PATH = Path("state/dry_run_900_last.json")
DEFAULT_CSV = Path("run/plaintiffs_canonical.csv")
ALLOWED_ENV = "dev"
MAX_CALL_OUTCOMES = 150
VIEW_TARGETS = [
    ("public", "v_plaintiffs_overview"),
    ("public", "v_judgment_pipeline"),
    ("public", "v_enforcement_overview"),
    ("public", "v_enforcement_recent"),
    ("public", "v_plaintiff_call_queue"),
    ("public", "v_collectability_snapshot"),
]
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9\-_/]+$")
DIAG_ISSUE_WIDTH = 60
DIAG_NOTES_WIDTH = 80


@dataclass
class DryRunContext:
    env: str
    batch_name: str
    plaintiff_ids: List[str]
    judgment_ids: List[str]


def _ensure_dev_only(env: str) -> None:
    if env != ALLOWED_ENV:
        raise click.ClickException(
            "tools.dry_run_900 only runs against dev credentials (SUPABASE_MODE=dev)."
        )


def _generate_batch_name() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"dry_run_900_{timestamp}"


def _maybe_limit_csv(csv_path: Path, count: int) -> tuple[Path, Optional[Path]]:
    if count <= 0:
        raise click.ClickException("--count must be greater than zero")

    lines = csv_path.read_text(encoding="utf-8").splitlines()
    if len(lines) <= 1 or (len(lines) - 1) <= count:
        return csv_path, None

    header, data_rows = lines[0], lines[1:]
    trimmed = [header] + data_rows[:count]
    tmp_file = Path(tempfile.mkstemp(prefix="dry_run_900_", suffix=".csv")[1])
    tmp_file.write_text("\n".join(trimmed), encoding="utf-8")
    return tmp_file, tmp_file


def _collect_inserted_ids(result: Dict[str, Any], env: str, batch_name: str) -> DryRunContext:
    metadata = result.get("metadata") or {}
    row_ops = metadata.get("row_operations") or []
    plaintiffs: List[str] = []
    judgments: List[str] = []
    for operation in row_ops:
        if not isinstance(operation, dict) or operation.get("status") != "inserted":
            continue
        plaintiff_id = operation.get("plaintiff_id")
        judgment_id = operation.get("judgment_id")
        if plaintiff_id:
            plaintiffs.append(str(plaintiff_id))
        if judgment_id:
            judgments.append(str(judgment_id))
    return DryRunContext(
        env=env,
        batch_name=batch_name,
        plaintiff_ids=sorted({pid for pid in plaintiffs}),
        judgment_ids=sorted({jid for jid in judgments}),
    )


def _write_state(ctx: DryRunContext) -> None:
    payload = {
        "env": ctx.env,
        "batch_name": ctx.batch_name,
        "plaintiff_ids": ctx.plaintiff_ids,
        "judgment_ids": ctx.judgment_ids,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _load_state(env: str) -> Optional[DryRunContext]:
    if not STATE_PATH.is_file():
        return None
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if payload.get("env") != env:
        return None
    return DryRunContext(
        env=env,
        batch_name=str(payload.get("batch_name") or "dry_run_900_unknown"),
        plaintiff_ids=[str(pid) for pid in payload.get("plaintiff_ids", [])],
        judgment_ids=[str(jid) for jid in payload.get("judgment_ids", [])],
    )


def _cleanup_previous_run(conn: psycopg.Connection, env: str) -> Dict[str, int]:
    ctx = _load_state(env)
    if ctx is None:
        return {"plaintiffs": 0, "judgments": 0}

    removed = {
        "foil_responses": 0,
        "enrichment_runs": 0,
        "call_attempts": 0,
        "tasks": 0,
        "statuses": 0,
        "contacts": 0,
        "judgments": 0,
        "plaintiffs": 0,
    }
    with conn.cursor() as cur:
        if ctx.judgment_ids:
            ids = ctx.judgment_ids
            cur.execute(
                "delete from judgments.foil_responses where case_id = any(%s)",
                (ids,),
            )
            removed["foil_responses"] = cur.rowcount or 0
            cur.execute(
                "delete from judgments.enrichment_runs where case_id = any(%s)",
                (ids,),
            )
            removed["enrichment_runs"] = cur.rowcount or 0
            cur.execute(
                "delete from public.judgments where id = any(%s)",
                (ids,),
            )
            removed["judgments"] = cur.rowcount or 0
        if ctx.plaintiff_ids:
            ids = ctx.plaintiff_ids
            cur.execute(
                "delete from public.plaintiff_call_attempts where plaintiff_id = any(%s)",
                (ids,),
            )
            removed["call_attempts"] = cur.rowcount or 0
            cur.execute(
                "delete from public.plaintiff_tasks where plaintiff_id = any(%s)",
                (ids,),
            )
            removed["tasks"] = cur.rowcount or 0
            cur.execute(
                "delete from public.plaintiff_status_history where plaintiff_id = any(%s)",
                (ids,),
            )
            removed["statuses"] = cur.rowcount or 0
            cur.execute(
                "delete from public.plaintiff_contacts where plaintiff_id = any(%s)",
                (ids,),
            )
            removed["contacts"] = cur.rowcount or 0
            cur.execute(
                "delete from public.plaintiffs where id = any(%s)",
                (ids,),
            )
            removed["plaintiffs"] = cur.rowcount or 0
    try:
        STATE_PATH.unlink()
    except FileNotFoundError:
        pass
    return removed


def _fetch_judgments(
    conn: psycopg.Connection, judgment_ids: Sequence[str]
) -> Dict[str, Dict[str, Any]]:
    if not judgment_ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id, case_number, plaintiff_id, judgment_amount, entry_date
            from public.judgments
            where id = any(%s)
            """,
            (list(judgment_ids),),
        )
        rows = cur.fetchall()
    return {str(row["id"]): row for row in rows if row.get("id")}


def _simulate_enrichment(
    conn: psycopg.Connection,
    judgments: Dict[str, Dict[str, Any]],
    batch_name: str,
) -> Dict[str, Any]:
    if not judgments:
        return {"case_count": 0, "enrichment_runs": 0}

    case_ids = list(judgments)
    with conn.cursor() as cur:
        cur.execute(
            "delete from judgments.enrichment_runs where case_id = any(%s)",
            (case_ids,),
        )

    created = 0
    for case_id, row in judgments.items():
        snapshot = {
            "case_number": row.get("case_number"),
            "judgment_amount": row.get("judgment_amount"),
            "judgment_date": row.get("entry_date"),
        }
        stub = build_stub_enrichment(case_id, snapshot)
        tier = (stub.raw.get("tier_hint") or "C").upper()
        contacts = [{}] if tier != "C" else []
        assets = [{}] if tier == "A" else []
        context = {
            "entities": [{"role": "defendant"}],
            "defendants": [{"role": "defendant"}],
            "contacts": contacts,
            "assets": assets,
            "signals": stub.raw.get("signals", {}),
        }
        scores = _derive_score_components(stub.raw, context)
        with conn.cursor() as cur:
            cur.execute(
                """
                insert into judgments.enrichment_runs (case_id, status, summary, raw)
                values (%s, %s, %s, %s)
                """,
                (
                    case_id,
                    "success",
                    stub.summary,
                    Jsonb({**stub.raw, "batch_name": batch_name}),
                ),
            )
            cur.execute(
                "select public.set_case_enrichment(%s, %s, %s, %s)",
                (
                    case_id,
                    scores.get("collectability_score"),
                    scores.get("collectability_tier"),
                    stub.summary,
                ),
            )
            cur.execute(
                "select public.set_case_scores(%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    case_id,
                    scores.get("identity_score"),
                    scores.get("contactability_score"),
                    scores.get("asset_score"),
                    scores.get("recency_amount_score"),
                    scores.get("adverse_penalty"),
                    scores.get("collectability_score"),
                    scores.get("collectability_tier"),
                ),
            )
        created += 1
    return {"case_count": len(judgments), "enrichment_runs": created}


def _simulate_foil(
    conn: psycopg.Connection,
    judgments: Dict[str, Dict[str, Any]],
    batch_name: str,
) -> Dict[str, Any]:
    if not judgments:
        return {"foil_responses": 0}

    agencies = ["NYC Department of Finance", "NYC Sheriff", "NYS DMV"]
    today = datetime.now(timezone.utc).date()
    inserted = 0
    with conn.cursor() as cur:
        cur.execute(
            "delete from judgments.foil_responses where case_id = any(%s)",
            (list(judgments),),
        )
        for case_id, row in judgments.items():
            request_date = today - timedelta(days=random.randint(10, 45))
            received_date = min(
                today,
                request_date + timedelta(days=random.randint(3, 14)),
            )
            cur.execute(
                """
                insert into judgments.foil_responses (
                    case_id, agency, request_date, received_date, status, response_reference, raw
                ) values (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    case_id,
                    random.choice(agencies),
                    request_date,
                    received_date,
                    "fulfilled",
                    f"DRY-{row.get('case_number')}",
                    Jsonb({"batch_name": batch_name}),
                ),
            )
            inserted += 1
    return {"foil_responses": inserted}


def _simulate_call_outcomes(conn: psycopg.Connection, ctx: DryRunContext) -> Dict[str, Any]:
    if not ctx.plaintiff_ids:
        return {"total": 0}

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id, plaintiff_id
            from public.plaintiff_tasks
            where plaintiff_id = any(%s)
              and kind = 'call'
              and status = 'open'
            order by due_at asc
            limit %s
            """,
            (ctx.plaintiff_ids, MAX_CALL_OUTCOMES),
        )
        tasks = cur.fetchall()

    stats = {"total": 0, "reached": 0, "voicemail": 0, "do_not_call": 0}
    now = datetime.now(timezone.utc)
    with conn.cursor() as cur:
        for task in tasks:
            outcome = random.choices(
                ["reached", "voicemail", "do_not_call"],
                weights=[0.5, 0.35, 0.15],
            )[0]
            interest = random.choice(["hot", "warm", "cold"]) if outcome == "reached" else None
            follow_up = (
                now + timedelta(days=random.randint(2, 10)) if outcome == "reached" else None
            )
            note = f"Dry run simulated outcome: {outcome}"
            cur.execute(
                "select public.log_call_outcome(%s, %s, %s, %s, %s, %s)",
                (
                    task["plaintiff_id"],
                    task["id"],
                    outcome,
                    interest,
                    note,
                    follow_up,
                ),
            )
            stats["total"] += 1
            stats[outcome] += 1
    return stats


def _enqueue_foil_jobs(
    conn: psycopg.Connection,
    judgments: Dict[str, Dict[str, Any]],
    batch_name: str,
) -> Dict[str, Any]:
    manager = QueueJobManager(conn)
    if not manager.available or not judgments:
        return {"queued": 0, "available": manager.available}

    for case_id, row in judgments.items():
        payload = {
            "case_id": case_id,
            "case_number": row.get("case_number"),
            "batch_name": batch_name,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        manager.enqueue(
            kind="foil_request",
            payload=payload,
            idempotency_key=f"dryrun:foil:{case_id}",
        )
    return {"queued": len(judgments), "available": True}


def _collect_view_counts(conn: psycopg.Connection) -> Dict[str, Optional[int]]:
    metrics: Dict[str, Optional[int]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        for schema, view in VIEW_TARGETS:
            key = f"{schema}.{view}"
            try:
                cur.execute(
                    sql.SQL("select count(*) as total from {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(view)
                    )
                )
                row = cur.fetchone()
                metrics[key] = int(row["total"]) if row else None
            except psycopg.errors.UndefinedTable:
                metrics[key] = None
    return metrics


# ---------------------------------------------------------------------------
# Reporting helpers (--report)
# ---------------------------------------------------------------------------


def _configure_report_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="[%(asctime)s] %(levelname)s %(message)s")


def _count_csv_rows(csv_path: Path) -> int:
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        return sum(1 for _ in reader)


def _prepare_report_sample(csv_path: Path, count: int) -> tuple[Path, Optional[Path], int, int]:
    total_rows = _count_csv_rows(csv_path)
    limited_csv, temp_csv = _maybe_limit_csv(csv_path, count)
    sample_rows = min(count, total_rows) if total_rows else 0
    return limited_csv, temp_csv, total_rows, sample_rows


def _identifier_issue_list(value: Optional[str]) -> list[str]:
    issues: list[str] = []
    if not value:
        issues.append("missing")
        return issues
    if value.strip() != value:
        issues.append("leading/trailing whitespace")
    if " " in value:
        issues.append("contains spaces")
    if not IDENTIFIER_PATTERN.match(value):
        issues.append("invalid characters")
    if not any(char.isdigit() for char in value):
        issues.append("no digits")
    if len(value) < 4:
        issues.append("too short")
    return issues


def _collect_row_notes(operation: Dict[str, Any]) -> list[str]:
    notes: list[str] = []
    status = operation.get("status")
    action = operation.get("action")
    if status == "skipped" and action:
        notes.append(action)
    if operation.get("existing_plaintiff_id"):
        notes.append(f"existing_plaintiff={operation['existing_plaintiff_id']}")
    if operation.get("new_plaintiff") is True:
        notes.append("new_plaintiff")
    if operation.get("error"):
        notes.append(str(operation["error"]))
    return notes


def _build_report_diagnostics(metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    diagnostics: List[Dict[str, str]] = []
    row_operations = metadata.get("row_operations") or []
    parse_errors = metadata.get("parse_errors") or []

    for operation in row_operations:
        row_number = str(operation.get("row_number") or "-")
        case_number = str(operation.get("case_number") or "-")
        judgment_number = str(operation.get("judgment_number") or "-")
        case_issues = _identifier_issue_list(None if case_number == "-" else case_number)
        judgment_issues = _identifier_issue_list(
            None if judgment_number == "-" else judgment_number
        )
        issues = case_issues + judgment_issues
        notes = _collect_row_notes(operation)
        diagnostics.append(
            {
                "row": row_number,
                "action": operation.get("action") or "-",
                "status": operation.get("status") or "-",
                "case": case_number,
                "judgment": judgment_number,
                "issues": "; ".join(issues) if issues else "-",
                "notes": "; ".join(notes) if notes else "-",
            }
        )

    for err in parse_errors:
        diagnostics.append(
            {
                "row": str(err.get("row_number") or "-"),
                "action": "parse_error",
                "status": "parse_error",
                "case": "-",
                "judgment": "-",
                "issues": "-",
                "notes": err.get("error", "parse failure"),
            }
        )

    diagnostics.sort(key=lambda item: int(item["row"]) if item["row"].isdigit() else 10**9)
    return diagnostics


def _build_report_summary(
    metadata: Dict[str, Any], diagnostics: List[Dict[str, str]]
) -> Dict[str, int]:
    row_operations = metadata.get("row_operations") or []
    parse_errors = metadata.get("parse_errors") or []
    summary_block = metadata.get("summary") or {}
    row_count = int(summary_block.get("row_count") or (len(row_operations) + len(parse_errors)))

    potential_inserts = sum(
        1
        for op in row_operations
        if op.get("status") == "planned" and op.get("action") == "create_plaintiff_and_judgment"
    )
    potential_updates = sum(
        1
        for op in row_operations
        if op.get("status") == "planned"
        and op.get("action") == "attach_judgment_to_existing_plaintiff"
    )
    skipped_rows = sum(1 for op in row_operations if op.get("status") == "skipped")
    error_rows = sum(1 for op in row_operations if op.get("status") == "error") + len(parse_errors)
    identifier_warnings = sum(1 for row in diagnostics if row["issues"] != "-")

    return {
        "row_count": row_count,
        "potential_inserts": potential_inserts,
        "potential_updates": potential_updates,
        "skipped_rows": skipped_rows,
        "error_rows": error_rows,
        "identifier_warnings": identifier_warnings,
        "parse_errors": len(parse_errors),
    }


def _shorten(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return textwrap.shorten(text, width=width, placeholder="…")


def _render_table(title: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    click.echo()
    click.echo(title)
    if not rows:
        click.echo("  (no data)")
        return

    string_rows = [[str(cell) for cell in row] for row in rows]
    widths = [len(col) for col in columns]
    for row in string_rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    header = "  " + "  ".join(columns[idx].ljust(widths[idx]) for idx in range(len(columns)))
    divider = "  " + "  ".join("-" * widths[idx] for idx in range(len(columns)))
    click.echo(header)
    click.echo(divider)
    for row in string_rows:
        line = "  " + "  ".join(row[idx].ljust(widths[idx]) for idx in range(len(columns)))
        click.echo(line)


def _run_report(
    csv_path: Path,
    count: int,
    batch_name: Optional[str],
    env: str,
    max_diagnostics: int,
    verbose: bool,
) -> None:
    _configure_report_logging(verbose)
    os.environ["SUPABASE_MODE"] = env

    limited_csv: Path
    temp_csv: Optional[Path] = None
    try:
        limited_csv, temp_csv, total_rows, sample_rows = _prepare_report_sample(csv_path, count)
        if temp_csv:
            logger.info(
                "Using sampled CSV subset",
                extra={
                    "rows": sample_rows,
                    "source": str(csv_path),
                    "sample": str(limited_csv),
                },
            )
        else:
            logger.info(
                "Using full CSV payload",
                extra={"rows": total_rows, "source": str(csv_path)},
            )

        batch = (
            batch_name or f"dry_run_report_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        )
        logger.info("Running dry-run Simplicity import", extra={"batch": batch, "env": env})
        result = run_simplicity_import(
            str(limited_csv),
            batch_name=batch,
            dry_run=True,
            source_reference=batch,
        )

        metadata = result.get("metadata", {})
        diagnostics = _build_report_diagnostics(metadata)
        summary = _build_report_summary(metadata, diagnostics)

        summary_rows = [
            ("Row Count", summary["row_count"]),
            ("Potential Inserts", summary["potential_inserts"]),
            ("Potential Updates", summary["potential_updates"]),
            ("Skipped Rows", summary["skipped_rows"]),
            ("Errors", summary["error_rows"]),
            ("Identifier Warnings", summary["identifier_warnings"]),
            ("Parse Errors", summary["parse_errors"]),
        ]
        _render_table("[dry_run_900] Summary", ["Metric", "Value"], summary_rows)

        if diagnostics:
            display = diagnostics[:max_diagnostics]
            diag_rows = [
                (
                    row["row"],
                    row["action"],
                    row["status"],
                    row["case"],
                    row["judgment"],
                    _shorten(row["issues"], DIAG_ISSUE_WIDTH),
                    _shorten(row["notes"], DIAG_NOTES_WIDTH),
                )
                for row in display
            ]
            _render_table(
                f"[dry_run_900] Per-row diagnostics (showing {len(display)} of {len(diagnostics)})",
                [
                    "Row",
                    "Action",
                    "Status",
                    "Case #",
                    "Judgment #",
                    "Identifier Issues",
                    "Notes",
                ],
                diag_rows,
            )
            if len(display) < len(diagnostics):
                click.echo(
                    f"\nDisplayed {len(display)} rows out of {len(diagnostics)}. Increase --max-diagnostics to show more."
                )
        else:
            click.echo("\nNo diagnostics available; importer returned zero operations.")

        logger.info(
            "Dry-run report completed",
            extra={"batch": batch, "rows": summary["row_count"]},
        )
    finally:
        if temp_csv and temp_csv.exists():
            temp_csv.unlink(missing_ok=True)


@click.command()
@click.option(
    "--env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Supabase credential set to target",
)
@click.option(
    "--csv",
    type=click.Path(path_type=Path),
    default=DEFAULT_CSV,
    show_default=True,
    help="CSV file to feed into the importer",
)
@click.option(
    "--count",
    type=int,
    default=900,
    show_default=True,
    help="Number of rows to load from the CSV",
)
@click.option(
    "--batch-name",
    type=str,
    default=None,
    help="Override the auto-generated batch label",
)
@click.option(
    "--reset",
    is_flag=True,
    help="Remove the previously recorded dry run cohort before seeding",
)
@click.option("--reset-only", is_flag=True, help="Only perform the cleanup step and exit")
@click.option(
    "--report",
    is_flag=True,
    help="Run a dry-run Simplicity import preview with diagnostics instead of the full simulator.",
)
@click.option(
    "--max-diagnostics",
    type=int,
    default=25,
    show_default=True,
    help="Number of per-row diagnostics to display when using --report.",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable verbose logging for --report runs.",
)
def main(
    env: Optional[str],
    csv: Path,
    count: int,
    batch_name: Optional[str],
    reset: bool,
    reset_only: bool,
    report: bool,
    max_diagnostics: int,
    verbose: bool,
) -> None:
    resolved_env = env or get_supabase_env()
    _ensure_dev_only(resolved_env)

    csv_path = csv.resolve()
    if not csv_path.is_file():
        raise click.ClickException(f"CSV not found: {csv_path}")

    if report:
        if reset or reset_only:
            raise click.ClickException("--report cannot be combined with --reset or --reset-only")
        _run_report(
            csv_path=csv_path,
            count=count,
            batch_name=batch_name,
            env=resolved_env,
            max_diagnostics=max_diagnostics,
            verbose=verbose,
        )
        return

    db_url = get_supabase_db_url(resolved_env)
    tmp_csv: Optional[Path] = None
    try:
        with psycopg.connect(db_url, autocommit=False) as conn:
            if reset or reset_only:
                removed = _cleanup_previous_run(conn, resolved_env)
                conn.commit()
                click.echo(f"[cleanup] {removed}")
                if reset_only:
                    return

            limited_csv, tmp_csv = _maybe_limit_csv(csv_path, count)

            batch = batch_name or _generate_batch_name()
            click.echo(f"[import] batch={batch} env={resolved_env} csv={limited_csv}")
            result = run_jbi_900_import(
                str(limited_csv),
                batch_name=batch,
                dry_run=False,
                source_reference=batch,
                connection=conn,
                enable_new_pipeline=True,
            )
            ctx = _collect_inserted_ids(result, resolved_env, batch)
            conn.commit()

            if not ctx.judgment_ids:
                click.echo("[warn] Import produced no new judgments; aborting simulation")
                return

            judgments = _fetch_judgments(conn, ctx.judgment_ids)
            enrichment_stats = _simulate_enrichment(conn, judgments, batch)
            foil_stats = _simulate_foil(conn, judgments, batch)
            call_stats = _simulate_call_outcomes(conn, ctx)
            queue_stats = _enqueue_foil_jobs(conn, judgments, batch)
            view_stats = _collect_view_counts(conn)
            conn.commit()

            _write_state(ctx)
            summary = {
                "batch_name": batch,
                "env": resolved_env,
                "plaintiffs": len(ctx.plaintiff_ids),
                "judgments": len(ctx.judgment_ids),
                "enrichment": enrichment_stats,
                "foil": foil_stats,
                "call_outcomes": call_stats,
                "queue": queue_stats,
                "views": view_stats,
            }
            click.echo(json.dumps(summary, indent=2, sort_keys=True, default=str))
    finally:
        if tmp_csv is not None and tmp_csv.exists():
            tmp_csv.unlink()


if __name__ == "__main__":
    main()
