import os

import psycopg

project_ref = os.environ.get("SUPABASE_PROJECT_REF", "ejiddanxtqcleyswqvkc")
db_password = os.environ.get("SUPABASE_DB_PASSWORD", "Norwaykmt99!!")
DB_URL = (
    os.environ.get("SUPABASE_DB_URL")
    or f"postgresql://postgres:{db_password}@db.{project_ref}.supabase.co:5432/postgres"
)

with psycopg.connect(DB_URL) as conn:
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
