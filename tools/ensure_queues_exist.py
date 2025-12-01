"""Ensure required pgmq queues exist in Supabase."""

from __future__ import annotations

from typing import Iterable

import psycopg

from tools.db_check import _build_db_url, _load_env

REQUIRED_QUEUES: tuple[str, ...] = ("enrich", "outreach", "enforce")


def _format_status(created: Iterable[tuple[str, bool]]) -> str:
    parts = []
    for name, did_create in created:
        label = "created" if did_create else "exists"
        parts.append(f"{name}:{label}")
    return ", ".join(parts)


def ensure_queues() -> None:
    _load_env()
    db_url, error = _build_db_url()
    if error:
        print(f"[ensure_queues] {error}")
        raise SystemExit(1)
    assert db_url is not None  # for mypy

    created_status: list[tuple[str, bool]] = []
    try:
        with psycopg.connect(db_url, autocommit=False) as conn:
            with conn.cursor() as cur:
                for queue in REQUIRED_QUEUES:
                    try:
                        cur.execute("select pgmq.create(queue_name => %s)", (queue,))
                        cur.fetchone()
                        created_status.append((queue, True))
                    except psycopg.errors.DuplicateObject:  # type: ignore[attr-defined]
                        created_status.append((queue, False))
                    except psycopg.errors.UndefinedFunction:  # type: ignore[attr-defined]
                        print(
                            "[ensure_queues] pgmq.create is unavailable. "
                            "Run `supabase db push` to apply 0052_queue_bootstrap.sql."
                        )
                        raise SystemExit(1)
                    except psycopg.Error as exc:
                        if exc.sqlstate in {"42710", "P0001"}:
                            created_status.append((queue, False))
                        else:
                            raise
                conn.commit()

                cur.execute("select queue_name from pgmq.list_queues() order by 1")
                rows = [row[0] for row in cur.fetchall()]
    except psycopg.errors.UndefinedFunction:  # type: ignore[attr-defined]
        print(
            "[ensure_queues] pgmq.list_queues is unavailable. "
            "Run `supabase db push` to apply 0052_queue_bootstrap.sql."
        )
        raise SystemExit(1)
    except psycopg.Error as exc:
        print(f"[ensure_queues] Database error: {exc}")
        raise SystemExit(1)

    print(f"[ensure_queues] { _format_status(created_status) }")
    print(f"[ensure_queues] queues present: {', '.join(rows)}")


if __name__ == "__main__":
    ensure_queues()
