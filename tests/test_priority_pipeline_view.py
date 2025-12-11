from __future__ import annotations

import os
import uuid
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.integration


def _resolve_db_url() -> str:
    direct = os.environ.get("SUPABASE_DB_URL")
    if direct:
        return direct

    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"

    pytest.skip("Supabase database credentials not configured for priority pipeline tests")
    return ""


@pytest.fixture(scope="module")
def db_url() -> str:
    return _resolve_db_url()


def _connect(db_url: str) -> psycopg.Connection:
    return psycopg.connect(db_url)


@pytest.mark.integration
def test_priority_pipeline_ranks_rows_by_tier_and_priority(db_url: str) -> None:
    conn = _connect(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status, source_system)
                values (%s, %s, %s, %s)
                """,
                (
                    plaintiff_id,
                    "Priority Pipeline Plaintiff",
                    "contacted",
                    "priority_test",
                ),
            )

            case_rows = [
                (f"PRIORITY-A1-{uuid.uuid4().hex[:6]}", "Kings", Decimal("6000")),
                (f"PRIORITY-A2-{uuid.uuid4().hex[:6]}", "Kings", Decimal("4500")),
                (
                    f"PRIORITY-B1-{uuid.uuid4().hex[:6]}",
                    "Queens",
                    Decimal("1500"),
                ),
            ]
            for case_number, county, amount in case_rows:
                cur.execute(
                    """
                    insert into judgments.cases (case_number, title, court_name, county, status, judgment_date, amount_awarded)
                    values (%s, %s, %s, %s, 'active', current_date, %s)
                    """,
                    (
                        case_number,
                        "Priority Pipeline Case",
                        "Priority Pipeline Court",
                        county,
                        amount,
                    ),
                )

            judgment_specs = [
                (case_rows[0][0], "urgent", Decimal("6000")),
                (case_rows[1][0], "high", Decimal("4500")),
                (case_rows[2][0], "normal", Decimal("1500")),
            ]
            judgment_ids: list[int] = []
            for case_number, priority_level, amount in judgment_specs:
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
                        enforcement_stage_updated_at,
                        priority_level,
                        priority_level_updated_at
                    )
                    values (%s, %s, %s, %s, %s, current_date, 'pre_enforcement', timezone('utc', now()), %s, timezone('utc', now()))
                    returning id
                    """,
                    (
                        case_number,
                        plaintiff_id,
                        "Priority Pipeline Plaintiff",
                        "Priority Defendant",
                        amount,
                        priority_level,
                    ),
                )
                result = cur.fetchone()
                assert result is not None
                judgment_ids.append(result["id"])

            cur.execute(
                """
                select judgment_id, collectability_tier, priority_level, tier_rank, stage, plaintiff_status
                from public.v_priority_pipeline
                where judgment_id = any(%s)
                """,
                (judgment_ids,),
            )
            rows = cur.fetchall()

        assert len(rows) == len(judgment_ids)
        row_by_id = {row["judgment_id"]: row for row in rows}

        urgent_row = row_by_id[judgment_ids[0]]
        assert urgent_row["collectability_tier"] == "A"
        assert urgent_row["priority_level"] == "urgent"
        assert urgent_row["plaintiff_status"] == "contacted"
        assert urgent_row["stage"] == "pre_enforcement"

        high_row = row_by_id[judgment_ids[1]]
        assert high_row["collectability_tier"] == "A"
        assert high_row["priority_level"] == "high"

        normal_row = row_by_id[judgment_ids[2]]
        assert normal_row["collectability_tier"] == "B"
        assert normal_row["priority_level"] == "normal"

        # Verify relative ranking: within tier A, urgent should rank higher than high
        assert urgent_row["tier_rank"] < high_row["tier_rank"], (
            f"Urgent row (tier_rank={urgent_row['tier_rank']}) should rank "
            f"higher than high row (tier_rank={high_row['tier_rank']}) within tier A"
        )

        # Verify tier B row has a valid positive tier_rank (absolute value depends on existing data)
        assert (
            normal_row["tier_rank"] >= 1
        ), f"Tier B row should have positive tier_rank, got {normal_row['tier_rank']}"
    finally:
        conn.rollback()
        conn.close()
