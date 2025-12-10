"""
Dragonfly Engine - Error Handling

Structured error responses for API consistency.
Provides clear distinction between 4xx (client) and 5xx (server) errors.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from .middleware import get_request_id

logger = logging.getLogger(__name__)


# =============================================================================
# Error Response Models
# =============================================================================


class ErrorDetail(BaseModel):
    """Detailed error information for debugging."""

    field: str | None = None
    message: str
    code: str | None = None


class ErrorResponse(BaseModel):
    """
    Standardized error response format.

    All API errors return this structure for consistency.
    """

    error: str  # Machine-readable error code
    message: str  # Human-readable error message
    status_code: int  # HTTP status code
    request_id: str | None = None  # Correlation ID for debugging
    details: list[ErrorDetail] | None = None  # Additional error details


# =============================================================================
# Error Codes
# =============================================================================

# Client errors (4xx)
ERROR_VALIDATION = "validation_error"
ERROR_NOT_FOUND = "not_found"
ERROR_UNAUTHORIZED = "unauthorized"
ERROR_FORBIDDEN = "forbidden"
ERROR_RATE_LIMITED = "rate_limit_exceeded"
ERROR_BAD_REQUEST = "bad_request"
ERROR_CONFLICT = "conflict"

# Server errors (5xx)
ERROR_INTERNAL = "internal_error"
ERROR_DATABASE = "database_error"
ERROR_SERVICE_UNAVAILABLE = "service_unavailable"


# =============================================================================
# Exception Handlers
# =============================================================================


def create_error_response(
    status_code: int,
    error: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Create a standardized error response."""
    request_id = get_request_id()

    response = ErrorResponse(
        error=error,
        message=message,
        status_code=status_code,
        request_id=request_id if request_id else None,
        details=details,
    )

    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """
    Handle FastAPI/Starlette HTTP exceptions.

    Maps standard HTTP errors to our error format.
    """
    # Map status codes to error codes
    error_map = {
        400: ERROR_BAD_REQUEST,
        401: ERROR_UNAUTHORIZED,
        403: ERROR_FORBIDDEN,
        404: ERROR_NOT_FOUND,
        409: ERROR_CONFLICT,
        429: ERROR_RATE_LIMITED,
        500: ERROR_INTERNAL,
        503: ERROR_SERVICE_UNAVAILABLE,
    }

    error_code = error_map.get(exc.status_code, ERROR_INTERNAL)

    # Log server errors
    if exc.status_code >= 500:
        logger.error(
            f"HTTP {exc.status_code}: {exc.detail}",
            extra={
                "request_id": get_request_id(),
                "path": request.url.path,
                "status_code": exc.status_code,
            },
        )

    # Get message - handle dict details from HTTPException
    if isinstance(exc.detail, dict):
        message = exc.detail.get("message", str(exc.detail))
    else:
        message = str(exc.detail)

    return create_error_response(
        status_code=exc.status_code,
        error=error_code,
        message=message,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """
    Handle Pydantic validation errors.

    Converts validation errors to structured format with field-level details.
    """
    details = []
    for error in exc.errors():
        # Build field path (e.g., "body.offer_amount")
        loc = error.get("loc", [])
        field = ".".join(str(x) for x in loc) if loc else None

        details.append(
            ErrorDetail(
                field=field,
                message=error.get("msg", "Validation error"),
                code=error.get("type", "validation"),
            )
        )

    logger.warning(
        f"Validation error on {request.url.path}: {len(details)} errors",
        extra={
            "request_id": get_request_id(),
            "path": request.url.path,
            "error_count": len(details),
        },
    )

    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        error=ERROR_VALIDATION,
        message="Request validation failed",
        details=details,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unhandled exceptions.

    Logs the full traceback but returns a generic error to the client.
    Never exposes internal details in production.
    """
    request_id = get_request_id()

    # Log the full exception with traceback
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {exc}",
        extra={
            "request_id": request_id,
            "path": request.url.path,
            "method": request.method,
            "exception_type": type(exc).__name__,
        },
        exc_info=True,
    )

    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error=ERROR_INTERNAL,
        message="An unexpected error occurred. Please try again later.",
    )


# =============================================================================
# Setup Function
# =============================================================================


def setup_error_handlers(app: FastAPI) -> None:
    """
    Register all error handlers with the FastAPI app.

    Call this in create_app() after creating the FastAPI instance.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    logger.info("Error handlers registered")


# =============================================================================
# Convenience Exceptions
# =============================================================================


class DragonflyError(Exception):
    """Base exception for Dragonfly business logic errors."""

    def __init__(
        self,
        message: str,
        error_code: str = ERROR_INTERNAL,
        status_code: int = 500,
        details: list[ErrorDetail] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details


class NotFoundError(DragonflyError):
    """Resource not found."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            message=message,
            error_code=ERROR_NOT_FOUND,
            status_code=404,
        )


class ValidationError(DragonflyError):
    """Request validation failed."""

    def __init__(self, message: str, details: list[ErrorDetail] | None = None):
        super().__init__(
            message=message,
            error_code=ERROR_VALIDATION,
            status_code=422,
            details=details,
        )


class DatabaseError(DragonflyError):
    """Database operation failed."""

    def __init__(self, message: str = "Database operation failed"):
        super().__init__(
            message=message,
            error_code=ERROR_DATABASE,
            status_code=503,
        )
