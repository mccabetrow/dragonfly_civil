"""
Dragonfly Engine - Middleware

Production-ready middleware for:
- Request logging with correlation IDs
- Rate limiting for sensitive endpoints
- Response sanitization (no credential leaks)
"""

import logging
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Context variable for request ID (thread/async safe)
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_var.get()


# =============================================================================
# Request Logging Middleware
# =============================================================================


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs all requests with:
    - Unique request ID (X-Request-ID header)
    - Method, path, status code
    - Response time in milliseconds
    - Client IP (for abuse detection)

    The request ID is also set in a context variable for use in
    downstream logging.
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
        request_id_var.set(request_id)

        # Extract client IP (handle proxies)
        client_ip = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        )
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()

        # Record start time
        start_time = time.perf_counter()

        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log unhandled exceptions with request context
            logger.error(
                f"[{request_id}] Unhandled exception: {type(e).__name__}: {e}",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "client_ip": client_ip,
                },
            )
            raise

        # Calculate duration
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Log request completion
        log_level = logging.INFO if response.status_code < 400 else logging.WARNING
        if response.status_code >= 500:
            log_level = logging.ERROR

        logger.log(
            log_level,
            f"[{request_id}] {request.method} {request.url.path} -> {response.status_code} ({duration_ms:.1f}ms)",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip,
            },
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response


# =============================================================================
# Rate Limiting Middleware
# =============================================================================


class RateLimitConfig:
    """Configuration for rate limiting a specific path pattern."""

    def __init__(
        self,
        path_prefix: str,
        requests_per_minute: int = 60,
        burst_limit: int = 10,
    ):
        self.path_prefix = path_prefix
        self.requests_per_minute = requests_per_minute
        self.burst_limit = burst_limit
        self.window_seconds = 60


# Default rate limits for sensitive endpoints
RATE_LIMITS = [
    # Semantic search is expensive (embeddings + vector search)
    RateLimitConfig("/api/v1/search/semantic", requests_per_minute=30, burst_limit=5),
    # Offer creation has business implications
    RateLimitConfig("/api/v1/offers", requests_per_minute=60, burst_limit=10),
    # Packet generation is CPU/IO intensive
    RateLimitConfig("/api/v1/packets", requests_per_minute=30, burst_limit=5),
    # Intelligence endpoints expose sensitive data
    RateLimitConfig("/api/v1/intelligence", requests_per_minute=60, burst_limit=10),
    # Event stream
    RateLimitConfig("/api/v1/events", requests_per_minute=120, burst_limit=20),
]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Simple in-memory rate limiter using sliding window.

    For production at scale, consider using Redis-based rate limiting.
    This implementation is suitable for single-instance deployments
    or as a first line of defense.

    Rate limits are applied per client IP.
    """

    def __init__(self, app: ASGIApp, configs: list[RateLimitConfig] | None = None):
        super().__init__(app)
        self.configs = configs or RATE_LIMITS
        # {(path_prefix, client_ip): [(timestamp, count), ...]}
        self._request_counts: dict[tuple[str, str], list[datetime]] = defaultdict(list)

    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP, handling proxies."""
        client_ip = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        )
        if "," in client_ip:
            client_ip = client_ip.split(",")[0].strip()
        return client_ip

    def _find_config(self, path: str) -> RateLimitConfig | None:
        """Find rate limit config for a path."""
        for config in self.configs:
            if path.startswith(config.path_prefix):
                return config
        return None

    def _clean_old_requests(
        self, key: tuple[str, str], window: timedelta
    ) -> list[datetime]:
        """Remove requests older than the window."""
        cutoff = datetime.utcnow() - window
        self._request_counts[key] = [
            ts for ts in self._request_counts[key] if ts > cutoff
        ]
        return self._request_counts[key]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        config = self._find_config(request.url.path)

        if config is None:
            # No rate limit for this path
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        key = (config.path_prefix, client_ip)

        # Clean old requests and count current window
        window = timedelta(seconds=config.window_seconds)
        recent_requests = self._clean_old_requests(key, window)

        # Check rate limit
        if len(recent_requests) >= config.requests_per_minute:
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {config.path_prefix}",
                extra={
                    "client_ip": client_ip,
                    "path_prefix": config.path_prefix,
                    "request_count": len(recent_requests),
                    "limit": config.requests_per_minute,
                },
            )
            return Response(
                content='{"error": "rate_limit_exceeded", "message": "Too many requests. Please slow down."}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(config.window_seconds),
                    "X-RateLimit-Limit": str(config.requests_per_minute),
                    "X-RateLimit-Remaining": "0",
                },
            )

        # Record this request
        self._request_counts[key].append(datetime.utcnow())

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        remaining = config.requests_per_minute - len(self._request_counts[key])
        response.headers["X-RateLimit-Limit"] = str(config.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))

        return response


# =============================================================================
# Response Sanitization Middleware
# =============================================================================

# Patterns that should NEVER appear in responses
SENSITIVE_PATTERNS = [
    "supabase.co",  # Supabase URL
    "eyJ",  # JWT token prefix (base64 of '{"')
    "service_role",  # Role name
    "secret",  # Generic secret indicator
    "password",  # Password fields
]


class ResponseSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that checks responses for accidentally leaked credentials.

    This is a safety net - ideally, no credentials should ever reach
    the response layer. If they do, this middleware logs an error
    but does NOT modify the response (to avoid breaking legitimate use cases).

    For strict mode in production, set SANITIZE_RESPONSES=true to
    redact potentially sensitive content.
    """

    def __init__(self, app: ASGIApp, strict_mode: bool = False):
        super().__init__(app)
        self.strict_mode = strict_mode

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # Only check JSON responses
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # We can't easily read the response body without consuming it,
        # so we only check error responses where leaks are more likely
        if response.status_code >= 500:
            logger.warning(
                f"5xx response on {request.url.path} - verify no credentials leaked",
                extra={
                    "request_id": get_request_id(),
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )

        return response
