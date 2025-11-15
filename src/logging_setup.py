"""Logging configuration helpers for the Dragonfly project."""

import logging
import os


def _resolve_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


def configure_logging() -> None:
    """Configure root logging using LOG_LEVEL and a concise format."""
    level = _resolve_level(os.getenv("LOG_LEVEL", "INFO"))
    formatter = _build_formatter()
    root_logger = logging.getLogger()

    if root_logger.handlers:
        root_logger.setLevel(level)
        for handler in root_logger.handlers:
            handler.setLevel(level)
            handler.setFormatter(formatter)
        return

    logging.basicConfig(level=level)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)


def _build_formatter() -> logging.Formatter:
    pattern = "%(asctime)s %(levelname)s run_id=%(run_id)s file=%(file)s %(message)s"
    return logging.Formatter(pattern, defaults={"run_id": "-", "file": "-"})
