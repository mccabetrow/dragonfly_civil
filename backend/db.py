# backend/db.py

from __future__ import annotations

from typing import Any, Optional, Sequence

import psycopg
from loguru import logger
from psycopg.rows import dict_row

from supabase import Client, create_client

from .config import get_settings

settings = get_settings()

# We don't actually need a heavy connection pool yet.
# We just keep a single async connection for health checks, etc.
_db_conn: Optional[psycopg.AsyncConnection] = None
_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Lazily create and return a Supabase Python client that uses the
    SERVICE ROLE key. This is what the services use for RPC/views.
    """
    global _supabase_client
    if _supabase_client is None:
        logger.info("Creating Supabase client")
        _supabase_client = create_client(
            settings.supabase_url, settings.supabase_service_role_key
        )
    return _supabase_client


async def init_db_pool() -> None:
    """
    Called from FastAPI lifespan startup.

    We don't create a full pool – just open one async connection and
    run a trivial SELECT to verify the DB URL and credentials.
    """
    global _db_conn

    if _db_conn is not None:
        return

    if not settings.supabase_db_url:
        logger.warning("SUPABASE_DB_URL is not set; skipping DB init")
        return

    logger.info("Opening async PostgreSQL connection for health checks")
    _db_conn = await psycopg.AsyncConnection.connect(settings.supabase_db_url)
    # Simple ping
    async with _db_conn.cursor() as cur:
        await cur.execute("SELECT 1;")
        await cur.fetchone()
    logger.info("Database connection OK")


async def close_db_pool() -> None:
    """
    Called from FastAPI lifespan shutdown.
    """
    global _db_conn
    if _db_conn is not None:
        logger.info("Closing PostgreSQL connection")
        await _db_conn.close()
        _db_conn = None


async def ping_db() -> bool:
    """
    Used by /api/health/db to check live DB connectivity.
    """
    global _db_conn

    if _db_conn is None:
        # Lazily connect if init_db_pool wasn't called for some reason.
        await init_db_pool()

    if _db_conn is None:
        return False

    try:
        async with _db_conn.cursor() as cur:
            await cur.execute("SELECT 1 AS ok;")
            row = await cur.fetchone()
        return bool(row and row[0] == 1)
    except Exception as exc:
        logger.error(f"DB ping failed: {exc}")
        return False


async def fetch_one(
    query: str, params: Sequence[Any] | None = None
) -> Optional[dict[str, Any]]:
    """
    Convenience helper if any service wants to run a one-off SELECT.
    Not heavily used yet, but keeps the API similar to the old asyncpg version.
    """
    global _db_conn

    if _db_conn is None:
        await init_db_pool()

    if _db_conn is None:
        raise RuntimeError("Database connection is not initialized")

    async with _db_conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params or [])
        row = await cur.fetchone()
        return row
