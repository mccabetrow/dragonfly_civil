"""
Dragonfly Retry Utilities - Demo Mode Resilience

Provides jittered retry logic for HTTP and database operations.
Designed to handle Supabase pooler 429s and PostgREST 503s gracefully.

Usage:
    from backend.utils.retry import run_with_jitter, get_resilient_session

    # HTTP requests with automatic retry
    session = get_resilient_session()
    response = session.get("https://api.example.com/health")

    # Function-level retry with jitter
    @run_with_jitter
    def flaky_operation():
        ...
"""

from __future__ import annotations

import logging
import random
from functools import wraps
from typing import Any, Callable, Optional, Type, TypeVar, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Type variable for generic decorator
F = TypeVar("F", bound=Callable[..., Any])

# =============================================================================
# Configuration
# =============================================================================

# Jitter bounds (seconds)
JITTER_MIN_SECONDS = 0.25
JITTER_MAX_SECONDS = 0.75

# Default retry settings
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_FACTOR = 0.5

# HTTP status codes to retry
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Exceptions to retry
RETRYABLE_EXCEPTIONS: tuple[Type[Exception], ...] = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Database exceptions (imported lazily to avoid circular deps)
DB_RETRYABLE_EXCEPTIONS: tuple[Type[Exception], ...] = ()

try:
    import psycopg

    DB_RETRYABLE_EXCEPTIONS = (psycopg.OperationalError,)
except ImportError:
    pass


# =============================================================================
# HTTP Session with Retry
# =============================================================================


def get_resilient_session(
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_factor: float = DEFAULT_BACKOFF_FACTOR,
    status_forcelist: Optional[frozenset[int]] = None,
    timeout: float = 10.0,
) -> requests.Session:
    """
    Create a requests Session with automatic retry and backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        backoff_factor: Backoff factor for exponential delay.
        status_forcelist: HTTP status codes to retry (default: 429, 5xx).
        timeout: Default timeout for requests.

    Returns:
        Configured requests.Session with retry adapter mounted.

    Example:
        session = get_resilient_session()
        response = session.get("https://api.supabase.co/health")
    """
    if status_forcelist is None:
        status_forcelist = RETRY_STATUS_CODES

    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=list(status_forcelist),
        allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        raise_on_status=False,  # Don't raise on status, let caller handle
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # Set default timeout
    session.request = _timeout_wrapper(session.request, timeout)  # type: ignore[method-assign]

    return session


def _timeout_wrapper(
    original_request: Callable[..., requests.Response],
    default_timeout: float,
) -> Callable[..., requests.Response]:
    """Wrap session.request to add default timeout."""

    @wraps(original_request)
    def wrapper(*args: Any, **kwargs: Any) -> requests.Response:
        if "timeout" not in kwargs:
            kwargs["timeout"] = default_timeout
        return original_request(*args, **kwargs)

    return wrapper


# =============================================================================
# Jittered Retry Decorator
# =============================================================================


def run_with_jitter(
    max_retries: int = DEFAULT_MAX_RETRIES,
    jitter_min: float = JITTER_MIN_SECONDS,
    jitter_max: float = JITTER_MAX_SECONDS,
    exceptions: Optional[tuple[Type[Exception], ...]] = None,
) -> Callable[[F], F]:
    """
    Decorator that retries a function with random jitter between attempts.

    Args:
        max_retries: Maximum number of retry attempts.
        jitter_min: Minimum jitter delay (seconds).
        jitter_max: Maximum jitter delay (seconds).
        exceptions: Tuple of exception types to catch and retry.
                   Defaults to HTTP + DB retryable exceptions.

    Returns:
        Decorated function with retry logic.

    Example:
        @run_with_jitter(max_retries=3)
        def list_storage_buckets():
            return client.storage.list_buckets()
    """
    if exceptions is None:
        exceptions = RETRYABLE_EXCEPTIONS + DB_RETRYABLE_EXCEPTIONS

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_error = e
                    if attempt < max_retries:
                        jitter = random.uniform(jitter_min, jitter_max)
                        logger.warning(
                            f"[retry] {func.__name__} failed (attempt {attempt}/{max_retries}), "
                            f"retrying in {jitter:.2f}s: {e}"
                        )
                        import time

                        time.sleep(jitter)
                    else:
                        logger.error(
                            f"[retry] {func.__name__} failed after {max_retries} attempts: {e}"
                        )

            # Re-raise the last error if all retries exhausted
            if last_error is not None:
                raise last_error
            raise RuntimeError(f"{func.__name__} failed with no captured exception")

        return wrapper  # type: ignore[return-value]

    return decorator


# =============================================================================
# Tenacity-based Retry (if available)
# =============================================================================

try:
    from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_random

    def tenacity_jitter_retry(
        max_retries: int = DEFAULT_MAX_RETRIES,
        jitter_min: float = JITTER_MIN_SECONDS,
        jitter_max: float = JITTER_MAX_SECONDS,
        exceptions: Optional[tuple[Type[Exception], ...]] = None,
    ) -> Callable[[F], F]:
        """
        Tenacity-based retry decorator with jitter.

        Preferred over run_with_jitter when tenacity is available.
        """
        if exceptions is None:
            exceptions = RETRYABLE_EXCEPTIONS + DB_RETRYABLE_EXCEPTIONS

        return retry(  # type: ignore[return-value]
            stop=stop_after_attempt(max_retries),
            wait=wait_random(min=jitter_min, max=jitter_max),
            retry=retry_if_exception_type(exceptions),
            reraise=True,
        )

    TENACITY_AVAILABLE = True

except ImportError:
    TENACITY_AVAILABLE = False

    def tenacity_jitter_retry(*args: Any, **kwargs: Any) -> Callable[[F], F]:
        """Fallback when tenacity is not installed."""
        return run_with_jitter(*args, **kwargs)


# =============================================================================
# Resilient HTTP Helpers
# =============================================================================


def resilient_get(
    url: str,
    session: Optional[requests.Session] = None,
    **kwargs: Any,
) -> requests.Response:
    """
    Perform a GET request with automatic retry.

    Args:
        url: Target URL.
        session: Optional pre-configured session. Creates one if not provided.
        **kwargs: Additional arguments passed to session.get().

    Returns:
        Response object.
    """
    if session is None:
        session = get_resilient_session()
    return session.get(url, **kwargs)


def resilient_post(
    url: str,
    session: Optional[requests.Session] = None,
    **kwargs: Any,
) -> requests.Response:
    """
    Perform a POST request with automatic retry.

    Args:
        url: Target URL.
        session: Optional pre-configured session.
        **kwargs: Additional arguments passed to session.post().

    Returns:
        Response object.
    """
    if session is None:
        session = get_resilient_session()
    return session.post(url, **kwargs)


# =============================================================================
# Connection Storm Prevention
# =============================================================================


class RateLimiter:
    """
    Simple rate limiter to prevent connection storms.

    Usage:
        limiter = RateLimiter(max_calls=5, period_seconds=1.0)
        for item in items:
            limiter.wait()
            process(item)
    """

    def __init__(self, max_calls: int = 10, period_seconds: float = 1.0):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._call_times: list[float] = []

    def wait(self) -> None:
        """Wait if necessary to respect rate limit."""
        import time

        now = time.time()

        # Remove calls outside the window
        self._call_times = [t for t in self._call_times if now - t < self.period_seconds]

        if len(self._call_times) >= self.max_calls:
            # Wait for the oldest call to expire
            sleep_time = self.period_seconds - (now - self._call_times[0])
            if sleep_time > 0:
                time.sleep(sleep_time)

        self._call_times.append(time.time())


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "get_resilient_session",
    "run_with_jitter",
    "tenacity_jitter_retry",
    "resilient_get",
    "resilient_post",
    "RateLimiter",
    "TENACITY_AVAILABLE",
    "RETRY_STATUS_CODES",
    "RETRYABLE_EXCEPTIONS",
]
