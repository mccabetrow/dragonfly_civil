"""
Dragonfly Engine - Trace ID Middleware

Generates and manages trace IDs for request tracing and debugging.
Every request gets a unique trace_id that flows through logs and responses.

Usage:
    from backend.core.trace_middleware import get_trace_id

    # In an endpoint or service
    trace_id = get_trace_id()  # Returns current request's trace ID
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# Optional structlog support
try:
    import structlog

    HAS_STRUCTLOG = True
except ImportError:
    HAS_STRUCTLOG = False

logger = logging.getLogger(__name__)

# Context variable for trace ID (thread/async safe)
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="no-trace")


def get_trace_id() -> str:
    """
    Get the current request's trace ID.

    Returns:
        The trace ID for the current request, or "no-trace" if not in a request context.
    """
    return _trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    """
    Set the trace ID for the current context.

    This is primarily used by middleware and tests.
    """
    _trace_id_var.set(trace_id)


class TraceMiddleware(BaseHTTPMiddleware):
    """
    Middleware that generates and manages trace IDs for every request.

    - Generates a UUID trace_id for each request
    - Stores it in context variable for downstream access
    - Injects it into structlog context for structured logging
    - Adds X-Trace-ID header to response
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate unique trace ID or use one from header (for distributed tracing)
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))

        # Set in context variable for get_trace_id() access
        _trace_id_var.set(trace_id)

        # Bind to structlog context for structured logging (if available)
        if HAS_STRUCTLOG:
            try:
                structlog.contextvars.clear_contextvars()
                structlog.contextvars.bind_contextvars(trace_id=trace_id)
            except Exception:
                # structlog may not be configured - graceful fallback
                pass

        # Also set in standard logging extra for compatibility
        old_factory = logging.getLogRecordFactory()

        def record_factory(*args, **kwargs):
            record = old_factory(*args, **kwargs)
            record.trace_id = trace_id
            return record

        logging.setLogRecordFactory(record_factory)

        try:
            # Process request
            response = await call_next(request)

            # Add trace ID to response headers
            response.headers["X-Trace-ID"] = trace_id

            return response
        finally:
            # Restore log factory
            logging.setLogRecordFactory(old_factory)
