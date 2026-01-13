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
import logging as stdlib_logging
import os  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
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
from .core.config_guard import validate_db_config  # noqa: E402
from .dsn_sanitizer import DSNSanitizationError, sanitize_dsn  # noqa: E402
from .utils.logging import get_log_metadata  # noqa: E402

# NOTE: settings is loaded lazily via get_settings() inside functions
# to avoid triggering Pydantic validation at import time

# ---------------------------------------------------------------------------
# Pool Health State
# ---------------------------------------------------------------------------

# ═══════════════════════════════════════════════════════════════════════════
# AUTH FAILURE DETECTION via psycopg.pool log interception
# ═══════════════════════════════════════════════════════════════════════════
# psycopg_pool logs auth failures to the psycopg.pool logger, but raises only
# a generic timeout to the caller. We intercept these logs to detect auth
# failures and trigger the KILL SWITCH even when main thread sees a timeout.


_auth_failure_signal_detected = False  # Module-level flag set by log handler


class _AuthFailureDetector(stdlib_logging.Handler):
    """Detect auth failures from psycopg.pool log messages."""

    def emit(self, record: stdlib_logging.LogRecord) -> None:
        global _auth_failure_signal_detected
        msg = record.getMessage().lower()
        # Check for auth failure keywords in pool log messages
        auth_keywords = [
            "server_login_retry",
            "password authentication failed",
            "authentication failed",
            "no pg_hba.conf entry",
            "fatal:",
        ]
        for keyword in auth_keywords:
            if keyword in msg:
                _auth_failure_signal_detected = True
                # Log at error level when we detect auth failures
                logger.error(f"🚨 Auth failure detected in pool logs: {msg[:200]}")
                return


# Attach handler to psycopg.pool logger
_pool_logger = stdlib_logging.getLogger("psycopg.pool")
_pool_logger.addHandler(_AuthFailureDetector())


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

# Attach version metadata to loguru logger for parity with stdlib logs
logger = logger.bind(**get_log_metadata())

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

# ═══════════════════════════════════════════════════════════════════════════
# POOL CONFIGURATION - Polite, Environment-Aware
# ═══════════════════════════════════════════════════════════════════════════
# Workers only need 1 connection; API servers can use more.
# Detects environment via WORKER_MODE env var or process name heuristics.


def _detect_worker_mode() -> bool:
    """Detect if we're running as a worker (small pool) vs API (larger pool)."""
    import sys

    # Explicit env var takes precedence
    if os.getenv("WORKER_MODE", "").lower() in ("1", "true", "yes"):
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
    )
    return any(p in script.lower() for p in worker_patterns)


_IS_WORKER = _detect_worker_mode()

# Pool sizing: workers get minimal pool, API servers get more headroom
POOL_MIN_SIZE = 1 if _IS_WORKER else 2
POOL_MAX_SIZE = 1 if _IS_WORKER else 5  # Reduced from 10 → 5 for Supabase limits
POOL_TIMEOUT = 30.0  # Seconds to wait for connection from pool
POOL_RECYCLE = 1800  # Recycle connections every 30 minutes
CONNECT_TIMEOUT = 5  # TCP connect timeout (fail fast if DB is down)
STATEMENT_TIMEOUT_MS = 10000  # Kill queries taking > 10 seconds

# Retry configuration with exponential backoff
# Polite backoff: 1s → 2s → 4s → 8s → 16s → 30s (capped)
MAX_RETRY_ATTEMPTS = 6  # Initial startup attempts ≈ 60s total wait
MAX_TOTAL_WAIT_SECONDS = 60.0  # Hard cap on total retry time for startup
BASE_DELAY_SECONDS = 1.0  # Initial delay
MAX_DELAY_SECONDS = 30.0  # Cap individual retry delay
JITTER_FACTOR = 0.2  # Add ±20% jitter to prevent thundering herd

# Authentication failure handling: IMMEDIATE EXIT to prevent lockouts
# Supabase pooler triggers "server_login_retry" after repeated bad auth
# See: https://supabase.com/docs/guides/platform/going-into-prod#pooler-considerations
AUTH_FAILURE_KEYWORDS = frozenset(
    [
        "server_login_retry",
        "password authentication failed",
        "no pg_hba.conf entry",
        "authentication failed",
        "fatal:",  # PostgreSQL FATAL errors
        "role",  # "role X does not exist" (paired with "does not exist")
    ]
)

# Network failure handling: POLITE BACKOFF with infinite retry in production
NETWORK_FAILURE_KEYWORDS = frozenset(
    [
        "connection refused",
        "could not connect to server",
        "connection timed out",
        "timeout expired",
        "network is unreachable",
        "could not translate host name",
        "ssl syscall error",
    ]
)

# Readiness check configuration
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


def _classify_db_init_error(exc: Exception) -> str:
    """Classify database init errors for retry strategy.

    Returns one of:
        - "auth_failure": authentication/authorization issues → KILL SWITCH (exit 1)
        - "network": transient network/connection problems → POLITE BACKOFF
        - "other": everything else → treat as network (retry)

    KILL SWITCH POLICY:
        Auth failures trigger IMMEDIATE sys.exit(1) to prevent Supabase pooler
        "server_login_retry" lockouts. Bad credentials should NEVER be retried.

    POLITE BACKOFF POLICY:
        Network failures use exponential backoff (1s → 2s → 4s → ... → 30s cap)
        with infinite retry in production for resilience against transient issues.
    """
    global _auth_failure_signal_detected

    # Check if psycopg.pool log handler detected auth failure
    # This catches cases where pool workers fail with auth errors but the
    # main thread only sees a generic timeout exception
    if _auth_failure_signal_detected:
        return "auth_failure"

    message = str(exc).lower()

    # Auth-related failures: KILL SWITCH - exit immediately
    for marker in AUTH_FAILURE_KEYWORDS:
        if marker in message:
            # Special case: "role" needs "does not exist" context
            if marker == "role" and "does not exist" not in message:
                continue
            return "auth_failure"

    # Network/connectivity problems: POLITE BACKOFF
    for marker in NETWORK_FAILURE_KEYWORDS:
        if marker in message:
            return "network"

    # Default: treat unknown errors as network (retry)
    return "other"


async def init_db_pool(app: Any | None = None) -> None:
    """
    Initialize async PostgreSQL connection pool with robust retry logic.

    Called from FastAPI startup. Implements:
    - Environment-aware pool sizing (workers: 1, API: 5)
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

    # Enforce runtime DB policies before touching the database
    validate_db_config()

    settings = get_settings()  # Lazy load

    # Log pool mode at startup
    pool_mode = "worker" if _IS_WORKER else "api"
    logger.info(
        f"DB pool mode: {pool_mode}",
        extra={
            "pool_mode": pool_mode,
            "pool_min_size": POOL_MIN_SIZE,
            "pool_max_size": POOL_MAX_SIZE,
        },
    )

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
                extra={
                    "original_length": sanitized.original_length,
                    "sanitized_length": sanitized.sanitized_length,
                },
            )

    except DSNSanitizationError as e:
        # Critical failure - DSN is malformed
        error_msg = f"DSN sanitization failed: {e.message}"
        logger.critical(
            error_msg,
            extra={"safe_components": e.safe_dsn_info},
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
        extra={
            "db_host": dsn_info.get("host"),
            "db_port": dsn_info.get("port"),
            "db_name": dsn_info.get("dbname"),
            "db_user": dsn_info.get("user"),
            "db_sslmode": dsn_info.get("sslmode"),
        },
    )

    # Exponential backoff retry loop with immediate exit on auth failures
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

            # Create pool with open=False to avoid deprecation warning
            # Pool is explicitly opened below via await pool.open()
            #
            # NOTE: Supabase Transaction Pooler (PgBouncer on port 6543) does NOT support
            # the "options" startup parameter. We must omit it when using the pooler.
            # Direct connections (port 5432) can use options for statement_timeout.
            db_port = dsn_info.get("port", "6543")
            using_pooler = str(db_port) == "6543"

            conn_kwargs: dict[str, str | int] = {
                "application_name": app_name,
                "connect_timeout": CONNECT_TIMEOUT,  # Fail fast if DB unreachable
            }
            # Only add options parameter for direct connections (not pooler)
            if not using_pooler:
                conn_kwargs["options"] = f"-c statement_timeout={STATEMENT_TIMEOUT_MS}"
            else:
                logger.info("Pooler detected (port 6543): skipping 'options' parameter")

            pool = AsyncConnectionPool(
                dsn,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                timeout=POOL_TIMEOUT,  # Wait for connection from pool
                max_lifetime=POOL_RECYCLE,  # Recycle stale connections
                open=False,  # Explicit lifecycle - no auto-open in constructor
                kwargs=conn_kwargs,
            )
            # Explicitly open the pool (required when open=False)
            await pool.open()
            logger.info("🔌 Database Pool Opened")

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
                "✅ DB Connected",
                extra={
                    "attempt": attempt,
                    "init_duration_ms": round(init_duration),
                },
            )
            return

        except Exception as e:
            last_error = e
            category = _classify_db_init_error(e)
            _pool_health.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            _pool_health.healthy = False

            # ═══════════════════════════════════════════════════════════════════
            # KILL SWITCH: Auth failures → Exit immediately (NEVER retry)
            # ═══════════════════════════════════════════════════════════════════
            if category == "auth_failure":
                logger.critical(
                    "⛔ AUTH FATAL: Credentials rejected. Exiting immediately.",
                    extra={
                        "classification": "auth_failure",
                        "guidance": "Check SUPABASE_DB_URL credentials, username, password",
                        "attempt": attempt,
                        "db_host": dsn_info.get("host"),
                        "db_port": dsn_info.get("port"),
                        "db_user": dsn_info.get("user"),
                        "error_type": type(e).__name__,
                        "error_msg": str(e)[:300],
                    },
                )
                print(
                    f"\n{'=' * 70}\n"
                    f"  ⛔ AUTH FATAL: Credentials rejected. Exiting immediately.\n"
                    f"{'=' * 70}\n\n"
                    f"  Error: {str(e)[:200]}\n\n"
                    f"  Host: {dsn_info.get('host')}\n"
                    f"  Port: {dsn_info.get('port')}\n"
                    f"  User: {dsn_info.get('user')}\n\n"
                    f"  ACTION: Verify SUPABASE_DB_URL credentials in Railway/env.\n"
                    f"  Exiting NOW to prevent server_login_retry lockout.\n\n"
                    f"{'=' * 70}\n",
                    file=sys.stderr,
                )
                sys.exit(1)

            # ═══════════════════════════════════════════════════════════════════
            # POLITE BACKOFF: Network/transient errors → Exponential retry
            # ═══════════════════════════════════════════════════════════════════
            logger.warning(
                f"DB pool init attempt {attempt} failed: {category}",
                extra={
                    "attempt": attempt,
                    "error_type": type(e).__name__,
                    "error_msg": str(e)[:200],
                    "classification": category,
                },
            )

            if attempt < MAX_RETRY_ATTEMPTS:
                # Exponential backoff: 1s → 2s → 4s → 8s → 16s → 30s (capped)
                delay = BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                delay = min(delay, MAX_DELAY_SECONDS)  # Cap at 30s
                jitter = random.uniform(-delay * JITTER_FACTOR, delay * JITTER_FACTOR)
                actual_delay = max(0.5, delay + jitter)  # Minimum 0.5s

                # Respect time budget during startup
                remaining = MAX_TOTAL_WAIT_SECONDS - elapsed
                if remaining > 0:
                    actual_delay = min(actual_delay, remaining)
                    logger.info(f"DB pool init: waiting {actual_delay:.1f}s before retry")
                    await asyncio.sleep(actual_delay)
                else:
                    logger.warning("DB pool init: time budget exhausted during startup")
                    break

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
        logger.info("🔌 Database Pool Closed")


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
# Database Class with Explicit Lifecycle (Preferred for FastAPI lifespan)
# ---------------------------------------------------------------------------


class Database:
    """
    Database manager with explicit lifecycle methods.

    Preferred pattern for FastAPI lifespan to avoid the deprecation warning:
    "AsyncConnectionPool constructor open is deprecated"

    Usage in FastAPI lifespan:
        db = Database()

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await db.start()
            yield
            await db.stop()

        app = FastAPI(lifespan=lifespan)
    """

    def __init__(self) -> None:
        """
        Initialize database configuration.

        Does NOT open any connections - call start() to open the pool.
        """
        self._pool: Optional[AsyncConnectionPool] = None
        self._dsn: Optional[str] = None
        self._initialized = False

    async def start(self) -> None:
        """
        Initialize and open the connection pool.

        This is the explicit startup - call from FastAPI lifespan startup.
        Logs: "🔌 Database Pool Opened."
        """
        # Delegate to the global init function for now (maintains compatibility)
        await init_db_pool()
        self._pool = _db_pool
        self._initialized = True
        logger.info("🔌 Database Pool Opened.")

    async def stop(self) -> None:
        """
        Close the connection pool.

        This is the explicit shutdown - call from FastAPI lifespan shutdown.
        Logs: "🔌 Database Pool Closed."
        """
        await close_db_pool()
        self._pool = None
        self._initialized = False
        logger.info("🔌 Database Pool Closed.")

    @property
    def pool(self) -> Optional[AsyncConnectionPool]:
        """Return the connection pool (may be None if not started)."""
        return self._pool or _db_pool

    @property
    def is_initialized(self) -> bool:
        """Check if the database is initialized."""
        return self._initialized or (_db_pool is not None)

    async def ping(self) -> bool:
        """Check database connectivity."""
        return await ping_db()


# Global database instance for FastAPI lifespan
database = Database()


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
