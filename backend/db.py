# backend/db.py

from __future__ import annotations

from typing import Any, Optional, Sequence

import psycopg
from psycopg.rows import dict_row
from loguru import logger
from supabase import create_client, Client

from .config import get_settings

settings = get_settings()

# Single async connection used for health checks and simple queries.
_db_conn: Optional[psycopg.AsyncConnection] = None
_supabase_client: Optional[Client] = None


# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------


def get_supabase_client() -> Client:
    """
    Lazily create and return a Supabase Python client that uses the
    SERVICE ROLE key.
    """
    global _supabase_client
    if _supabase_client is None:
        logger.info("Creating Supabase client")
        _supabase_client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _supabase_client


# ---------------------------------------------------------------------------
# Low-level DB connection management (psycopg async)
# ---------------------------------------------------------------------------


async def init_db_pool(app: Any | None = None) -> None:
    """
    Called from FastAPI startup.

    We don't use a full pool here; just a single AsyncConnection that we reuse.
    `app` is accepted for FastAPI startup compatibility but is unused.
    """
    global _db_conn

    if _db_conn is not None:
        return

    if not settings.supabase_db_url:
        logger.warning("SUPABASE_DB_URL is not set; skipping DB init")
        return

    logger.info("Opening async PostgreSQL connection for health checks")
    _db_conn = await psycopg.AsyncConnection.connect(settings.supabase_db_url)

    # Simple ping to verify credentials & connectivity
    async with _db_conn.cursor() as cur:
        await cur.execute("SELECT 1;")
        await cur.fetchone()

    logger.info("Database connection OK")


async def close_db_pool() -> None:
    """
    Called from FastAPI shutdown.
    """
    global _db_conn
    if _db_conn is not None:
        logger.info("Closing PostgreSQL connection")
        await _db_conn.close()
        _db_conn = None


async def get_pool() -> Optional[psycopg.AsyncConnection]:
    """
    Backwards-compatible helper for code that expects a connection "pool".
    Returns the shared AsyncConnection (or None if DB URL isn't set).
    """
    global _db_conn

    if _db_conn is None:
        await init_db_pool()

    return _db_conn


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def ping_db() -> bool:
    """
    Used by /api/health/db to check live DB connectivity.
    """
    conn = await get_pool()
    if conn is None:
        return False

    try:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1 AS ok;")
            row = await cur.fetchone()
        return bool(row and row[0] == 1)
    except Exception as exc:
        logger.error(f"DB ping failed: {exc}")
        return False


async def fetch_one(
    query: str,
    params: Sequence[Any] | None = None,
) -> Optional[dict[str, Any]]:
    """
    Convenience helper returning a single row as a dict.
    """
    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection is not initialized")

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params or [])
        row = await cur.fetchone()
        return row


async def fetch_val(
    query: str,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Backwards-compatible version of the old asyncpg helper used in health.py.

    health.py may call this as:
        await fetch_val("SELECT 1")
    or possibly:
        pool = await get_pool()
        await fetch_val("SELECT 1", pool=pool)

    We accept and ignore any 'pool' argument and just use our global connection.
    """
    # Ignore optional 'pool' kwarg or first positional arg that looks like a pool
    kwargs.pop("pool", None)

    # If the first positional arg is clearly NOT part of the SQL params (i.e.
    # looks like a connection object), drop it.
    if args and not isinstance(args[0], (str, int, float, bytes, dict, list, tuple)):
        args = args[1:]

    conn = await get_pool()
    if conn is None:
        raise RuntimeError("Database connection is not initialized")

    async with conn.cursor() as cur:
        await cur.execute(query, args)
        row = await cur.fetchone()
        return None if row is None else row[0]
