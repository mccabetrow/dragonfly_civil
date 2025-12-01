"""Supabase client bootstrap helpers."""

from __future__ import annotations

import os
from typing import Any

from .log import get_logger

__all__ = ["get_client"]

_LOG = get_logger(__name__)


def get_client() -> Any:
    """Create and return a Supabase client using environment credentials.

    Environment
    -----------
    SUPABASE_URL:
        Base URL for the Supabase instance.
    SUPABASE_SERVICE_ROLE_KEY:
        Service role API key for privileged access.

    Raises
    ------
    ValueError
        If the required environment variables are missing.
    RuntimeError
        If the Supabase Python client is not installed.
    """

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

    try:
        from supabase import create_client  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "The 'supabase' package is required. Install it with 'pip install supabase'."
        ) from exc

    _LOG.debug("Creating Supabase client for %s", url)
    return create_client(url, key)
