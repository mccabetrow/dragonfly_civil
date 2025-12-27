#!/usr/bin/env python3
"""Check dragonfly roles in prod."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

os.environ.setdefault("SUPABASE_MODE", "prod")

from src.supabase_client import get_supabase_db_url

url = get_supabase_db_url("prod")
print(f"Connecting to: {url[:40]}...")

with psycopg.connect(url) as conn:
    # Check function overloads
    result = conn.execute(
        """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid)
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops' AND p.proname = 'reap_stuck_jobs'
    """
    )
    for r in result:
        print(f"ops.{r[0]}({r[1]})")
