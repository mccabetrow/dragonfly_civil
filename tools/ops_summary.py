from __future__ import annotations

import argparse
from typing import Any, Dict, List

import psycopg

from src.supabase_client import get_supabase_db_url, get_supabase_env

SUMMARY_QUERY = """
select summary_date,
       new_plaintiffs,
       plaintiffs_contacted,
       calls_made,
       agreements_sent,
       agreements_signed
from public.v_ops_daily_summary
"""

DISPLAY_FIELDS: tuple[tuple[str, str], ...] = (
    ("summary_date", "DATE"),
    ("new_plaintiffs", "new_plaintiffs"),
    ("plaintiffs_contacted", "contacted"),
    ("calls_made", "calls"),
    ("agreements_sent", "agreements_sent"),
    ("agreements_signed", "agreements_signed"),
)


def fetch_ops_summary(*, env: str | None = None) -> List[Dict[str, Any]]:
    """Return the current ops summary rows."""

    supabase_env = env or get_supabase_env()
    db_url = get_supabase_db_url(supabase_env)

    with psycopg.connect(db_url, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute(SUMMARY_QUERY)
            description = cur.description or ()
            columns = [desc[0] for desc in description]
            rows: List[Dict[str, Any]] = []
            for record in cur.fetchall():
                rows.append({col: value for col, value in zip(columns, record)})
    return rows


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _print_summary(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("[ops_summary] v_ops_daily_summary returned no rows.")
        return

    header = " | ".join(title for _, title in DISPLAY_FIELDS)
    print(header)
    print("-" * len(header))

    row = rows[0]
    line = " | ".join(_format_value(row.get(field)) for field, _ in DISPLAY_FIELDS)
    print(line)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tools.ops_summary",
        description="Show the current ops daily summary row.",
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
    rows = fetch_ops_summary(env=args.env)
    _print_summary(rows)
    return 0


if __name__ == "__main__":  # pragma: no cover - manual CLI usage
    raise SystemExit(main())
