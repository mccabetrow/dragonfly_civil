"""
Dragonfly Engine - Middleware Package

Security and observability middleware for FastAPI.
"""

from backend.middleware.correlation import (
    CorrelationMiddleware,
    get_request_id,
    reset_request_id,
    set_request_id,
)
from backend.middleware.security import (
    SecurityMiddleware,
    add_security_middleware,
    get_security_stats,
)
from backend.middleware.version import (
    ENV_NAME,
    GIT_SHA,
    GIT_SHA_SHORT,
    SHA_SOURCE,
    VERSION,
    VersionMiddleware,
    add_version_middleware,
    get_version_info,
)

__all__ = [
    # Correlation
    "CorrelationMiddleware",
    "get_request_id",
    "set_request_id",
    "reset_request_id",
    # Security
    "SecurityMiddleware",
    "add_security_middleware",
    "get_security_stats",
    # Version
    "VersionMiddleware",
    "add_version_middleware",
    "get_version_info",
    "GIT_SHA",
    "GIT_SHA_SHORT",
    "SHA_SOURCE",
    "ENV_NAME",
    "VERSION",
]
