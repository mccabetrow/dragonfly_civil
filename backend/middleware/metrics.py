"""
Metrics collection middleware.

Tracks request counts and error rates for the /api/metrics endpoint.
Lightweight - no external dependencies, just increments in-memory counters.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from backend.core import metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware that tracks request and error counts.

    - Increments request counter for every request
    - Increments error counter for 5xx responses
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Always count the request
        metrics.increment_requests()

        try:
            response = await call_next(request)
        except Exception:
            # Unhandled exception counts as error
            metrics.increment_errors()
            raise

        # Track 5xx responses as errors
        if response.status_code >= 500:
            metrics.increment_errors()

        return response
