from dotenv import load_dotenv
import os
import psycopg2


def main() -> None:
    load_dotenv()
    pg_url = os.getenv("PG_URL")
    if not pg_url:
        raise SystemExit("PG_URL not configured")
    with psycopg2.connect(pg_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schemaname, tablename, indexname, indexdef
                  FROM pg_indexes
                 WHERE schemaname IN ('judgments', 'ingestion')
                 ORDER BY schemaname, tablename, indexname;
                """
            )
            for schema, table, name, definition in cur.fetchall():
                print(f"{schema}.{table} -> {name}: {definition}")


if __name__ == "__main__":
    main()
