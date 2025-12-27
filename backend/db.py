# backend/db.py
"""
Dragonfly Engine - Database Layer

Provides async PostgreSQL connection pooling via psycopg3 + psycopg_pool.
Implements robust initialization with:
- Exponential backoff retry (6 attempts, max 60s total)
- SSL enforcement (sslmode=require)
- Structured logging (DSN host/port/dbname/user, no password)
- Pool health state tracking for readiness probes
"""

from __future__ import annotations

# Must be early - fixes Windows asyncio compatibility with psycopg3
from .asyncio_compat import ensure_selector_policy_on_windows

ensure_selector_policy_on_windows()

import asyncio  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from typing import Any, AsyncGenerator, Optional, Sequence  # noqa: E402
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse  # noqa: E402

import psycopg  # noqa: E402
from loguru import logger  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from psycopg_pool import AsyncConnectionPool  # noqa: E402

from supabase import Client, create_client  # noqa: E402

from . import __version__  # noqa: E402
from .config import get_settings  # noqa: E402
from .dsn_sanitizer import DSNSanitizationError, sanitize_dsn  # noqa: E402

# NOTE: settings is loaded lazily via get_settings() inside functions
# to avoid triggering Pydantic validation at import time

# ---------------------------------------------------------------------------
# Pool Health State
# ---------------------------------------------------------------------------


@dataclass
class PoolHealthState:
    """Tracks database pool initialization state for readiness probes."""

    initialized: bool = False
    healthy: bool = False
    last_error: str | None = None
    last_check_at: float | None = None
    init_attempts: int = 0
    init_duration_ms: float | None = None


_pool_health = PoolHealthState()

# Async connection pool for database operations
_db_pool: Optional[AsyncConnectionPool] = None
_supabase_client: Optional[Client] = None


def get_pool_health() -> PoolHealthState:
    """Return the current pool health state for readiness probes."""
    return _pool_health


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
        settings = get_settings()  # Lazy load
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

# Retry configuration for pool initialization
MAX_RETRY_ATTEMPTS = 6
MAX_TOTAL_WAIT_SECONDS = 60.0
BASE_DELAY_SECONDS = 1.0
READINESS_CHECK_TIMEOUT = 2.0  # 2s timeout for readiness probe SELECT 1


def _parse_dsn_for_logging(dsn: str) -> dict[str, str | None]:
    """
    Parse DSN and extract loggable components (no password).

    Returns dict with host, port, dbname, user, sslmode.
    """
    try:
        parsed = urlparse(dsn)
        # Parse query string for sslmode
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

    If sslmode is not set, append it. If set to a weaker mode,
    upgrade to require.
    """
    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)

        current_sslmode = query_params.get("sslmode", [None])[0]
        weak_modes = {"disable", "allow", "prefer"}

        if current_sslmode is None or current_sslmode in weak_modes:
            # Set or upgrade to require
            query_params["sslmode"] = ["require"]
            new_query = urlencode(query_params, doseq=True)
            new_parsed = parsed._replace(query=new_query)
            new_dsn = urlunparse(new_parsed)

            if current_sslmode in weak_modes:
                logger.warning(
                    f"Upgraded sslmode from '{current_sslmode}' to 'require' for security"
                )
            else:
                logger.info("Added sslmode=require to DSN (was not set)")

            return new_dsn

        return dsn
    except Exception as e:
        logger.error(f"Failed to parse/modify DSN for sslmode: {e}")
        return dsn


async def init_db_pool(app: Any | None = None) -> None:
    """
    Initialize async PostgreSQL connection pool with robust retry logic.

    Called from FastAPI startup. Implements:
    - DSN sanitization (rejects quotes, internal whitespace, malformed values)
    - Exponential backoff retry (6 attempts, max 60s total)
    - SSL enforcement (sslmode=require)
    - Structured logging (DSN host/port/dbname/user, no password)
    - Pool health state tracking for readiness probes

    Args:
        app: FastAPI app instance (accepted for compatibility, unused)

    Raises:
        RuntimeError: Only in production if all retries exhausted
    """
    global _db_pool, _pool_health

    if _db_pool is not None:
        return

    settings = get_settings()  # Lazy load

    if not settings.supabase_db_url:
        logger.warning("SUPABASE_DB_URL is not set; skipping DB init")
        _pool_health.last_error = "SUPABASE_DB_URL not configured"
        return

    # Step 1: Sanitize DSN (reject quotes, internal whitespace, malformed values)
    try:
        sanitized = sanitize_dsn(settings.supabase_db_url, raise_on_error=True)
        raw_dsn = sanitized.dsn

        # Log sanitization result
        if sanitized.stripped_leading or sanitized.stripped_trailing:
            stripped_parts = []
            if sanitized.stripped_leading:
                stripped_parts.append("leading")
            if sanitized.stripped_trailing:
                stripped_parts.append("trailing")
            logger.warning(
                f"DSN whitespace stripped ({' and '.join(stripped_parts)})",
                original_length=sanitized.original_length,
                sanitized_length=sanitized.sanitized_length,
            )

    except DSNSanitizationError as e:
        # Critical failure - DSN is malformed
        error_msg = f"DSN sanitization failed: {e.message}"
        logger.critical(
            error_msg,
            safe_components=e.safe_dsn_info,
        )
        _pool_health.last_error = error_msg
        _pool_health.healthy = False
        _pool_health.initialized = False
        # Don't raise - let readiness probe return 503
        return

    # Step 2: Ensure sslmode=require for security
    dsn = _ensure_sslmode(raw_dsn)

    # Log DSN info (never log password)
    dsn_info = _parse_dsn_for_logging(dsn)
    logger.info(
        "Database connection parameters",
        host=dsn_info.get("host"),
        port=dsn_info.get("port"),
        dbname=dsn_info.get("dbname"),
        user=dsn_info.get("user"),
        sslmode=dsn_info.get("sslmode"),
    )

    # Exponential backoff retry loop
    start_time = time.monotonic()
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
        _pool_health.init_attempts = attempt
        elapsed = time.monotonic() - start_time

        if elapsed >= MAX_TOTAL_WAIT_SECONDS:
            logger.error(
                f"DB pool init: time budget exhausted ({elapsed:.1f}s >= {MAX_TOTAL_WAIT_SECONDS}s)"
            )
            break

        try:
            logger.info(f"DB pool init: attempt {attempt}/{MAX_RETRY_ATTEMPTS}")

            # Use application_name without spaces/dots to avoid PostgreSQL option parsing issues
            # The space in 'Dragonfly v1.3.1' was causing: invalid command-line argument
            # Use underscores only: dragonfly_v1_3_1
            safe_version = __version__.replace(".", "_").replace(" ", "_").replace("-", "_")
            app_name = f"dragonfly_v{safe_version}"

            # DEBUG: Verification log before pool connects (never log password)
            dsn_host = dsn_info.get("host", "unknown")
            logger.info(f"DEBUG: Connecting to DB Host: {dsn_host} | App Name: {app_name}")

            pool = AsyncConnectionPool(
                dsn,
                min_size=2,
                max_size=10,
                kwargs={"application_name": app_name},
            )
            await pool.open()

            # Verify connectivity with a simple ping
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1;")
                    result = await cur.fetchone()
                    if result is None or result[0] != 1:
                        raise RuntimeError("SELECT 1 did not return expected result")

            # Success!
            init_duration = (time.monotonic() - start_time) * 1000
            _db_pool = pool
            _pool_health.initialized = True
            _pool_health.healthy = True
            _pool_health.last_error = None
            _pool_health.init_duration_ms = init_duration
            _pool_health.last_check_at = time.monotonic()

            logger.info(
                f"✅ Database pool initialized OK (attempt {attempt}, {init_duration:.0f}ms total)"
            )
            return

        except Exception as e:
            last_error = e
            _pool_health.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            _pool_health.healthy = False

            logger.warning(f"DB pool init attempt {attempt} failed: {type(e).__name__}: {e}")

            if attempt < MAX_RETRY_ATTEMPTS:
                # Exponential backoff with jitter
                delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                jitter = random.uniform(0, delay * 0.3)
                actual_delay = min(delay + jitter, MAX_TOTAL_WAIT_SECONDS - elapsed)

                if actual_delay > 0:
                    logger.info(f"DB pool init: waiting {actual_delay:.1f}s before retry")
                    await asyncio.sleep(actual_delay)

    # All retries exhausted
    total_elapsed = time.monotonic() - start_time
    error_msg = (
        f"Failed to initialize database pool after {MAX_RETRY_ATTEMPTS} attempts "
        f"({total_elapsed:.1f}s): {last_error}"
    )

    _pool_health.initialized = False
    _pool_health.healthy = False
    _pool_health.init_duration_ms = total_elapsed * 1000

    # In production, we keep the app running for logs but /readyz will fail
    # This allows container orchestrators to see the pod is unhealthy
    is_prod = settings.ENVIRONMENT.lower() in ("prod", "production")

    if is_prod:
        logger.error(f"❌ {error_msg} - app will start but /readyz will return 503")
        # Don't raise - keep running so logs are accessible and /readyz works
    else:
        logger.error(f"❌ {error_msg}")
        # In dev, also don't crash - easier for local development


async def check_db_ready(timeout: float = READINESS_CHECK_TIMEOUT) -> tuple[bool, str]:
    """
    Perform a readiness check on the database connection.

    Executes SELECT 1 with a timeout to verify the pool is healthy.

    Args:
        timeout: Maximum seconds to wait for the query (default: 2.0)

    Returns:
        Tuple of (is_ready, status_message)
    """
    global _pool_health

    pool = _db_pool  # Capture for closure
    if pool is None:
        return False, _pool_health.last_error or "Pool not initialized"

    try:
        start = time.monotonic()

        async def _ping() -> int:
            assert pool is not None  # Type narrowing for mypy/pylance
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1;")
                    row = await cur.fetchone()
                    return row[0] if row else 0

        result = await asyncio.wait_for(_ping(), timeout=timeout)
        latency_ms = (time.monotonic() - start) * 1000

        if result == 1:
            _pool_health.healthy = True
            _pool_health.last_error = None
            _pool_health.last_check_at = time.monotonic()
            return True, f"ok ({latency_ms:.0f}ms)"
        else:
            _pool_health.healthy = False
            _pool_health.last_error = f"SELECT 1 returned {result}"
            return False, f"unexpected_result: {result}"

    except asyncio.TimeoutError:
        _pool_health.healthy = False
        _pool_health.last_error = f"Query timeout ({timeout}s)"
        return False, f"timeout ({timeout}s)"
    except Exception as e:
        _pool_health.healthy = False
        _pool_health.last_error = f"{type(e).__name__}: {str(e)[:100]}"
        return False, f"error: {type(e).__name__}"


async def close_db_pool() -> None:
    """
    Called from FastAPI shutdown.

    Closes the connection pool and resets health state.
    """
    global _db_pool, _pool_health
    if _db_pool is not None:
        logger.info("Closing PostgreSQL connection pool")
        await _db_pool.close()
        _db_pool = None
        _pool_health.initialized = False
        _pool_health.healthy = False


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
