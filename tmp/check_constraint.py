from __future__ import annotations

import psycopg
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env


def main() -> None:
    env = get_supabase_env()
    with psycopg.connect(get_supabase_db_url(env), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select pg_get_constraintdef(oid)
                from pg_constraint
                where conname = 'judgments_decision_type_check'
                """
            )
            for row in cur.fetchall():
                print(row[0])


if __name__ == "__main__":
    main()
