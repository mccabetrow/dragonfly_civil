"""Connectivity check for Supabase Postgres pooler."""

from __future__ import annotations

import os

import psycopg

try:  # Prefer python-dotenv when available.
    from dotenv import load_dotenv  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    load_dotenv = None


def _load_env() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _project_ref_from_url(url: str | None) -> str:
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    prefix = "https://"
    if url.startswith(prefix):
        url = url[len(prefix) :]
    return url.split(".")[0]


def _build_db_url() -> tuple[str | None, str | None]:
    explicit = os.getenv("SUPABASE_DB_URL")
    if explicit:
        return explicit, None

    password = os.getenv("SUPABASE_DB_PASSWORD")
    project_ref = os.getenv("SUPABASE_PROJECT_REF")

    if not project_ref:
        project_ref = _project_ref_from_url(os.getenv("SUPABASE_URL"))

    if not password or not project_ref:
        return None, (
            "Missing configuration. Set SUPABASE_DB_URL or "
            "SUPABASE_DB_PASSWORD and SUPABASE_PROJECT_REF/SUPABASE_URL."
        )

    db_url = (
        "postgresql://postgres:{password}@"
        "aws-1-us-east-2.pooler.supabase.com:5432/postgres"
        "?user=postgres.{project_ref}&sslmode=require"
    ).format(password=password, project_ref=project_ref)
    return db_url, None


def _classify_error(message: str) -> str:
    lowered = message.lower()
    if any(token in lowered for token in ("timeout", "could not translate host name", "connection refused")):
        return f"[db_check] Network or pooler issue: {message}"
    if any(token in lowered for token in ("password", "authentication")):
        return (
            "[db_check] Authentication error: check SUPABASE_DB_URL / "
            "SUPABASE_DB_PASSWORD / SUPABASE_PROJECT_REF."
        )
    return f"[db_check] Unexpected database error: {message}"


def main() -> None:
    _load_env()

    db_url, error = _build_db_url()
    if error:
        print(f"[db_check] {error}")
        raise SystemExit(1)

    assert db_url is not None  # for type checkers

    try:
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("select now()")
                cur.fetchone()
        print("[db_check] Success: connected to Supabase Postgres and executed a test query.")
    except psycopg.Error as exc:
        message = str(exc).strip()
        print(_classify_error(message))
        raise SystemExit(1)
    except Exception as exc:  # pragma: no cover - fallback for unexpected failures
        message = str(exc).strip()
        print(f"[db_check] Unexpected database error: {message}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
