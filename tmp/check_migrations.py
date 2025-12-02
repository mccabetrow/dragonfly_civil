import psycopg

from src.supabase_client import get_supabase_db_url


def main() -> None:
    url = get_supabase_db_url("dev")
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM supabase_migrations.schema_migrations ORDER BY version DESC LIMIT 10"
            )
            col_names = [desc[0] for desc in cur.description]
            print("Columns:", ", ".join(col_names))
            for row in cur.fetchall():
                print(row)


if __name__ == "__main__":
    main()
