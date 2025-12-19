"""
Dragonfly Engine - Robust Database Connection for Workers

Provides production-grade database connection utilities for background workers:
- DSN sanitization (rejects quotes, internal whitespace, malformed values)
- DSN parsing and validation (never logs password)
- sslmode=require enforcement
- Exponential backoff with jitter (configurable retries)
- Structured logging for connection diagnostics
- Distinct exit codes for infrastructure alerting

Usage:
    from backend.workers.db_connect import (
        parse_and_validate_dsn,
        ensure_sslmode,
        connect_with_retry,
        db_smoke_test,
        EXIT_CODE_DB_UNAVAILABLE,
    )

Exit Codes:
    0  - Clean shutdown
    1  - General error
    2  - Database unavailable after retries (EXIT_CODE_DB_UNAVAILABLE)
"""

from __future__ import annotations

import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import psycopg
import psycopg.errors
from psycopg.rows import dict_row

from backend.dsn_sanitizer import DSNSanitizationError, sanitize_dsn

# Import version for application_name
try:
    from backend import __version__
except ImportError:
    __version__ = "0.0.0"

logger = logging.getLogger(__name__)

# Exit code when database is unavailable after all retries
EXIT_CODE_DB_UNAVAILABLE = 2

# Default retry configuration
DEFAULT_INITIAL_DELAY = 0.5  # seconds
DEFAULT_MAX_DELAY = 10.0  # seconds


def get_safe_application_name(worker_type: str = "worker") -> str:
    """
    Generate a PostgreSQL-safe application_name.

    Uses underscores only (no spaces, dots, or special chars) to avoid
    PostgreSQL option parsing issues that caused the v1.3.1 failure.

    Returns:
        String like "dragonfly_v1_3_1_ingest" (no spaces, no dots)
    """
    # Sanitize version: replace dots, spaces, dashes with underscores
    safe_version = __version__.replace(".", "_").replace(" ", "_").replace("-", "_")
    # Sanitize worker type
    safe_worker = worker_type.replace(" ", "_").replace("-", "_").replace(".", "_")
    return f"dragonfly_v{safe_version}_{safe_worker}"


DEFAULT_MAX_ATTEMPTS = 30
DEFAULT_JITTER_FACTOR = 0.2  # 20% jitter


# =============================================================================
# DSN Parsing and Validation
# =============================================================================


@dataclass
class DSNComponents:
    """Parsed DSN components (password excluded for safety)."""

    host: str | None
    port: str
    user: str | None
    dbname: str | None
    sslmode: str | None
    application_name: str | None
    is_valid: bool
    validation_error: str | None = None


def parse_and_validate_dsn(dsn: str) -> DSNComponents:
    """
    Parse DSN and extract loggable components.

    NEVER logs or returns the password.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        DSNComponents with parsed fields and validation status
    """
    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)

        # Extract components
        host = parsed.hostname
        port = str(parsed.port) if parsed.port else "5432"
        user = parsed.username
        dbname = parsed.path.lstrip("/") if parsed.path else None
        sslmode = query_params.get("sslmode", [None])[0]
        app_name = query_params.get("application_name", [None])[0]

        # Validate required fields
        errors = []
        if not host:
            errors.append("missing host")
        if not user:
            errors.append("missing user")
        if not dbname:
            errors.append("missing dbname")

        is_valid = len(errors) == 0
        validation_error = "; ".join(errors) if errors else None

        return DSNComponents(
            host=host,
            port=port,
            user=user,
            dbname=dbname,
            sslmode=sslmode,
            application_name=app_name,
            is_valid=is_valid,
            validation_error=validation_error,
        )

    except Exception as e:
        return DSNComponents(
            host=None,
            port="5432",
            user=None,
            dbname=None,
            sslmode=None,
            application_name=None,
            is_valid=False,
            validation_error=f"DSN parse error: {e}",
        )


def log_dsn_info(dsn: str, worker_type: str) -> DSNComponents:
    """
    Parse DSN and log connection parameters.

    NEVER logs the password.

    Args:
        dsn: PostgreSQL connection string
        worker_type: Worker name for log context

    Returns:
        DSNComponents for validation checks
    """
    components = parse_and_validate_dsn(dsn)

    if components.is_valid:
        logger.info(
            f"[{worker_type}] Database connection parameters: "
            f"host={components.host}, port={components.port}, "
            f"user={components.user}, dbname={components.dbname}, "
            f"sslmode={components.sslmode or 'not_set'}"
        )
    else:
        logger.error(f"[{worker_type}] Invalid DSN: {components.validation_error}")

    return components


# =============================================================================
# SSL Mode Enforcement
# =============================================================================


def ensure_sslmode(dsn: str, required_mode: str = "require") -> str:
    """
    Ensure sslmode is set to the required level.

    If sslmode is not set or is weaker than required, upgrade it.
    Weak modes: disable, allow, prefer

    Args:
        dsn: PostgreSQL connection string
        required_mode: Minimum SSL mode (default: "require")

    Returns:
        DSN with sslmode enforced
    """
    weak_modes = {"disable", "allow", "prefer"}

    try:
        parsed = urlparse(dsn)
        query_params = parse_qs(parsed.query)

        current_sslmode = query_params.get("sslmode", [None])[0]

        if current_sslmode is None or current_sslmode in weak_modes:
            # Set or upgrade to required mode
            query_params["sslmode"] = [required_mode]
            new_query = urlencode(query_params, doseq=True)
            new_parsed = parsed._replace(query=new_query)
            new_dsn = urlunparse(new_parsed)

            if current_sslmode in weak_modes:
                logger.warning(
                    f"Upgraded sslmode from '{current_sslmode}' to '{required_mode}' for security"
                )
            else:
                logger.info(f"Added sslmode={required_mode} to DSN (was not set)")

            return new_dsn

        return dsn

    except Exception as e:
        logger.error(f"Failed to parse/modify DSN for sslmode: {e}")
        return dsn


# =============================================================================
# Connection with Retry
# =============================================================================


@dataclass
class RetryConfig:
    """Configuration for connection retry behavior."""

    initial_delay: float = DEFAULT_INITIAL_DELAY
    max_delay: float = DEFAULT_MAX_DELAY
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    jitter_factor: float = DEFAULT_JITTER_FACTOR
    connect_timeout: int = 10  # seconds


def connect_with_retry(
    dsn: str,
    worker_type: str,
    config: RetryConfig | None = None,
    exit_on_failure: bool = True,
) -> Optional[psycopg.Connection]:
    """
    Connect to PostgreSQL with exponential backoff and jitter.

    Performs DSN sanitization first to reject malformed connection strings.

    Args:
        dsn: PostgreSQL connection string (should have sslmode set)
        worker_type: Worker name for log context
        config: Retry configuration (uses defaults if None)
        exit_on_failure: If True, call sys.exit(EXIT_CODE_DB_UNAVAILABLE) on failure

    Returns:
        psycopg.Connection if successful, None if failed (when exit_on_failure=False)
    """
    config = config or RetryConfig()

    # Step 1: Sanitize DSN (reject quotes, internal whitespace, malformed values)
    try:
        sanitized = sanitize_dsn(dsn, raise_on_error=True)
        clean_dsn = sanitized.dsn

        # Log sanitization result
        if sanitized.stripped_leading or sanitized.stripped_trailing:
            stripped_parts = []
            if sanitized.stripped_leading:
                stripped_parts.append("leading")
            if sanitized.stripped_trailing:
                stripped_parts.append("trailing")
            logger.warning(
                f"[{worker_type}] DSN whitespace stripped ({' and '.join(stripped_parts)}): "
                f"original={sanitized.original_length}, sanitized={sanitized.sanitized_length}"
            )

        # Log safe components
        c = sanitized.components
        logger.info(
            f"[{worker_type}] DSN validated: "
            f"host={c.get('host')}, port={c.get('port')}, "
            f"user={c.get('user')}, dbname={c.get('dbname')}, "
            f"sslmode={c.get('sslmode')}"
        )

    except DSNSanitizationError as e:
        # Critical failure - DSN is malformed
        error_msg = f"[{worker_type}] FATAL: DSN sanitization failed: {e.message}"
        logger.critical(error_msg)
        if e.safe_dsn_info:
            logger.error(f"[{worker_type}] Safe DSN components: {e.safe_dsn_info}")

        if exit_on_failure:
            print(f"\n❌ {error_msg}", file=sys.stderr)
            print(f"Exiting with code {EXIT_CODE_DB_UNAVAILABLE} (invalid DSN)", file=sys.stderr)
            sys.exit(EXIT_CODE_DB_UNAVAILABLE)
        return None

    last_error: Exception | None = None
    delay = config.initial_delay

    for attempt in range(1, config.max_attempts + 1):
        try:
            logger.info(
                f"[{worker_type}] Connecting to database (attempt {attempt}/{config.max_attempts})"
            )

            start_time = time.monotonic()
            app_name = get_safe_application_name(worker_type)
            conn = psycopg.connect(
                clean_dsn,
                connect_timeout=config.connect_timeout,
                row_factory=dict_row,
                application_name=app_name,
            )
            elapsed_ms = (time.monotonic() - start_time) * 1000

            logger.info(f"[{worker_type}] Database connection established ({elapsed_ms:.0f}ms)")
            return conn

        except psycopg.OperationalError as e:
            last_error = e
            logger.warning(
                f"[{worker_type}] Connection attempt {attempt} failed: " f"{type(e).__name__}: {e}"
            )

        except Exception as e:
            last_error = e
            logger.error(
                f"[{worker_type}] Unexpected error on attempt {attempt}: "
                f"{type(e).__name__}: {e}"
            )

        # Calculate next delay with exponential backoff and jitter
        if attempt < config.max_attempts:
            jitter = random.uniform(-config.jitter_factor, config.jitter_factor) * delay
            actual_delay = min(delay + jitter, config.max_delay)
            actual_delay = max(actual_delay, config.initial_delay)  # Never go below initial

            logger.info(f"[{worker_type}] Waiting {actual_delay:.2f}s before retry...")
            time.sleep(actual_delay)

            # Exponential backoff for next iteration
            delay = min(delay * 2, config.max_delay)

    # All attempts exhausted
    error_msg = (
        f"[{worker_type}] FATAL: Database unavailable after {config.max_attempts} attempts. "
        f"Last error: {last_error}"
    )
    logger.critical(error_msg)

    if exit_on_failure:
        print(f"\n❌ {error_msg}", file=sys.stderr)
        print(f"Exiting with code {EXIT_CODE_DB_UNAVAILABLE} (DB unavailable)", file=sys.stderr)
        sys.exit(EXIT_CODE_DB_UNAVAILABLE)

    return None


# =============================================================================
# DB Smoke Test
# =============================================================================


def db_smoke_test(
    conn: psycopg.Connection,
    worker_type: str,
    timeout_seconds: float = 5.0,
) -> bool:
    """
    Run a quick connectivity smoke test before entering the job loop.

    Executes SELECT 1 to verify the connection is usable.

    Args:
        conn: Active database connection
        worker_type: Worker name for log context
        timeout_seconds: Query timeout

    Returns:
        True if smoke test passed, False otherwise
    """
    try:
        logger.info(f"[{worker_type}] Running DB smoke test (SELECT 1)...")
        start_time = time.monotonic()

        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS smoke_test")
            row = cur.fetchone()

        elapsed_ms = (time.monotonic() - start_time) * 1000

        if row and row.get("smoke_test") == 1:
            logger.info(f"[{worker_type}] DB smoke test passed ({elapsed_ms:.0f}ms)")
            return True
        else:
            logger.error(f"[{worker_type}] DB smoke test failed: unexpected result {row}")
            return False

    except Exception as e:
        logger.error(f"[{worker_type}] DB smoke test failed: {type(e).__name__}: {e}")
        return False


# =============================================================================
# Throttled Warning Logger
# =============================================================================


class ThrottledWarningLogger:
    """
    Logger that throttles repeated warnings to avoid log spam.

    Useful for heartbeat or polling loops where DB might be down
    for extended periods.

    Usage:
        throttled = ThrottledWarningLogger(
            logger=logger,
            min_interval=60.0,  # Log at most once per minute
        )

        # In loop:
        throttled.warning("DB connection failed", key="db_down")
    """

    def __init__(
        self,
        log: logging.Logger,
        min_interval: float = 60.0,
    ) -> None:
        self._logger = log
        self._min_interval = min_interval
        self._last_log_time: dict[str, float] = {}
        self._suppressed_count: dict[str, int] = {}

    def warning(self, message: str, key: str = "default") -> bool:
        """
        Log a warning if not recently logged for this key.

        Args:
            message: Warning message
            key: Deduplication key

        Returns:
            True if message was logged, False if suppressed
        """
        now = time.monotonic()
        last_time = self._last_log_time.get(key, 0)

        if now - last_time >= self._min_interval:
            # Time to log
            suppressed = self._suppressed_count.get(key, 0)
            if suppressed > 0:
                message = f"{message} (suppressed {suppressed} similar warnings)"

            self._logger.warning(message)
            self._last_log_time[key] = now
            self._suppressed_count[key] = 0
            return True
        else:
            # Suppress
            self._suppressed_count[key] = self._suppressed_count.get(key, 0) + 1
            return False

    def error(self, message: str, key: str = "default") -> bool:
        """Log an error if not recently logged for this key."""
        now = time.monotonic()
        last_time = self._last_log_time.get(key, 0)

        if now - last_time >= self._min_interval:
            suppressed = self._suppressed_count.get(key, 0)
            if suppressed > 0:
                message = f"{message} (suppressed {suppressed} similar errors)"

            self._logger.error(message)
            self._last_log_time[key] = now
            self._suppressed_count[key] = 0
            return True
        else:
            self._suppressed_count[key] = self._suppressed_count.get(key, 0) + 1
            return False
