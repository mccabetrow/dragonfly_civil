import psycopg
from src.supabase_client import get_supabase_db_url, get_supabase_env

conn = psycopg.connect(get_supabase_db_url(get_supabase_env()))
cur = conn.cursor()
cur.execute(
    """
    select column_name
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'import_runs'
    order by ordinal_position
    """
)
print([row[0] for row in cur.fetchall()])
cur.close()
conn.close()
