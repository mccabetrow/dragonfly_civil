from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.integration


def _resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit

    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if project_ref and password:
        return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"

    pytest.skip("Supabase database credentials not configured for call outcome tests")
    return ""


@pytest.fixture(scope="module")
def db_url() -> str:
    return _resolve_db_url()


def _fresh_connection(db_url: str) -> psycopg.Connection:
    return psycopg.connect(db_url)


def _assert_timestamp_close(
    actual: datetime | None, expected: datetime, tolerance_seconds: float = 1.0
) -> None:
    assert actual is not None, "timestamp value is missing"
    delta = abs((actual - expected).total_seconds())
    assert (
        delta <= tolerance_seconds
    ), f"timestamps differ by {delta} seconds which exceeds tolerance"


@pytest.mark.integration
def test_log_call_outcome_reached_creates_follow_up(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status, source_system)
                values (%s, %s, 'new', 'test_call_rpc')
                """,
                (plaintiff_id, "Call Queue Test Plaintiff"),
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
                    'First outreach',
                    'pytest',
                    '{"test": "log_call_outcome"}'::jsonb
                )
                """,
                (task_id, plaintiff_id),
            )

            follow_up_at = datetime.now(timezone.utc) + timedelta(days=2)
            cur.execute(
                "select public.log_call_outcome(%s, %s, %s, %s, %s, %s) as payload",
                (
                    plaintiff_id,
                    task_id,
                    "reached",
                    "hot",
                    "Reached primary contact and scheduled follow-up",
                    follow_up_at,
                ),
            )
            rpc_result = cur.fetchone()
            assert rpc_result is not None
            payload = rpc_result["payload"]
            assert isinstance(payload, dict)
            assert payload["call_attempt_id"] is not None
            call_attempt_id = uuid.UUID(payload["call_attempt_id"])
            assert uuid.UUID(payload["task_id"]) == task_id
            assert payload["created_follow_up_task_id"] is not None
            created_follow_up_task_id = uuid.UUID(payload["created_follow_up_task_id"])

            cur.execute(
                """
                select outcome, interest_level, next_follow_up_at
                from public.plaintiff_call_attempts
                where id = %s
                """,
                (call_attempt_id,),
            )
            attempt = cur.fetchone()
            assert attempt is not None
            assert attempt["outcome"] == "reached"
            assert attempt["interest_level"] == "hot"
            _assert_timestamp_close(attempt["next_follow_up_at"], follow_up_at)

            cur.execute(
                "select status, closed_at, result from public.plaintiff_tasks where id = %s",
                (task_id,),
            )
            closed_task = cur.fetchone()
            assert closed_task is not None
            assert closed_task["status"] == "closed"
            assert closed_task["closed_at"] is not None
            assert closed_task["result"] == "reached"

            cur.execute(
                """
                select status
                from public.plaintiff_status_history
                where plaintiff_id = %s
                order by changed_at desc
                limit 1
                """,
                (plaintiff_id,),
            )
            latest_status = cur.fetchone()
            assert latest_status is not None
            assert latest_status["status"] == "reached_hot"

            cur.execute(
                "select status, due_at, metadata from public.plaintiff_tasks where id = %s",
                (created_follow_up_task_id,),
            )
            follow_up_task = cur.fetchone()
            assert follow_up_task is not None
            assert follow_up_task["status"] == "open"
            _assert_timestamp_close(follow_up_task["due_at"], follow_up_at)
            metadata: Dict[str, Any] = follow_up_task["metadata"] or {}
            assert metadata["from_outcome"] == "reached"
            assert metadata["interest_level"] == "hot"
    finally:
        conn.rollback()
        conn.close()


@pytest.mark.integration
def test_log_call_outcome_do_not_call_blocks_follow_up(db_url: str) -> None:
    conn = _fresh_connection(db_url)
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            plaintiff_id = uuid.uuid4()
            cur.execute(
                """
                insert into public.plaintiffs (id, name, status, source_system)
                values (%s, %s, 'contacted', 'test_call_rpc')
                """,
                (plaintiff_id, "Do Not Call Plaintiff"),
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
                    'Follow-up request',
                    'pytest',
                    '{"test": "log_call_outcome"}'::jsonb
                )
                """,
                (task_id, plaintiff_id),
            )

            cur.execute(
                "select public.log_call_outcome(%s, %s, %s, %s, %s, %s) as payload",
                (
                    plaintiff_id,
                    task_id,
                    "do_not_call",
                    None,
                    "Requested removal from list",
                    datetime.now(timezone.utc) + timedelta(days=7),
                ),
            )
            rpc_result = cur.fetchone()
            assert rpc_result is not None
            payload = rpc_result["payload"]
            assert isinstance(payload, dict)
            assert payload["call_attempt_id"] is not None
            call_attempt_id = uuid.UUID(payload["call_attempt_id"])
            assert uuid.UUID(payload["task_id"]) == task_id
            assert payload["created_follow_up_task_id"] is None

            cur.execute(
                """
                select outcome, interest_level, next_follow_up_at
                from public.plaintiff_call_attempts
                where id = %s
                """,
                (call_attempt_id,),
            )
            attempt = cur.fetchone()
            assert attempt is not None
            assert attempt["outcome"] == "do_not_call"
            assert attempt["interest_level"] is None
            assert attempt["next_follow_up_at"] is None

            cur.execute(
                "select status, closed_at, result from public.plaintiff_tasks where id = %s",
                (task_id,),
            )
            closed_task = cur.fetchone()
            assert closed_task is not None
            assert closed_task["status"] == "closed"
            assert closed_task["result"] == "do_not_call"

            cur.execute(
                """
                select status
                from public.plaintiff_status_history
                where plaintiff_id = %s
                order by changed_at desc
                limit 1
                """,
                (plaintiff_id,),
            )
            latest_status = cur.fetchone()
            assert latest_status is not None
            assert latest_status["status"] == "do_not_call"

            cur.execute(
                """
                select count(*) as open_followups
                from public.plaintiff_tasks
                where plaintiff_id = %s and status = 'open' and id <> %s
                """,
                (plaintiff_id, task_id),
            )
            open_followups_row = cur.fetchone()
            assert open_followups_row is not None
            open_followups = open_followups_row["open_followups"]
            assert open_followups == 0
    finally:
        conn.rollback()
        conn.close()


# From project root:
# $env:SUPABASE_MODE = 'dev'
# .\.venv\Scripts\python.exe -m pytest tests/test_plaintiff_call_outcomes.py -q
