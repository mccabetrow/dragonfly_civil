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
from typing import Any, Callable, Dict, Generator, Literal, Optional, TypeVar
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
        service_name: str = "dragonfly",
    ):
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_traceback = include_traceback
        self.redact_sensitive_data = redact_sensitive_data
        self.service_name = service_name

        # Cache version info at init (called once per process lifetime)
        self._version_info: Dict[str, str] = {}
        try:
            from backend.middleware.version import get_version_info

            self._version_info = get_version_info()
        except Exception:
            pass

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON with required fields."""
        # Import here to avoid circular imports
        from backend.utils.context import get_request_id

        # Resolve request_id from contextvar
        request_id = get_request_id() or getattr(record, "request_id", None)

        # Base log structure - REQUIRED fields first
        log_dict: Dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "env": self._version_info.get("env", "unknown"),
            "sha": self._version_info.get("sha", "unknown"),
            "sha_short": self._version_info.get("sha_short", "unknown"),
        }

        # Only include request_id if present (workers don't have one)
        if request_id:
            log_dict["request_id"] = request_id

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
# Trace Execution Decorator
# =============================================================================


def trace_execution(
    operation: Optional[str] = None,
    include_args: bool = False,
    log_result: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that provides structured START/END tracing with correlation IDs.

    Automatically logs:
    - START: function entry with trace_id, operation name, optional args
    - END: function exit with duration_ms, status (success/error)
    - EXCEPTION: full traceback with trace_id for correlation

    The decorator generates a trace_id if none exists in context, ensuring
    all logs within the decorated function can be correlated.

    Usage:
        @trace_execution("ingest_batch")
        async def process_batch(batch_id: str) -> int:
            ...

        @trace_execution(include_args=True)
        def calculate_score(judgment_id: int, factors: list) -> float:
            ...

    Args:
        operation: Name for the operation (defaults to function name)
        include_args: If True, log function arguments in START message
        log_result: If True, log return value in END message

    Returns:
        Decorated function with START/END tracing
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        op_name = operation or func.__name__
        func_logger = logging.getLogger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            # Generate or reuse trace_id
            trace_id = get_run_id()

            # Build START log extras
            start_extra: Dict[str, Any] = {
                "trace_id": trace_id,
                "operation": op_name,
                "event": "START",
            }
            if include_args:
                # Redact sensitive args before logging
                safe_kwargs = redact_sensitive(kwargs)
                start_extra["func_args"] = str(args)[:200]
                start_extra["func_kwargs"] = str(safe_kwargs)[:500]

            func_logger.info(f"[{op_name}] START", extra=start_extra)

            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000

                end_extra: Dict[str, Any] = {
                    "trace_id": trace_id,
                    "operation": op_name,
                    "event": "END",
                    "status": "success",
                    "duration_ms": round(duration_ms, 2),
                }
                if log_result:
                    end_extra["result"] = str(result)[:200]

                func_logger.info(f"[{op_name}] END", extra=end_extra)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                func_logger.error(
                    f"[{op_name}] EXCEPTION: {type(e).__name__}: {e}",
                    extra={
                        "trace_id": trace_id,
                        "operation": op_name,
                        "event": "EXCEPTION",
                        "status": "error",
                        "duration_ms": round(duration_ms, 2),
                        "error_type": type(e).__name__,
                        "error_message": str(e)[:500],
                        "traceback": traceback.format_exc(),
                    },
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            trace_id = get_run_id()

            start_extra: Dict[str, Any] = {
                "trace_id": trace_id,
                "operation": op_name,
                "event": "START",
            }
            if include_args:
                safe_kwargs = redact_sensitive(kwargs)
                start_extra["func_args"] = str(args)[:200]
                start_extra["func_kwargs"] = str(safe_kwargs)[:500]

            func_logger.info(f"[{op_name}] START", extra=start_extra)

            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000

                end_extra: Dict[str, Any] = {
                    "trace_id": trace_id,
                    "operation": op_name,
                    "event": "END",
                    "status": "success",
                    "duration_ms": round(duration_ms, 2),
                }
                if log_result:
                    end_extra["result"] = str(result)[:200]

                func_logger.info(f"[{op_name}] END", extra=end_extra)
                return result

            except Exception as e:
                duration_ms = (time.perf_counter() - start) * 1000
                func_logger.error(
                    f"[{op_name}] EXCEPTION: {type(e).__name__}: {e}",
                    extra={
                        "trace_id": trace_id,
                        "operation": op_name,
                        "event": "EXCEPTION",
                        "status": "error",
                        "duration_ms": round(duration_ms, 2),
                        "error_type": type(e).__name__,
                        "error_message": str(e)[:500],
                        "traceback": traceback.format_exc(),
                    },
                )
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore
        return sync_wrapper

    return decorator


# =============================================================================
# Metrics Helper Class
# =============================================================================


class Metrics:
    """
    Structured metrics logging for job processing and pipeline observability.

    Emits standardized "METRIC" log events that can be parsed by log
    aggregation systems (Datadog, CloudWatch, Grafana Loki) for dashboards.

    Usage:
        metrics = Metrics("enrichment_worker")

        metrics.job_claimed(job_id=123, job_kind="tloxp")
        metrics.job_success(job_id=123, job_kind="tloxp", duration_ms=1234.5)
        metrics.job_failure(job_id=123, job_kind="tloxp", error="timeout")

        metrics.record_latency("enrichment", 1234.5)
        metrics.increment("rows_processed", 100)

    Log format:
        {"event": "METRIC", "metric": "job_claimed", "job_id": 123, ...}
    """

    def __init__(self, namespace: str = "dragonfly"):
        """
        Initialize metrics with a namespace.

        Args:
            namespace: Prefix for metric identification (e.g., "enrichment_worker")
        """
        self.namespace = namespace
        self._logger = logging.getLogger(f"metrics.{namespace}")

    def _emit(self, metric: str, **fields: Any) -> None:
        """Emit a structured metric log entry."""
        self._logger.info(
            f"[METRIC] {self.namespace}.{metric}",
            extra={
                "event": "METRIC",
                "namespace": self.namespace,
                "metric": metric,
                "trace_id": get_run_id(),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                **fields,
            },
        )

    # -------------------------------------------------------------------------
    # Job Lifecycle Metrics
    # -------------------------------------------------------------------------

    def job_claimed(self, job_id: int, job_kind: str, **extra: Any) -> None:
        """Record a job claim event."""
        self._emit("job_claimed", job_id=job_id, job_kind=job_kind, **extra)

    def job_success(
        self,
        job_id: int,
        job_kind: str,
        duration_ms: float,
        **extra: Any,
    ) -> None:
        """Record a successful job completion."""
        self._emit(
            "job_success",
            job_id=job_id,
            job_kind=job_kind,
            duration_ms=round(duration_ms, 2),
            **extra,
        )

    def job_failure(
        self,
        job_id: int,
        job_kind: str,
        error: str,
        duration_ms: Optional[float] = None,
        attempt: int = 1,
        **extra: Any,
    ) -> None:
        """Record a job failure."""
        self._emit(
            "job_failure",
            job_id=job_id,
            job_kind=job_kind,
            error=error[:500],
            duration_ms=round(duration_ms, 2) if duration_ms else None,
            attempt=attempt,
            **extra,
        )

    def job_retry(
        self,
        job_id: int,
        job_kind: str,
        attempt: int,
        max_attempts: int,
        **extra: Any,
    ) -> None:
        """Record a job retry event."""
        self._emit(
            "job_retry",
            job_id=job_id,
            job_kind=job_kind,
            attempt=attempt,
            max_attempts=max_attempts,
            **extra,
        )

    # -------------------------------------------------------------------------
    # Latency & Counter Metrics
    # -------------------------------------------------------------------------

    def record_latency(self, operation: str, duration_ms: float, **extra: Any) -> None:
        """Record operation latency for tracking percentiles."""
        self._emit(
            "latency",
            operation=operation,
            duration_ms=round(duration_ms, 2),
            **extra,
        )

    def increment(self, counter: str, value: int = 1, **extra: Any) -> None:
        """Increment a counter metric."""
        self._emit("counter", counter=counter, value=value, **extra)

    # -------------------------------------------------------------------------
    # Batch / Pipeline Metrics
    # -------------------------------------------------------------------------

    def batch_started(self, batch_id: str, total_rows: int, **extra: Any) -> None:
        """Record batch processing start."""
        self._emit(
            "batch_started",
            batch_id=batch_id,
            total_rows=total_rows,
            **extra,
        )

    def batch_completed(
        self,
        batch_id: str,
        total_rows: int,
        valid_rows: int,
        error_rows: int,
        duration_ms: float,
        **extra: Any,
    ) -> None:
        """Record batch processing completion."""
        success_rate = (valid_rows / total_rows * 100) if total_rows > 0 else 0.0
        self._emit(
            "batch_completed",
            batch_id=batch_id,
            total_rows=total_rows,
            valid_rows=valid_rows,
            error_rows=error_rows,
            success_rate=round(success_rate, 2),
            duration_ms=round(duration_ms, 2),
            **extra,
        )

    def enrichment_completed(
        self,
        judgment_id: int,
        enrichment_type: str,
        duration_ms: float,
        success: bool,
        **extra: Any,
    ) -> None:
        """Record enrichment completion for a single judgment."""
        self._emit(
            "enrichment_completed",
            judgment_id=judgment_id,
            enrichment_type=enrichment_type,
            duration_ms=round(duration_ms, 2),
            success=success,
            **extra,
        )


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


# =============================================================================
# Redacting Formatter (Security: masks secrets in log output)
# =============================================================================

import re

# Patterns that should be redacted from log messages
_REDACT_PATTERNS = [
    # JWTs (eyJ... format)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[JWT_REDACTED]"),
    # Supabase service role keys (typically start with eyJ)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{50,}"), "[SERVICE_KEY_REDACTED]"),
    # API keys (sk_..., pk_..., api_...)
    (re.compile(r"\b(sk_|pk_|api_)[A-Za-z0-9_-]{20,}"), "[API_KEY_REDACTED]"),
    # Bearer tokens
    (re.compile(r"Bearer\s+[A-Za-z0-9_-]{20,}", re.IGNORECASE), "Bearer [TOKEN_REDACTED]"),
    # Database URLs with passwords
    (re.compile(r"(postgresql://[^:]+:)[^@]+(@)"), r"\1[REDACTED]\2"),
    # Generic secrets in key=value format
    (
        re.compile(r"(password|secret|token|key|credential)[=:]\s*['\"]?[^\s'\"]+", re.IGNORECASE),
        r"\1=[REDACTED]",
    ),
]


class RedactingFormatter(logging.Formatter):
    """
    Formatter that redacts sensitive patterns from log messages.

    Automatically masks:
    - JWTs (eyJ... format)
    - API keys (sk_*, pk_*, api_*)
    - Bearer tokens
    - Database URLs with passwords
    - Generic secrets in key=value format

    Usage:
        formatter = RedactingFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
    ):
        if fmt is None:
            fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        if datefmt is None:
            datefmt = "%Y-%m-%d %H:%M:%S"
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)

    def format(self, record: logging.LogRecord) -> str:
        """Format the record, redacting sensitive patterns."""
        # Format normally first
        formatted = super().format(record)

        # Apply all redaction patterns
        for pattern, replacement in _REDACT_PATTERNS:
            formatted = pattern.sub(replacement, formatted)

        return formatted

    @staticmethod
    def redact_string(text: str) -> str:
        """Utility method to redact a string without formatting."""
        for pattern, replacement in _REDACT_PATTERNS:
            text = pattern.sub(replacement, text)
        return text


class _RedactingSimpleFormatter(RedactingFormatter):
    """Simple format with redaction for workers."""

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

    Security: Uses RedactingFormatter to mask JWTs, API keys, and secrets.

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

    # Create split handlers with REDACTING format (security: masks secrets)
    formatter = _RedactingSimpleFormatter()
    handlers = _create_split_handlers(formatter, getattr(logging, level.upper()))
    for handler in handlers:
        root_logger.addHandler(handler)

    return logging.getLogger(worker_name)
