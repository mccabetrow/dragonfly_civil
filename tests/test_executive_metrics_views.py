from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

UTC = timezone.utc


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit

    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"

    pytest.skip(
        "Supabase database credentials not configured for executive metrics tests"
    )
    return ""


@pytest.fixture(scope="module")
def db_url() -> str:
    return _resolve_db_url()


def _connect(db_url: str) -> psycopg.Connection:
    return psycopg.connect(db_url)


def _future_timestamp(days_offset: int) -> datetime:
    base = datetime(2090, 1, 8, 14, 0, tzinfo=UTC)
    return base + timedelta(days=days_offset)


@pytest.mark.integration
def test_metrics_intake_daily_rolls_counts(db_url: str) -> None:
    conn = _connect(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            activity_ts = _future_timestamp(0)
            source_system = f"exec_src_{uuid.uuid4().hex[:8]}"

            cur.execute(
                """
                insert into public.import_runs (import_kind, source_system, status, started_at)
                values (%s, %s, %s, %s)
                """,
                ("pytest_demo", source_system, "success", activity_ts),
            )

            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status, source_system, created_at, updated_at)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    plaintiff_id,
                    "Executive Metrics Plaintiff",
                    "new",
                    source_system,
                    activity_ts,
                    activity_ts,
                ),
            )

            cur.execute(
                """
                insert into public.judgments (
                    case_number,
                    plaintiff_id,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    created_at,
                    enforcement_stage,
                    enforcement_stage_updated_at
                )
                values (%s, %s, %s, %s, %s, current_date, %s, 'exec_metrics', %s)
                """,
                (
                    f"EXEC-MET-{uuid.uuid4().hex[:8].upper()}",
                    plaintiff_id,
                    "Executive Metrics Plaintiff",
                    "Defendant",
                    Decimal("12500"),
                    activity_ts,
                    activity_ts,
                ),
            )

            cur.execute(
                """
                select import_count, plaintiff_count, judgment_count, total_judgment_amount
                from public.v_metrics_intake_daily
                where activity_date = %s and source_system = %s
                """,
                (activity_ts.date(), source_system),
            )
            row = cur.fetchone()

        assert row is not None
        row_map = dict(row)
        assert row_map["import_count"] >= 1
        assert row_map["plaintiff_count"] >= 1
        assert row_map["judgment_count"] >= 1
        assert Decimal(row_map["total_judgment_amount"]) >= Decimal("12500")
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_metrics_pipeline_groups_stage_exposure(db_url: str) -> None:
    conn = _connect(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status, source_system)
                values (%s, %s, 'new', %s)
                """,
                (plaintiff_id, "Pipeline Metrics Plaintiff", "exec_pipeline"),
            )

            stage = "exec_test_stage"
            amounts = [Decimal("4000"), Decimal("7000")]
            latest_update = None
            for index, amount in enumerate(amounts):
                updated_at = datetime.now(tz=UTC) + timedelta(minutes=index)
                latest_update = updated_at
                cur.execute(
                    """
                    insert into public.judgments (
                        case_number,
                        plaintiff_id,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date,
                        enforcement_stage,
                        enforcement_stage_updated_at
                    )
                    values (%s, %s, %s, %s, %s, current_date, %s, %s)
                    """,
                    (
                        f"EXEC-PIPE-{uuid.uuid4().hex[:8].upper()}",
                        plaintiff_id,
                        "Pipeline Metrics Plaintiff",
                        f"Defendant {index}",
                        amount,
                        stage,
                        updated_at,
                    ),
                )

            cur.execute(
                """
                select judgment_count, total_judgment_amount, average_judgment_amount, latest_stage_update
                from public.v_metrics_pipeline
                where enforcement_stage = %s and collectability_tier = 'unscored'
                """,
                (stage,),
            )
            row = cur.fetchone()

        assert row is not None
        row_map = dict(row)
        assert row_map["judgment_count"] == len(amounts)
        assert Decimal(row_map["total_judgment_amount"]) == sum(amounts)
        expected_average = sum(amounts) / len(amounts)
        assert Decimal(row_map["average_judgment_amount"]) == expected_average
        assert isinstance(row_map["latest_stage_update"], datetime)
        assert row_map["latest_stage_update"] == latest_update
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_metrics_enforcement_tracks_open_and_closed_cases(db_url: str) -> None:
    conn = _connect(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "select active_case_count, active_judgment_amount from public.v_metrics_enforcement limit 1"
            )
            baseline_row = cur.fetchone()
            if baseline_row is None:
                baseline_count = 0
                baseline_amount = Decimal("0")
            else:
                baseline_map = dict(baseline_row)
                baseline_count = baseline_map["active_case_count"] or 0
                baseline_amount = Decimal(baseline_map["active_judgment_amount"] or 0)

            def _insert_judgment(amount: Decimal) -> int:
                case_number = f"EXEC-ENF-{uuid.uuid4().hex[:8].upper()}"
                cur.execute(
                    """
                    insert into public.judgments (
                        case_number,
                        plaintiff_name,
                        defendant_name,
                        judgment_amount,
                        entry_date
                    )
                    values (%s, %s, %s, %s, current_date)
                    returning id
                    """,
                    (
                        case_number,
                        "Enforcement Metrics Plaintiff",
                        "Enforcement Defendant",
                        amount,
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                row_map = dict(row)
                return row_map["id"]

            open_judgment_id = _insert_judgment(Decimal("5000"))
            closed_judgment_id = _insert_judgment(Decimal("8000"))

            open_opened_at = _future_timestamp(7)
            closed_opened_at = _future_timestamp(14)
            closed_at = _future_timestamp(21)

            cur.execute(
                """
                insert into public.enforcement_cases (
                    judgment_id,
                    case_number,
                    opened_at,
                    current_stage,
                    status,
                    metadata
                )
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    open_judgment_id,
                    f"ENF-OPEN-{uuid.uuid4().hex[:6].upper()}",
                    open_opened_at,
                    "exec_stage",
                    "open",
                    Jsonb({}),
                ),
            )
            open_case_row = cur.fetchone()
            assert open_case_row is not None
            open_case_map = dict(open_case_row)
            open_case_id = open_case_map["id"]

            cur.execute(
                """
                insert into public.enforcement_cases (
                    judgment_id,
                    case_number,
                    opened_at,
                    current_stage,
                    status,
                    metadata
                )
                values (%s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    closed_judgment_id,
                    f"ENF-CLOSED-{uuid.uuid4().hex[:6].upper()}",
                    closed_opened_at,
                    "exec_stage",
                    "closed",
                    Jsonb({"closed_at": closed_at.isoformat()}),
                ),
            )
            closed_case_row = cur.fetchone()
            assert closed_case_row is not None
            closed_case_map = dict(closed_case_row)
            closed_case_id = closed_case_map["id"]

            cur.execute(
                """
                insert into public.enforcement_events (case_id, event_type, event_date)
                values (%s, %s, %s)
                """,
                (closed_case_id, "case_closed", closed_at),
            )

            cur.execute(
                """
                select bucket_week, cases_opened, opened_judgment_amount, cases_closed, closed_judgment_amount, active_case_count, active_judgment_amount
                from public.v_metrics_enforcement
                where bucket_week in (%s, %s, %s)
                """,
                (
                    open_opened_at.date() - timedelta(days=open_opened_at.weekday()),
                    closed_opened_at.date()
                    - timedelta(days=closed_opened_at.weekday()),
                    closed_at.date() - timedelta(days=closed_at.weekday()),
                ),
            )
            raw_rows = cur.fetchall()

        rows = [dict(row) for row in raw_rows]
        buckets = {row["bucket_week"]: row for row in rows}
        open_week = open_opened_at.date() - timedelta(days=open_opened_at.weekday())
        closed_week = closed_opened_at.date() - timedelta(
            days=closed_opened_at.weekday()
        )
        closing_week = closed_at.date() - timedelta(days=closed_at.weekday())

        assert open_week in buckets
        assert buckets[open_week]["cases_opened"] >= 1
        assert Decimal(buckets[open_week]["opened_judgment_amount"]) >= Decimal("5000")

        assert closed_week in buckets
        assert buckets[closed_week]["cases_opened"] >= 1
        assert Decimal(buckets[closed_week]["opened_judgment_amount"]) >= Decimal(
            "8000"
        )

        assert closing_week in buckets
        assert buckets[closing_week]["cases_closed"] >= 1
        assert Decimal(buckets[closing_week]["closed_judgment_amount"]) >= Decimal(
            "8000"
        )

        active_snapshot = next(iter(buckets.values()))
        assert active_snapshot["active_case_count"] == baseline_count + 1
        assert Decimal(
            active_snapshot["active_judgment_amount"]
        ) == baseline_amount + Decimal("5000")
    finally:
        conn.rollback()
        conn.close()
