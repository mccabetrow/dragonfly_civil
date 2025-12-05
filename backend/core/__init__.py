"""
Dragonfly Engine - Core Module

Contains security, configuration extensions, and shared utilities.
"""

from .errors import (
    DatabaseError,
    DragonflyError,
    ErrorResponse,
    NotFoundError,
    ValidationError,
    setup_error_handlers,
)
from .middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    ResponseSanitizationMiddleware,
    get_request_id,
)
from .security import AuthContext, get_current_user, require_auth

__all__ = [
    # Security
    "AuthContext",
    "get_current_user",
    "require_auth",
    # Middleware
    "RequestLoggingMiddleware",
    "RateLimitMiddleware",
    "ResponseSanitizationMiddleware",
    "get_request_id",
    # Errors
    "ErrorResponse",
    "DragonflyError",
    "NotFoundError",
    "ValidationError",
    "DatabaseError",
    "setup_error_handlers",
]
