from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from etl.src.foil_utils import record_foil_response


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ["SUPABASE_PROJECT_REF"]
    password = os.environ["SUPABASE_DB_PASSWORD"]
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _ensure_foil_schema(db_url: str) -> None:
    migration_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    migration_files = [
        migration_dir / "0059_foil_responses.sql",
        migration_dir / "0060_foil_responses_agency.sql",
    ]

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            for migration_path in migration_files:
                up_sql_text = migration_path.read_text(encoding="utf-8")
                up_sql_section = up_sql_text.split("-- migrate:down", 1)[0]
                if "-- migrate:up" in up_sql_section:
                    up_sql_section = up_sql_section.split("-- migrate:up", 1)[1]
                up_sql = up_sql_section.strip()
                if not up_sql:
                    raise AssertionError(
                        f"Migration {migration_path.name} is missing migrate:up SQL"
                    )
                cur.execute(up_sql)  # type: ignore[arg-type]


def _extract_case_id(raw_value: Any) -> UUID:
    if isinstance(raw_value, UUID):
        return raw_value
    if isinstance(raw_value, str):
        return UUID(raw_value)
    if isinstance(raw_value, dict):
        for candidate_key in (
            "case_id",
            "insert_or_get_case_with_entities",
            "insert_case_with_entities",
        ):
            candidate = raw_value.get(candidate_key)
            if candidate:
                return _extract_case_id(candidate)
    if isinstance(raw_value, (list, tuple)) and raw_value:
        return _extract_case_id(raw_value[0])
    raise AssertionError(f"Unexpected RPC return payload: {raw_value!r}")


def _insert_case(db_url: str) -> UUID:
    today = date.today()
    case_number = f"FOIL-{uuid4().hex[:10].upper()}"
    payload = {
        "case": {
            "case_number": case_number,
            "docket_number": case_number,
            "source": "pytest",
            "title": "Pytest FOIL Case",
            "court": "NYC Civil Court",
            "filing_date": today.isoformat(),
            "judgment_date": today.isoformat(),
            "amount_awarded": "1500.00",
        },
        "entities": [
            {
                "role": "plaintiff",
                "name_full": "Plaintiff Example",
            },
            {
                "role": "defendant",
                "name_full": "Defendant Example",
            },
        ],
    }

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select public.insert_or_get_case_with_entities(%s::jsonb)",
                (Json(payload),),
            )
            row = cur.fetchone()
    if row is None:
        raise AssertionError("insert_or_get_case_with_entities returned no result")
    return _extract_case_id(row[0])


def test_record_foil_response_roundtrip() -> None:
    db_url = _resolve_db_url()
    _ensure_foil_schema(db_url)

    case_id = _insert_case(db_url)
    response_payload = {
        "documents": [{"filename": "foil-response.pdf", "pages": 4}],
        "notes": "Synthetic FOIL payload for tests",
    }

    received_on = date.today()

    record_foil_response(
        case_id,
        agency="NY Unified Court System",
        payload=response_payload,
        received_date=received_on,
    )

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id, case_id, agency, received_date, payload
                from judgments.foil_responses
                where case_id = %s
                order by id desc
                limit 1
                """,
                (case_id,),
            )
            foil_row = cur.fetchone()
            assert foil_row is not None
            foil_id = foil_row["id"]
            assert foil_row["case_id"] == case_id
            assert foil_row["agency"] == "NY Unified Court System"
            assert foil_row["received_date"] == received_on
            assert foil_row["payload"] == response_payload

            cur.execute(
                """
                select id, case_id, agency, received_date, payload
                from public.foil_responses
                where id = %s and case_id = %s
                """,
                (foil_id, case_id),
            )
            public_row = cur.fetchone()
            assert public_row is not None
            assert public_row["agency"] == "NY Unified Court System"
            assert public_row["received_date"] == received_on
            assert public_row["payload"] == response_payload

            cur.execute(
                """
                select policyname
                from pg_policies
                where schemaname = 'judgments'
                  and tablename = 'foil_responses'
                  and policyname = 'service_foil_responses_rw'
                """,
            )
            assert cur.fetchone() is not None

            cur.execute("delete from judgments.foil_responses where id = %s", (foil_id,))
            cur.execute("delete from judgments.cases where case_id = %s", (case_id,))


# End of file
