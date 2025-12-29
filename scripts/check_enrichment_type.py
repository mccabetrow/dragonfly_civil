#!/usr/bin/env python3
"""Check if enrichment schema and types exist."""

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
                "SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'enrichment'"
            )
            result = cur.fetchone()
            print(f"enrichment schema exists: {result is not None}")

            cur.execute(
                """
                SELECT typname FROM pg_type t
                JOIN pg_namespace n ON t.typnamespace = n.oid
                WHERE n.nspname = 'enrichment' AND t.typname = 'contact_kind'
            """
            )
            result = cur.fetchone()
            print(f"contact_kind type exists: {result is not None}")


if __name__ == "__main__":
    main()
