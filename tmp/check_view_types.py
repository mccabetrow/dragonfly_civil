from __future__ import annotations

import os

import psycopg

from src.supabase_client import get_supabase_db_url


def dump_view(view: str) -> None:
    db_url = get_supabase_db_url(os.environ.get("SUPABASE_MODE"))
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                                SELECT column_name, data_type
                                FROM information_schema.columns
                                WHERE table_schema = 'public'
                                    AND table_name = %s
                                ORDER BY ordinal_position
                                """,
                (view,),
            )
            rows = cur.fetchall()
            cur.execute(
                """
                                SELECT definition
                                FROM pg_views
                                WHERE schemaname = 'public'
                                    AND viewname = %s
                                """,
                (view,),
            )
            definition_row = cur.fetchone()
            definition = definition_row[0] if definition_row else "<missing>"
        print(f"{view} columns: {rows}")
        print(f"{view} definition:\n{definition}\n")


if __name__ == "__main__":
    dump_view("v_enforcement_recent")
    dump_view("v_judgment_pipeline")
