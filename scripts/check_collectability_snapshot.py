import os
from pathlib import Path

import psycopg


def resolve_db_url() -> str:
    explicit = os.environ.get("SUPABASE_DB_URL")
    if explicit:
        return explicit
    project_ref = os.environ["SUPABASE_PROJECT_REF"]
    password = os.environ["SUPABASE_DB_PASSWORD"]
    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def main() -> None:
    db_url = resolve_db_url()
    ensure_view(db_url)
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("select count(*) from public.v_collectability_snapshot")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("collectability snapshot view query returned no result")
            (count,) = row
            print("rows:", count)

def ensure_view(db_url: str) -> None:
    migration_path = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "0058_collectability_public_view.sql"
    up_sql_text = migration_path.read_text(encoding="utf-8")
    up_sql_section = up_sql_text.split("-- migrate:down", 1)[0]
    if "-- migrate:up" in up_sql_section:
        up_sql_section = up_sql_section.split("-- migrate:up", 1)[1]
    up_sql = up_sql_section.strip()
    if not up_sql:
        raise RuntimeError("Collectability migration missing migrate:up SQL block.")

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(up_sql)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
