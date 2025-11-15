from __future__ import annotations

import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import db_check

STATEMENTS = [
    "create index if not exists idx_judgments_enrichment_runs_case_id on judgments.enrichment_runs (case_id)",
    "create index if not exists idx_judgments_enrichment_runs_status on judgments.enrichment_runs (status)",
    "alter table judgments.enrichment_runs enable row level security",
    "do $$ begin if not exists (select 1 from pg_policies where schemaname = 'judgments' and tablename = 'enrichment_runs' and policyname = 'service_enrichment_runs_rw') then create policy service_enrichment_runs_rw on judgments.enrichment_runs for all using (auth.role() = 'service_role') with check (auth.role() = 'service_role'); end if; end; $$",
    "revoke all on judgments.enrichment_runs from public",
    "revoke all on judgments.enrichment_runs from anon",
    "revoke all on judgments.enrichment_runs from authenticated",
    "grant select, insert, update, delete on judgments.enrichment_runs to service_role",
    "drop view if exists public.enrichment_runs",
    "create or replace view public.enrichment_runs as select id, case_id, status, summary, raw, created_at from judgments.enrichment_runs",
    "revoke all on public.enrichment_runs from public",
    "revoke all on public.enrichment_runs from anon",
    "revoke all on public.enrichment_runs from authenticated",
    "grant select, insert, update, delete on public.enrichment_runs to service_role",
]


def main() -> None:
    db_url, err = db_check._build_db_url()
    if err:
        raise SystemExit(err)
    assert db_url is not None

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for statement in STATEMENTS:
                cur.execute(statement)  # type: ignore[arg-type]
        conn.commit()


if __name__ == "__main__":
    main()
