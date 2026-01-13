"""Logging configuration helpers for the Dragonfly project.

Workers and CLI tools should use this module to get consistent structured logging.
"""

import logging
import os
from typing import Optional


def configure_logging(service_name: Optional[str] = None) -> None:
    """
    Configure root logging using the central JSON formatter.

    For workers, call: configure_logging(service_name="dragonfly-worker")
    """
    # Import here to avoid circular imports at module load time
    from backend.utils.logging import setup_logging

    effective_service = service_name or os.getenv("DRAGONFLY_SERVICE", "dragonfly-worker")
    setup_logging(service_name=effective_service)


def _build_formatter() -> logging.Formatter:
    """Legacy formatter for edge cases where JSON isn't desired."""
    pattern = "%(asctime)s %(levelname)s run_id=%(run_id)s file=%(file)s %(message)s"
    return logging.Formatter(pattern, defaults={"run_id": "-", "file": "-"})
