"""
Dragonfly Structured Logging - Production-Grade Observability

Features:
- JSON-formatted logs for log aggregation systems
- Automatic contextvars injection (job_id, batch_id, worker_id)
- Human-readable fallback for local development
- Correlation ID propagation

Usage:
    from backend.utils.logger import get_logger, set_context

    logger = get_logger(__name__)

    # Set context for current request/job
    set_context(job_id="abc-123", worker_id="worker-1")

    # All subsequent logs will include context
    logger.info("Processing job")
    # Output: {"timestamp": "...", "level": "INFO", "message": "Processing job",
    #          "job_id": "abc-123", "worker_id": "worker-1", ...}
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Contextvars for automatic log enrichment
_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)

# Standard context keys that are automatically included
CONTEXT_KEYS = frozenset(
    [
        "job_id",
        "batch_id",
        "worker_id",
        "worker_type",
        "request_id",
        "correlation_id",
        "plaintiff_id",
        "judgment_id",
    ]
)


def set_context(**kwargs: Any) -> None:
    """
    Set context values for the current async context.

    These values will be automatically included in all log records
    within this context scope.

    Args:
        **kwargs: Context key-value pairs (job_id, batch_id, worker_id, etc.)

    Example:
        set_context(job_id="abc-123", worker_id="worker-1")
    """
    current = _log_context.get().copy()
    for key, value in kwargs.items():
        if value is not None:
            current[key] = str(value) if not isinstance(value, str) else value
        elif key in current:
            del current[key]
    _log_context.set(current)


def clear_context() -> None:
    """Clear all context values."""
    _log_context.set({})


def get_context() -> dict[str, Any]:
    """Get a copy of the current context."""
    return _log_context.get().copy()


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter that includes contextvars automatically.

    Output format:
    {
        "timestamp": "2024-01-01T12:00:00.000Z",
        "level": "INFO",
        "logger": "backend.workers.ingest",
        "message": "Job completed",
        "job_id": "abc-123",
        "worker_id": "worker-1",
        ...
    }
    """

    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add context from contextvars
        context = _log_context.get()
        for key in CONTEXT_KEYS:
            if key in context:
                log_entry[key] = context[key]

        # Add any extra fields from the log record
        if hasattr(record, "__dict__"):
            for key, value in record.__dict__.items():
                if key in CONTEXT_KEYS and key not in log_entry:
                    log_entry[key] = value

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add source location for DEBUG/ERROR
        if record.levelno >= logging.WARNING or record.levelno == logging.DEBUG:
            log_entry["source"] = f"{record.filename}:{record.lineno}"
            log_entry["function"] = record.funcName

        return json.dumps(log_entry, default=str)


class HumanReadableFormatter(logging.Formatter):
    """
    Human-readable formatter with context for local development.

    Output format:
    2024-01-01 12:00:00 | INFO | backend.workers.ingest | job_id=abc-123 | Job completed
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level = record.levelname.ljust(8)
        logger_name = record.name

        # Build context string
        context = _log_context.get()
        context_parts = []
        for key in sorted(CONTEXT_KEYS):
            if key in context:
                context_parts.append(f"{key}={context[key]}")

        context_str = " | ".join(context_parts) if context_parts else ""

        # Format message
        message = record.getMessage()

        if context_str:
            formatted = f"{timestamp} | {level} | {logger_name} | {context_str} | {message}"
        else:
            formatted = f"{timestamp} | {level} | {logger_name} | {message}"

        # Add exception if present
        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)

        return formatted


def configure_logging(
    level: str | int = "INFO",
    json_output: bool | None = None,
    stream: Any = None,
) -> None:
    """
    Configure the logging system with structured output.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: Force JSON output (None = auto-detect based on DRAGONFLY_LOG_FORMAT)
        stream: Output stream (default: sys.stderr)

    Environment Variables:
        DRAGONFLY_LOG_LEVEL: Override log level
        DRAGONFLY_LOG_FORMAT: "json" or "human" (default: auto-detect)
    """
    # Determine log level
    env_level = os.getenv("DRAGONFLY_LOG_LEVEL", "").upper()
    if env_level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        level = env_level

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Determine output format
    if json_output is None:
        env_format = os.getenv("DRAGONFLY_LOG_FORMAT", "").lower()
        if env_format == "json":
            json_output = True
        elif env_format == "human":
            json_output = False
        else:
            # Auto-detect: JSON in production (Railway sets RAILWAY_ENVIRONMENT)
            json_output = bool(os.getenv("RAILWAY_ENVIRONMENT"))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create handler with appropriate formatter
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setLevel(level)

    if json_output:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(HumanReadableFormatter())

    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("supabase").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.

    This is the preferred way to get loggers in Dragonfly.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for scoped logging context.

    Usage:
        with LogContext(job_id="abc-123"):
            logger.info("Processing")  # Includes job_id
        logger.info("Done")  # No job_id
    """

    def __init__(self, **kwargs: Any):
        self.new_context = kwargs
        self.old_context: dict[str, Any] = {}

    def __enter__(self) -> "LogContext":
        self.old_context = _log_context.get().copy()
        new = self.old_context.copy()
        new.update(self.new_context)
        _log_context.set(new)
        return self

    def __exit__(self, *args: Any) -> None:
        _log_context.set(self.old_context)


# Auto-configure on import if not already configured
if not logging.getLogger().handlers:
    configure_logging()
