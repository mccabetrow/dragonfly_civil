"""Trigger a PostgREST schema cache reload for Supabase.

This module triggers a schema cache reload using the standard PostgreSQL
NOTIFY mechanism. PostgREST listens for 'pgrst' notifications and reloads
its schema cache when one is received.

Usage:
    python -m tools.pgrst_reload
"""

from __future__ import annotations

import sys

import psycopg

from src.supabase_client import get_supabase_db_url, get_supabase_env


def _reload_schema_via_notify(db_url: str) -> bool:
    """Send NOTIFY pgrst to trigger PostgREST schema cache reload."""
    try:
        with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("NOTIFY pgrst")
        return True
    except psycopg.Error as e:
        print(f"[pgrst_reload] Database error: {e}", file=sys.stderr)
        return False


def main() -> None:
    env = get_supabase_env()
    db_url = get_supabase_db_url(env)

    if not db_url:
        print(
            "[pgrst_reload] Missing database URL. Check SUPABASE_DB_URL.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[pgrst_reload] Sending NOTIFY pgrst to {env} database...")

    if _reload_schema_via_notify(db_url):
        print("[pgrst_reload] ✅ PostgREST Schema Cache Reloaded via NOTIFY")
        sys.exit(0)
    else:
        print("[pgrst_reload] Failed to reload schema cache", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
