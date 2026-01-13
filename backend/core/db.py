# backend/core/db.py
"""
Dragonfly Civil - "Polite" Async Database Pool

DESIGN GOALS:
=============
1. LAZY LOADING: Pool is NOT instantiated in __init__. Only when start() is called.
2. EXPONENTIAL BACKOFF WITH JITTER: Connection retries with 1s → 2s → 4s → 8s... up to 30s max.
3. KILL SWITCH: Immediate sys.exit(1) on authentication failures to prevent Supabase lockouts.
4. QUIET LOGGING: Avoid noisy logs during outages that look like a DDoS attack.
5. ENV-DRIVEN POOL SIZE: Read DB_POOL_SIZE from environment (default: 1 for workers, 5 for API).
6. SSL ENFORCEMENT: Always ensures sslmode=require for production security.

CRITICAL - THE "KILL SWITCH":
==============================
Supabase pooler (PgBouncer) triggers "server_login_retry" lockouts after repeated
failed authentication attempts. This locks the ENTIRE PROJECT for up to 30 minutes.

To prevent this, we IMMEDIATELY exit on:
- "password authentication failed"
- "FATAL:" (PostgreSQL FATAL errors include auth failures)
- Role/database does not exist

DO NOT RETRY invalid credentials. Log CRITICAL and sys.exit(1).
Network errors (connection refused, timeout) are safe to retry with backoff.

Usage:
    db = Database(url=dsn)
    await db.start()       # Opens pool with exponential backoff

    async with db.get_connection() as conn:
        await conn.execute("SELECT 1")

    await db.stop()        # Closes the pool
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import sys
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from loguru import logger
from psycopg_pool import AsyncConnectionPool

if TYPE_CHECKING:
    from psycopg import AsyncConnection


# =============================================================================
# Configuration Constants
# =============================================================================

# Exponential backoff settings
INITIAL_RETRY_DELAY = 1.0  # Start with 1 second
MAX_RETRY_DELAY = 30.0  # Cap at 30 seconds
MAX_RETRY_ATTEMPTS = 10  # Give up after 10 attempts (~2 minutes total)
JITTER_FACTOR = 0.3  # Add up to 30% jitter to prevent thundering herd

# Default pool sizes - WORKERS GET 1 CONNECTION (polite to Supabase limits)
DEFAULT_API_POOL_SIZE = 5  # For API servers
DEFAULT_WORKER_POOL_SIZE = 1  # For worker processes (single connection)

# Authentication failure patterns - IMMEDIATE EXIT to prevent lockouts
# These patterns trigger sys.exit(1) on FIRST occurrence - NO RETRIES
AUTH_FAILURE_PATTERNS = (
    "password authentication failed",
    "fatal:",  # PostgreSQL FATAL errors (includes auth, shutdown, etc.)
    "authentication failed",
    "no pg_hba.conf entry",
    "server_login_retry",  # Supabase-specific lockout indicator
)

# Config/setup failures that also shouldn't be retried
CONFIG_FAILURE_PATTERNS = (
    r"role .* does not exist",
    r"database .* does not exist",
)

# Network failures - safe to retry with backoff
NETWORK_FAILURE_PATTERNS = (
    "connection refused",
    "could not connect to server",
    "connection timed out",
    "timeout expired",
    "network is unreachable",
    "could not translate host name",
    "temporary failure in name resolution",
)


# =============================================================================
# Worker Detection
# =============================================================================


def _is_worker_process() -> bool:
    """
    Detect if we're running as a worker process (should use minimal pool).

    Workers only need 1 connection. API servers can use more.
    Detection order:
    1. WORKER_MODE env var (explicit)
    2. DB_POOL_SIZE env var (if set to 1)
    3. Process name heuristics (worker, celery, ingest, etc.)
    """
    # Explicit env var takes precedence
    if os.getenv("WORKER_MODE", "").lower() in ("1", "true", "yes"):
        return True

    # If DB_POOL_SIZE is explicitly 1, treat as worker
    pool_size = os.getenv("DB_POOL_SIZE", "")
    if pool_size == "1":
        return True

    # Heuristics: check if invoked as a worker module
    script = sys.argv[0] if sys.argv else ""
    worker_patterns = (
        "worker",
        "celery",
        "rq",
        "dramatiq",
        "ingest",
        "watcher",
        "scheduler",
        "cron",
    )
    return any(p in script.lower() for p in worker_patterns)


# =============================================================================
# DSN Helpers
# =============================================================================


def _parse_dsn_info(dsn: str) -> dict[str, str | None]:
    """
    Parse DSN and extract loggable components (never includes password).

    Returns dict with host, port, dbname, user, sslmode.
    """
    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)
        sslmode = query_params.get("sslmode", ["not_set"])[0]

        return {
            "host": parsed.hostname,
            "port": str(parsed.port) if parsed.port else "5432",
            "dbname": parsed.path.lstrip("/") if parsed.path else None,
            "user": parsed.username,
            "sslmode": sslmode,
        }
    except Exception as e:
        return {"error": str(e)}


def _ensure_sslmode(dsn: str) -> str:
    """
    Ensure sslmode=require is present in the DSN.

    If sslmode is not set or set to a weaker mode, upgrade to require.
    """
    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)

        current_sslmode = query_params.get("sslmode", [None])[0]
        weak_modes = {"disable", "allow", "prefer"}

        if current_sslmode is None or current_sslmode in weak_modes:
            query_params["sslmode"] = ["require"]
            new_query = urlencode(query_params, doseq=True)
            new_parsed = parsed._replace(query=new_query)
            return urlunparse(new_parsed)

        return dsn
    except Exception:
        # If parsing fails, return original (connection will fail anyway)
        return dsn


def _get_sha_short() -> str:
    """Get short git SHA from environment (8 chars)."""
    # Check environment variables in priority order
    env_vars = [
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "GITHUB_SHA",
        "GIT_COMMIT",
        "GIT_SHA",
    ]
    for env_var in env_vars:
        value = os.environ.get(env_var, "").strip()
        if value and value.lower() not in ("unknown", "local", ""):
            return value[:8] if len(value) >= 8 else value
    return "local-dev"


def _get_env_name() -> str:
    """Get environment name from environment."""
    return os.environ.get(
        "DRAGONFLY_ENV", os.environ.get("ENVIRONMENT", os.environ.get("RAILWAY_ENVIRONMENT", "dev"))
    ).lower()


# =============================================================================
# Exceptions
# =============================================================================


class DatabaseNotStartedError(RuntimeError):
    """Raised when attempting to use the database before calling start()."""

    def __init__(self) -> None:
        super().__init__("Database pool not started. Did you forget to await db.start()?")


class DatabaseConnectionError(RuntimeError):
    """Raised when all connection retry attempts are exhausted."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Failed to connect to database after {attempts} attempts. " f"Last error: {last_error}"
        )


# =============================================================================
# Database Class
# =============================================================================


class Database:
    """
    Lazy-loaded async PostgreSQL connection pool with "polite" retry behavior.

    The pool is NOT instantiated in __init__. It is only created and opened
    when start() is explicitly called. Connection failures are retried with
    exponential backoff to avoid hammering the database during outages.

    THE KILL SWITCH:
    ================
    Authentication failures trigger IMMEDIATE sys.exit(1) to prevent
    Supabase "server_login_retry" lockouts. DO NOT RETRY bad credentials.

    Pool Size Configuration:
        - Workers: max_size=1 (detected via WORKER_MODE or heuristics)
        - API servers: max_size=5 (or DB_POOL_SIZE env var)
        - min_size is always 1 (conservative)

    Logging Strategy:
        - First attempt: INFO "🔌 Connecting..."
        - Retries: WARNING "⚠️ Connection failed. Retrying in Xs..."
        - Success: INFO "✅ Database Connected (Pool Size: N)"
        - Auth failure: CRITICAL + sys.exit(1)
        - Exhausted: ERROR with full traceback

    Attributes:
        url: PostgreSQL connection string (DSN)
        min_size: Minimum connections to keep in pool (always 1)
        max_size: Maximum connections allowed (from DB_POOL_SIZE or auto-detect)
        pool: The underlying AsyncConnectionPool (None until start())

    Example::

        db = Database(url="<dsn>")
        await db.start()  # Opens pool, exits on auth failure
        async with db.get_connection() as conn:
            await conn.execute("SELECT 1")
        await db.stop()
    """

    __slots__ = (
        "url",
        "min_size",
        "max_size",
        "timeout",
        "max_lifetime",
        "pool",
        "_app_name",
        "_is_worker",
    )

    def __init__(
        self,
        url: str,
        *,
        min_size: int = 1,
        max_size: Optional[int] = None,
        timeout: float = 30.0,
        max_lifetime: float = 1800.0,
        app_name: Optional[str] = None,
    ) -> None:
        """
        Prepare database configuration. Does NOT open any connections.

        Args:
            url: PostgreSQL DSN (connection string)
            min_size: Minimum idle connections (default: 1, conservative)
            max_size: Maximum connections (default: 1 for workers, 5 for API)
            timeout: Seconds to wait for a connection from pool (default: 30)
            max_lifetime: Recycle connections after this many seconds (default: 1800)
            app_name: PostgreSQL application_name (default: auto-generated)
        """
        if not url:
            raise ValueError("Database URL cannot be empty")

        self.url = url
        self.min_size = min_size
        self.timeout = timeout
        self.max_lifetime = max_lifetime
        self.pool: Optional[AsyncConnectionPool] = None  # NOT instantiated here
        self._is_worker = _is_worker_process()

        # Determine pool size: explicit > env var > auto-detect
        if max_size is not None:
            self.max_size = max_size
        else:
            env_pool_size = os.environ.get("DB_POOL_SIZE")
            if env_pool_size:
                try:
                    self.max_size = int(env_pool_size)
                except ValueError:
                    default = DEFAULT_WORKER_POOL_SIZE if self._is_worker else DEFAULT_API_POOL_SIZE
                    logger.warning(
                        f"Invalid DB_POOL_SIZE '{env_pool_size}', using default {default}"
                    )
                    self.max_size = default
            else:
                # Auto-detect: workers get 1, API gets 5
                self.max_size = (
                    DEFAULT_WORKER_POOL_SIZE if self._is_worker else DEFAULT_API_POOL_SIZE
                )

        # Generate safe application name (no spaces/dots for PostgreSQL option parsing)
        if app_name:
            self._app_name = app_name.replace(".", "_").replace(" ", "_").replace("-", "_")
        else:
            mode = "worker" if self._is_worker else "api"
            self._app_name = f"dragonfly_{mode}"

        logger.debug(
            f"Database configured (pool not yet open) | "
            f"mode={'worker' if self._is_worker else 'api'} "
            f"min_size={self.min_size} max_size={self.max_size} app_name={self._app_name}"
        )

    @property
    def is_open(self) -> bool:
        """Return True if the pool is open and ready for connections."""
        return self.pool is not None

    async def start(self, *, max_retries: int | None = None) -> None:
        """
        Instantiate and open the connection pool with exponential backoff + jitter.

        Connection attempts use exponential backoff with jitter:
        - Attempt 1: immediate
        - Attempt 2: wait 1s + jitter
        - Attempt 3: wait 2s + jitter
        - Attempt 4: wait 4s + jitter
        - ...up to 30s max delay

        Features:
        - SSL enforcement: sslmode=require added if not present
        - Jitter: 0-30% random delay to prevent thundering herd
        - Structured logging: Single event on success/failure with metrics

        Args:
            max_retries: Maximum connection attempts. If None (default), uses
                         MAX_RETRY_ATTEMPTS (10). Set to 1 in tests for fast failure.

        Logging Strategy:
        - First attempt: INFO
        - Retries: WARNING (no stack trace, single line per attempt)
        - Final success: Structured INFO with attempt_count, elapsed_ms, host, port, env, sha
        - Exhausted retries: Structured ERROR with full details

        Raises:
            RuntimeError: If pool is already started
            DatabaseConnectionError: If all retry attempts fail
        """
        if self.pool is not None:
            logger.warning("Database pool already started, skipping")
            return

        # Ensure SSL for security
        dsn = _ensure_sslmode(self.url)
        dsn_info = _parse_dsn_info(dsn)

        start_time = time.monotonic()
        attempt = 0
        delay = INITIAL_RETRY_DELAY
        last_error: Optional[Exception] = None
        pool: Optional[AsyncConnectionPool] = None
        effective_max_retries = max_retries if max_retries is not None else MAX_RETRY_ATTEMPTS

        while attempt < effective_max_retries:
            attempt += 1

            try:
                if attempt == 1:
                    logger.info(
                        f"🔌 Connecting to database... "
                        f"(host={dsn_info.get('host')}, port={dsn_info.get('port')})"
                    )

                # Create pool with open=False (explicit lifecycle)
                pool = AsyncConnectionPool(
                    conninfo=dsn,
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

                # Explicitly open the pool (this is where connection happens)
                await pool.open()

                # Verify connectivity with a simple ping
                async with pool.connection() as conn:
                    result = await conn.execute("SELECT 1")
                    row = await result.fetchone()
                    if row is None or row[0] != 1:
                        raise RuntimeError("Database ping failed: SELECT 1 did not return 1")

                # Success! Calculate elapsed time
                elapsed_ms = (time.monotonic() - start_time) * 1000
                self.pool = pool

                # Structured success log with all context
                logger.info(
                    f"✅ Database Connected | "
                    f"attempts={attempt} elapsed_ms={elapsed_ms:.0f} "
                    f"pool_size={self.max_size} host={dsn_info.get('host')} "
                    f"port={dsn_info.get('port')} env={_get_env_name()} sha={_get_sha_short()}"
                )
                return

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # ═══════════════════════════════════════════════════════════════
                # THE KILL SWITCH - IMMEDIATE EXIT ON AUTH FAILURES
                # ═══════════════════════════════════════════════════════════════
                # Supabase pooler triggers "server_login_retry" lockout after
                # repeated bad auth. This locks the ENTIRE PROJECT for 30 minutes.
                # DO NOT RETRY - exit immediately on first auth failure.

                # Check for auth failure patterns (case-insensitive)
                is_auth_failure = any(pattern in error_str for pattern in AUTH_FAILURE_PATTERNS)

                # Check for config failures (role/database doesn't exist) - use regex
                is_config_failure = any(
                    re.search(pattern, error_str) for pattern in CONFIG_FAILURE_PATTERNS
                )

                if is_auth_failure or is_config_failure:
                    # Log CRITICAL and EXIT IMMEDIATELY
                    logger.critical(
                        f"⛔ FATAL: {'Authentication' if is_auth_failure else 'Configuration'} "
                        f"error detected - EXITING to prevent Supabase lockout\n"
                        f"   Host: {dsn_info.get('host')}\n"
                        f"   Port: {dsn_info.get('port')}\n"
                        f"   User: {dsn_info.get('user')}\n"
                        f"   Error: {type(e).__name__}: {e}\n"
                        f"   Action: Check SUPABASE_DB_URL credentials and database settings"
                    )
                    # Print to stderr for visibility in container logs
                    print(
                        f"\n{'=' * 70}\n"
                        f"  ⛔ FATAL: DATABASE AUTHENTICATION FAILURE\n"
                        f"{'=' * 70}\n\n"
                        f"  Error: {str(e)[:200]}\n\n"
                        f"  Host: {dsn_info.get('host')}\n"
                        f"  Port: {dsn_info.get('port')}\n"
                        f"  User: {dsn_info.get('user')}\n\n"
                        f"  ACTION: Check SUPABASE_DB_URL credentials.\n"
                        f"  Exiting immediately to prevent server_login_retry lockout.\n\n"
                        f"{'=' * 70}\n",
                        file=sys.stderr,
                    )
                    sys.exit(1)

                # Close any partially opened pool
                if pool is not None:
                    try:
                        await pool.close()
                    except Exception:
                        pass  # Ignore close errors
                    pool = None

                # Network errors are safe to retry with backoff
                if attempt < effective_max_retries:
                    # Add jitter to prevent thundering herd
                    jitter = random.uniform(0, delay * JITTER_FACTOR)
                    actual_delay = delay + jitter

                    # Log retry warning (quiet - single line, no stack trace)
                    logger.warning(
                        f"⚠️ DB Connection failed (attempt {attempt}/{effective_max_retries}). "
                        f"Retrying in {actual_delay:.1f}s... ({type(e).__name__}: {e})"
                    )
                    await asyncio.sleep(actual_delay)

                    # Exponential backoff: double the delay, cap at MAX_RETRY_DELAY
                    delay = min(delay * 2, MAX_RETRY_DELAY)
                else:
                    # All attempts exhausted - structured error log with full details
                    elapsed_ms = (time.monotonic() - start_time) * 1000
                    logger.error(
                        f"❌ Database connection FAILED | "
                        f"attempts={attempt} elapsed_ms={elapsed_ms:.0f} "
                        f"host={dsn_info.get('host')} port={dsn_info.get('port')} "
                        f"env={_get_env_name()} sha={_get_sha_short()} "
                        f"error={type(e).__name__}: {e}"
                    )

        # All retries exhausted
        raise DatabaseConnectionError(attempt, last_error or RuntimeError("Unknown error"))

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

    async def check_connection(self) -> tuple[bool, str]:
        """
        Lightweight DB connection check for readiness probes.

        This method is designed for /readyz endpoints and health checks.
        It performs a minimal query (SELECT 1) to verify database connectivity
        without consuming significant resources.

        Returns:
            tuple[bool, str]: (is_healthy, message)
                - (True, "ok") if connection succeeds
                - (False, "Pool not started") if pool is None
                - (False, "Connection failed: <redacted>") on error

        Note:
            Error messages are redacted to prevent information leakage
            in public health endpoints. Full details are logged internally.
        """
        if self.pool is None:
            return False, "Pool not started"

        try:
            async with self.pool.connection() as conn:
                result = await conn.execute("SELECT 1")
                row = await result.fetchone()
                if row is not None and row[0] == 1:
                    return True, "ok"
                return False, "Unexpected query result"
        except Exception as e:
            # Log full error internally, return redacted message externally
            logger.warning(f"check_connection failed: {type(e).__name__}: {e}")
            return False, "Connection failed"

    def __repr__(self) -> str:
        status = "open" if self.is_open else "closed"
        return f"<Database pool={status} min={self.min_size} max={self.max_size}>"


# =============================================================================
# Singleton instance for FastAPI lifespan
# =============================================================================

_default_db: Optional[Database] = None


def get_database() -> Database:
    """
    Get the default database instance.

    The instance is created lazily on first call, but the pool
    is NOT opened until start() is called.

    Pool Size:
        - Workers (WORKER_MODE=1 or heuristics): max_size=1
        - API servers: max_size=5 (or DB_POOL_SIZE env var)

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

        # Pool size is auto-detected by Database.__init__:
        # - Workers: max_size=1 (detected via WORKER_MODE or process name)
        # - API: max_size=5 (or DB_POOL_SIZE env var)
        _default_db = Database(
            url=url,
            min_size=1,  # Conservative: always start with 1
            # max_size auto-detected by Database.__init__ based on worker mode
            timeout=30.0,
            max_lifetime=1800.0,
        )

    return _default_db


async def startup_database() -> None:
    """
    FastAPI lifespan startup hook.

    Call this in your FastAPI lifespan context to open the database pool.
    Uses exponential backoff for resilient startup.

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
