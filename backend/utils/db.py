# backend/utils/db.py
"""
Resilient Database Connection Utilities

This module provides robust database connection handling with:
- Automatic retry with exponential backoff for pooler connections
- Fallback to direct connections when pooler is unavailable
- Circuit breaker pattern for production resilience

Usage:
    from backend.utils.db import get_db_connection, DatabaseOutageError

    # For workers (uses pooler with retries)
    with get_db_connection() as conn:
        ...

    # For migrations/CI (uses direct connection, no pooler)
    with get_db_connection(use_pooler=False) as conn:
        ...
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class DatabaseOutageError(Exception):
    """Raised when database is unreachable after all retry attempts."""

    def __init__(self, message: str, attempts: int, last_error: Optional[Exception] = None):
        super().__init__(message)
        self.attempts = attempts
        self.last_error = last_error


class PoolerUnavailableError(DatabaseOutageError):
    """Raised when the pooler (port 6543) is unavailable."""

    pass


# =============================================================================
# Configuration
# =============================================================================

# Retry configuration
MAX_RETRIES = int(os.environ.get("DB_MAX_RETRIES", "5"))
BASE_BACKOFF_SECONDS = float(os.environ.get("DB_BASE_BACKOFF_SECONDS", "1.0"))
MAX_BACKOFF_SECONDS = float(os.environ.get("DB_MAX_BACKOFF_SECONDS", "30.0"))

# Connection timeout
CONNECTION_TIMEOUT_SECONDS = int(os.environ.get("DB_CONNECTION_TIMEOUT_SECONDS", "10"))


# =============================================================================
# Connection Helpers
# =============================================================================


def _get_dsn(use_pooler: bool = True) -> str:
    """
    Get the appropriate database connection string.

    Args:
        use_pooler: If True, use SUPABASE_DB_URL (port 6543 pooler).
                   If False, use SUPABASE_MIGRATE_DB_URL (port 5432 direct).

    Returns:
        Database connection string

    Raises:
        ValueError: If required environment variable is not set
    """
    if use_pooler:
        # Workers/App use the pooler (port 6543)
        dsn = os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            raise ValueError("SUPABASE_DB_URL not configured (required for pooler connection)")
        return dsn
    else:
        # Migrations/CI use direct connection (port 5432)
        dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
        if not dsn:
            # Fallback to regular URL if migrate URL not set
            dsn = os.environ.get("SUPABASE_DB_URL")
        if not dsn:
            raise ValueError("SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL not configured")
        return dsn


def _calculate_backoff(attempt: int) -> float:
    """
    Calculate exponential backoff delay.

    Args:
        attempt: Current attempt number (1-indexed)

    Returns:
        Delay in seconds (capped at MAX_BACKOFF_SECONDS)
    """
    delay = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
    return min(delay, MAX_BACKOFF_SECONDS)


def _is_retryable_error(error: Exception) -> bool:
    """
    Check if an error is retryable (transient connection issue).

    Args:
        error: The exception that was raised

    Returns:
        True if the error is retryable
    """
    # psycopg3 connection errors
    if isinstance(error, psycopg.OperationalError):
        error_msg = str(error).lower()
        retryable_patterns = [
            "connection refused",
            "timeout",
            "circuit breaker",
            "could not connect",
            "server closed the connection",
            "connection reset",
            "network is unreachable",
            "no route to host",
            "too many connections",
            "canceling statement due to conflict",
        ]
        return any(pattern in error_msg for pattern in retryable_patterns)

    # Generic connection errors
    if isinstance(error, (ConnectionRefusedError, ConnectionResetError, TimeoutError)):
        return True

    return False


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for logging."""
    import re

    return re.sub(r":([^@:]+)@", ":****@", dsn)


# =============================================================================
# Main Connection Function
# =============================================================================


def connect_with_retry(
    use_pooler: bool = True,
    max_retries: int = MAX_RETRIES,
    row_factory=dict_row,
) -> psycopg.Connection:
    """
    Establish a database connection with retry logic.

    Args:
        use_pooler: If True, use pooler (6543). If False, use direct (5432).
        max_retries: Maximum number of retry attempts.
        row_factory: psycopg row factory (default: dict_row).

    Returns:
        Active database connection

    Raises:
        DatabaseOutageError: If all retry attempts fail
        PoolerUnavailableError: If pooler specifically is unavailable
    """
    dsn = _get_dsn(use_pooler)
    connection_type = "pooler (6543)" if use_pooler else "direct (5432)"

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            conn = psycopg.connect(
                dsn,
                row_factory=row_factory,
                connect_timeout=CONNECTION_TIMEOUT_SECONDS,
            )

            # Verify connection is alive
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

            if attempt > 1:
                logger.info(f"✅ Database connection established on attempt {attempt}")

            return conn

        except Exception as e:
            last_error = e

            if not _is_retryable_error(e):
                # Non-retryable error (auth failure, etc.) - fail immediately
                logger.error(f"❌ Non-retryable database error: {e}")
                raise

            if attempt < max_retries:
                backoff = _calculate_backoff(attempt)
                logger.warning(
                    f"⚠️ {connection_type} connection failed (attempt {attempt}/{max_retries}). "
                    f"Retrying in {backoff:.1f}s... Error: {e}"
                )
                time.sleep(backoff)
            else:
                logger.error(
                    f"❌ {connection_type} connection failed after {max_retries} attempts. "
                    f"Last error: {e}"
                )

    # All retries exhausted
    error_cls = PoolerUnavailableError if use_pooler else DatabaseOutageError
    raise error_cls(
        f"Database unreachable via {connection_type} after {max_retries} attempts",
        attempts=max_retries,
        last_error=last_error,
    )


@contextmanager
def get_db_connection(
    use_pooler: bool = True,
    max_retries: int = MAX_RETRIES,
    row_factory=dict_row,
    autocommit: bool = False,
) -> Generator[psycopg.Connection, None, None]:
    """
    Context manager for database connections with automatic retry and cleanup.

    Args:
        use_pooler: If True, use pooler (6543). If False, use direct (5432).
        max_retries: Maximum number of retry attempts.
        row_factory: psycopg row factory (default: dict_row).
        autocommit: If True, enable autocommit mode.

    Yields:
        Active database connection

    Example:
        # For workers (uses pooler with retries)
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM ops.job_queue")

        # For CI/migrations (uses direct connection)
        with get_db_connection(use_pooler=False) as conn:
            ...
    """
    conn = connect_with_retry(
        use_pooler=use_pooler,
        max_retries=max_retries,
        row_factory=row_factory,
    )

    try:
        if autocommit:
            conn.autocommit = True
        yield conn
    finally:
        try:
            conn.close()
        except Exception as e:
            logger.warning(f"Error closing database connection: {e}")


# =============================================================================
# Convenience Functions
# =============================================================================


def get_pooler_connection(**kwargs):  # type: ignore[no-untyped-def]
    """Get a connection via the pooler (port 6543). For workers/app."""
    return get_db_connection(use_pooler=True, **kwargs)


def get_direct_connection(**kwargs):  # type: ignore[no-untyped-def]
    """Get a direct connection (port 5432). For migrations/CI."""
    return get_db_connection(use_pooler=False, **kwargs)


def test_connection(use_pooler: bool = True) -> bool:
    """
    Test if database is reachable.

    Args:
        use_pooler: Which connection type to test

    Returns:
        True if connection succeeded, False otherwise
    """
    try:
        with get_db_connection(use_pooler=use_pooler, max_retries=1) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except Exception:
        return False
