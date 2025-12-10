from __future__ import annotations

import argparse
from typing import Any, Iterable, Iterator

import psycopg

from src.supabase_client import get_supabase_db_url, get_supabase_env

PIPELINE_QUERY = """
select plaintiff_name,
       judgment_id,
       collectability_tier,
       priority_level,
       judgment_amount,
       stage,
       plaintiff_status,
       tier_rank
from public.v_priority_pipeline
order by collectability_tier, priority_level, judgment_amount desc
limit %s
"""

DISPLAY_COLUMNS: tuple[str, ...] = (
    "plaintiff_name",
    "collectability_tier",
    "priority_level",
    "judgment_amount",
    "stage",
    "plaintiff_status",
    "tier_rank",
    "judgment_id",
)


def fetch_priority_pipeline(
    limit: int = 50,
    *,
    env: str | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield ranked judgment rows from the priority pipeline view."""

    supabase_env = env or get_supabase_env()
    db_url = get_supabase_db_url(supabase_env)

    def _rows() -> Iterator[dict[str, Any]]:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(PIPELINE_QUERY, (limit,))
                description = cur.description or ()
                col_names = [desc[0] for desc in description]
                for record in cur.fetchall():
                    yield {col: value for col, value in zip(col_names, record)}

    return _rows()


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _print_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("[priority_pipeline] No judgments matched the current query.")
        return

    widths = {column: len(column) for column in DISPLAY_COLUMNS}
    for row in rows:
        for column in DISPLAY_COLUMNS:
            widths[column] = max(widths[column], len(_format_value(row.get(column))))

    header = " | ".join(f"{column:<{widths[column]}}" for column in DISPLAY_COLUMNS)
    print(header)
    print("-" * len(header))

    for row in rows:
        line = " | ".join(
            f"{_format_value(row.get(column)):<{widths[column]}}" for column in DISPLAY_COLUMNS
        )
        print(line)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.priority_pipeline",
        description="Inspect the ranked judgment pipeline (collectability + priority).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of rows to fetch (default: 50)",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Override SUPABASE_MODE / get_supabase_env()",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    rows = list(fetch_priority_pipeline(limit=args.limit, env=args.env))
    _print_rows(rows)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual CLI usage
    raise SystemExit(main())
