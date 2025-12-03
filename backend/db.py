"""
Dragonfly Engine - Database Layer

Async Postgres connection pool using asyncpg.
Also provides a thin Supabase HTTP client for REST API calls.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import asyncpg
import httpx

from .config import Settings, get_settings

logger = logging.getLogger(__name__)

# Global connection pool
_pool: asyncpg.Pool | None = None


async def init_db_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """
    Initialize the async database connection pool.

    Args:
        settings: Application settings (uses default if not provided)

    Returns:
        asyncpg.Pool: The connection pool
    """
    global _pool

    if settings is None:
        settings = get_settings()

    if _pool is not None:
        logger.warning("Database pool already initialized")
        return _pool

    logger.info("Initializing database connection pool...")

    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.supabase_db_url,
            min_size=2,
            max_size=10,
            max_inactive_connection_lifetime=300,  # 5 minutes
            command_timeout=60,
        )
        logger.info("Database pool initialized successfully")
        return _pool
    except Exception as e:
        logger.error(f"Failed to initialize database pool: {e}")
        raise


async def close_db_pool() -> None:
    """
    Close the database connection pool.
    """
    global _pool

    if _pool is not None:
        logger.info("Closing database connection pool...")
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    """
    Get the current database pool.

    Raises:
        RuntimeError: If pool is not initialized
    """
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db_pool() first.")
    return _pool


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Get a database connection from the pool.

    Usage:
        async with get_connection() as conn:
            result = await conn.fetch("SELECT * FROM users")
    """
    pool = get_pool()
    async with pool.acquire() as connection:
        yield connection


async def execute_query(query: str, *args: Any) -> str:
    """
    Execute a query that doesn't return rows.

    Returns:
        Status string (e.g., "INSERT 0 1")
    """
    async with get_connection() as conn:
        return await conn.execute(query, *args)


async def fetch_all(query: str, *args: Any) -> list[asyncpg.Record]:
    """
    Fetch all rows from a query.
    """
    async with get_connection() as conn:
        return await conn.fetch(query, *args)


async def fetch_one(query: str, *args: Any) -> asyncpg.Record | None:
    """
    Fetch a single row from a query.
    """
    async with get_connection() as conn:
        return await conn.fetchrow(query, *args)


async def fetch_val(query: str, *args: Any) -> Any:
    """
    Fetch a single value from a query.
    """
    async with get_connection() as conn:
        return await conn.fetchval(query, *args)


# =============================================================================
# Supabase HTTP Client
# =============================================================================


class SupabaseClient:
    """
    Thin async HTTP client for Supabase REST API.

    Use this for operations that should go through PostgREST/RLS,
    or when you need Supabase-specific features like Storage.
    """

    def __init__(self, settings: Settings | None = None):
        if settings is None:
            settings = get_settings()

        self.base_url = str(settings.supabase_url).rstrip("/")
        self.headers = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SupabaseClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SupabaseClient not initialized. Use async with.")
        return self._client

    async def rpc(
        self, function_name: str, params: dict[str, Any] | None = None
    ) -> Any:
        """
        Call a Supabase RPC function.

        Args:
            function_name: Name of the Postgres function
            params: Parameters to pass to the function

        Returns:
            The function result
        """
        response = await self.client.post(
            f"/rest/v1/rpc/{function_name}",
            json=params or {},
        )
        response.raise_for_status()
        return response.json()

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Select rows from a table.

        Args:
            table: Table name
            columns: Columns to select (default: *)
            filters: Query filters as key-value pairs

        Returns:
            List of rows
        """
        params = {"select": columns}
        if filters:
            for key, value in filters.items():
                params[key] = f"eq.{value}"

        response = await self.client.get(f"/rest/v1/{table}", params=params)
        response.raise_for_status()
        return response.json()

    async def insert(
        self,
        table: str,
        data: dict[str, Any] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Insert rows into a table.
        """
        response = await self.client.post(f"/rest/v1/{table}", json=data)
        response.raise_for_status()
        return response.json()

    async def update(
        self,
        table: str,
        data: dict[str, Any],
        match: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Update rows in a table.
        """
        params = {k: f"eq.{v}" for k, v in match.items()}
        response = await self.client.patch(
            f"/rest/v1/{table}",
            params=params,
            json=data,
        )
        response.raise_for_status()
        return response.json()


# Convenience function for one-off Supabase calls
async def supabase_rpc(function_name: str, params: dict[str, Any] | None = None) -> Any:
    """
    Quick helper to call a Supabase RPC function.
    """
    async with SupabaseClient() as client:
        return await client.rpc(function_name, params)
