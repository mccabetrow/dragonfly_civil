#!/usr/bin/env python3
"""Apply ingest migration directly."""
import psycopg

from src.supabase_client import get_supabase_db_url

dsn = get_supabase_db_url("dev")
print(f"Connecting to dev...")

with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        # Check if ingest schema exists
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'ingest'"
        )
        row = cur.fetchone()
        ingest_exists = row is not None
        print(f"ingest schema exists: {ingest_exists}")

        if not ingest_exists:
            print("Applying 20261101_ingestion_idempotency.sql...")
            with open("supabase/migrations/20261101_ingestion_idempotency.sql", "r") as f:
                migration_sql = f.read()
            cur.execute(migration_sql)
            conn.commit()
            print("Migration applied!")

        # Verify
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'ingest'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables in ingest schema: {tables}")
