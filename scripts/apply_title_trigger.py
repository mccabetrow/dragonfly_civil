#!/usr/bin/env python3
"""Apply the title default trigger to judgments.cases."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url


def main():
    env = os.environ.get("SUPABASE_MODE", "dev")
    url = get_supabase_db_url(env)

    trigger_sql = """
    CREATE OR REPLACE FUNCTION judgments.default_case_title()
    RETURNS TRIGGER
    LANGUAGE plpgsql
    AS $func$
    BEGIN
        IF NEW.title IS NULL OR NEW.title = '' THEN
            NEW.title := COALESCE(NEW.case_number, 'Untitled Case');
        END IF;
        RETURN NEW;
    END;
    $func$;
    """

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            # Create trigger function
            cur.execute(trigger_sql)
            print("Created trigger function")

            # Drop and create trigger
            cur.execute("DROP TRIGGER IF EXISTS trg_cases_default_title ON judgments.cases;")
            cur.execute(
                """
                CREATE TRIGGER trg_cases_default_title
                    BEFORE INSERT OR UPDATE ON judgments.cases
                    FOR EACH ROW
                    EXECUTE FUNCTION judgments.default_case_title();
            """
            )
            print("Created trigger")

            conn.commit()
            print("Trigger applied successfully")


if __name__ == "__main__":
    main()
