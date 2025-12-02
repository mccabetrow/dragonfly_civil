from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env


def main() -> None:
    env = get_supabase_env()
    url = get_supabase_db_url(env)
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, status, row_count, insert_count, update_count, error_count, metadata
                FROM public.import_runs
                WHERE source_system = %s
                ORDER BY started_at DESC
                LIMIT 5
                """,
                ("simplicity_test",),
            )
            for row in cur.fetchall():
                print(row)


if __name__ == "__main__":
    main()
