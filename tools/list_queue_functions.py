from __future__ import annotations

import os
from typing import Iterable, Sequence
from urllib.parse import urlparse

import psycopg

try:  # Prefer python-dotenv when available, keep optional.
    from dotenv import load_dotenv  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()  # Loads values from .env into the current environment.


def _project_ref_from_url(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not host:
        return ""
    return host.split(".")[0]


def _build_db_url() -> str:
    explicit = os.getenv("SUPABASE_DB_URL")
    if explicit:
        return explicit

    password = os.getenv("SUPABASE_DB_PASSWORD")
    project_ref = os.getenv("SUPABASE_PROJECT_REF")
    if not project_ref:
        project_ref = _project_ref_from_url(os.getenv("SUPABASE_URL"))

    if not password:
        # Fallback to service role key if no dedicated DB password is set.
        password = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not project_ref or not password:
        raise RuntimeError(
            "SUPABASE_DB_URL or (SUPABASE_PROJECT_REF + SUPABASE_DB_PASSWORD) must be configured."
        )

    return f"postgresql://postgres:{password}@db.{project_ref}.supabase.co:5432/postgres"


def _format_row(row: Sequence[object]) -> str:
    schema, name, argnames, argtypes = row
    argnames = list(argnames or [])
    argtypes = list(argtypes or [])
    def _stringify(items: Iterable[object]) -> str:
        return ",".join(str(item) for item in items)

    return f"{schema}.{name}({{{_stringify(argnames)}}}: {{{_stringify(argtypes)}}})"


def list_queue_functions() -> None:
    _load_env()
    db_url = _build_db_url()

    query = """
        select
          n.nspname as schema,
          p.proname as name,
          p.proargnames,
          p.proargtypes::regtype[] as argtypes
        from pg_proc p
        join pg_namespace n on n.oid = p.pronamespace
        where n.nspname = 'public'
          and p.proname = 'queue_job'
        order by 1, 2
    """

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()

    if not rows:
        print("No queue_job functions found.")
        return

    for row in rows:
        print(_format_row(row))


if __name__ == "__main__":
    list_queue_functions()
