"""
Dragonfly Engine - Enterprise Metadata Middleware

Unified middleware that combines correlation ID, version headers, and
logging context propagation into a single optimized layer.

Headers injected into every response:
  - X-Request-ID: Unique correlation ID (generated or extracted from request)
  - X-Dragonfly-SHA-Short: 8-char Git commit SHA for traceability
  - X-Dragonfly-Env: Environment name (prod/dev/staging)

Context propagated to all loggers:
  - request_id: Correlation ID for request tracing
  - env: Environment name
  - sha: Full Git commit SHA
  - sha_short: 8-char Git commit SHA
  - service: Service name (e.g., "dragonfly-api")

Usage:
    from backend.middleware.meta import MetadataMiddleware
    app.add_middleware(MetadataMiddleware)
"""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from backend.utils import context as ctx_utils

from .version import get_version_info

# Pre-resolve version info at import (cached for lifetime of process)
_VERSION_INFO = get_version_info()


class MetadataMiddleware(BaseHTTPMiddleware):
    """
    Enterprise-grade middleware that:
    1. Generates/extracts X-Request-ID for correlation
    2. Injects X-Dragonfly-SHA-Short and X-Dragonfly-Env headers
    3. Sets contextvars for structured logging

    This is the single "outer shell" for all Dragonfly API requests.
    """

    def __init__(self, app: ASGIApp, service_name: str = "dragonfly-api") -> None:
        super().__init__(app)
        self.service_name = service_name
        self._sha_short = _VERSION_INFO.get("sha_short", "unknown")
        self._sha_full = _VERSION_INFO.get("sha", "unknown")
        self._env = _VERSION_INFO.get("env", "unknown")
        self._version = _VERSION_INFO.get("version", "unknown")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # 1. Extract or generate correlation ID
        incoming_id = request.headers.get("X-Request-ID")
        request_id = incoming_id or str(uuid.uuid4())

        # 2. Set contextvar so all loggers in this request have access
        token = ctx_utils.set_request_id(request_id)

        try:
            response = await call_next(request)
        finally:
            ctx_utils.reset_request_id(token)

        # 3. Inject headers into response
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Dragonfly-SHA-Short"] = self._sha_short
        response.headers["X-Dragonfly-Env"] = self._env

        return response

    def get_log_context(self, request_id: str) -> dict[str, str]:
        """
        Build structured logging context for the current request.

        Returns dict suitable for `logger.info("msg", extra=context)`.
        """
        return {
            "request_id": request_id,
            "env": self._env,
            "sha": self._sha_full,
            "sha_short": self._sha_short,
            "service": self.service_name,
            "version": self._version,
        }


__all__ = ["MetadataMiddleware"]
