import uuid

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env


@pytest.mark.integration
def test_spawn_enforcement_flow_round_trip():
    env = get_supabase_env()
    url = get_supabase_db_url(env)

    case_number = "UNIT_TEST_CASE_0140"
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.plaintiffs (id, name, status, source_system)
                VALUES (%s, %s, 'new', 'test_spawn_enforcement')
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                RETURNING id
                """,
                (uuid.uuid4(), "Spawn Flow Plaintiff"),
            )
            row = cur.fetchone()
            assert row is not None
            plaintiff_id = row[0]

            cur.execute(
                """
                INSERT INTO public.judgments (case_number, plaintiff_id, status)
                VALUES (%s, %s, 'open')
                ON CONFLICT (case_number)
                DO UPDATE SET plaintiff_id = EXCLUDED.plaintiff_id
                RETURNING id
                """,
                (case_number, plaintiff_id),
            )
            row = cur.fetchone()
            assert row is not None
            judgment_id = row[0]

            cur.execute(
                "SELECT public.spawn_enforcement_flow(%s, %s);",
                (case_number, "UNIT_TEST_TEMPLATE"),
            )
            row = cur.fetchone()
            assert row is not None
            task_ids = row[0]

            assert isinstance(task_ids, list)
            # Flow should produce deterministic uuid list even if empty
