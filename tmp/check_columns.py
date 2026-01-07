import os

import psycopg

from src.supabase_client import get_supabase_db_url

os.environ["SUPABASE_MODE"] = "dev"
conn = psycopg.connect(get_supabase_db_url())
cur = conn.cursor()
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'plaintiffs' AND table_schema = 'public'"
)
print([r[0] for r in cur.fetchall()])
