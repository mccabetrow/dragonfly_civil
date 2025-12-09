"""Quick schema check for dev environment."""

import os

os.environ.setdefault("SUPABASE_MODE", "dev")

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
cur = conn.cursor()

# Check plaintiffs columns
cur.execute(
    """
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'plaintiffs' 
    ORDER BY ordinal_position
"""
)
print("=== plaintiffs columns ===")
for r in cur.fetchall():
    print(r[0])

# Check plaintiff_contacts columns
cur.execute(
    """
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'plaintiff_contacts' 
    ORDER BY ordinal_position
"""
)
print("\n=== plaintiff_contacts columns ===")
for r in cur.fetchall():
    print(r[0])

conn.close()
