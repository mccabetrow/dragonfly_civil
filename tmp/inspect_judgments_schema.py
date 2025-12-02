from __future__ import annotations

import json
from pathlib import Path
import sys

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
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = 'judgments'
                  AND table_name = 'judgments'
                ORDER BY ordinal_position
                """
            )
            rows = cur.fetchall()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM judgments.judgments LIMIT 0")
            description = [col.name for col in cur.description]
    print(json.dumps(rows, indent=2))
    print(json.dumps(description, indent=2))


if __name__ == "__main__":
    main()
