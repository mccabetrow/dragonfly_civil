from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from psycopg import errors
from psycopg.rows import dict_row


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit

    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"

    pytest.skip("Supabase database credentials not configured for RPC integration tests")
    return ""


@pytest.fixture(scope="module")
def db_url() -> str:
    return _resolve_db_url()


def _fresh_connection(db_url: str) -> psycopg.Connection:
    return psycopg.connect(db_url)


@pytest.mark.integration
def test_set_plaintiff_status_updates_status_and_history(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status)
                values (%s, %s, 'new')
                """,
                (plaintiff_id, "RPC Test Plaintiff"),
            )

            cur.execute(
                "select * from public.set_plaintiff_status(%s, %s, %s, %s)",
                (plaintiff_id, "qualified", "automated status update", "pytest"),
            )
            row = cur.fetchone()
            assert row is not None
            assert row["status"] == "qualified"

            cur.execute(
                """
                select count(*) as history_count
                from public.plaintiff_status_history
                where plaintiff_id = %s and status = %s
                """,
                (plaintiff_id, "qualified"),
            )
            history_count = cur.fetchone()["history_count"]
            assert history_count >= 1
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_set_plaintiff_status_rejects_invalid_status(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor() as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                "insert into public.plaintiffs (id, name, status) values (%s, %s, 'new')",
                (plaintiff_id, "Invalid Status Plaintiff"),
            )
            with pytest.raises(errors.InvalidParameterValue):
                cur.execute(
                    "select public.set_plaintiff_status(%s, %s, %s, %s)",
                    (plaintiff_id, "not_real", None, None),
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_set_enforcement_stage_updates_stage_and_history(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                insert into public.judgments (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    enforcement_stage,
                    enforcement_stage_updated_at
                )
                values (%s, %s, %s, %s, current_date, 'pre_enforcement', timezone('utc', now()))
                returning id
                """,
                (f"RPC-{uuid.uuid4().hex[:8].upper()}", "Plaintiff", "Defendant", 1000),
            )
            judgment_id = cur.fetchone()["id"]

            cur.execute(
                "select * from public.set_enforcement_stage(%s, %s, %s, %s)",
                (judgment_id, "levy_issued", "stage promotion", "pytest"),
            )
            updated = cur.fetchone()
            assert updated is not None
            assert updated["enforcement_stage"] == "levy_issued"

            cur.execute(
                """
                select count(*) as history_count
                from public.enforcement_history
                where judgment_id = %s and stage = %s
                """,
                (judgment_id, "levy_issued"),
            )
            history_count = cur.fetchone()["history_count"]
            assert history_count >= 1
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_set_enforcement_stage_rejects_invalid_stage(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor() as cur:
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
                (f"RPC-{uuid.uuid4().hex[:8].upper()}", "Plaintiff", "Defendant", 2000),
            )
            judgment_id = cur.fetchone()[0]

            with pytest.raises(errors.RaiseException):
                cur.execute(
                    "select public.set_enforcement_stage(%s, %s, %s, %s)",
                    (judgment_id, "not_a_stage", None, None),
                )
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_set_judgment_priority_updates_level_and_history(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                insert into public.judgments (
                    case_number,
                    plaintiff_name,
                    defendant_name,
                    judgment_amount,
                    entry_date,
                    priority_level,
                    priority_level_updated_at
                )
                values (%s, %s, %s, %s, current_date, 'normal', timezone('utc', now()))
                returning id, priority_level
                """,
                (
                    f"PRIORITY-{uuid.uuid4().hex[:8].upper()}",
                    "Plaintiff",
                    "Defendant",
                    3000,
                ),
            )
            inserted = cur.fetchone()
            judgment_id = inserted["id"]
            assert inserted["priority_level"] == "normal"

            cur.execute(
                "select * from public.set_judgment_priority(%s, %s, %s, %s)",
                (judgment_id, "urgent", "expedite garnishment", "pytest"),
            )
            updated = cur.fetchone()
            assert updated is not None
            assert updated["priority_level"] == "urgent"

            cur.execute(
                """
                select note, changed_by
                from public.judgment_priority_history
                where judgment_id = %s
                order by changed_at desc
                limit 1
                """,
                (judgment_id,),
            )
            history_entry = cur.fetchone()
            assert history_entry is not None
            assert history_entry["note"] == "expedite garnishment"
            assert history_entry["changed_by"] == "pytest"
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_set_judgment_priority_rejects_invalid_level(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor() as cur:
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
                    f"PRIORITY-{uuid.uuid4().hex[:8].upper()}",
                    "Plaintiff",
                    "Defendant",
                    1500,
                ),
            )
            judgment_id = cur.fetchone()[0]

            with pytest.raises(errors.InvalidParameterValue):
                cur.execute(
                    "select public.set_judgment_priority(%s, %s, %s, %s)",
                    (judgment_id, "super_urgent", None, None),
                )
    finally:
        conn.rollback()
        conn.close()
