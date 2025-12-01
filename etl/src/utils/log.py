"""Lightweight structured logging helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Final

__all__ = ["SafeFilter", "event", "get_logger"]

_DEFAULT_FORMAT: Final[str] = "[%(levelname)s] %(name)s: %(message)s"
_SENSITIVE_PATTERN = re.compile(r"(pass|token|cookie|key|secret|authorization)", re.IGNORECASE)
_ROOT_CONFIGURED = False


def _determine_level() -> int:
    configured = os.environ.get("LOG_LEVEL", "INFO").upper()
    return getattr(logging, configured, logging.INFO)


def _configure_root_logger() -> None:
    global _ROOT_CONFIGURED
    if _ROOT_CONFIGURED:
        return
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
        root.addHandler(handler)
    root.setLevel(_determine_level())
    if not any(isinstance(f, SafeFilter) for f in root.filters):
        root.addFilter(SafeFilter())
    _ROOT_CONFIGURED = True


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    return bool(_SENSITIVE_PATTERN.search(key))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: ("***" if _is_sensitive_key(k) else _redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(element) for element in value]
    return value


class SafeFilter(logging.Filter):
    """Filter that redacts sensitive values on structured log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - behavior verified via event
        payload = getattr(record, "_event_payload", None)
        if isinstance(payload, dict):
            redacted = _redact(payload)
            record.msg = json.dumps(redacted, separators=(",", ":"), sort_keys=True)
            record.args = ()
        return True


def event(name: str, **fields: Any) -> None:
    """Emit a structured JSON log line with sensitive fields redacted."""

    _configure_root_logger()
    payload = {"event": name, **fields}
    logging.getLogger().info("", extra={"_event_payload": payload})


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger that inherits the root configuration."""

    _configure_root_logger()
    logger = logging.getLogger(name)
    logger.setLevel(_determine_level())
    return logger
