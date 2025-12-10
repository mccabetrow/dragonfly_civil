"""Clean up bad test row."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
cur = conn.cursor()
cur.execute("DELETE FROM public.judgments WHERE case_number = 'SIMP-TEST-007'")
conn.commit()
print("Cleaned up SIMP-TEST-007")
conn.close()
