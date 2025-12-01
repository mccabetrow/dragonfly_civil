"""Validate that critical Supabase relations remain intact before deployments."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import DefaultDict, Dict, List, Sequence

import psycopg

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env
from tools.schema_guard import (
    SCHEMA_FREEZE_PATH,
    SchemaDiff,
    catalog_to_snapshot,
    capture_catalog,
    compute_snapshot_hash,
    diff_connection_against_freeze,
    format_drift,
    load_schema_freeze,
)


@dataclass(frozen=True)
class RelationExpectation:
    """Represents a database object required by the platform."""

    schema: str
    name: str
    columns: Sequence[str]
    category: str
    description: str | None = None
    object_type: str = "relation"  # relation | function
    function_arg_types: Sequence[str] | None = None


CATEGORY_ORDER: Sequence[str] = (
    "table",
    "queue",
    "metric_view",
    "dashboard_view",
    "rpc",
)

CATEGORY_LABELS: Dict[str, str] = {
    "table": "tables",
    "queue": "queues",
    "metric_view": "metrics",
    "dashboard_view": "dashboards",
    "rpc": "rpcs",
}

RELATION_EXPECTATIONS: Sequence[RelationExpectation] = (
    # Core tables behind intake + enforcement
    RelationExpectation(
        "public",
        "judgments",
        (
            "id",
            "case_number",
            "plaintiff_name",
            "judgment_amount",
            "enforcement_stage",
            "created_at",
        ),
        "table",
        "Primary registry of enforceable matters",
    ),
    RelationExpectation(
        "public",
        "enforcement_cases",
        ("id", "judgment_id", "case_number", "current_stage", "status"),
        "table",
        "Enforcement pipeline tracker",
    ),
    RelationExpectation(
        "public",
        "enforcement_timeline",
        ("id", "case_id", "judgment_id", "title", "occurred_at"),
        "table",
        "Chronological enforcement events",
    ),
    RelationExpectation(
        "public",
        "plaintiffs",
        ("id", "name", "status", "tier", "created_at"),
        "table",
        "Plaintiff CRM record",
    ),
    RelationExpectation(
        "public",
        "plaintiff_contacts",
        ("id", "plaintiff_id", "kind", "value"),
        "table",
        "Contact methods used by outreach + call queues",
    ),
    RelationExpectation(
        "public",
        "plaintiff_tasks",
        ("id", "plaintiff_id", "kind", "status", "due_at"),
        "table",
        "Task assignments surfaced in the dashboard",
    ),
    RelationExpectation(
        "public",
        "plaintiff_call_attempts",
        ("id", "plaintiff_id", "task_id", "call_outcome", "called_at"),
        "table",
        "Operator call logging",
    ),
    RelationExpectation(
        "public",
        "plaintiff_status_history",
        ("id", "plaintiff_id", "status", "recorded_at"),
        "table",
        "Status transitions consumed by intake tools",
    ),
    RelationExpectation(
        "public",
        "import_runs",
        ("id", "source_system", "status", "created_at"),
        "table",
        "ETL ingestion bookkeeping",
    ),
    RelationExpectation(
        "public",
        "ops_metadata",
        ("id", "key", "value", "created_at"),
        "table",
        "Ops key/value store for snapshots and config",
    ),
    RelationExpectation(
        "public",
        "ops_triage_alerts",
        ("id", "alert_kind", "severity", "payload", "status", "acked_at", "created_at"),
        "table",
        "Alerting queue for ops triage workflows",
    ),
    # Queue tables (pgmq)
    RelationExpectation(
        "pgmq", "q_enrich", ("msg_id", "message"), "queue", "Enrichment worker queue"
    ),
    RelationExpectation(
        "pgmq", "q_outreach", ("msg_id", "message"), "queue", "Outreach worker queue"
    ),
    RelationExpectation(
        "pgmq", "q_enforce", ("msg_id", "message"), "queue", "Enforcement worker queue"
    ),
    RelationExpectation(
        "pgmq",
        "q_case_copilot",
        ("msg_id", "message"),
        "queue",
        "Case Copilot worker queue",
    ),
    RelationExpectation(
        "public",
        "dequeue_job",
        (),
        "rpc",
        "Worker dequeue RPC",
        object_type="function",
        function_arg_types=("kind text",),
    ),
    RelationExpectation(
        "public",
        "pgmq_delete",
        (),
        "rpc",
        "Queue acknowledgement RPC",
        object_type="function",
        function_arg_types=("queue_name text", "msg_id bigint"),
    ),
    RelationExpectation(
        "public",
        "queue_job",
        (),
        "rpc",
        "Queue submission RPC",
        object_type="function",
        function_arg_types=("payload jsonb",),
    ),
    # Executive metric views
    RelationExpectation(
        "public",
        "v_metrics_intake_daily",
        ("activity_date", "source_system", "import_count", "plaintiff_count"),
        "metric_view",
        "Daily intake rollups",
    ),
    RelationExpectation(
        "public",
        "v_case_copilot_latest",
        (
            "case_id",
            "case_number",
            "judgment_id",
            "current_stage",
            "case_status",
            "assigned_to",
            "model",
            "generated_at",
            "summary",
            "recommended_actions",
            "enforcement_suggestions",
            "draft_documents",
            "risk_value",
            "risk_label",
            "risk_drivers",
            "timeline_analysis",
            "contact_strategy",
            "invocation_status",
            "error_message",
            "env",
            "duration_ms",
            "log_id",
        ),
        "dashboard_view",
        "Latest Case Copilot output",
    ),
    RelationExpectation(
        "public",
        "v_metrics_pipeline",
        (
            "enforcement_stage",
            "collectability_tier",
            "judgment_count",
            "total_judgment_amount",
        ),
        "metric_view",
        "Pipeline + tiering rollups",
    ),
    RelationExpectation(
        "public",
        "v_metrics_enforcement",
        ("bucket_week", "cases_opened", "cases_closed", "active_case_count"),
        "metric_view",
        "Enforcement trend lines",
    ),
    RelationExpectation(
        "public",
        "v_ops_daily_summary",
        (
            "summary_date",
            "new_plaintiffs",
            "plaintiffs_contacted",
            "calls_made",
            "agreements_sent",
            "agreements_signed",
        ),
        "metric_view",
        "Single-row daily ops rollup",
    ),
    # Dashboard-critical views
    RelationExpectation(
        "public",
        "v_enforcement_overview",
        (
            "enforcement_stage",
            "collectability_tier",
            "case_count",
            "total_judgment_amount",
        ),
        "dashboard_view",
        "Stage x tier rollup",
    ),
    RelationExpectation(
        "public",
        "v_enforcement_timeline",
        ("case_id", "source_id", "item_kind", "occurred_at", "title"),
        "dashboard_view",
        "Unified timeline for enforcement activity",
    ),
    RelationExpectation(
        "public",
        "v_enforcement_recent",
        (
            "judgment_id",
            "case_number",
            "plaintiff_name",
            "enforcement_stage",
            "enforcement_stage_updated_at",
            "collectability_tier",
        ),
        "dashboard_view",
        "Recent enforcement transitions",
    ),
    RelationExpectation(
        "public",
        "v_plaintiffs_overview",
        (
            "plaintiff_id",
            "plaintiff_name",
            "status",
            "total_judgment_amount",
            "case_count",
        ),
        "dashboard_view",
        "Aggregate plaintiff exposure",
    ),
    RelationExpectation(
        "public",
        "v_plaintiff_call_queue",
        ("plaintiff_id", "plaintiff_name", "firm_name", "status", "last_contacted_at"),
        "dashboard_view",
        "Call queue surface",
    ),
    RelationExpectation(
        "public",
        "v_priority_pipeline",
        (
            "plaintiff_name",
            "judgment_id",
            "collectability_tier",
            "priority_level",
            "judgment_amount",
            "stage",
            "plaintiff_status",
            "tier_rank",
        ),
        "dashboard_view",
        "Ranked pipeline view powering Ops dashboard",
    ),
    RelationExpectation(
        "public",
        "v_pipeline_snapshot",
        (
            "snapshot_at",
            "simplicity_plaintiff_count",
            "lifecycle_counts",
            "tier_totals",
            "jbi_summary",
        ),
        "dashboard_view",
        "Pipeline snapshot summary",
    ),
    RelationExpectation(
        "public",
        "v_plaintiff_open_tasks",
        ("task_id", "plaintiff_id", "plaintiff_name", "kind", "status", "due_at"),
        "dashboard_view",
        "Task triage view",
    ),
    RelationExpectation(
        "public",
        "v_judgment_pipeline",
        ("plaintiff_id", "judgment_id", "enforcement_stage"),
        "dashboard_view",
        "Stage-level drilldowns feeding the workbench",
    ),
    RelationExpectation(
        "public",
        "v_collectability_snapshot",
        (
            "case_id",
            "case_number",
            "collectability_tier",
            "last_enriched_at",
            "last_enrichment_status",
        ),
        "dashboard_view",
        "Collectability joins powering ops + exec surfaces",
    ),
    RelationExpectation(
        "public",
        "request_case_copilot",
        (),
        "rpc",
        "Case Copilot queue RPC",
        object_type="function",
        function_arg_types=("p_case_id uuid", "requested_by text"),
    ),
    RelationExpectation(
        "public",
        "set_enforcement_stage",
        (),
        "rpc",
        "Judgment enforcement stage update RPC",
        object_type="function",
        function_arg_types=(
            "_judgment_id bigint",
            "_new_stage text",
            "_note text",
            "_changed_by text",
        ),
    ),
    RelationExpectation(
        "public",
        "log_call_outcome",
        (),
        "rpc",
        "Call outcome logging RPC",
        object_type="function",
        function_arg_types=(
            "p_plaintiff_id uuid",
            "p_outcome text",
            "p_interest_level text",
            "p_notes text",
            "p_next_follow_up_at timestamp with time zone",
            "p_assignee text",
        ),
    ),
    RelationExpectation(
        "public",
        "log_event",
        (),
        "rpc",
        "Generic event logging RPC for n8n",
        object_type="function",
        function_arg_types=(
            "p_judgment_id bigint",
            "p_title text",
            "p_details text",
            "p_metadata jsonb",
            "p_source text",
        ),
    ),
    RelationExpectation(
        "public",
        "log_enforcement_event",
        (),
        "rpc",
        "Enforcement-branded event logging RPC",
        object_type="function",
        function_arg_types=(
            "p_case_id uuid",
            "p_title text",
            "p_details text",
            "p_stage_key text",
            "p_status text",
            "p_metadata jsonb",
            "p_source text",
        ),
    ),
    RelationExpectation(
        "public",
        "pgmq_metrics",
        (),
        "rpc",
        "Read-only PGMQ queue health metrics",
        object_type="function",
        function_arg_types=(),
    ),
    RelationExpectation(
        "public",
        "ops_triage_alerts_fetch",
        (),
        "rpc",
        "Fetch triage alerts for n8n",
        object_type="function",
        function_arg_types=("p_status text", "p_limit integer"),
    ),
    RelationExpectation(
        "public",
        "ops_triage_alerts_ack",
        (),
        "rpc",
        "Acknowledge or resolve triage alert",
        object_type="function",
        function_arg_types=("p_alert_id uuid", "p_status text"),
    ),
)


def freeze_schema(env: str, output_path: Path = SCHEMA_FREEZE_PATH) -> Path:
    db_url = get_supabase_db_url(env)
    with psycopg.connect(db_url, connect_timeout=5) as conn:
        catalog = capture_catalog(conn)

    snapshot = catalog_to_snapshot(catalog)
    digest = compute_snapshot_hash(snapshot)
    payload = {
        "env": env,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "hash": digest,
        **snapshot,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2))
    print(
        f"[INFO] Schema freeze written to {output_path} (env={env}, hash={digest[:12]}...)"
    )
    return output_path


def _load_schema_freeze() -> tuple[dict[str, object] | None, str | None, str | None]:
    try:
        freeze_data = load_schema_freeze(SCHEMA_FREEZE_PATH)
    except FileNotFoundError:
        return None, None, f"schema freeze missing at {SCHEMA_FREEZE_PATH}"
    except ValueError as exc:
        return None, None, f"schema freeze invalid: {exc}"

    hash_value = freeze_data.get("hash")
    hash_str = str(hash_value) if isinstance(hash_value, str) else None
    return freeze_data, hash_str, None


def _format_hash(hash_value: str | None) -> str:
    if not hash_value:
        return "n/a"
    return f"{hash_value[:12]}..."


def _report_schema_freeze_result(
    drift: SchemaDiff, *, freeze_hash: str | None
) -> List[str]:
    if drift.is_clean():
        print(f"[OK] schema freeze: matches snapshot ({_format_hash(freeze_hash)})")
        return []

    issues = format_drift(drift)
    for message in issues:
        print(f"[FAIL] schema freeze: {message}")
    print(f"[FAIL] schema freeze: detected {len(issues)} issue(s) vs snapshot")
    return issues


def _fetch_columns(conn: psycopg.Connection, schema: str, name: str) -> set[str] | None:
    """Return a normalized set of columns for a relation or None if it is missing."""

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (schema, name),
        )
        rows = cur.fetchall()

    if not rows:
        return None
    return {str(row[0]).strip().lower() for row in rows if row and row[0]}


def _fetch_function_signatures(
    conn: psycopg.Connection, schema: str, name: str
) -> list[tuple[str, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pg_catalog.pg_get_function_identity_arguments(p.oid)
            FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = %s AND p.proname = %s
            """,
            (schema, name),
        )
        rows = cur.fetchall()

    signatures: list[tuple[str, ...]] = []
    for row in rows:
        raw_args = (row[0] or "").strip()
        if not raw_args:
            signatures.append(())
            continue
        parts = [part.strip() for part in raw_args.split(",") if part.strip()]
        signatures.append(tuple(parts))
    return signatures


def _format_function_signature(schema: str, name: str, args: Sequence[str]) -> str:
    args_repr = ", ".join(args)
    return f"{schema}.{name}({args_repr})"


def _format_relation(expectation: RelationExpectation) -> str:
    return f"{expectation.schema}.{expectation.name}"


def _check_expectation(
    conn: psycopg.Connection, expectation: RelationExpectation
) -> str | None:
    if expectation.object_type == "function":
        signatures = _fetch_function_signatures(
            conn, expectation.schema, expectation.name
        )
        if not signatures:
            return f"{_format_function_signature(expectation.schema, expectation.name, expectation.function_arg_types or ())} is missing"
        if expectation.function_arg_types is None:
            return None
        normalized_expected = tuple(expectation.function_arg_types)
        if normalized_expected not in signatures:
            observed = "; ".join(
                _format_function_signature(expectation.schema, expectation.name, sig)
                for sig in signatures
            )
            return (
                f"{_format_function_signature(expectation.schema, expectation.name, normalized_expected)} signature mismatch; "
                f"observed: {observed or 'n/a'}"
            )
        return None

    columns = _fetch_columns(conn, expectation.schema, expectation.name)
    if columns is None:
        return f"{_format_relation(expectation)} is missing"

    missing = [col for col in expectation.columns if col.lower() not in columns]
    if missing:
        return f"{_format_relation(expectation)} missing columns: {', '.join(missing)}"
    return None


def _group_expectations(
    expectations: Sequence[RelationExpectation],
) -> DefaultDict[str, List[RelationExpectation]]:
    grouped: DefaultDict[str, List[RelationExpectation]] = defaultdict(list)
    for expectation in expectations:
        grouped[expectation.category].append(expectation)
    return grouped


def _category_iter(grouped: DefaultDict[str, List[RelationExpectation]]):
    seen = set()
    for category in CATEGORY_ORDER:
        if category in grouped:
            seen.add(category)
            yield category, grouped[category]
    for category, relations in grouped.items():
        if category not in seen:
            yield category, relations


def run_checks(env: str | None = None) -> int:
    target_env = env or get_supabase_env()
    print(f"[INFO] Running schema consistency checks (env={target_env})")

    try:
        db_url = get_supabase_db_url(target_env)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return 1

    freeze_data, freeze_hash, freeze_error = _load_schema_freeze()
    host, dbname, user = describe_db_url(db_url)
    print(f"[INFO] Connecting to {host}/{dbname} as {user}")

    grouped = _group_expectations(RELATION_EXPECTATIONS)
    errors: List[str] = []
    total_relations = 0

    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            for category, expectations in _category_iter(grouped):
                total_relations += len(expectations)
                category_errors: List[str] = []
                for expectation in expectations:
                    issue = _check_expectation(conn, expectation)
                    if issue:
                        category_errors.append(issue)

                label = CATEGORY_LABELS.get(category, category)
                if category_errors:
                    for message in category_errors:
                        print(f"[FAIL] {label}: {message}")
                    errors.extend(category_errors)
                else:
                    print(f"[OK] {label}: validated {len(expectations)} relation(s)")

            if freeze_data is None:
                if freeze_error:
                    errors.append(freeze_error)
                    print(f"[FAIL] schema freeze: {freeze_error}")
            else:
                try:
                    drift = diff_connection_against_freeze(
                        conn,
                        freeze_data=freeze_data,
                        freeze_path=SCHEMA_FREEZE_PATH,
                    )
                except psycopg.Error as exc:
                    message = f"schema freeze diff failed: {exc}"
                    print(f"[FAIL] {message}")
                    errors.append(message)
                else:
                    errors.extend(
                        _report_schema_freeze_result(
                            drift,
                            freeze_hash=freeze_hash,
                        )
                    )
    except psycopg.Error as exc:
        print(f"[FAIL] database: unable to connect or query - {exc}")
        return 1

    if errors:
        print(f"[FAIL] Schema consistency check failed ({len(errors)} issue(s))")
        return 1

    print(f"[SUCCESS] Schema consistency OK ({total_relations} relation(s) verified)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate that critical Supabase views and tables match expectations."
    )
    parser.add_argument(
        "--env",
        choices=("dev", "prod"),
        default=None,
        help="Override SUPABASE_MODE (defaults to current environment)",
    )
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="Capture the current schema signature to state/schema_freeze.json after successful checks.",
    )
    args = parser.parse_args(argv)

    try:
        result = run_checks(args.env)
        if result == 0 and args.freeze:
            target_env = args.env or get_supabase_env()
            freeze_schema(target_env)
        return result
    except RuntimeError as exc:  # Defensive guard for missing env vars
        print(f"[FAIL] {exc}")
        return 1


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
