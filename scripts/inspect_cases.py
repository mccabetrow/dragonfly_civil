"""Read-only helpers for inspecting demo cases in Supabase.

Usage examples (run from the project root):
    python -m scripts.inspect_cases summary
    python -m scripts.inspect_cases demo

Both subcommands connect using the configured Supabase **read-only** URL and
print lightweight tables that help demo operators confirm what is stored in
`judgments.cases` along with related party and judgment counts.
"""

from __future__ import annotations

import argparse
from typing import Iterable, Sequence

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url


def _connect() -> psycopg.Connection:
    """Return a read-only connection to the Supabase Postgres database."""

    db_url = get_supabase_db_url()
    # Enforce a read-only session for safety.
    return psycopg.connect(db_url, options="-c default_transaction_read_only=on")


def _format_created_at(value: object) -> str:
    if value is None:
        return "<unknown>"
    if hasattr(value, "isoformat"):
        return value.isoformat()  # type: ignore[arg-type]
    return str(value)


def _print_table(
    rows: Iterable[dict[str, object]], *, columns: Sequence[tuple[str, str]]
) -> None:
    headers = [title for _, title in columns]
    extracted_rows = []
    for row in rows:
        extracted_rows.append([str(row.get(key, "")) for key, _ in columns])

    if not extracted_rows:
        print("(no rows)")
        return

    widths = [len(header) for header in headers]
    for extracted in extracted_rows:
        for idx, cell in enumerate(extracted):
            widths[idx] = max(widths[idx], len(cell))

    def _render(values: Sequence[str]) -> str:
        return "  ".join(value.ljust(widths[idx]) for idx, value in enumerate(values))

    print(_render(headers))
    print(_render(["-" * width for width in widths]))
    for extracted in extracted_rows:
        print(_render(extracted))


def _handle_summary() -> None:
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select case_id::text as case_id,
                   case_number,
                   created_at
            from judgments.cases
            order by created_at desc nulls last
            limit 5
            """
        )
        rows = cur.fetchall()

    for row in rows:
        row["created_at"] = _format_created_at(row.get("created_at"))

    print("Latest cases (up to 5):")
    _print_table(
        rows,
        columns=[
            ("case_id", "case_id"),
            ("case_number", "case_number"),
            ("created_at", "created_at"),
        ],
    )


def _handle_demo() -> None:
    with _connect() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select c.case_id::text as case_id,
                   c.case_number,
                   c.created_at,
                   count(distinct j.id) as judgments_count,
                   count(distinct p.id) as parties_count
            from judgments.cases c
            left join judgments.judgments j on j.case_id = c.id
            left join judgments.parties p on p.case_id = c.id
            where c.case_number like %s
            group by c.case_id, c.case_number, c.created_at
            order by c.created_at desc nulls last
            """,
            ("DEMO-%",),
        )
        rows = cur.fetchall()

    for row in rows:
        row["created_at"] = _format_created_at(row.get("created_at"))

    print("Demo cases with related row counts:")
    _print_table(
        rows,
        columns=[
            ("case_id", "case_id"),
            ("case_number", "case_number"),
            ("created_at", "created_at"),
            ("judgments_count", "judgments"),
            ("parties_count", "parties"),
        ],
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Supabase judgments cases")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("summary", help="show the latest five cases")
    subparsers.add_parser("demo", help="list demo cases with related counts")

    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "summary":
        _handle_summary()
    elif args.command == "demo":
        _handle_demo()
    else:  # pragma: no cover - argparse enforces valid subcommands
        raise RuntimeError(f"Unknown command: {args.command}")

    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())
