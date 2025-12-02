"""Direct Supabase migration runner for production fallback."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg

MIGRATIONS_TABLE = "public.dragonfly_migrations"
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"


def _get_db_url() -> str:
    db_url = os.getenv("SUPABASE_DB_URL_DIRECT_PROD")
    if not db_url:
        print(
            "[FAIL] SUPABASE_DB_URL_DIRECT_PROD is not set in the environment.",
            file=sys.stderr,
        )
        sys.exit(1)
    return db_url


def _ensure_table(conn: psycopg.Connection) -> None:
    create_sql = f"""
    create table if not exists {MIGRATIONS_TABLE} (
        migration_filename text primary key,
        applied_at timestamptz not null default timezone('utc', now())
    );
    """
    with conn.cursor() as cur:
        cur.execute(create_sql, prepare=False)


def _load_applied(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            f"select migration_filename from {MIGRATIONS_TABLE}",
            prepare=False,
        )
        return {row[0] for row in cur.fetchall()}


def _seed_from_supabase_history(
    conn: psycopg.Connection, applied: set[str]
) -> set[str]:
    check_sql = "select to_regclass('supabase_migrations.schema_migrations')"
    with conn.cursor() as cur:
        cur.execute(check_sql, prepare=False)
        row = cur.fetchone()
        exists = row[0] if row else None
    if not exists:
        return applied

    with conn.cursor() as cur:
        cur.execute(
            "select name from supabase_migrations.schema_migrations",
            prepare=False,
        )
        supabase_rows = [row[0] for row in cur.fetchall() if row[0]]

    if not supabase_rows:
        return applied

    with conn.cursor() as cur:
        for name in supabase_rows:
            if name in applied:
                continue
            cur.execute(
                f"""
                insert into {MIGRATIONS_TABLE} (migration_filename, applied_at)
                values (%s, %s)
                on conflict (migration_filename) do nothing
                """,
                (name, datetime.now(timezone.utc)),
                prepare=False,
            )
            applied.add(name)
    return applied


def _iter_migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.is_dir():
        print(
            f"[FAIL] Migrations directory not found: {MIGRATIONS_DIR}", file=sys.stderr
        )
        sys.exit(1)
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def apply_migrations() -> int:
    migrations = _iter_migration_files()
    if not migrations:
        print("[INFO] No migration files found; nothing to do.")
        return 0

    db_url = _get_db_url()

    try:
        with psycopg.connect(db_url) as conn:
            _ensure_table(conn)
            applied = _load_applied(conn)
            applied = _seed_from_supabase_history(conn, applied)

            applied_count = 0
            skipped_count = 0

            for path in migrations:
                name = path.name
                if name in applied:
                    skipped_count += 1
                    continue

                sql_text = path.read_text(encoding="utf-8")
                if not sql_text.strip():
                    print(f"[WARN] Skipping empty migration {name}")
                    skipped_count += 1
                    continue

                print(f"[INFO] Applying migration {name}")

                try:
                    with conn.transaction():
                        with conn.cursor() as cur:
                            cur.execute(sql_text, prepare=False)  # type: ignore[arg-type]
                            cur.execute(
                                f"""
                                insert into {MIGRATIONS_TABLE} (migration_filename, applied_at)
                                values (%s, %s)
                                """,
                                (name, datetime.now(timezone.utc)),
                                prepare=False,
                            )
                    applied_count += 1
                except Exception as exc:  # noqa: BLE001
                    print(
                        f"[FAIL] Migration {name} failed: {exc}",
                        file=sys.stderr,
                    )
                    return 1

            print(
                f"[OK] Applied {applied_count} migrations; {skipped_count} already up-to-date.",
            )
            return 0
    except psycopg.Error as exc:
        print(f"[FAIL] Could not connect or run migrations: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    sys.exit(apply_migrations())


if __name__ == "__main__":
    main()
