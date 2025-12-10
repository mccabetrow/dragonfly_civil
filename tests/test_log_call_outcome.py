from __future__ import annotations

import os
import uuid
from collections.abc import Generator

import psycopg
import pytest
from psycopg.rows import dict_row


def _resolve_db_url() -> str:
    direct = os.environ.get("SUPABASE_DB_URL")
    if direct:
        return direct

    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"

    pytest.skip("Supabase database credentials not configured for call outcome tests")
    return ""


@pytest.fixture(scope="module")
def db_url() -> str:
    return _resolve_db_url()


@pytest.fixture()
def conn(db_url: str) -> Generator[psycopg.Connection, None, None]:
    connection = psycopg.connect(db_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.integration
def test_log_call_outcome_inserts_attempt(conn: psycopg.Connection) -> None:
    with conn.cursor(row_factory=dict_row) as cur:
        plaintiff_id = uuid.uuid4()
        cur.execute(
            """
                        insert into public.plaintiffs (id, name, status, source_system)
                        values (%s, %s, %s, %s)
                        """,
            (
                plaintiff_id,
                "Call Queue Plaintiff",
                "new",
                "log_call_outcome_test",
            ),
        )

        task_id = uuid.uuid4()
        cur.execute(
            """
                        insert into public.plaintiff_tasks (
                            id, plaintiff_id, kind, status, due_at, note, created_by, metadata
                        ) values (
                            %s,
                            %s,
                            'call',
                            'open',
                            timezone('utc', now()),
                            'Initial call',
                            'pytest',
                            '{}'::jsonb
                        )
                        """,
            (task_id, plaintiff_id),
        )

        cur.execute(
            """
                        select public.log_call_outcome(%s, %s, %s, %s, %s, %s)
                        """,
            (
                plaintiff_id,
                task_id,
                "left_voicemail",
                "warm",
                "Left a voicemail with callback info",
                None,
            ),
        )
        result = cur.fetchone()
        assert result is not None
        payload = result["log_call_outcome"]
        assert isinstance(payload, dict)
        attempt_id = payload["call_attempt_id"]
        assert attempt_id is not None

        cur.execute(
            """
                        select plaintiff_id, task_id, outcome, interest_level, notes
                        from public.plaintiff_call_attempts
                        where id = %s
                        """,
            (uuid.UUID(str(attempt_id)),),
        )
        row = cur.fetchone()
        assert row is not None
        assert row["plaintiff_id"] == plaintiff_id
        assert row["task_id"] == task_id
        assert row["outcome"] == "left_voicemail"
        assert row["interest_level"] == "warm"
        assert "voicemail" in (row["notes"] or "")
