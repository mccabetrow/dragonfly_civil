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
    table = os.environ.get("TABLE", "public.plaintiff_call_attempts")
    with psycopg.connect(resolve_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("select to_regclass(%s)", (table,))
            (name,) = cur.fetchone()
    print(name)


if __name__ == "__main__":
    main()
