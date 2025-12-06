"""
tests/conftest.py

Pytest configuration and shared fixtures for the Dragonfly Civil test suite.

IMPORTANT: By default, all tests run against DEV Supabase (SUPABASE_MODE=dev).
Tests that explicitly need PROD should set SUPABASE_MODE=prod themselves and
are expected to be read-only / non-destructive.
"""

from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

import pytest

# =============================================================================
# GLOBAL TEST CONFIGURATION
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """
    Global pytest configuration.

    Sets SUPABASE_MODE=dev by default to ensure tests never accidentally
    hit production. This runs BEFORE any test collection.
    """
    if "SUPABASE_MODE" not in os.environ:
        os.environ["SUPABASE_MODE"] = "dev"


# ═══════════════════════════════════════════════════════════════════════════
# SKIP DECORATORS
# ═══════════════════════════════════════════════════════════════════════════


def _has_db_connection() -> bool:
    """Check if database connection is available."""
    try:
        from src.supabase_client import create_supabase_client

        client = create_supabase_client()
        # Simple health check - just ensure we can get the client
        return client is not None
    except Exception:
        return False


def skip_if_no_db(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to skip tests that require database connection.
    Use this for integration tests that hit the real Supabase instance.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _has_db_connection():
            pytest.skip("Database connection not available")
        return func(*args, **kwargs)

    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# TEST CLIENT HELPERS
# ═══════════════════════════════════════════════════════════════════════════


def get_test_client():
    """
    Get a Supabase client for testing.
    Returns the client or raises if not available.
    """
    from src.supabase_client import create_supabase_client

    return create_supabase_client()


# ═══════════════════════════════════════════════════════════════════════════
# PYTEST FIXTURES
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def supabase_client():
    """Fixture providing a Supabase client for tests."""
    if not _has_db_connection():
        pytest.skip("Database connection not available")
    return get_test_client()


@pytest.fixture
def test_env():
    """Fixture ensuring SUPABASE_MODE is set for tests."""
    original = os.environ.get("SUPABASE_MODE")
    if not original:
        os.environ["SUPABASE_MODE"] = "dev"
    yield os.environ.get("SUPABASE_MODE")
    if original:
        os.environ["SUPABASE_MODE"] = original
    elif "SUPABASE_MODE" in os.environ:
        del os.environ["SUPABASE_MODE"]
