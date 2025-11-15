import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ["SUPABASE_PROJECT_REF"]
    password = os.environ["SUPABASE_DB_PASSWORD"]
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _ensure_collectability_view(db_url: str) -> None:
    """Ensure the snapshot view exists for environments that have not run the migration."""

    migration_path = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0057_collectability_snapshot.sql"
    up_sql_text = migration_path.read_text(encoding="utf-8")
    up_sql_section = up_sql_text.split("-- migrate:down", 1)[0]
    if "-- migrate:up" in up_sql_section:
        up_sql_section = up_sql_section.split("-- migrate:up", 1)[1]
    up_sql = up_sql_section.strip()
    if not up_sql:
        raise AssertionError("Collectability snapshot migration missing migrate:up SQL")

    with psycopg.connect(db_url, autocommit=True) as ensure_conn:
        with ensure_conn.cursor() as cur:
            cur.execute(up_sql)  # type: ignore[arg-type]


def test_collectability_snapshot_view_returns_latest_enrichment() -> None:
    db_url = _resolve_db_url()
    _ensure_collectability_view(db_url)
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

    with psycopg.connect(db_url, autocommit=False) as conn:
        inserted = {}
        base_now = datetime.now(timezone.utc).replace(microsecond=0)

        with conn.cursor() as cur:
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

        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
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
            rows = cur.fetchall()

        conn.rollback()

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
