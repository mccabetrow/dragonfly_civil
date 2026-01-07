# backend/core/db.py
"""
Lazy-Loaded Async Database Pool

This module provides a Database class that is strictly lazy-loaded:
- Config is prepared in __init__ but no connection is made
- Pool is only instantiated and opened when start() is called
- Eliminates psycopg_pool deprecation warnings about implicit open

Usage:
    db = Database(url=dsn, min_size=2, max_size=10)
    await db.start()       # Explicitly opens the pool

    async with db.get_connection() as conn:
        await conn.execute("SELECT 1")

    await db.stop()        # Closes the pool
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Optional

from loguru import logger
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from psycopg import AsyncConnection


class DatabaseNotStartedError(RuntimeError):
    """Raised when attempting to use the database before calling start()."""

    def __init__(self) -> None:
        super().__init__("Database pool not started. Did you forget to await db.start()?")


class Database:
    """
    Lazy-loaded async PostgreSQL connection pool.

    The pool is NOT instantiated in __init__. It is only created and opened
    when start() is explicitly called. This eliminates the psycopg_pool
    deprecation warning about implicit pool opening.

    Attributes:
        url: PostgreSQL connection string (DSN)
        min_size: Minimum number of connections to keep in the pool
        max_size: Maximum number of connections allowed
        pool: The underlying AsyncConnectionPool (None until start() is called)

    Example::

        db = Database(url="<dsn>", min_size=2, max_size=10)
        await db.start()
        async with db.get_connection() as conn:
            await conn.execute("SELECT 1")
        await db.stop()
    """

    __slots__ = ("url", "min_size", "max_size", "timeout", "max_lifetime", "pool", "_app_name")

    def __init__(
        self,
        url: str,
        *,
        min_size: int = 2,
        max_size: int = 10,
        timeout: float = 30.0,
        max_lifetime: float = 1800.0,
        app_name: Optional[str] = None,
    ) -> None:
        """
        Prepare database configuration. Does NOT open any connections.

        Args:
            url: PostgreSQL DSN (connection string)
            min_size: Minimum idle connections (default: 2)
            max_size: Maximum connections (default: 10)
            timeout: Seconds to wait for a connection from pool (default: 30)
            max_lifetime: Recycle connections after this many seconds (default: 1800)
            app_name: PostgreSQL application_name (default: auto-generated)
        """
        if not url:
            raise ValueError("Database URL cannot be empty")

        self.url = url
        self.min_size = min_size
        self.max_size = max_size
        self.timeout = timeout
        self.max_lifetime = max_lifetime
        self.pool: Optional[AsyncConnectionPool] = None  # NOT instantiated here

        # Generate safe application name (no spaces/dots for PostgreSQL option parsing)
        if app_name:
            self._app_name = app_name.replace(".", "_").replace(" ", "_").replace("-", "_")
        else:
            # Default: dragonfly_backend
            self._app_name = "dragonfly_backend"

        logger.debug(
            "Database configured (pool not yet open)",
            min_size=self.min_size,
            max_size=self.max_size,
            app_name=self._app_name,
        )

    @property
    def is_open(self) -> bool:
        """Return True if the pool is open and ready for connections."""
        return self.pool is not None

    async def start(self) -> None:
        """
        Instantiate and open the connection pool.

        This is where the pool is actually created. Before this call,
        self.pool is None and no database connections exist.

        Raises:
            RuntimeError: If pool is already started
            Exception: If connection to database fails
        """
        if self.pool is not None:
            logger.warning("Database pool already started, skipping")
            return

        logger.info("🔌 Starting database pool...")

        # Create pool with open=False (explicit lifecycle)
        self.pool = AsyncConnectionPool(
            conninfo=self.url,
            min_size=self.min_size,
            max_size=self.max_size,
            timeout=self.timeout,
            max_lifetime=self.max_lifetime,
            open=False,  # Critical: NO implicit open in constructor
            kwargs={
                "application_name": self._app_name,
                "connect_timeout": 5,  # Fail fast if DB unreachable
            },
        )

        # Explicitly open the pool
        await self.pool.open()

        # Verify connectivity with a simple ping
        async with self.pool.connection() as conn:
            result = await conn.execute("SELECT 1")
            row = await result.fetchone()
            if row is None or row[0] != 1:
                raise RuntimeError("Database ping failed: SELECT 1 did not return 1")

        logger.info("🔌 Database Pool Opened")

    async def stop(self) -> None:
        """
        Close the connection pool and release all connections.

        Safe to call multiple times. After stop(), the pool must be
        started again with start() before use.
        """
        if self.pool is None:
            logger.debug("Database pool not open, nothing to close")
            return

        logger.info("🔌 Closing database pool...")
        await self.pool.close()
        self.pool = None
        logger.info("🔌 Database Pool Closed")

    @asynccontextmanager
    async def get_connection(self) -> AsyncIterator["AsyncConnection[tuple]"]:
        """
        Get a database connection from the pool.

        Yields:
            AsyncConnection: A psycopg async connection

        Raises:
            DatabaseNotStartedError: If start() was not called
            PoolTimeout: If no connection available within timeout

        Example:
            async with db.get_connection() as conn:
                result = await conn.execute("SELECT * FROM users")
                rows = await result.fetchall()
        """
        if self.pool is None:
            raise DatabaseNotStartedError()

        async with self.pool.connection() as conn:
            yield conn

    async def execute(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> None:
        """
        Execute a query without returning results.

        Convenience method for INSERT/UPDATE/DELETE operations.

        Args:
            query: SQL query string
            params: Query parameters (optional)
        """
        async with self.get_connection() as conn:
            if params:
                await conn.execute(query, params)
            else:
                await conn.execute(query)

    async def fetch_one(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> Optional[tuple]:
        """
        Execute a query and return the first row.

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            First row as tuple, or None if no results
        """
        async with self.get_connection() as conn:
            if params:
                result = await conn.execute(query, params)
            else:
                result = await conn.execute(query)
            return await result.fetchone()

    async def fetch_all(
        self,
        query: str,
        params: Optional[tuple] = None,
    ) -> list[tuple]:
        """
        Execute a query and return all rows.

        Args:
            query: SQL query string
            params: Query parameters (optional)

        Returns:
            List of rows as tuples
        """
        async with self.get_connection() as conn:
            if params:
                result = await conn.execute(query, params)
            else:
                result = await conn.execute(query)
            return await result.fetchall()

    async def ping(self) -> bool:
        """
        Check if the database connection is healthy.

        Returns:
            True if SELECT 1 succeeds, False otherwise
        """
        if self.pool is None:
            return False

        try:
            async with self.pool.connection() as conn:
                result = await conn.execute("SELECT 1")
                row = await result.fetchone()
                return row is not None and row[0] == 1
        except Exception as e:
            logger.warning(f"Database ping failed: {e}")
            return False

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        return f"<Database pool={status} min={self.min_size} max={self.max_size}>"


# ---------------------------------------------------------------------------
# Singleton instance for FastAPI lifespan
# ---------------------------------------------------------------------------

_default_db: Optional[Database] = None


def get_database() -> Database:
    """
    Get the default database instance.

    The instance is created lazily on first call, but the pool
    is NOT opened until start() is called.

    Returns:
        Database: The singleton database instance

    Raises:
        ValueError: If SUPABASE_DB_URL is not configured
    """
    global _default_db

    if _default_db is None:
        url = os.environ.get("SUPABASE_DB_URL")
        if not url:
            raise ValueError("SUPABASE_DB_URL environment variable is not set")

        _default_db = Database(
            url=url,
            min_size=2,
            max_size=10,
            timeout=30.0,
            max_lifetime=1800.0,
        )

    return _default_db


async def startup_database() -> None:
    """
    FastAPI lifespan startup hook.

    Call this in your FastAPI lifespan context to open the database pool.

    Example:
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await startup_database()
            yield
            await shutdown_database()
    """
    db = get_database()
    await db.start()


async def shutdown_database() -> None:
    """
    FastAPI lifespan shutdown hook.

    Call this in your FastAPI lifespan context to close the database pool.
    """
    global _default_db

    if _default_db is not None:
        await _default_db.stop()
        _default_db = None
