#!/usr/bin/env python3
"""Quick check for ingest schema."""
import psycopg

from src.supabase_client import get_supabase_db_url

dsn = get_supabase_db_url("dev")
with psycopg.connect(dsn) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'ingest'"
        )
        row = cur.fetchone()
        print(f"ingest schema exists: {row is not None}")

        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'ingest'")
        tables = [r[0] for r in cur.fetchall()]
        print(f"Tables in ingest schema: {tables}")
