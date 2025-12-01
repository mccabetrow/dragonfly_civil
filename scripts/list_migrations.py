from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import db_check


def main() -> None:
    db_url, err = db_check._build_db_url()
    if err:
        raise SystemExit(err)
    assert db_url is not None

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select version
                from supabase_migrations.schema_migrations
                order by version
                """
            )
            versions = [row[0] for row in cur.fetchall()]

    print("Applied migrations:")
    for version in versions[-10:]:
        print(f"- {version}")


if __name__ == "__main__":
    main()
