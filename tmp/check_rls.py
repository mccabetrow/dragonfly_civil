#!/usr/bin/env python3
"""Quick script to check RLS status."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url

url = get_supabase_db_url()
print(f"Checking RLS status in database...")

with psycopg.connect(url, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT n.nspname, c.relname, c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname IN ('public', 'ops', 'intake')
              AND c.relkind = 'r'
            ORDER BY n.nspname, c.relname
        """
        )

        print("\n" + "=" * 70)
        print(f"{'SCHEMA.TABLE':<40} {'RLS':<8} {'FORCED':<8}")
        print("=" * 70)

        no_rls = []
        for row in cur.fetchall():
            schema, table, rls, forced = row
            rls_str = "✓" if rls else "✗"
            forced_str = "✓" if forced else "✗"
            print(f"{schema}.{table:<38} {rls_str:<8} {forced_str:<8}")
            if not rls:
                no_rls.append(f"{schema}.{table}")

        print("=" * 70)
        print(f"\nTables without RLS: {len(no_rls)}")
        if no_rls:
            for t in no_rls:
                print(f"  - {t}")
