"""Structured JSON logging utilities for Dragonfly services."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Set

from .context import get_request_id

_DEFAULT_SERVICE = os.getenv("DRAGONFLY_SERVICE", "dragonfly-api")
_BASE_ENV = os.getenv("ENVIRONMENT", os.getenv("DRAGONFLY_ACTIVE_ENV", "dev"))

_LOG_DEFAULTS_READY = False
_LOG_DEFAULTS: Dict[str, str] = {
    "env": _BASE_ENV,
    "sha": "unknown",
    "sha_short": "unknown",
    "version": "unknown",
    "sha_source": "unknown",
}
_BOOT_LOG_EMITTED = False


def _populate_log_defaults(force: bool = False) -> None:
    """Load version metadata from the centralized resolver."""

    global _LOG_DEFAULTS_READY
    if _LOG_DEFAULTS_READY and not force:
        return

    info: Dict[str, str] = {}
    try:
        from backend.middleware.version import get_version_info as _resolve_version_info

        info = _resolve_version_info()
    except Exception:
        info = {}

    if info:
        _LOG_DEFAULTS.update(
            {
                "env": info.get("env", _LOG_DEFAULTS["env"]),
                "sha": info.get("sha", _LOG_DEFAULTS["sha"]),
                "sha_short": info.get("sha_short", _LOG_DEFAULTS["sha_short"]),
                "version": info.get("version", _LOG_DEFAULTS["version"]),
                "sha_source": info.get("sha_source", _LOG_DEFAULTS["sha_source"]),
            }
        )

    _LOG_DEFAULTS_READY = True


def get_log_metadata() -> Dict[str, str]:
    """Return a copy of the current log metadata (env/sha/version)."""

    _populate_log_defaults()
    return dict(_LOG_DEFAULTS)


def _log_version_bootline() -> None:
    """Emit the single boot log line once logging is configured."""

    global _BOOT_LOG_EMITTED
    if _BOOT_LOG_EMITTED:
        return

    metadata = get_log_metadata()
    logging.getLogger(__name__).info(
        "🚀 Version resolved | sha_short=%s env=%s version=%s source=%s",
        metadata.get("sha_short", "unknown"),
        metadata.get("env", "unknown"),
        metadata.get("version", "unknown"),
        metadata.get("sha_source", "unknown"),
    )
    _BOOT_LOG_EMITTED = True


# Patterns for sensitive values that should never be logged
_SENSITIVE_PATTERNS: Set[re.Pattern[str]] = {
    re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+", re.I),  # JWT tokens
    re.compile(r"sbp_[a-zA-Z0-9]+", re.I),  # Supabase keys
    re.compile(r"sk-[a-zA-Z0-9]+", re.I),  # OpenAI keys
    re.compile(r"password\s*=\s*[^\s]+", re.I),  # Password in DSN
}

# Field names that indicate sensitive content
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "key",
        "authorization",
        "auth",
        "credential",
        "private_key",
    }
)


def _redact_sensitive(value: Any) -> Any:
    """Redact sensitive patterns from a string value."""
    if not isinstance(value, str):
        return value
    result = value
    for pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _is_sensitive_key(key: str) -> bool:
    """Check if a key name indicates sensitive content."""
    key_lower = key.lower()
    return any(s in key_lower for s in _SENSITIVE_FIELD_NAMES)


class JSONFormatter(logging.Formatter):
    """Format log records as structured JSON lines with sensitive value redaction."""

    def __init__(self, service_name: str | None = None) -> None:
        super().__init__()
        self.service_name = service_name or _DEFAULT_SERVICE
        _populate_log_defaults()
        self._defaults = dict(_LOG_DEFAULTS)

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - inherited docstring
        request_id = get_request_id() or getattr(record, "request_id", None)

        log_record: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service_name,
            "env": self._defaults["env"],
            "sha": self._defaults["sha"],
            "sha_short": self._defaults["sha_short"],
            "version": self._defaults["version"],
            "msg": _redact_sensitive(record.getMessage()),
        }

        # Only include request_id if present (avoid noise in workers)
        if request_id:
            log_record["request_id"] = request_id

        # Include extra fields passed via extra= or loguru-style kwargs
        # Filter out standard LogRecord attributes
        standard_attrs = {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "message",
            "request_id",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                if _is_sensitive_key(key):
                    log_record[key] = "[REDACTED]"
                else:
                    log_record[key] = _redact_sensitive(value)

        if record.exc_info:
            error_type = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            log_record["error_type"] = error_type
            log_record["error_msg"] = _redact_sensitive(str(record.exc_info[1]))

        if record.stack_info:
            log_record["stack"] = _redact_sensitive(record.stack_info)

        return json.dumps(log_record, default=str, ensure_ascii=False)


def setup_logging(service_name: str | None = None, level: int | None = None) -> None:
    """
    Configure root logging with JSON output and sane defaults.

    Args:
        service_name: Service identifier for logs (default: dragonfly-api)
        level: Override log level (default: DEBUG for dev, INFO otherwise)
    """
    env = os.getenv("ENVIRONMENT", os.getenv("DRAGONFLY_ACTIVE_ENV", "dev")).lower()
    if level is None:
        level = logging.DEBUG if env in ("dev", "development") else logging.INFO

    _populate_log_defaults(force=True)

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter(service_name=service_name))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.addHandler(handler)

    # Silence noisy third-party loggers
    noisy_loggers = (
        "uvicorn.access",
        "uvicorn.error",
        "httpx",
        "httpcore",
        "hpack",
        "asyncio",
        "apscheduler.scheduler",
        "apscheduler.executors",
    )
    for noisy_logger in noisy_loggers:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _log_version_bootline()


def get_structured_logger(name: str) -> logging.Logger:
    """Get a logger that's compatible with structured logging."""
    return logging.getLogger(name)
