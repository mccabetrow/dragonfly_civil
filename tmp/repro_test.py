from __future__ import annotations

import psycopg

from etl.simplicity_importer.import_simplicity import import_simplicity_batch
from src.supabase_client import get_supabase_db_url, get_supabase_env

SOURCE_SYSTEM = "simplicity_test_repro"
CSV_PATH = "tests/data/simplicity_sample.csv"


def cleanup(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM judgments.judgments WHERE case_id IN (SELECT id FROM judgments.cases WHERE source_system = %s)",
            (SOURCE_SYSTEM,),
        )
        cur.execute(
            "DELETE FROM judgments.cases WHERE source_system = %s",
            (SOURCE_SYSTEM,),
        )
        cur.execute(
            "DELETE FROM plaintiff_contacts WHERE plaintiff_id IN (SELECT id FROM plaintiffs WHERE source_system = %s)",
            (SOURCE_SYSTEM,),
        )
        cur.execute(
            "DELETE FROM plaintiffs WHERE source_system = %s",
            (SOURCE_SYSTEM,),
        )
        cur.execute(
            "DELETE FROM import_runs WHERE source_system = %s",
            (SOURCE_SYSTEM,),
        )


def counts(conn: psycopg.Connection) -> dict[str, int]:
    def scalar(query: str, params: tuple[object, ...]) -> int:
        with conn.cursor() as cur:
            cur.execute(query, params)
            (value,) = cur.fetchone()
            return value or 0

    plaintiff_count = scalar(
        "SELECT COUNT(*) FROM plaintiffs WHERE source_system = %s", (SOURCE_SYSTEM,)
    )
    case_count = scalar(
        "SELECT COUNT(*) FROM judgments.cases WHERE source_system = %s",
        (SOURCE_SYSTEM,),
    )
    judgment_count = scalar(
        "SELECT COUNT(*) FROM judgments.judgments WHERE case_id IN (SELECT id FROM judgments.cases WHERE source_system = %s)",
        (SOURCE_SYSTEM,),
    )
    return {
        "plaintiffs": plaintiff_count,
        "cases": case_count,
        "judgments": judgment_count,
    }


def main() -> None:
    env = get_supabase_env()
    with psycopg.connect(get_supabase_db_url(env), autocommit=True) as conn:
        cleanup(conn)
        print("before", counts(conn))
        import_simplicity_batch(CSV_PATH, source_system=SOURCE_SYSTEM)
        print("after", counts(conn))


if __name__ == "__main__":
    main()
