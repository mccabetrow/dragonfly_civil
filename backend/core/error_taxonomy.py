"""
Dragonfly Engine - Error Taxonomy

Structured error classification for observability and incident response.
All errors get a stable error_code that can be:
- Aggregated in logs/metrics
- Used for alerting rules
- Referenced in incident documentation

Error Code Format: DFE-{CATEGORY}-{NUMBER}
- DFE = DragonflyError prefix
- CATEGORY = CONFIG, DB, NET, VENDOR, AUTH, VALIDATION, INTERNAL
- NUMBER = 3-digit error number

Categories:
- CONFIG (001-099): Configuration and environment errors
- DB (100-199): Database connectivity and query errors
- NET (200-299): Network and HTTP errors
- VENDOR (300-399): Third-party service errors (Supabase, OpenAI, etc.)
- AUTH (400-499): Authentication and authorization errors
- VALIDATION (500-599): Input validation errors
- INTERNAL (900-999): Unexpected internal errors
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# =============================================================================
# ERROR CODES
# =============================================================================


class ErrorCategory(str, Enum):
    """Error category for classification."""

    CONFIG = "CONFIG"
    DB = "DB"
    NET = "NET"
    VENDOR = "VENDOR"
    AUTH = "AUTH"
    VALIDATION = "VALIDATION"
    INTERNAL = "INTERNAL"


@dataclass(frozen=True)
class ErrorCode:
    """Immutable error code definition."""

    code: str
    category: ErrorCategory
    message: str
    http_status: int = 500
    retryable: bool = False

    def __str__(self) -> str:
        return self.code


# -----------------------------------------------------------------------------
# CONFIG Errors (001-099)
# -----------------------------------------------------------------------------
ERR_CONFIG_MISSING_ENV = ErrorCode(
    code="DFE-CONFIG-001",
    category=ErrorCategory.CONFIG,
    message="Required environment variable is missing",
    http_status=500,
    retryable=False,
)
ERR_CONFIG_INVALID_VALUE = ErrorCode(
    code="DFE-CONFIG-002",
    category=ErrorCategory.CONFIG,
    message="Environment variable has invalid value",
    http_status=500,
    retryable=False,
)
ERR_CONFIG_SUPABASE_URL = ErrorCode(
    code="DFE-CONFIG-010",
    category=ErrorCategory.CONFIG,
    message="Invalid or missing SUPABASE_URL",
    http_status=500,
    retryable=False,
)
ERR_CONFIG_SERVICE_KEY = ErrorCode(
    code="DFE-CONFIG-011",
    category=ErrorCategory.CONFIG,
    message="Invalid or missing SUPABASE_SERVICE_ROLE_KEY",
    http_status=500,
    retryable=False,
)

# -----------------------------------------------------------------------------
# DB Errors (100-199)
# -----------------------------------------------------------------------------
ERR_DB_CONNECTION = ErrorCode(
    code="DFE-DB-100",
    category=ErrorCategory.DB,
    message="Database connection failed",
    http_status=503,
    retryable=True,
)
ERR_DB_POOL_EXHAUSTED = ErrorCode(
    code="DFE-DB-101",
    category=ErrorCategory.DB,
    message="Database connection pool exhausted",
    http_status=503,
    retryable=True,
)
ERR_DB_TIMEOUT = ErrorCode(
    code="DFE-DB-102",
    category=ErrorCategory.DB,
    message="Database query timeout",
    http_status=503,
    retryable=True,
)
ERR_DB_QUERY_ERROR = ErrorCode(
    code="DFE-DB-110",
    category=ErrorCategory.DB,
    message="Database query failed",
    http_status=500,
    retryable=False,
)
ERR_DB_CONSTRAINT = ErrorCode(
    code="DFE-DB-111",
    category=ErrorCategory.DB,
    message="Database constraint violation",
    http_status=409,
    retryable=False,
)
ERR_DB_NOT_FOUND = ErrorCode(
    code="DFE-DB-120",
    category=ErrorCategory.DB,
    message="Record not found",
    http_status=404,
    retryable=False,
)

# -----------------------------------------------------------------------------
# NET Errors (200-299)
# -----------------------------------------------------------------------------
ERR_NET_TIMEOUT = ErrorCode(
    code="DFE-NET-200",
    category=ErrorCategory.NET,
    message="Network request timed out",
    http_status=504,
    retryable=True,
)
ERR_NET_CONNECTION = ErrorCode(
    code="DFE-NET-201",
    category=ErrorCategory.NET,
    message="Network connection failed",
    http_status=503,
    retryable=True,
)
ERR_NET_DNS = ErrorCode(
    code="DFE-NET-202",
    category=ErrorCategory.NET,
    message="DNS resolution failed",
    http_status=503,
    retryable=True,
)
ERR_NET_SSL = ErrorCode(
    code="DFE-NET-203",
    category=ErrorCategory.NET,
    message="SSL/TLS error",
    http_status=503,
    retryable=False,
)

# -----------------------------------------------------------------------------
# VENDOR Errors (300-399)
# -----------------------------------------------------------------------------
ERR_VENDOR_SUPABASE = ErrorCode(
    code="DFE-VENDOR-300",
    category=ErrorCategory.VENDOR,
    message="Supabase API error",
    http_status=503,
    retryable=True,
)
ERR_VENDOR_SUPABASE_AUTH = ErrorCode(
    code="DFE-VENDOR-301",
    category=ErrorCategory.VENDOR,
    message="Supabase authentication failed",
    http_status=401,
    retryable=False,
)
ERR_VENDOR_SUPABASE_RATE_LIMIT = ErrorCode(
    code="DFE-VENDOR-302",
    category=ErrorCategory.VENDOR,
    message="Supabase rate limit exceeded",
    http_status=429,
    retryable=True,
)
ERR_VENDOR_OPENAI = ErrorCode(
    code="DFE-VENDOR-310",
    category=ErrorCategory.VENDOR,
    message="OpenAI API error",
    http_status=503,
    retryable=True,
)
ERR_VENDOR_OPENAI_RATE_LIMIT = ErrorCode(
    code="DFE-VENDOR-311",
    category=ErrorCategory.VENDOR,
    message="OpenAI rate limit exceeded",
    http_status=429,
    retryable=True,
)

# -----------------------------------------------------------------------------
# AUTH Errors (400-499)
# -----------------------------------------------------------------------------
ERR_AUTH_MISSING_TOKEN = ErrorCode(
    code="DFE-AUTH-400",
    category=ErrorCategory.AUTH,
    message="Authentication token missing",
    http_status=401,
    retryable=False,
)
ERR_AUTH_INVALID_TOKEN = ErrorCode(
    code="DFE-AUTH-401",
    category=ErrorCategory.AUTH,
    message="Authentication token invalid",
    http_status=401,
    retryable=False,
)
ERR_AUTH_EXPIRED_TOKEN = ErrorCode(
    code="DFE-AUTH-402",
    category=ErrorCategory.AUTH,
    message="Authentication token expired",
    http_status=401,
    retryable=False,
)
ERR_AUTH_FORBIDDEN = ErrorCode(
    code="DFE-AUTH-403",
    category=ErrorCategory.AUTH,
    message="Access forbidden",
    http_status=403,
    retryable=False,
)

# -----------------------------------------------------------------------------
# VALIDATION Errors (500-599)
# -----------------------------------------------------------------------------
ERR_VALIDATION_INPUT = ErrorCode(
    code="DFE-VALIDATION-500",
    category=ErrorCategory.VALIDATION,
    message="Input validation failed",
    http_status=422,
    retryable=False,
)
ERR_VALIDATION_SCHEMA = ErrorCode(
    code="DFE-VALIDATION-501",
    category=ErrorCategory.VALIDATION,
    message="Schema validation failed",
    http_status=422,
    retryable=False,
)
ERR_VALIDATION_BUSINESS = ErrorCode(
    code="DFE-VALIDATION-510",
    category=ErrorCategory.VALIDATION,
    message="Business rule validation failed",
    http_status=400,
    retryable=False,
)

# -----------------------------------------------------------------------------
# INTERNAL Errors (900-999)
# -----------------------------------------------------------------------------
ERR_INTERNAL_UNKNOWN = ErrorCode(
    code="DFE-INTERNAL-900",
    category=ErrorCategory.INTERNAL,
    message="Unknown internal error",
    http_status=500,
    retryable=False,
)
ERR_INTERNAL_NOT_IMPLEMENTED = ErrorCode(
    code="DFE-INTERNAL-901",
    category=ErrorCategory.INTERNAL,
    message="Feature not implemented",
    http_status=501,
    retryable=False,
)


# =============================================================================
# STRUCTURED ERROR
# =============================================================================


@dataclass
class StructuredError:
    """
    Structured error for logging and reporting.

    Captures all relevant context for incident response.
    """

    error_code: ErrorCode
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)
    original_exception: Exception | None = None
    traceback_str: str | None = None

    def __post_init__(self):
        if self.original_exception and not self.traceback_str:
            self.traceback_str = "".join(
                traceback.format_exception(
                    type(self.original_exception),
                    self.original_exception,
                    self.original_exception.__traceback__,
                )
            )

    def to_log_dict(self) -> dict[str, Any]:
        """Convert to dict suitable for structured logging."""
        return {
            "error_code": str(self.error_code),
            "error_category": self.error_code.category.value,
            "error_message": self.message,
            "http_status": self.error_code.http_status,
            "retryable": self.error_code.retryable,
            "timestamp": self.timestamp.isoformat(),
            **self.context,
        }

    def log(self, level: int = logging.ERROR) -> None:
        """Log this error with structured context."""
        logger.log(
            level,
            f"[{self.error_code}] {self.message}",
            extra=self.to_log_dict(),
            exc_info=self.original_exception,
        )


# =============================================================================
# ERROR CLASSIFIER
# =============================================================================


def classify_exception(exc: Exception, context: dict[str, Any] | None = None) -> StructuredError:
    """
    Classify an exception into a structured error.

    Maps common exception types to appropriate error codes.

    Args:
        exc: The exception to classify
        context: Additional context for logging

    Returns:
        StructuredError with appropriate classification
    """
    context = context or {}
    exc_type = type(exc).__name__
    exc_msg = str(exc)

    # Database errors
    if "psycopg" in exc_type.lower() or "postgres" in exc_type.lower():
        if "timeout" in exc_msg.lower():
            error_code = ERR_DB_TIMEOUT
        elif "connection" in exc_msg.lower() or "connect" in exc_msg.lower():
            error_code = ERR_DB_CONNECTION
        elif "pool" in exc_msg.lower():
            error_code = ERR_DB_POOL_EXHAUSTED
        elif "violates" in exc_msg.lower() or "constraint" in exc_msg.lower():
            error_code = ERR_DB_CONSTRAINT
        else:
            error_code = ERR_DB_QUERY_ERROR

    # Network errors
    elif "timeout" in exc_type.lower() or "TimeoutError" in exc_type:
        error_code = ERR_NET_TIMEOUT
    elif "ConnectionError" in exc_type or "connection" in exc_msg.lower():
        error_code = ERR_NET_CONNECTION
    elif "SSLError" in exc_type or "ssl" in exc_msg.lower():
        error_code = ERR_NET_SSL
    elif "gaierror" in exc_type.lower() or "dns" in exc_msg.lower():
        error_code = ERR_NET_DNS

    # Vendor errors (Supabase)
    elif "supabase" in exc_type.lower() or "postgrest" in exc_type.lower():
        if "401" in exc_msg or "unauthorized" in exc_msg.lower():
            error_code = ERR_VENDOR_SUPABASE_AUTH
        elif "429" in exc_msg or "rate" in exc_msg.lower():
            error_code = ERR_VENDOR_SUPABASE_RATE_LIMIT
        else:
            error_code = ERR_VENDOR_SUPABASE

    # Vendor errors (OpenAI)
    elif "openai" in exc_type.lower():
        if "rate" in exc_msg.lower():
            error_code = ERR_VENDOR_OPENAI_RATE_LIMIT
        else:
            error_code = ERR_VENDOR_OPENAI

    # Validation errors
    elif "ValidationError" in exc_type or "Validation" in exc_type:
        error_code = ERR_VALIDATION_INPUT
    elif "ValueError" in exc_type:
        error_code = ERR_VALIDATION_BUSINESS

    # Config errors
    elif "KeyError" in exc_type and "env" in exc_msg.lower():
        error_code = ERR_CONFIG_MISSING_ENV

    # Not implemented
    elif "NotImplementedError" in exc_type:
        error_code = ERR_INTERNAL_NOT_IMPLEMENTED

    # Default: unknown internal error
    else:
        error_code = ERR_INTERNAL_UNKNOWN

    return StructuredError(
        error_code=error_code,
        message=exc_msg,
        context={
            "exception_type": exc_type,
            **context,
        },
        original_exception=exc,
    )


def log_classified_error(
    exc: Exception,
    context: dict[str, Any] | None = None,
    level: int = logging.ERROR,
) -> StructuredError:
    """
    Classify and log an exception in one call.

    Args:
        exc: The exception to classify and log
        context: Additional context for logging
        level: Log level (default: ERROR)

    Returns:
        The classified StructuredError
    """
    structured = classify_exception(exc, context)
    structured.log(level)
    return structured
