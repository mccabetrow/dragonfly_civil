import os
import sys

import psycopg

# Use environment variables only - no hardcoded defaults for secrets
db_url = os.environ.get("SUPABASE_DB_URL")
if not db_url:
    print("ERROR: SUPABASE_DB_URL environment variable not set", file=sys.stderr)
    print("Run: ./scripts/load_env.ps1 to load environment", file=sys.stderr)
    sys.exit(1)

with psycopg.connect(db_url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            select column_name, data_type, is_nullable
            from information_schema.columns
            where table_schema = 'judgments'
              and table_name = 'cases'
            order by ordinal_position
            """
        )
        print("Columns:")
        for column in cur.fetchall():
            print(column)

        cur.execute(
            """
            select conname, contype, pg_get_constraintdef(oid)
            from pg_constraint
            where conrelid = 'judgments.cases'::regclass
            order by conname
            """
        )
        print("\nConstraints:")
        for constraint in cur.fetchall():
            print(constraint)
