import os
import pathlib
import sys

import psycopg

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.supabase_client import get_supabase_db_url

env = os.environ.get("SUPABASE_MODE", "dev")
conn = psycopg.connect(get_supabase_db_url(env))
with conn, conn.cursor() as cur:
    cur.execute(
        "REVOKE ALL PRIVILEGES ON TABLE public.v_collectability_snapshot FROM anon, authenticated, public"
    )
