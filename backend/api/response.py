"""
Dragonfly Engine - Standardized API Response Envelope

All UI-facing endpoints MUST return this envelope so the frontend can handle
success, failure, and degradation consistently.

Usage:
    from backend.api import api_response, degraded_response, ApiResponse

    # Success
    return api_response(data=my_data)

    # Degraded (partial failure, still 200 OK)
    return degraded_response(error="Database timeout", data=[])

    # Full response control
    return ApiResponse(
        ok=True,
        data=my_data,
        meta=ResponseMeta(trace_id=get_trace_id())
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

from ..core.trace_middleware import get_trace_id

T = TypeVar("T")


class ResponseMeta(BaseModel):
    """Metadata included in every API response."""

    trace_id: str = Field(..., description="Request trace ID for debugging")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 response timestamp",
    )


class ApiResponse(BaseModel, Generic[T]):
    """
    Standardized API response envelope.

    All UI-facing endpoints return this envelope for consistent handling.

    Attributes:
        ok: True if request succeeded, False otherwise
        data: The response payload (type varies by endpoint)
        degraded: True if partial data due to downstream failures
        error: Error message if ok=False or degraded=True
        meta: Response metadata including trace_id
    """

    ok: bool = Field(..., description="True if request succeeded")
    data: T | None = Field(None, description="Response payload")
    degraded: bool = Field(False, description="True if partial data due to errors")
    error: str | None = Field(None, description="Error message if failed or degraded")
    meta: ResponseMeta = Field(..., description="Response metadata")

    model_config = {
        "json_schema_extra": {
            "example": {
                "ok": True,
                "data": {},
                "meta": {"trace_id": "abc123", "timestamp": "2025-01-01T00:00:00Z"},
            }
        }
    }


def api_response(
    data: Any = None,
    *,
    ok: bool = True,
    degraded: bool = False,
    error: str | None = None,
) -> ApiResponse[Any]:
    """
    Create a standard API response envelope.

    Args:
        data: Response payload
        ok: Whether the request succeeded (default True)
        degraded: Whether data is partial due to errors (default False)
        error: Error message if applicable

    Returns:
        ApiResponse with trace_id from current request context
    """
    return ApiResponse(
        ok=ok,
        data=data,
        degraded=degraded,
        error=error,
        meta=ResponseMeta(trace_id=get_trace_id()),
    )


def degraded_response(
    error: str,
    data: Any = None,
) -> ApiResponse[Any]:
    """
    Create a degraded response (partial failure, still 200 OK).

    Use this when an endpoint can return partial data but encountered
    an error. The UI should show the data but indicate degraded state.

    Args:
        error: Description of what failed
        data: Partial data to return (e.g., empty list)

    Returns:
        ApiResponse with ok=False, degraded=True
    """
    return ApiResponse(
        ok=False,
        data=data,
        degraded=True,
        error=error[:500] if error else None,  # Truncate for safety
        meta=ResponseMeta(trace_id=get_trace_id()),
    )
