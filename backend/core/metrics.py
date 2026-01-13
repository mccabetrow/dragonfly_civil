"""
In-memory metrics state container for lightweight observability.

This is a simple singleton module that tracks application vital signs:
- Request counts
- Error counts (5xx responses)
- Uptime

Thread-safe for single-worker deployments. For multi-worker deployments,
consider using Redis or a proper metrics backend.
"""

from __future__ import annotations

import threading
import time
from typing import TypedDict


class MetricCounts(TypedDict):
    """Type for metric counts dictionary."""

    requests: int
    errors: int


# Module-level state - initialized on import
_START_TIME: float = time.time()
_request_count: int = 0
_error_count: int = 0
_lock = threading.Lock()


def increment_requests() -> None:
    """Increment the total request count."""
    global _request_count
    with _lock:
        _request_count += 1


def increment_errors() -> None:
    """Increment the error (5xx) count."""
    global _error_count
    with _lock:
        _error_count += 1


def get_uptime() -> int:
    """Return uptime in seconds since module import."""
    return int(time.time() - _START_TIME)


def get_counts() -> MetricCounts:
    """Return current request and error counts."""
    with _lock:
        return MetricCounts(requests=_request_count, errors=_error_count)


def get_start_time() -> float:
    """Return the epoch timestamp when the application started."""
    return _START_TIME


def reset_for_testing() -> None:
    """Reset all counters - only for use in tests."""
    global _request_count, _error_count, _START_TIME
    with _lock:
        _request_count = 0
        _error_count = 0
        _START_TIME = time.time()
