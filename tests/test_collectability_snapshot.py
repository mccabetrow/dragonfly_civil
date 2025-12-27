"""
Test suite for judgments.v_collectability_snapshot view.

Zero Trust Dual-Connection Pattern:
  - admin_db: Superuser connection (from conftest.py) for DDL, direct INSERTs to tables
             without SECURITY DEFINER wrappers
  - Savepoints: Used for rollback to avoid polluting database

Note: Uses public.insert_case RPC (SECURITY DEFINER) for case insertion,
      but direct INSERT to judgments.enrichment_runs requires admin access.

NOTE: Marked as integration because insert_case(jsonb) RPC not yet deployed to prod.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Json

# Mark entire module as integration - requires insert_case(jsonb) RPC
pytestmark = pytest.mark.integration


def _ensure_collectability_view(cur: psycopg.Cursor) -> None:
    """Ensure the snapshot view exists for environments that have not run the migration."""

    up_sql = """
create or replace view judgments.v_collectability_snapshot as
with latest_enrichment as (
    select
        er.case_id,
        er.created_at,
        er.status,
        row_number() over (
            partition by er.case_id
            order by er.created_at desc, er.id desc
        ) as row_num
    from judgments.enrichment_runs er
)
select
    c.case_id,
    c.case_number,
    c.amount_awarded as judgment_amount,
    c.judgment_date,
    case
        when c.judgment_date is not null then (current_date - c.judgment_date)
    end as age_days,
    le.created_at as last_enriched_at,
    le.status as last_enrichment_status,
    case
        when
            coalesce(c.amount_awarded, 0) >= 3000
            and c.judgment_date is not null
            and (current_date - c.judgment_date) <= 365 then 'A'
        when
            (
                coalesce(c.amount_awarded, 0) between 1000 and 2999
            )
            or (
                c.judgment_date is not null
                and (current_date - c.judgment_date) between 366 and 1095
            ) then 'B'
        else 'C'
    end as collectability_tier
from judgments.cases c
    left join latest_enrichment le
        on c.case_id = le.case_id
        and le.row_num = 1;
grant select on judgments.v_collectability_snapshot to service_role;
""".strip()

    cur.execute(up_sql)  # type: ignore[arg-type]


def test_collectability_snapshot_view_returns_latest_enrichment(
    admin_db_autocommit: psycopg.Connection,
    admin_db: psycopg.Connection,
) -> None:
    """
    Test that v_collectability_snapshot returns correct tier and latest enrichment.

    Uses admin_db_autocommit for DDL (view creation) and admin_db for data seeding.
    """
    # Ensure view exists (DDL requires autocommit)
    with admin_db_autocommit.cursor() as ddl_cur:
        _ensure_collectability_view(ddl_cur)

    # Exercise all tier branches: amount-driven A/B, age-driven B, and default C.
    case_specs = [
        {
            "age_days": 100,
            "amount": Decimal("5000"),
            "expected_tier": "A",
            "runs": [
                {"status": "seed", "minutes_ago": 180},
                {"status": "success", "minutes_ago": 10},
            ],
        },
        {
            "age_days": 45,
            "amount": Decimal("1500"),
            "expected_tier": "B",
            "runs": [
                {"status": "queued", "minutes_ago": 90},
                {"status": "in_progress", "minutes_ago": 5},
            ],
        },
        {
            "age_days": 500,
            "amount": Decimal("400"),
            "expected_tier": "B",
            "runs": [
                {"status": "seed", "minutes_ago": 300},
                {"status": "researching", "minutes_ago": 15},
            ],
        },
        {
            "age_days": 1400,
            "amount": Decimal("400"),
            "expected_tier": "C",
            "runs": [
                {"status": "seed", "minutes_ago": 400},
                {"status": "stale", "minutes_ago": 20},
            ],
        },
    ]

    inserted = {}
    base_now = datetime.now(timezone.utc).replace(microsecond=0)

    cur = admin_db.cursor()
    cur.execute("SAVEPOINT test_collectability")

    try:
        cur.execute("select current_date")
        current_date_row = cur.fetchone()
        assert current_date_row is not None
        (current_date,) = current_date_row

        for spec_index, spec in enumerate(case_specs):
            case_number = f"COL-{uuid.uuid4().hex[:8].upper()}"
            docket_number = f"DCK-{uuid.uuid4().hex[:8].upper()}"
            judgment_date = current_date - timedelta(days=spec["age_days"])

            insert_payload = {
                "case_number": case_number,
                "docket_number": docket_number,
                "source": "pytest",
                "title": "Collectability Snapshot",
                "court": "Kings County Civil Court",
                "filing_date": current_date.isoformat(),
                "judgment_date": judgment_date.isoformat(),
                "amount_awarded": str(spec["amount"]),
            }
            cur.execute("select public.insert_case(%s::jsonb)", (Json(insert_payload),))
            case_row = cur.fetchone()
            assert case_row is not None
            (case_id,) = case_row

            latest_status = None
            latest_created_at = None
            for run in spec["runs"]:
                created_at = base_now - timedelta(minutes=run["minutes_ago"], seconds=spec_index)
                cur.execute(
                    """
                    insert into judgments.enrichment_runs (case_id, status, summary, raw, created_at)
                    values (%s, %s, %s, %s, %s)
                    """,
                    (
                        case_id,
                        run["status"],
                        f"test-{run['status']}",
                        Json({"status": run["status"]}),
                        created_at,
                    ),
                )
                if latest_created_at is None or created_at > latest_created_at:
                    latest_created_at = created_at
                    latest_status = run["status"]

            inserted[case_id] = {
                "case_number": case_number,
                "judgment_date": judgment_date,
                "amount": spec["amount"],
                "age_days": spec["age_days"],
                "expected_tier": spec["expected_tier"],
                "last_status": latest_status,
                "last_created_at": latest_created_at,
            }

        # Query the view
        with admin_db.cursor(row_factory=dict_row) as view_cur:
            view_cur.execute(
                """
                select
                    case_id,
                    case_number,
                    judgment_amount,
                    judgment_date,
                    age_days,
                    last_enriched_at,
                    last_enrichment_status,
                    collectability_tier
                from judgments.v_collectability_snapshot
                where case_id = any(%s)
                """,
                (list(inserted.keys()),),
            )
            rows = view_cur.fetchall()

        # Assertions
        assert len(rows) == len(inserted)
        outcomes = {row["case_id"]: row for row in rows}

        for case_id, expected in inserted.items():
            row = outcomes[case_id]
            assert row["case_number"] == expected["case_number"]
            assert row["judgment_amount"] == expected["amount"]
            assert row["judgment_date"] == expected["judgment_date"]
            assert row["age_days"] == expected["age_days"]
            assert row["collectability_tier"] == expected["expected_tier"]
            assert row["last_enrichment_status"] == expected["last_status"]
            assert row["last_enriched_at"] == expected["last_created_at"]

    finally:
        cur.execute("ROLLBACK TO SAVEPOINT test_collectability")
