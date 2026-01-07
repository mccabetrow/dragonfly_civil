"""
Dragonfly Engine - Security Middleware

Production-grade security middleware providing:
- Rate limiting (per-IP request throttling)
- Enumeration detection (404 pattern analysis)
- Security incident logging to database
- Request fingerprinting for abuse detection

Configuration via environment:
    RATE_LIMIT_REQUESTS_PER_MINUTE=100
    RATE_LIMIT_BURST_SIZE=20
    ENUMERATION_THRESHOLD=10
    ENUMERATION_WINDOW_SECONDS=60
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional
from weakref import WeakValueDictionary

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================


def get_rate_limit_config() -> tuple[int, int, int]:
    """Get current rate limit configuration."""
    requests = int(os.environ.get("RATE_LIMIT_REQUESTS_PER_MINUTE", "100"))
    burst = int(os.environ.get("RATE_LIMIT_BURST_SIZE", "20"))
    window = 60  # seconds
    return requests, burst, window


def get_enumeration_config() -> tuple[int, int]:
    """Get current enumeration detection configuration."""
    threshold = int(os.environ.get("ENUMERATION_THRESHOLD", "10"))
    window = int(os.environ.get("ENUMERATION_WINDOW_SECONDS", "60"))
    return threshold, window


# Cleanup interval for expired entries
CLEANUP_INTERVAL = 300  # 5 minutes

# Paths to exclude from rate limiting
EXCLUDED_PATHS = frozenset(
    [
        "/health",
        "/healthz",
        "/ready",
        "/metrics",
        "/api/health",
        "/api/v1/health",
        "/docs",
        "/openapi.json",
        "/redoc",
    ]
)


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class RateLimitBucket:
    """Token bucket for rate limiting."""

    requests: int = field(init=False)
    burst: int = field(init=False)
    window: int = field(init=False)
    tokens: float = field(init=False)
    last_update: float = field(default_factory=time.monotonic)
    request_count: int = 0  # Total requests in current window
    window_start: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        self.requests, self.burst, self.window = get_rate_limit_config()
        self.tokens = float(self.burst)

    def consume(self, tokens: int = 1) -> bool:
        """
        Attempt to consume tokens. Returns True if allowed.

        Uses token bucket algorithm with refill rate.
        """
        now = time.monotonic()

        # Refill tokens based on elapsed time
        elapsed = now - self.last_update
        refill_rate = self.requests / self.window
        self.tokens = min(self.burst, self.tokens + elapsed * refill_rate)
        self.last_update = now

        # Track request count for logging
        if now - self.window_start > self.window:
            self.request_count = 0
            self.window_start = now
        self.request_count += 1

        # Check if we have enough tokens
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def is_expired(self) -> bool:
        """Check if bucket should be cleaned up (no activity for 2x window)."""
        return time.monotonic() - self.last_update > self.window * 2


@dataclass
class EnumerationTracker:
    """Track 404 errors for enumeration detection."""

    threshold: int = field(init=False)
    window: int = field(init=False)
    errors: list[float] = field(default_factory=list)
    flagged: bool = False
    last_flag_time: Optional[float] = None

    def __post_init__(self):
        self.threshold, self.window = get_enumeration_config()

    def record_404(self) -> bool:
        """
        Record a 404 error. Returns True if enumeration threshold exceeded.
        """
        now = time.monotonic()

        # Remove old entries outside window
        cutoff = now - self.window
        self.errors = [t for t in self.errors if t > cutoff]

        # Add new error
        self.errors.append(now)

        # Check threshold
        if len(self.errors) >= self.threshold:
            if not self.flagged or (
                self.last_flag_time and now - self.last_flag_time > self.window
            ):
                self.flagged = True
                self.last_flag_time = now
                return True  # New flag event

        return False

    @property
    def is_expired(self) -> bool:
        """Check if tracker should be cleaned up."""
        if not self.errors:
            return True
        return time.monotonic() - self.errors[-1] > self.window * 2


# =============================================================================
# In-Memory Storage
# =============================================================================


class SecurityStore:
    """
    Thread-safe in-memory storage for rate limiting and enumeration tracking.

    Uses WeakValueDictionary for automatic cleanup of unused entries.
    """

    def __init__(self):
        self._rate_limits: dict[str, RateLimitBucket] = {}
        self._enumeration: dict[str, EnumerationTracker] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.monotonic()

    async def get_rate_bucket(self, key: str) -> RateLimitBucket:
        """Get or create rate limit bucket for key."""
        async with self._lock:
            if key not in self._rate_limits:
                self._rate_limits[key] = RateLimitBucket()
            return self._rate_limits[key]

    async def get_enum_tracker(self, key: str) -> EnumerationTracker:
        """Get or create enumeration tracker for key."""
        async with self._lock:
            if key not in self._enumeration:
                self._enumeration[key] = EnumerationTracker()
            return self._enumeration[key]

    async def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        now = time.monotonic()
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return 0

        async with self._lock:
            self._last_cleanup = now

            # Cleanup rate limit buckets
            expired_rate = [k for k, v in self._rate_limits.items() if v.is_expired]
            for k in expired_rate:
                del self._rate_limits[k]

            # Cleanup enumeration trackers
            expired_enum = [k for k, v in self._enumeration.items() if v.is_expired]
            for k in expired_enum:
                del self._enumeration[k]

            total = len(expired_rate) + len(expired_enum)
            if total > 0:
                logger.debug(f"Cleaned up {total} expired security entries")
            return total

    @property
    def stats(self) -> dict:
        """Get current storage statistics."""
        return {
            "rate_limit_entries": len(self._rate_limits),
            "enumeration_entries": len(self._enumeration),
        }


# Global store instance
_security_store = SecurityStore()


# =============================================================================
# Incident Logging
# =============================================================================


async def log_security_incident(
    severity: str,
    event_type: str,
    source_ip: Optional[str],
    request: Optional[Request] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Log security incident to database.

    Uses Supabase RPC for atomic insertion.
    """
    try:
        import httpx

        # Get Supabase config
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        if not supabase_url or not supabase_key:
            logger.warning("Supabase not configured, incident logged locally only")
            logger.warning(f"SECURITY INCIDENT: {severity} - {event_type} from {source_ip}")
            return

        # Build request metadata
        incident_metadata = metadata or {}
        if request:
            incident_metadata.update(
                {
                    "path": str(request.url.path),
                    "method": request.method,
                }
            )

        # Extract request details
        request_path = str(request.url.path) if request else None
        request_method = request.method if request else None
        user_agent = request.headers.get("user-agent", "")[:500] if request else None

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{supabase_url}/rest/v1/rpc/log_incident",
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "p_severity": severity,
                    "p_event_type": event_type,
                    "p_source_ip": source_ip,
                    "p_user_id": None,  # Could extract from JWT if needed
                    "p_request_path": request_path,
                    "p_request_method": request_method,
                    "p_user_agent": user_agent,
                    "p_metadata": incident_metadata,
                },
            )

            if response.status_code != 200:
                logger.error(f"Failed to log incident: {response.status_code}")

    except Exception as e:
        # Never let incident logging crash the request
        logger.error(f"Error logging security incident: {e}")


# =============================================================================
# Security Middleware
# =============================================================================


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Production security middleware with rate limiting and abuse detection.

    Features:
    - Token bucket rate limiting per IP
    - Enumeration detection (excessive 404s)
    - Automatic incident logging
    - Configurable thresholds
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.store = _security_store

    def _get_client_ip(self, request: Request) -> str:
        """
        Extract client IP, respecting proxy headers.

        Order of precedence:
        1. X-Forwarded-For (first IP)
        2. X-Real-IP
        3. client.host
        """
        # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Take the first (original client) IP
            return xff.split(",")[0].strip()

        # X-Real-IP from nginx
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()

        # Direct connection
        if request.client:
            return request.client.host

        return "unknown"

    def _should_rate_limit(self, request: Request) -> bool:
        """Check if this request should be rate limited."""
        path = request.url.path

        # Exclude health/docs endpoints
        if path in EXCLUDED_PATHS:
            return False

        # Exclude static files
        if path.startswith("/static/") or path.startswith("/_next/"):
            return False

        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with security checks."""
        client_ip = self._get_client_ip(request)

        # Get current config values
        rate_requests, rate_burst, rate_window = get_rate_limit_config()
        enum_threshold, enum_window = get_enumeration_config()

        # Periodic cleanup
        await self.store.cleanup_expired()

        # Skip rate limiting for excluded paths
        if not self._should_rate_limit(request):
            return await call_next(request)

        # Rate limiting check
        bucket = await self.store.get_rate_bucket(client_ip)
        if not bucket.consume():
            # Rate limit exceeded
            logger.warning(f"Rate limit exceeded for {client_ip}: {bucket.request_count} requests")

            # Log incident (fire and forget)
            asyncio.create_task(
                log_security_incident(
                    severity="warning",
                    event_type="rate_limit_exceeded",
                    source_ip=client_ip,
                    request=request,
                    metadata={
                        "requests_in_window": bucket.request_count,
                        "threshold": rate_requests,
                    },
                )
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too Many Requests",
                    "detail": "Rate limit exceeded. Please slow down.",
                    "retry_after": rate_window,
                },
                headers={
                    "Retry-After": str(rate_window),
                    "X-RateLimit-Limit": str(rate_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + rate_window),
                },
            )

        # Process request
        response = await call_next(request)

        # Enumeration detection (track 404s)
        if response.status_code == 404:
            tracker = await self.store.get_enum_tracker(client_ip)
            if tracker.record_404():
                # Enumeration pattern detected
                logger.warning(
                    f"Enumeration attempt detected from {client_ip}: "
                    f"{len(tracker.errors)} 404s in {enum_window}s"
                )

                # Log critical incident
                asyncio.create_task(
                    log_security_incident(
                        severity="critical",
                        event_type="enumeration_attempt",
                        source_ip=client_ip,
                        request=request,
                        metadata={
                            "error_count": len(tracker.errors),
                            "threshold": enum_threshold,
                            "window_seconds": enum_window,
                        },
                    )
                )

        # Add rate limit headers to response
        response.headers["X-RateLimit-Limit"] = str(rate_requests)
        response.headers["X-RateLimit-Remaining"] = str(max(0, int(bucket.tokens)))

        return response


# =============================================================================
# Utility Functions
# =============================================================================


def get_security_stats() -> dict:
    """Get current security middleware statistics."""
    rate_requests, rate_burst, _ = get_rate_limit_config()
    enum_threshold, enum_window = get_enumeration_config()
    return {
        "rate_limit_config": {
            "requests_per_minute": rate_requests,
            "burst_size": rate_burst,
        },
        "enumeration_config": {
            "threshold": enum_threshold,
            "window_seconds": enum_window,
        },
        "store_stats": _security_store.stats,
    }


async def check_ip_reputation(ip: str) -> dict:
    """
    Check IP reputation based on recent incidents.

    Returns:
        Dict with reputation score and recent incidents
    """
    try:
        import httpx

        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        if not supabase_url or not supabase_key:
            return {"error": "Supabase not configured"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                f"{supabase_url}/rest/v1/rpc/get_recent_incidents_by_ip",
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "p_source_ip": ip,
                    "p_window_minutes": 60,
                },
            )

            if response.status_code == 200:
                data = response.json()
                if data:
                    return {
                        "ip": ip,
                        "incident_count": data[0].get("incident_count", 0),
                        "first_incident": data[0].get("first_incident"),
                        "last_incident": data[0].get("last_incident"),
                        "severities": data[0].get("severities", []),
                    }
                return {"ip": ip, "incident_count": 0, "status": "clean"}

            return {"error": f"API error: {response.status_code}"}

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# FastAPI Integration
# =============================================================================


def add_security_middleware(
    app,
    requests_per_minute: Optional[int] = None,
    enumeration_threshold: Optional[int] = None,
) -> None:
    """
    Add security middleware to FastAPI app.

    Args:
        app: FastAPI application
        requests_per_minute: Override RATE_LIMIT_REQUESTS_PER_MINUTE env var
        enumeration_threshold: Override ENUMERATION_THRESHOLD env var

    Usage:
        from backend.middleware.security import add_security_middleware

        app = FastAPI()
        add_security_middleware(app)
    """
    # Override env vars if provided (useful for testing)
    if requests_per_minute is not None:
        os.environ["RATE_LIMIT_REQUESTS_PER_MINUTE"] = str(requests_per_minute)
    if enumeration_threshold is not None:
        os.environ["ENUMERATION_THRESHOLD"] = str(enumeration_threshold)

    app.add_middleware(SecurityMiddleware)

    # Get current config for logging
    rate_requests, _, _ = get_rate_limit_config()
    enum_threshold, _ = get_enumeration_config()

    logger.info(
        f"Security middleware enabled: "
        f"{rate_requests} req/min, "
        f"enum threshold: {enum_threshold}"
    )
