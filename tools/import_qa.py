from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import psycopg
import typer
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from src.supabase_client import SupabaseEnv, get_supabase_db_url, get_supabase_env

app = typer.Typer(help="QA checks for Simplicity + JBI 900 imports.")

__all__ = [
    "check_simplicity_batch",
    "check_jbi_900_batch",
    "app",
]


@dataclass(frozen=True)
class ImportQAConfig:
    name: str
    import_kind: str
    changed_by: str
    note_hint: str


SIMPLICITY_CONFIG = ImportQAConfig(
    name="simplicity",
    import_kind="simplicity_plaintiffs",
    changed_by="simplicity_import",
    note_hint="simplicity",
)

JBI_CONFIG = ImportQAConfig(
    name="jbi_900",
    import_kind="jbi_900_plaintiffs",
    changed_by="jbi_900_import",
    note_hint="jbi",
)

_COHORT_METRICS_SQL = """
WITH cohort AS (
    SELECT DISTINCT plaintiff_id
    FROM public.plaintiff_status_history
    WHERE changed_by = %(changed_by)s
      AND note ILIKE %(note_match)s
      AND plaintiff_id IS NOT NULL
),
plaintiff_counts AS (
    SELECT
        COUNT(*) AS total_plaintiffs,
        COUNT(*) FILTER (WHERE p.phone IS NULL OR btrim(p.phone) = '') AS missing_phone,
        COUNT(*) FILTER (WHERE p.email IS NULL OR btrim(p.email) = '') AS missing_email,
        COUNT(*) FILTER (
            WHERE (p.phone IS NULL OR btrim(p.phone) = '')
              AND (p.email IS NULL OR btrim(p.email) = '')
        ) AS missing_both
    FROM cohort c
    JOIN public.plaintiffs p ON p.id = c.plaintiff_id
),
task_base AS (
    SELECT
        c.plaintiff_id,
        COUNT(t.*) AS total_tasks,
        COUNT(*) FILTER (WHERE t.kind = 'call' AND t.status IN ('open', 'in_progress')) AS open_call_tasks
    FROM cohort c
    LEFT JOIN public.plaintiff_tasks t ON t.plaintiff_id = c.plaintiff_id
    GROUP BY c.plaintiff_id
),
task_counts AS (
    SELECT
        COUNT(*) FILTER (WHERE COALESCE(total_tasks, 0) = 0) AS without_tasks,
        COUNT(*) FILTER (WHERE COALESCE(open_call_tasks, 0) = 0) AS without_open_calls,
        COUNT(*) FILTER (WHERE COALESCE(open_call_tasks, 0) > 1) AS multi_open_calls
    FROM task_base
),
judgment_counts AS (
    SELECT
        COUNT(*) AS total_judgments,
        COUNT(*) FILTER (WHERE j.judgment_amount IS NULL OR j.judgment_amount <= 0) AS non_positive
    FROM cohort c
    JOIN public.judgments j ON j.plaintiff_id = c.plaintiff_id
)
SELECT
    COALESCE(pc.total_plaintiffs, 0) AS total_plaintiffs,
    COALESCE(pc.missing_phone, 0) AS missing_phone,
    COALESCE(pc.missing_email, 0) AS missing_email,
    COALESCE(pc.missing_both, 0) AS missing_both,
    COALESCE(jc.total_judgments, 0) AS total_judgments,
    COALESCE(jc.non_positive, 0) AS non_positive_judgments,
    COALESCE(tc.without_tasks, 0) AS plaintiffs_without_tasks,
    COALESCE(tc.without_open_calls, 0) AS plaintiffs_without_open_calls,
    COALESCE(tc.multi_open_calls, 0) AS plaintiffs_multi_open_calls
FROM (SELECT 1) s
LEFT JOIN plaintiff_counts pc ON TRUE
LEFT JOIN judgment_counts jc ON TRUE
LEFT JOIN task_counts tc ON TRUE;
"""

_DUPLICATE_SQL = """
WITH cohort AS (
    SELECT DISTINCT plaintiff_id
    FROM public.plaintiff_status_history
    WHERE changed_by = %(changed_by)s
      AND note ILIKE %(note_match)s
      AND plaintiff_id IS NOT NULL
)
SELECT
    lower(trim(COALESCE(j.plaintiff_name, ''))) AS name_key,
    MIN(COALESCE(j.plaintiff_name, '')) AS sample_name,
    COALESCE(j.judgment_amount, 0)::numeric AS judgment_amount,
    'unknown'::text AS county_label,
    COUNT(*) AS duplicate_count,
    array_agg(j.id ORDER BY j.id) AS judgment_ids
FROM cohort c
JOIN public.judgments j ON j.plaintiff_id = c.plaintiff_id
GROUP BY name_key, judgment_amount
HAVING COUNT(*) > 1
ORDER BY duplicate_count DESC, name_key
LIMIT 25;
"""

_IMPORT_RUN_SQL = """
SELECT id
FROM public.import_runs
WHERE import_kind = %s
  AND metadata->>'batch_name' = %s
ORDER BY started_at DESC
LIMIT 1;
"""


def _connect(env: SupabaseEnv | None) -> psycopg.Connection:
    supabase_env = env or get_supabase_env()
    db_url = get_supabase_db_url(supabase_env)
    return psycopg.connect(db_url, autocommit=False, row_factory=dict_row)


def _pct(count: int, total: int) -> float:
    if not total:
        return 0.0
    return round((count / total) * 100, 2)


def _normalize_metrics(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Return a JSON-serializable copy."""

    def _default(obj: Any) -> Any:
        if hasattr(obj, "__float__"):
            try:
                return float(obj)
            except TypeError:  # pragma: no cover - defensive
                pass
        raise TypeError(f"Type {type(obj)} is not JSON serializable")

    return json.loads(json.dumps(metrics, default=_default))


def _cohort_params(config: ImportQAConfig, batch_name: str) -> Dict[str, Any]:
    return {
        "changed_by": config.changed_by,
        "note_match": f"%{batch_name}%",
    }


def _fetch_duplicates(
    conn: psycopg.Connection, params: Dict[str, Any]
) -> List[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(_DUPLICATE_SQL, params)
        rows = cur.fetchall()
    results: List[Dict[str, Any]] = []
    for row in rows:
        amount = row["judgment_amount"]
        results.append(
            {
                "plaintiff_name": row.get("sample_name") or row.get("name_key"),
                "county": row.get("county_label"),
                "judgment_amount": float(amount) if amount is not None else None,
                "count": row.get("duplicate_count", 0),
                "judgment_ids": row.get("judgment_ids", []),
            }
        )
    return results


def _collect_metrics(
    conn: psycopg.Connection,
    config: ImportQAConfig,
    batch_name: str,
) -> Dict[str, Any]:
    params = _cohort_params(config, batch_name)
    with conn.cursor() as cur:
        cur.execute(_COHORT_METRICS_SQL, params)
        base = cur.fetchone() or {}
    duplicates = _fetch_duplicates(conn, params)
    total_plaintiffs = base.get("total_plaintiffs", 0)
    total_judgments = base.get("total_judgments", 0)
    plaintiff_counts = {
        "total": total_plaintiffs,
        "missing_phone": base.get("missing_phone", 0),
        "missing_email": base.get("missing_email", 0),
        "missing_both": base.get("missing_both", 0),
    }
    plaintiff_counts.update(
        {
            "missing_phone_pct": _pct(
                plaintiff_counts["missing_phone"], total_plaintiffs
            ),
            "missing_email_pct": _pct(
                plaintiff_counts["missing_email"], total_plaintiffs
            ),
            "missing_both_pct": _pct(
                plaintiff_counts["missing_both"], total_plaintiffs
            ),
        }
    )
    judgment_counts = {
        "total": total_judgments,
        "non_positive": base.get("non_positive_judgments", 0),
        "non_positive_pct": _pct(
            base.get("non_positive_judgments", 0), total_judgments
        ),
    }
    task_counts = {
        "without_tasks": base.get("plaintiffs_without_tasks", 0),
        "without_open_calls": base.get("plaintiffs_without_open_calls", 0),
        "multi_open_calls": base.get("plaintiffs_multi_open_calls", 0),
    }
    task_counts.update(
        {
            "without_tasks_pct": _pct(task_counts["without_tasks"], total_plaintiffs),
            "multi_open_calls_pct": _pct(
                task_counts["multi_open_calls"], total_plaintiffs
            ),
        }
    )
    return {
        "batch_name": batch_name,
        "plaintiff_counts": plaintiff_counts,
        "judgment_counts": judgment_counts,
        "task_counts": task_counts,
        "duplicate_groups": duplicates,
        "cohort_size": total_plaintiffs,
        "total_judgments": total_judgments,
    }


def _attach_metrics(
    conn: psycopg.Connection,
    config: ImportQAConfig,
    batch_name: str,
    metrics: Dict[str, Any],
) -> Optional[str]:
    with conn.cursor() as cur:
        cur.execute(_IMPORT_RUN_SQL, (config.import_kind, batch_name))
        row = cur.fetchone()
    if not row:
        return None
    qa_payload = _normalize_metrics(metrics)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE public.import_runs
            SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('qa_metrics', %s::jsonb)
            WHERE id = %s
            """,
            (Jsonb(qa_payload), row["id"]),
        )
    conn.commit()
    return row["id"]


def _run_import_qa(
    batch_name: str,
    config: ImportQAConfig,
    *,
    env: SupabaseEnv | None = None,
    attach_metadata: bool = False,
) -> Dict[str, Any]:
    conn = _connect(env)
    try:
        metrics = _collect_metrics(conn, config, batch_name)
        metrics["import_kind"] = config.import_kind
        metrics["cohort_source"] = config.changed_by
        if attach_metadata:
            run_id = _attach_metrics(conn, config, batch_name, metrics)
            if run_id:
                metrics["import_run_id"] = run_id
        else:
            conn.rollback()
        return metrics
    finally:
        conn.close()


def _print_summary(metrics: Dict[str, Any]) -> None:
    batch = metrics["batch_name"]
    kind = metrics.get("import_kind", "unknown")
    plaintiffs = metrics["plaintiff_counts"]
    judgments = metrics["judgment_counts"]
    tasks = metrics["task_counts"]
    typer.echo(f"[import-qa] Batch '{batch}' ({kind})")
    typer.echo(
        "  Plaintiffs: {total} | missing phone {miss_phone} ({miss_phone_pct:.1f}%) | "
        "missing email {miss_email} ({miss_email_pct:.1f}%)".format(
            total=plaintiffs["total"],
            miss_phone=plaintiffs["missing_phone"],
            miss_phone_pct=plaintiffs["missing_phone_pct"],
            miss_email=plaintiffs["missing_email"],
            miss_email_pct=plaintiffs["missing_email_pct"],
        )
    )
    typer.echo(
        "  Missing both contact fields: {missing_both} ({missing_both_pct:.1f}%)".format(
            missing_both=plaintiffs["missing_both"],
            missing_both_pct=plaintiffs["missing_both_pct"],
        )
    )
    typer.echo(
        "  Judgments: {total} | non-positive {bad} ({pct:.1f}%)".format(
            total=judgments["total"],
            bad=judgments["non_positive"],
            pct=judgments["non_positive_pct"],
        )
    )
    typer.echo(
        "  Tasks: no tasks {none} ({none_pct:.1f}%), multiple open call tasks {multi} ({multi_pct:.1f}%)".format(
            none=tasks["without_tasks"],
            none_pct=tasks["without_tasks_pct"],
            multi=tasks["multi_open_calls"],
            multi_pct=tasks["multi_open_calls_pct"],
        )
    )
    if metrics["duplicate_groups"]:
        typer.echo("  Possible duplicates detected:")
        for dup in metrics["duplicate_groups"][:5]:
            typer.echo(
                "    - {name} | amount ${amount:,.2f} | records {count}".format(
                    name=(dup.get("plaintiff_name") or ""),
                    amount=dup.get("judgment_amount") or 0,
                    count=dup.get("count") or 0,
                )
            )
    else:
        typer.echo("  No duplicate plaintiff+amount combinations detected.")


def check_simplicity_batch(
    batch_name: str,
    *,
    env: SupabaseEnv | None = None,
    attach_metadata: bool = False,
) -> Dict[str, Any]:
    return _run_import_qa(
        batch_name, SIMPLICITY_CONFIG, env=env, attach_metadata=attach_metadata
    )


def check_jbi_900_batch(
    batch_name: str,
    *,
    env: SupabaseEnv | None = None,
    attach_metadata: bool = False,
) -> Dict[str, Any]:
    return _run_import_qa(
        batch_name, JBI_CONFIG, env=env, attach_metadata=attach_metadata
    )


def _emit(metrics: Dict[str, Any], json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(_normalize_metrics(metrics), indent=2))
    else:
        _print_summary(metrics)


@app.command("simplicity")
def cli_simplicity(
    batch_name: str = typer.Argument(
        ..., help="Batch label recorded in import_runs metadata"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of text summary"
    ),
    attach: bool = typer.Option(
        False, "--attach", help="Persist QA metrics back to import_runs.metadata"
    ),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
) -> None:
    metrics = check_simplicity_batch(batch_name, env=env, attach_metadata=attach)
    _emit(metrics, json_output)


@app.command("jbi900")
def cli_jbi(
    batch_name: str = typer.Argument(
        ..., help="Batch label recorded in import_runs metadata"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of text summary"
    ),
    attach: bool = typer.Option(
        False, "--attach", help="Persist QA metrics back to import_runs.metadata"
    ),
    env: SupabaseEnv | None = typer.Option(
        None, "--env", help="Override SUPABASE_MODE"
    ),
) -> None:
    metrics = check_jbi_900_batch(batch_name, env=env, attach_metadata=attach)
    _emit(metrics, json_output)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    app()
