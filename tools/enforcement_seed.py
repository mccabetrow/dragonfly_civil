"""Demo helper to seed enforcement stages for dashboard previews.

WARNING: Mutates judgment enforcement stages. Use with caution, especially
in production environments.
"""

from __future__ import annotations

from collections import Counter

import click
import psycopg

from src.supabase_client import describe_db_url, get_supabase_db_url, get_supabase_env

STAGE_CYCLE = (
    "pre_enforcement",
    "paperwork_filed",
    "levy_issued",
    "waiting_payment",
    "collected_partially",
)


@click.command()
@click.option(
    "--limit",
    "limit_",
    type=click.IntRange(1, 1000),
    default=10,
    show_default=True,
    help="Maximum judgments to update.",
)
def main(limit_: int) -> None:
    env = get_supabase_env()

    try:
        db_url = get_supabase_db_url(env)
    except RuntimeError as exc:
        click.echo(
            f"[enforcement_seed] failed to resolve database URL for env='{env}': {exc}",
            err=True,
        )
        raise SystemExit(1)

    host, dbname, user = describe_db_url(db_url)
    click.echo(f"[enforcement_seed] env={env} host={host} db={dbname} user={user}")

    try:
        updated_count, stage_counts = _seed_enforcement_stages(db_url, limit_)
    except psycopg.Error as exc:
        click.echo(f"[enforcement_seed] database error: {exc}", err=True)
        raise SystemExit(2)

    if updated_count == 0:
        click.echo(
            "[enforcement_seed] No eligible judgments found. No changes applied."
        )
        raise SystemExit(0)

    stage_summary = ", ".join(
        f"{stage}: {count}" for stage, count in stage_counts.items()
    )
    click.echo(
        f"[enforcement_seed] Updated {updated_count} judgments across stages: {stage_summary}"
    )
    raise SystemExit(0)


def _seed_enforcement_stages(db_url: str, limit_: int) -> tuple[int, Counter[str]]:
    stage_counter: Counter[str] = Counter()

    with psycopg.connect(db_url, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                select id
                from public.judgments
                where enforcement_stage is null or enforcement_stage = 'pre_enforcement'
                order by enforcement_stage_updated_at nulls first, updated_at nulls first, id
                limit %s
                for update skip locked
                """,
                (limit_,),
            )
            rows = cur.fetchall()

            if not rows:
                conn.rollback()
                return 0, stage_counter

            for idx, (judgment_id,) in enumerate(rows):
                stage = STAGE_CYCLE[idx % len(STAGE_CYCLE)]
                cur.execute(
                    """
                    update public.judgments
                    set enforcement_stage = %s,
                        enforcement_stage_updated_at = now()
                    where id = %s
                    """,
                    (stage, judgment_id),
                )
                stage_counter[stage] += 1

        conn.commit()

    return sum(stage_counter.values()), stage_counter


if __name__ == "__main__":
    main()
