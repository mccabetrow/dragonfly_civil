"""
tests/helpers.py

Test utilities for resilient PostgREST integration testing.

Provides retry mechanisms for transient infrastructure errors like PGRST002
(schema cache loading) that should not fail tests during temporary degradation.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, TypeVar

import pytest

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Retryable error patterns (transient infrastructure issues)
RETRYABLE_PATTERNS = [
    "PGRST002",  # Schema cache loading
    "503",  # Service Unavailable
    "502",  # Bad Gateway
    "connection refused",
    "connection reset",
    "timeout",
]


def execute_resilient(
    func: Callable[[], T],
    retries: int = 3,
    delay: float = 2.0,
    skip_on_exhaustion: bool = True,
) -> T:
    """
    Execute a PostgREST operation with retry logic for transient errors.

    This helper wraps Supabase client calls to handle temporary infrastructure
    degradation (PGRST002 schema cache, 503 errors) gracefully:
    - Retries transient errors up to `retries` times with exponential backoff
    - Skips the test (rather than failing) if infrastructure is persistently degraded
    - Immediately re-raises non-transient errors (4xx client errors, etc.)

    Usage:
        # Old: res = supabase.rpc("ping").execute()
        # New: res = execute_resilient(lambda: supabase.rpc("ping").execute())

    Args:
        func: Callable that performs the PostgREST operation
        retries: Maximum retry attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 2.0)
        skip_on_exhaustion: If True, pytest.skip() on retry exhaustion; else raise

    Returns:
        The result of func() if successful

    Raises:
        pytest.skip: If retries exhausted and skip_on_exhaustion=True
        Exception: The original exception if not retryable or skip_on_exhaustion=False
    """
    last_exception: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            return func()
        except Exception as exc:
            error_str = str(exc).lower()
            exc_type = type(exc).__name__

            # Check if this is a retryable transient error
            is_retryable = any(pattern.lower() in error_str for pattern in RETRYABLE_PATTERNS)

            if not is_retryable:
                # Non-retryable error (4xx, business logic error) - fail immediately
                logger.debug(f"Non-retryable error ({exc_type}): {exc}. Raising immediately.")
                raise

            last_exception = exc
            remaining = retries - attempt

            if remaining > 0:
                # Exponential backoff: delay * 2^(attempt-1)
                sleep_time = delay * (2 ** (attempt - 1))
                logger.warning(
                    f"Transient error ({exc_type}): {exc}. "
                    f"Retrying in {sleep_time:.1f}s ({remaining} attempts remaining)..."
                )
                time.sleep(sleep_time)
            else:
                logger.warning(
                    f"Transient error ({exc_type}): {exc}. All {retries} retries exhausted."
                )

    # All retries exhausted
    if skip_on_exhaustion:
        pytest.skip(
            f"Skipping due to PostgREST unavailable after {retries} retries: {last_exception}"
        )
    else:
        raise last_exception  # type: ignore[misc]


def is_postgrest_available(client: Any) -> bool:
    """
    Quick health check for PostgREST availability.

    Args:
        client: Supabase client instance

    Returns:
        True if PostgREST responds, False if degraded
    """
    try:
        # Minimal query to check connectivity
        client.table("_health_check_dummy").select("*").limit(0).execute()
        return True
    except Exception as exc:
        error_str = str(exc).lower()
        if any(pattern.lower() in error_str for pattern in RETRYABLE_PATTERNS):
            return False
        # If it's a different error (like table doesn't exist), PostgREST is up
        return True


def httpx_resilient(
    client: Any,
    method: str,
    url: str,
    retries: int = 3,
    delay: float = 2.0,
    skip_on_exhaustion: bool = True,
    **kwargs: Any,
) -> Any:
    """
    Execute an httpx request with retry logic for transient PostgREST errors.

    Args:
        client: httpx.Client instance
        method: HTTP method ('get', 'post', etc.)
        url: Request URL
        retries: Maximum retry attempts (default: 3)
        delay: Initial delay between retries in seconds (default: 2.0)
        skip_on_exhaustion: If True, pytest.skip() on retry exhaustion; else raise
        **kwargs: Passed to httpx request (headers, json, params, etc.)

    Returns:
        httpx.Response if successful

    Raises:
        pytest.skip: If retries exhausted and skip_on_exhaustion=True
    """

    def _make_request() -> Any:
        response = getattr(client, method.lower())(url, **kwargs)
        # Check for retryable status codes before raise_for_status
        if response.status_code in (502, 503):
            text = response.text
            if any(pattern.lower() in text.lower() for pattern in RETRYABLE_PATTERNS):
                from httpx import HTTPStatusError

                raise HTTPStatusError(
                    f"Retryable status {response.status_code}: {text}",
                    request=response.request,
                    response=response,
                )
        response.raise_for_status()
        return response

    return execute_resilient(
        _make_request, retries=retries, delay=delay, skip_on_exhaustion=skip_on_exhaustion
    )
