import os
import psycopg


def resolve_db_url() -> str:
    url = os.environ.get("SUPABASE_DB_URL")
    if url:
        return url
    project_ref = os.environ.get("SUPABASE_PROJECT_REF")
    password = os.environ.get("SUPABASE_DB_PASSWORD")
    if not project_ref or not password:
        raise SystemExit("Missing Supabase connection settings")
    return (
        f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"
    )


def main() -> None:
    query = """
    select 
      n.nspname as schema,
      p.proname as name,
      oidvectortypes(p.proargtypes) as args
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where p.proname = 'log_call_outcome';
    """
    with psycopg.connect(resolve_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    if not rows:
        print("FUNCTION_MISSING")
    else:
        for schema, name, args in rows:
            print(f"schema={schema}, name={name}, args={args}")


if __name__ == "__main__":
    main()
