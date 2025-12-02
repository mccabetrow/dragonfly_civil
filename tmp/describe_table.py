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
    table = os.environ.get("TABLE", "plaintiff_status_history")
    query = """
    select column_name, data_type
    from information_schema.columns
    where table_schema = 'public' and table_name = %s
    order by ordinal_position
    """
    with psycopg.connect(resolve_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(query, (table,))
            for column, data_type in cur.fetchall():
                print(f"{column}: {data_type}")


if __name__ == "__main__":
    main()
