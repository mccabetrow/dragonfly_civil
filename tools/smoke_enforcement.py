from __future__ import annotations

import sys

import click
import psycopg
from psycopg import sql

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

QUERIES: tuple[tuple[str, sql.SQL], ...] = (
    ("overview", sql.SQL("select count(*) from public.v_enforcement_overview")),
    ("recent", sql.SQL("select count(*) from public.v_enforcement_recent")),
    ("pipeline", sql.SQL("select count(*) from public.v_judgment_pipeline")),
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
            f"[smoke_enforcement] failed to resolve database URL for env='{env}': {exc}",
            err=True,
        )
        raise SystemExit(1)

    host, dbname, user = describe_db_url(db_url)
    click.echo(f"[smoke_enforcement] env={env} host={host} db={dbname} user={user}")

    try:
        counts = _fetch_counts(db_url)
    except psycopg.Error as exc:
        click.echo(f"[smoke_enforcement] query failed: {exc}", err=True)
        raise SystemExit(2)

    click.echo(
        "[smoke_enforcement] overview={overview} recent={recent} pipeline={pipeline}".format(
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
        click.echo(f"[smoke_enforcement] unexpected error: {exc}", err=True)
        sys.exit(1)
