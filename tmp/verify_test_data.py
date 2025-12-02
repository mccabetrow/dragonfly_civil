"""Quick script to verify test data was inserted."""

from src.supabase_client import get_supabase_db_url
import psycopg
from psycopg.rows import dict_row

conn = psycopg.connect(get_supabase_db_url())
cur = conn.cursor(row_factory=dict_row)

# Check for test plaintiff
cur.execute(
    """
    SELECT id, name, email 
    FROM public.plaintiffs 
    WHERE email = 'test_orchestrator@example.com'
"""
)
print("Test plaintiff:")
for r in cur.fetchall():
    print(f"  {r}")

# Check for test judgment
cur.execute(
    """
    SELECT id, case_number, judgment_number, plaintiff_name, defendant_name 
    FROM public.judgments 
    WHERE case_number = 'CN-ORCH-001'
"""
)
print("\nTest judgment:")
for r in cur.fetchall():
    print(f"  {r}")

conn.close()
