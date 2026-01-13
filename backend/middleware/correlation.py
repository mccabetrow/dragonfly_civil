"""
FastAPI middleware that manages correlation IDs and observability headers for every request.

Headers injected on EVERY response:
  - X-Request-ID: UUID correlation ID (from client or generated)
  - X-Dragonfly-SHA: Git commit SHA (8 chars) for version tracking
  - X-Dragonfly-Env: Environment name (prod/dev/staging)

Usage:
    from backend.middleware.correlation import CorrelationMiddleware
    app.add_middleware(CorrelationMiddleware)
"""

from __future__ import annotations

import contextvars
import os
import uuid
from typing import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# =============================================================================
# Context Variables for Request Correlation
# =============================================================================

# Request ID context variable - accessible throughout request lifecycle
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return _request_id_ctx.get()


def set_request_id(request_id: str) -> contextvars.Token[str]:
    """Set the request ID in context. Returns token for reset."""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: contextvars.Token[str]) -> None:
    """Reset the request ID context to previous value."""
    _request_id_ctx.reset(token)


# =============================================================================
# SHA Resolution - Identical to version.py for consistency
# =============================================================================

_SHA_ENV_VARS = [
    "RAILWAY_GIT_COMMIT_SHA",
    "VERCEL_GIT_COMMIT_SHA",
    "GITHUB_SHA",
    "GIT_COMMIT",
    "GIT_SHA",
]


def _get_sha_short() -> str:
    """Get short git SHA (8 chars) from environment."""
    for env_var in _SHA_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value and value.lower() not in ("unknown", "local", ""):
            return value[:8] if len(value) >= 8 else value
    return "local-dev"


def _get_env_name() -> str:
    """Get environment name from environment."""
    return os.environ.get(
        "DRAGONFLY_ENV",
        os.environ.get("ENVIRONMENT", os.environ.get("RAILWAY_ENVIRONMENT", "dev")),
    ).lower()


# Cache these at module load time for performance
_CACHED_SHA = _get_sha_short()
_CACHED_ENV = _get_env_name()


class CorrelationMiddleware(BaseHTTPMiddleware):
    """
    Ensures every request has correlation ID and observability headers.

    Response Headers Added:
        - X-Request-ID: UUID for request tracing (from client or generated)
        - X-Dragonfly-SHA: Git commit SHA (8 chars)
        - X-Dragonfly-Env: Environment name (prod/dev/staging)

    These headers are ALWAYS present on every response for:
        - Log correlation across services
        - Version tracking for debugging
        - Environment verification for security
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Get or generate correlation ID
        incoming_id = request.headers.get("X-Request-ID")
        correlation_id = incoming_id or str(uuid.uuid4())

        # Set in context for logging
        token = set_request_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)

        # Inject observability headers on EVERY response
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Dragonfly-SHA"] = _CACHED_SHA
        response.headers["X-Dragonfly-Env"] = _CACHED_ENV

        return response
