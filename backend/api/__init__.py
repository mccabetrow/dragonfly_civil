"""
Dragonfly Engine - API Module

Shared API utilities including response envelope, trace ID management,
and standardized error handling.
"""

from .response import ApiResponse, ResponseMeta, api_response, degraded_response

__all__ = [
    "ApiResponse",
    "ResponseMeta",
    "api_response",
    "degraded_response",
]
