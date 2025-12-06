"""
Dragonfly Engine - Security Layer

Provides authentication and authorization for API endpoints.
Supports API key authentication and JWT (Supabase) authentication.
"""

import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import Depends, Header, HTTPException, status
from loguru import logger


@dataclass
class AuthContext:
    """
    Authentication context for the current request.

    Attributes:
        subject: The authenticated user ID (from JWT) or None for API key auth
        via: How the user was authenticated
    """

    subject: str | None
    via: Literal["api_key", "jwt", "anonymous"]


def _get_api_key() -> str | None:
    """
    Get the configured API key from environment.

    Reads DRAGONFLY_API_KEY directly from os.environ (not file-based secrets).
    In production, logs a warning if missing to aid debugging.
    In dev/test, silently returns None to allow tests without secrets.
    """
    import os

    key = os.environ.get("DRAGONFLY_API_KEY")
    if not key:
        env = os.environ.get("ENVIRONMENT", "dev")
        if env == "prod":
            logger.warning(
                "DRAGONFLY_API_KEY not set in production - API key auth will fail"
            )
    return key


def _get_jwt_secret() -> str | None:
    """Get the Supabase JWT secret from settings."""
    import os

    return os.environ.get("SUPABASE_JWT_SECRET")


def _decode_jwt(token: str) -> dict | None:
    """
    Decode a Supabase JWT token.

    Returns the payload if valid, None otherwise.
    """
    try:
        import jwt

        secret = _get_jwt_secret()
        if not secret:
            logger.warning("SUPABASE_JWT_SECRET not configured, cannot validate JWT")
            return None

        # Supabase uses HS256 by default
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload

    except ImportError:
        logger.warning("PyJWT not installed, cannot validate JWT tokens")
        return None
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid JWT token: {type(e).__name__}")
        return None


async def get_current_user(
    authorization: str | None = Header(default=None),
    x_dragonfly_api_key: str | None = Header(default=None, alias="X-DRAGONFLY-API-KEY"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthContext:
    """
    FastAPI dependency for authenticating requests.

    Authentication methods (in order of priority):
    1. X-DRAGONFLY-API-KEY header: Primary API key header (frontend/services)
    2. X-API-Key header: Legacy header (n8n workflows, backward compatibility)
    3. Authorization: Bearer <token>: For user JWT tokens

    Raises:
        HTTPException 401: If authentication fails

    Returns:
        AuthContext with authenticated user info
    """
    # Method 1: API Key authentication (prefer X-DRAGONFLY-API-KEY, fallback to X-API-Key)
    api_key = x_dragonfly_api_key or x_api_key
    if api_key:
        configured_key = _get_api_key()
        if configured_key and secrets.compare_digest(api_key, configured_key):
            logger.debug("Authenticated via API key")
            return AuthContext(subject=None, via="api_key")
        else:
            logger.warning("Invalid API key attempted")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
                headers={"WWW-Authenticate": "API-Key"},
            )

    # Method 2: JWT Bearer token
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = authorization[7:]  # Strip "Bearer "

        payload = _decode_jwt(token)
        if payload:
            subject = payload.get("sub")
            logger.debug(f"Authenticated via JWT: subject={subject}")
            return AuthContext(subject=subject, via="jwt")
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # No authentication provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer, API-Key"},
    )


def require_auth() -> AuthContext:
    """
    Convenience dependency for requiring authentication.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(auth: AuthContext = Depends(require_auth)):
            ...
    """
    return Depends(get_current_user)


# Optional: Allow anonymous access for certain endpoints
async def get_optional_user(
    authorization: str | None = Header(default=None),
    x_dragonfly_api_key: str | None = Header(default=None, alias="X-DRAGONFLY-API-KEY"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> AuthContext:
    """
    Like get_current_user, but returns anonymous context instead of raising.

    Useful for endpoints that have different behavior for authenticated users.
    """
    try:
        return await get_current_user(authorization, x_dragonfly_api_key, x_api_key)
    except HTTPException:
        return AuthContext(subject=None, via="anonymous")
