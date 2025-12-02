from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Tuple

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env


def describe_table(schema: str, table: str) -> Tuple[Tuple[str, str], ...]:
    query = """
    select column_name, data_type
    from information_schema.columns
    where table_schema = %s and table_name = %s
    order by ordinal_position
    """
    env = get_supabase_env()
    url = get_supabase_db_url(env)
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (schema, table))
            return tuple(cur.fetchall())


def main() -> None:
    schema = os.environ.get("DESCRIBE_SCHEMA", "public")
    table = os.environ.get("DESCRIBE_TABLE", "plaintiffs")
    rows = describe_table(schema, table)
    for column, data_type in rows:
        print(f"{schema}.{table}.{column}: {data_type}")


if __name__ == "__main__":
    main()
