from __future__ import annotations

import psycopg

from etl.simplicity_importer.import_simplicity import import_simplicity_batch
from src.supabase_client import get_supabase_db_url, get_supabase_env

TEST_SOURCE_SYSTEM = "simplicity_test_manual"
CSV_PATH = "tests/data/simplicity_sample.csv"


def _collect_counts(conn: psycopg.Connection, source_system: str) -> dict[str, int]:
    def _fetch(query: str, params: tuple[object, ...]) -> list[tuple]:
        with conn.cursor() as cur:
            cur.execute(query, params)
            return cur.fetchall()

    plaintiffs = _fetch(
        "SELECT id FROM plaintiffs WHERE source_system = %s",
        (source_system,),
    )
    cases = _fetch(
        "SELECT case_id FROM judgments.cases WHERE source_system = %s",
        (source_system,),
    )
    case_ids = tuple(row[0] for row in cases)
    judgments: list[tuple]
    if case_ids:
        placeholders = ", ".join(["%s"] * len(case_ids))
        query = f"SELECT id FROM judgments.judgments WHERE case_id IN ({placeholders})"
        with conn.cursor() as cur:
            cur.execute(query, case_ids)
            judgments = cur.fetchall()
    else:
        judgments = []
    return {
        "plaintiffs": len(plaintiffs),
        "cases": len(cases),
        "judgments": len(judgments),
    }


def main() -> None:
    env = get_supabase_env()
    with psycopg.connect(get_supabase_db_url(env), autocommit=True) as conn:
        for table, schema in (("judgments", "judgments.cases"),):
            pass
        before = _collect_counts(conn, TEST_SOURCE_SYSTEM)
        print("before", before)
        import_simplicity_batch(CSV_PATH, source_system=TEST_SOURCE_SYSTEM)
        after = _collect_counts(conn, TEST_SOURCE_SYSTEM)
        print("after", after)


if __name__ == "__main__":
    main()
