"""Quick script to check table schemas."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

os.environ.setdefault("SUPABASE_MODE", "dev")

import psycopg

from src.supabase_client import get_supabase_db_url

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
