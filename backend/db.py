# backend/db.py

from __future__ import annotations

# Must be early - fixes Windows asyncio compatibility with psycopg3
from .asyncio_compat import ensure_selector_policy_on_windows

ensure_selector_policy_on_windows()

from contextlib import asynccontextmanager  # noqa: E402
from typing import Any, AsyncGenerator, Optional, Sequence  # noqa: E402

import psycopg  # noqa: E402
from loguru import logger  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402

from supabase import Client, create_client  # noqa: E402

from .config import get_settings  # noqa: E402

settings = get_settings()

# Async connection pool for database operations
_db_pool: Optional[AsyncConnectionPool] = None
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
        # Cast HttpUrl to str for Pydantic v2 compatibility
        _supabase_client = create_client(
            str(settings.supabase_url),
            settings.supabase_service_role_key,
        )
    return _supabase_client


# ---------------------------------------------------------------------------
# Low-level DB connection management (psycopg async)
# ---------------------------------------------------------------------------


async def init_db_pool(app: Any | None = None) -> None:
    """
    Called from FastAPI startup.

    Initializes an async connection pool for database operations.
    `app` is accepted for FastAPI startup compatibility but is unused.
    """
    global _db_pool

    if _db_pool is not None:
        return

    if not settings.supabase_db_url:
        logger.warning("SUPABASE_DB_URL is not set; skipping DB init")
        return

    logger.info("Initializing async PostgreSQL connection pool")
    _db_pool = AsyncConnectionPool(
        settings.supabase_db_url,
        min_size=2,
        max_size=10,
        kwargs={"options": "-c application_name='Dragonfly v1.3.1'"},
    )
    await _db_pool.open()

    # Simple ping to verify credentials & connectivity
    async with _db_pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1;")
            await cur.fetchone()

    logger.info("Database connection pool initialized OK")


async def close_db_pool() -> None:
    """
    Called from FastAPI shutdown.
    """
    global _db_pool
    if _db_pool is not None:
        logger.info("Closing PostgreSQL connection pool")
        await _db_pool.close()
        _db_pool = None


async def get_pool() -> Optional[AsyncConnectionPool]:
    """
    Returns the async connection pool.

    Callers can use:
        pool = await get_pool()
        async with pool.connection() as conn:
            ...
    """
    global _db_pool

    if _db_pool is None:
        await init_db_pool()

    return _db_pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator["AsyncConnectionWrapper", None]:
    """
    Get a database connection for use in a context manager.

    This provides backwards compatibility with code that uses:
        async with get_connection() as conn:
            rows = await conn.fetch("SELECT ...")

    The wrapper provides fetch/fetchrow/execute methods that work
    similarly to asyncpg's Connection interface.
    """
    pool = await get_pool()
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")

    async with pool.connection() as conn:
        wrapper = AsyncConnectionWrapper(conn)
        yield wrapper


def _convert_asyncpg_placeholders(query: str) -> str:
    """
    Convert asyncpg-style $1, $2, ... placeholders to psycopg3-style %s.

    This provides backward compatibility for code migrated from asyncpg.
    Only converts if $1-style placeholders are detected and %s are not present.
    """
    import re

    # If query already uses %s, don't convert
    if "%s" in query:
        return query

    # Check if query uses $N placeholders
    if not re.search(r"\$\d+", query):
        return query

    # Replace $1, $2, etc. with %s (psycopg3 uses positional %s)
    converted = re.sub(r"\$\d+", "%s", query)
    return converted


class AsyncConnectionWrapper:
    """
    Wrapper around psycopg.AsyncConnection that provides asyncpg-like interface.

    Provides fetch(), fetchrow(), and execute() methods that match asyncpg's API.
    Automatically converts $1, $2 style placeholders to %s for psycopg3.
    """

    def __init__(self, conn: psycopg.AsyncConnection):
        self._conn = conn

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Fetch all rows as a list of dicts."""
        query = _convert_asyncpg_placeholders(query)
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, args or None)
            rows = await cur.fetchall()
            return list(rows) if rows else []

    async def fetchrow(self, query: str, *args: Any) -> Optional[dict[str, Any]]:
        """Fetch a single row as a dict."""
        query = _convert_asyncpg_placeholders(query)
        async with self._conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, args or None)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Fetch a single value."""
        query = _convert_asyncpg_placeholders(query)
        async with self._conn.cursor() as cur:
            await cur.execute(query, args or None)
            row = await cur.fetchone()
            return row[0] if row else None

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a query without returning results."""
        query = _convert_asyncpg_placeholders(query)
        async with self._conn.cursor() as cur:
            await cur.execute(query, args or None)
            return cur.statusmessage or ""

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None, None]:
        """
        Context manager for a database transaction.

        Note: psycopg3 auto-commits, so we need to use a transaction block.
        """
        async with self._conn.transaction():
            yield


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


async def ping_db() -> bool:
    """
    Used by /api/health/db to check live DB connectivity.
    """
    pool = await get_pool()
    if pool is None:
        return False

    try:
        async with pool.connection() as conn:
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
    pool = await get_pool()
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")

    async with pool.connection() as conn:
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

    We accept and ignore any 'pool' argument and just use our global connection pool.
    """
    # Ignore optional 'pool' kwarg or first positional arg that looks like a pool
    kwargs.pop("pool", None)

    # If the first positional arg is clearly NOT part of the SQL params (i.e.
    # looks like a connection object), drop it.
    if args and not isinstance(args[0], (str, int, float, bytes, dict, list, tuple)):
        args = args[1:]

    pool = await get_pool()
    if pool is None:
        raise RuntimeError("Database connection pool is not initialized")

    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(query, args)
            row = await cur.fetchone()
            return None if row is None else row[0]


# ---------------------------------------------------------------------------
# Sync connection for FastAPI Depends
# ---------------------------------------------------------------------------


def get_db_connection():
    """
    Sync generator that yields a psycopg connection for FastAPI Depends.

    Usage:
        @router.get("/endpoint")
        async def endpoint(conn: psycopg.Connection = Depends(get_db_connection)):
            with conn.cursor() as cur:
                cur.execute("SELECT ...")
    """
    s = get_settings()
    dsn = s.supabase_db_url
    if not dsn:
        raise RuntimeError("SUPABASE_DB_URL not configured")

    conn = psycopg.connect(dsn)
    try:
        yield conn
    finally:
        conn.close()
