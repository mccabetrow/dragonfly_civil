from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import db_check


def main() -> None:
    db_url, err = db_check._build_db_url()
    if err:
        raise SystemExit(err)
    assert db_url is not None

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select table_schema, table_name
                from information_schema.tables
                where table_name = 'enrichment_runs'
                order by table_schema
                """
            )
            matches = cur.fetchall()

            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'enrichment_runs'
                order by ordinal_position
                """
            )
            public_columns = [row[0] for row in cur.fetchall()]

            cur.execute(
                """
                select column_name
                from information_schema.columns
                where table_schema = 'judgments'
                  and table_name = 'enrichment_runs'
                order by ordinal_position
                """
            )
            judgments_columns = [row[0] for row in cur.fetchall()]

            cur.execute(
                """
                select table_name
                from information_schema.tables
                where table_schema = 'judgments'
                order by table_name
                """
            )
            judgments_tables = [row[0] for row in cur.fetchall()]

            cur.execute(
                """
                select schemaname, tablename
                from pg_tables
                where tablename = 'enrichment_runs'
                order by schemaname
                """
            )
            pg_tables_matches = cur.fetchall()

        print("public.enrichment_runs columns:", public_columns)
        print("judgments.enrichment_runs columns:", judgments_columns)
        print("judgments schema tables:", judgments_tables)
        print("tables named enrichment_runs:", matches)
    print("pg_tables enrichment_runs entries:", pg_tables_matches)


if __name__ == "__main__":
    main()
