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
    with psycopg.connect(resolve_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version
                from supabase_migrations.schema_migrations
                order by version desc
                limit 10
                """
            )
            rows = cur.fetchall()
    for (version,) in rows:
        print(version)


if __name__ == "__main__":
    main()
