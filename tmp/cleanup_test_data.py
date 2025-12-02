"""Quick script to clean up test data."""

from src.supabase_client import get_supabase_db_url
import psycopg

conn = psycopg.connect(get_supabase_db_url())

# Delete test judgments
with conn.cursor() as cur:
    cur.execute(
        """
        DELETE FROM public.judgments 
        WHERE case_number LIKE 'CN-ORCH-%'
    """
    )
    print(f"Deleted {cur.rowcount} test judgments")

# Delete test plaintiffs
with conn.cursor() as cur:
    cur.execute(
        """
        DELETE FROM public.plaintiffs 
        WHERE email LIKE '%orchestrator@example.com' 
           OR email = 'good@example.com'
    """
    )
    print(f"Deleted {cur.rowcount} test plaintiffs")

conn.commit()
conn.close()
print("Test data cleaned up")
