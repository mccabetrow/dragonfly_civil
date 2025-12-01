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

    query = """
        select
            n.nspname as schema,
            c.relname as name,
            pg_get_userbyid(c.relowner) as owner,
            c.relacl
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'S'
          and c.relname = 'enrichment_runs_id_seq'
    """

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
    print(rows)


if __name__ == "__main__":
    main()
