from __future__ import annotations

import sys

import click
import psycopg
from psycopg import sql

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

QUERIES: tuple[tuple[str, sql.SQL], ...] = (
    ("plaintiffs", sql.SQL("select count(*) from public.plaintiffs")),
    ("contacts", sql.SQL("select count(*) from public.plaintiff_contacts")),
    ("overview", sql.SQL("select count(*) from public.v_plaintiffs_overview")),
    ("call_queue", sql.SQL("select count(*) from public.v_plaintiff_call_queue")),
)


def _fetch_counts(db_url: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            for label, query in QUERIES:
                cur.execute(query)
                row = cur.fetchone()
                value = row[0] if row else 0
                counts[label] = int(value) if value is not None else 0
    return counts


def main() -> None:
    env = get_supabase_env()

    try:
        db_url = get_supabase_db_url(env)
    except RuntimeError as exc:
        click.echo(
            f"[smoke_plaintiffs] failed to resolve database URL for env='{env}': {exc}",
            err=True,
        )
        raise SystemExit(1)

    host, dbname, user = describe_db_url(db_url)
    click.echo(f"[smoke_plaintiffs] env={env} host={host} db={dbname} user={user}")

    try:
        counts = _fetch_counts(db_url)
    except psycopg.Error as exc:
        click.echo(f"[smoke_plaintiffs] query failed: {exc}", err=True)
        raise SystemExit(2)

    click.echo(
        "[smoke_plaintiffs] plaintiffs={plaintiffs} contacts={contacts} overview={overview} call_queue={call_queue}".format(
            **counts,
        )
    )

    raise SystemExit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - unexpected failure path
        click.echo(f"[smoke_plaintiffs] unexpected error: {exc}", err=True)
        sys.exit(1)
