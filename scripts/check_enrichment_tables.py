#!/usr/bin/env python3
"""Check tables in enrichment schema."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url


def main():
    env = os.environ.get("SUPABASE_MODE", "dev")
    url = get_supabase_db_url(env)

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'enrichment'
                ORDER BY table_name
            """
            )
            tables = [row[0] for row in cur.fetchall()]
            print(f"Tables in enrichment schema: {tables}")


if __name__ == "__main__":
    main()
