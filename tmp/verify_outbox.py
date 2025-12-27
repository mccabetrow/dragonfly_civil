import os

import psycopg

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'ops' AND table_name = 'outbox' ORDER BY ordinal_position"
        )
        print("ops.outbox columns:")
        for row in cur.fetchall():
            print(f"  {row[0]}: {row[1]}")

        cur.execute(
            "SELECT routine_name FROM information_schema.routines WHERE routine_schema = 'ops' AND routine_name LIKE '%outbox%'"
        )
        print("\nops.outbox functions:")
        for row in cur.fetchall():
            print(f"  {row[0]}")
