"""Quick script to check table schemas."""

from src.supabase_client import get_supabase_db_url
import psycopg

conn = psycopg.connect(get_supabase_db_url())

# Check judgments columns
cur = conn.execute(
    """
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_schema='public' AND table_name='judgments' 
    ORDER BY ordinal_position
"""
)
print("judgments columns:")
for r in cur.fetchall():
    print(f"  {r[0]}")

# Check plaintiffs columns
cur = conn.execute(
    """
    SELECT column_name 
    FROM information_schema.columns 
    WHERE table_schema='public' AND table_name='plaintiffs' 
    ORDER BY ordinal_position
"""
)
print("\nplaintiffs columns:")
for r in cur.fetchall():
    print(f"  {r[0]}")

conn.close()
