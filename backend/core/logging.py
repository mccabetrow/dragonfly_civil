"""
Dragonfly Engine - Structured Logging

Production-grade structured logging with JSON output for observability.
All log entries include:
- timestamp (ISO 8601)
- level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
- logger name
- message
- Context fields (run_id, judgment_id, case_number, etc.)

Features:
- JSON format for log aggregation (Datadog, CloudWatch, etc.)
- Correlation IDs for request/job tracing
- Performance timing utilities
- Sensitive data redaction

Usage:
    from backend.core.logging import get_logger, LogContext

    logger = get_logger(__name__)

    with LogContext(run_id=run_id, judgment_id=123):
        logger.info("Processing started")
        # All logs in this block include run_id and judgment_id
"""

from __future__ import annotations

import json
import logging
import sys
import time
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Dict, Generator, Optional, TypeVar
from uuid import UUID, uuid4

from pydantic import BaseModel

# =============================================================================
# Context Variables for Correlation
# =============================================================================

_log_context: ContextVar[Dict[str, Any]] = ContextVar("log_context", default={})
_run_id: ContextVar[Optional[str]] = ContextVar("run_id", default=None)


def get_current_context() -> Dict[str, Any]:
    """Get current logging context."""
    return _log_context.get().copy()


def set_context(**kwargs: Any) -> None:
    """Set context values for current async context."""
    current = _log_context.get().copy()
    current.update(kwargs)
    _log_context.set(current)


def clear_context() -> None:
    """Clear all context values."""
    _log_context.set({})


def get_run_id() -> str:
    """Get or create run ID for current context."""
    run_id = _run_id.get()
    if run_id is None:
        run_id = str(uuid4())
        _run_id.set(run_id)
    return run_id


def set_run_id(run_id: str | UUID) -> None:
    """Set run ID for current context."""
    _run_id.set(str(run_id))


# =============================================================================
# Sensitive Data Redaction
# =============================================================================

REDACT_PATTERNS = frozenset(
    {
        "ssn",
        "social_security",
        "password",
        "secret",
        "api_key",
        "apikey",
        "token",
        "auth",
        "credential",
        "credit_card",
        "card_number",
        "cvv",
        "bank_account",
        "routing_number",
    }
)


def redact_sensitive(data: Any, max_depth: int = 10) -> Any:
    """
    Recursively redact sensitive fields from data structures.

    Args:
        data: Data to redact (dict, list, or primitive)
        max_depth: Maximum recursion depth to prevent infinite loops

    Returns:
        Data with sensitive fields redacted
    """
    if max_depth <= 0:
        return "[MAX_DEPTH_EXCEEDED]"

    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(pattern in key_lower for pattern in REDACT_PATTERNS):
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_sensitive(value, max_depth - 1)
        return result

    if isinstance(data, (list, tuple)):
        return [redact_sensitive(item, max_depth - 1) for item in data]

    if isinstance(data, BaseModel):
        return redact_sensitive(data.model_dump(), max_depth - 1)

    return data


# =============================================================================
# JSON Formatter
# =============================================================================


class StructuredJsonFormatter(logging.Formatter):
    """
    JSON log formatter for production environments.

    Output format:
    {
        "timestamp": "2025-12-07T10:30:00.123456Z",
        "level": "INFO",
        "logger": "backend.services.enrichment_service",
        "message": "Enrichment completed",
        "run_id": "abc-123",
        "judgment_id": 456,
        "duration_ms": 1234,
        ...
    }
    """

    def __init__(
        self,
        include_timestamp: bool = True,
        include_traceback: bool = True,
        redact_sensitive_data: bool = True,
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_traceback = include_traceback
        self.redact_sensitive_data = redact_sensitive_data

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        # Base log structure
        log_dict: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add timestamp
        if self.include_timestamp:
            log_dict["timestamp"] = datetime.now(timezone.utc).isoformat()

        # Add run_id from context
        run_id = _run_id.get()
        if run_id:
            log_dict["run_id"] = run_id

        # Merge context variables
        context = get_current_context()
        if context:
            if self.redact_sensitive_data:
                context = redact_sensitive(context)
            log_dict.update(context)

        # Add extra fields from record
        extra_keys = {
            "judgment_id",
            "case_number",
            "job_id",
            "batch_id",
            "duration_ms",
            "status",
            "error_code",
            "count",
            "pool_name",
            "score",
            "tier",
        }
        for key in extra_keys:
            value = getattr(record, key, None)
            if value is not None:
                log_dict[key] = value

        # Handle exception info
        if record.exc_info and self.include_traceback:
            log_dict["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # Redact if enabled
        if self.redact_sensitive_data:
            log_dict = redact_sensitive(log_dict)

        return json.dumps(log_dict, default=str, ensure_ascii=False)


# =============================================================================
# Console Formatter (for development)
# =============================================================================


class ColoredConsoleFormatter(logging.Formatter):
    """Colored console output for development."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")

        # Build context string
        context_parts = []
        run_id = _run_id.get()
        if run_id:
            context_parts.append(f"run={run_id[:8]}")

        context = get_current_context()
        for key in ("judgment_id", "case_number", "job_id"):
            if key in context:
                context_parts.append(f"{key}={context[key]}")

        context_str = f" [{', '.join(context_parts)}]" if context_parts else ""

        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        return (
            f"{color}[{timestamp}] {record.levelname:8}{self.RESET} "
            f"{record.name}:{context_str} {record.getMessage()}"
        )


# =============================================================================
# Split-Stream Handler (stdout for INFO/DEBUG, stderr for WARNING+)
# =============================================================================


class _MaxLevelFilter(logging.Filter):
    """Filter that passes records at or below a maximum level."""

    def __init__(self, max_level: int):
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def _create_split_handlers(
    formatter: logging.Formatter,
    level: int = logging.DEBUG,
) -> list[logging.Handler]:
    """
    Create handlers that route logs to stdout/stderr based on level.

    - DEBUG, INFO → stdout
    - WARNING, ERROR, CRITICAL → stderr

    This prevents PowerShell/CI from treating INFO logs as errors.
    """
    # stdout handler: DEBUG and INFO only
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(level)
    stdout_handler.addFilter(_MaxLevelFilter(logging.INFO))
    stdout_handler.setFormatter(formatter)

    # stderr handler: WARNING and above
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    stderr_handler.setFormatter(formatter)

    return [stdout_handler, stderr_handler]


# =============================================================================
# Logger Configuration
# =============================================================================


def configure_structured_logging(
    level: str = "INFO",
    json_output: bool = True,
    service_name: str = "dragonfly",
) -> None:
    """
    Configure structured logging for the application.

    Log routing:
    - DEBUG, INFO → stdout (avoids NativeCommandError in PowerShell/CI)
    - WARNING, ERROR, CRITICAL → stderr

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, use JSON format; else use colored console
        service_name: Service name for log tagging
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create formatter
    if json_output:
        formatter = StructuredJsonFormatter()
    else:
        formatter = ColoredConsoleFormatter()

    # Create split handlers (stdout for INFO-, stderr for WARNING+)
    handlers = _create_split_handlers(formatter, getattr(logging, level.upper()))
    for handler in handlers:
        root_logger.addHandler(handler)

    # Set context
    set_context(service=service_name)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance with structured logging support.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# =============================================================================
# Context Manager
# =============================================================================


@contextmanager
def LogContext(**kwargs: Any) -> Generator[None, None, None]:
    """
    Context manager for adding fields to all logs within the block.

    Usage:
        with LogContext(judgment_id=123, case_number="2024-CV-001"):
            logger.info("Processing")  # Includes judgment_id and case_number
    """
    # Save current context
    previous = _log_context.get().copy()
    previous_run_id = _run_id.get()

    try:
        # Merge new context
        new_context = previous.copy()

        # Handle run_id specially
        if "run_id" in kwargs:
            _run_id.set(str(kwargs.pop("run_id")))

        new_context.update(kwargs)
        _log_context.set(new_context)

        yield
    finally:
        # Restore previous context
        _log_context.set(previous)
        _run_id.set(previous_run_id)


# =============================================================================
# Timing Utilities
# =============================================================================


T = TypeVar("T")


def log_timing(
    logger: logging.Logger,
    operation: str,
    level: int = logging.INFO,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator to log function execution time.

    Usage:
        @log_timing(logger, "enrichment")
        async def enrich_judgment(judgment_id: int):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                logger.log(
                    level,
                    f"{operation} completed",
                    extra={"duration_ms": round(duration_ms, 2), "status": "success"},
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{operation} failed: {e}",
                    extra={"duration_ms": round(duration_ms, 2), "status": "error"},
                    exc_info=True,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                logger.log(
                    level,
                    f"{operation} completed",
                    extra={"duration_ms": round(duration_ms, 2), "status": "success"},
                )
                return result
            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.error(
                    f"{operation} failed: {e}",
                    extra={"duration_ms": round(duration_ms, 2), "status": "error"},
                    exc_info=True,
                )
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper

    return decorator


class Timer:
    """
    Context manager for timing code blocks.

    Usage:
        with Timer() as t:
            do_something()
        logger.info("Operation took", extra={"duration_ms": t.elapsed_ms})
    """

    def __init__(self) -> None:
        self.start_time: float = 0
        self.end_time: float = 0

    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.end_time = time.perf_counter()

    @property
    def elapsed_ms(self) -> float:
        """Elapsed time in milliseconds."""
        end = self.end_time or time.perf_counter()
        return (end - self.start_time) * 1000

    @property
    def elapsed_seconds(self) -> float:
        """Elapsed time in seconds."""
        return self.elapsed_ms / 1000


# =============================================================================
# Worker Logging Helpers
# =============================================================================


def log_worker_start(
    logger: logging.Logger,
    kind: str,
    job_id: int,
    run_id: str | UUID,
    **extra: Any,
) -> None:
    """Log worker job start with standard fields."""
    set_run_id(run_id)
    set_context(job_id=job_id, kind=kind, **extra)
    logger.info(
        "Worker job started",
        extra={"job_id": job_id, "kind": kind, "status": "started", **extra},
    )


def log_worker_success(
    logger: logging.Logger,
    kind: str,
    job_id: int,
    duration_ms: float,
    **extra: Any,
) -> None:
    """Log worker job success with standard fields."""
    logger.info(
        "Worker job completed",
        extra={
            "job_id": job_id,
            "kind": kind,
            "status": "success",
            "duration_ms": round(duration_ms, 2),
            **extra,
        },
    )


def log_worker_failure(
    logger: logging.Logger,
    kind: str,
    job_id: int,
    error: Exception,
    duration_ms: float,
    attempt: int = 1,
    max_attempts: int = 5,
    **extra: Any,
) -> None:
    """Log worker job failure with standard fields."""
    logger.error(
        f"Worker job failed: {error}",
        extra={
            "job_id": job_id,
            "kind": kind,
            "status": "failed",
            "duration_ms": round(duration_ms, 2),
            "attempt": attempt,
            "max_attempts": max_attempts,
            "error_type": type(error).__name__,
            "error_message": str(error),
            **extra,
        },
        exc_info=True,
    )


# =============================================================================
# Convenience Configuration
# =============================================================================


def configure_logging(
    level: str = "INFO",
    json_output: bool = True,
    service_name: str = "dragonfly",
) -> None:
    """
    Configure logging for the application (convenience alias).

    In production (Railway, etc.), uses JSON output for log aggregation.
    In development, can use colored console output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_output: If True, use JSON format; else use colored console
        service_name: Service name for log tagging
    """
    configure_structured_logging(
        level=level,
        json_output=json_output,
        service_name=service_name,
    )


class _SimpleFormatter(logging.Formatter):
    """Simple timestamp | level | name | message format for workers."""

    def __init__(self):
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def configure_worker_logging(
    worker_name: str,
    level: str = "INFO",
) -> logging.Logger:
    """
    Configure logging for a worker process with split stdout/stderr streams.

    - DEBUG, INFO → stdout (avoids NativeCommandError in PowerShell/CI)
    - WARNING, ERROR, CRITICAL → stderr

    Args:
        worker_name: Name of the worker (used as logger name).
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).

    Returns:
        Configured logger instance for the worker.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create split handlers with simple format
    formatter = _SimpleFormatter()
    handlers = _create_split_handlers(formatter, getattr(logging, level.upper()))
    for handler in handlers:
        root_logger.addHandler(handler)

    return logging.getLogger(worker_name)
