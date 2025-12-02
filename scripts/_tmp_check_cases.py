import sys
from pathlib import Path

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url


def main() -> None:
    conn = psycopg.connect(get_supabase_db_url())
    try:
        cur = conn.cursor()
        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = 'judgments'
              and table_name = 'cases'
            order by ordinal_position
            """
        )
        print("columns:", cur.fetchall())

        cur.execute(
            """
            select conname, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'judgments.cases'::regclass
            """
        )
        print("constraints:", cur.fetchall())

        cur.execute(
            """
            select case_id, id
            from judgments.cases
            order by created_at desc
            limit 5
            """
        )
        print("sample ids:", cur.fetchall())

        cur.execute(
            """
            select column_name, data_type
            from information_schema.columns
            where table_schema = 'judgments'
              and table_name = 'parties'
            order by ordinal_position
            """
        )
        print("parties columns:", cur.fetchall())

        cur.execute(
            """
            select conname, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'judgments.parties'::regclass
            """
        )
        print("parties constraints:", cur.fetchall())

        cur.execute(
            """
            select conname, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'judgments.judgments'::regclass
            """
        )
        print("judgments constraints:", cur.fetchall())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
