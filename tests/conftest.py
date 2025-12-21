"""
tests/conftest.py

Pytest configuration and shared fixtures for the Dragonfly Civil test suite.

IMPORTANT: By default, all tests run against DEV Supabase (SUPABASE_MODE=dev).
Tests that explicitly need PROD should set SUPABASE_MODE=prod themselves and
are expected to be read-only / non-destructive.

DUAL-CONNECTION PATTERN (Zero Trust Security Model):
====================================================
This module provides two database connection fixtures:

  admin_db  - Connects as postgres superuser (SERVICE_ROLE)
              Used ONLY for test setup/teardown (creating schemas, seeding data)
              Environment: SUPABASE_DB_URL_ADMIN or falls back to SUPABASE_DB_URL

  app_db    - Connects as dragonfly_app (restricted role)
              Used for testing actual application logic
              Environment: SUPABASE_DB_URL (should be dragonfly_app credentials)

Tests should:
  1. SETUP: Use admin_db to create schemas, insert seed data
  2. ACTION: Use app_db to test application code (RPCs, queries)
  3. VERIFY: Use admin_db for cleanup and verification of side effects
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator

import psycopg
import pytest

# Re-export helpers for convenient imports
from tests.helpers import execute_resilient, httpx_resilient, is_postgrest_available

# =============================================================================
# GLOBAL TEST CONFIGURATION
# =============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """
    Global pytest configuration.

    Sets SUPABASE_MODE=dev by default to ensure tests never accidentally
    hit production. This runs BEFORE any test collection.

    Registers custom markers:
      - integration: Tests that require external services (PostgREST, Pooler, Realtime)
      - legacy: Tests for deprecated or optional DB features
    """
    # Register custom markers to avoid pytest warnings
    config.addinivalue_line(
        "markers",
        "integration: marks tests as requiring external services (PostgREST, Supabase)",
    )
    config.addinivalue_line(
        "markers",
        "legacy: marks tests for deprecated or optional DB features",
    )

    if "SUPABASE_MODE" not in os.environ:
        os.environ["SUPABASE_MODE"] = "dev"


# ═══════════════════════════════════════════════════════════════════════════
# DATABASE URL RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


def _get_admin_db_url() -> str | None:
    """
    Get the admin/superuser database URL for test setup/teardown.

    Priority:
      1. SUPABASE_DB_URL_ADMIN (explicit admin connection)
      2. SUPABASE_DB_URL (fallback - assumes postgres superuser in dev)
      3. DATABASE_URL (legacy fallback)

    The admin connection should use postgres superuser credentials and is
    used ONLY for test fixture setup (schema creation, data seeding, cleanup).
    """
    return (
        os.environ.get("SUPABASE_DB_URL_ADMIN")
        or os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
    )


def _get_app_db_url() -> str | None:
    """
    Get the application database URL for testing app logic.

    Priority:
      1. SUPABASE_DB_URL_APP (explicit app connection with dragonfly_app)
      2. SUPABASE_DB_URL (should be dragonfly_app in production tests)
      3. DATABASE_URL (legacy fallback)

    The app connection should use dragonfly_app credentials and is used
    to test actual application behavior with least-privilege restrictions.
    """
    return (
        os.environ.get("SUPABASE_DB_URL_APP")
        or os.environ.get("SUPABASE_DB_URL")
        or os.environ.get("DATABASE_URL")
    )


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


def _has_admin_db() -> bool:
    """Check if admin database connection is available."""
    url = _get_admin_db_url()
    if not url:
        return False
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
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


def skip_if_no_admin_db(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to skip tests that require admin database connection.
    Use this for tests that need schema creation or direct table access.
    """

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _has_admin_db():
            pytest.skip("Admin database connection not available")
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
# PYTEST FIXTURES: DATABASE CONNECTIONS
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def admin_db() -> Generator[psycopg.Connection, None, None]:
    """
    Fixture providing an ADMIN database connection for test setup/teardown.

    This connection uses postgres superuser (or service_role) credentials
    and can perform privileged operations like:
      - CREATE SCHEMA
      - CREATE TABLE
      - INSERT INTO any table
      - DELETE FROM any table

    DO NOT use this fixture to test application logic - use app_db instead.

    Usage:
        def test_something(admin_db, app_db):
            # Setup with admin
            with admin_db.cursor() as cur:
                cur.execute("INSERT INTO ops.job_queue ...")

            # Test with restricted app user
            with app_db.cursor() as cur:
                cur.execute("SELECT ops.claim_pending_job(...)")

            # Cleanup with admin
            with admin_db.cursor() as cur:
                cur.execute("DELETE FROM ops.job_queue WHERE ...")
    """
    url = _get_admin_db_url()
    if not url:
        pytest.skip("Admin database URL not configured (SUPABASE_DB_URL_ADMIN or SUPABASE_DB_URL)")

    conn = psycopg.connect(url, autocommit=False)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


@pytest.fixture
def admin_db_autocommit() -> Generator[psycopg.Connection, None, None]:
    """
    Fixture providing an ADMIN database connection with autocommit=True.

    Use this for DDL operations (CREATE, ALTER, DROP) that require autocommit.
    """
    url = _get_admin_db_url()
    if not url:
        pytest.skip("Admin database URL not configured")

    conn = psycopg.connect(url, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def app_db() -> Generator[psycopg.Connection, None, None]:
    """
    Fixture providing an APPLICATION database connection for testing app logic.

    This connection uses dragonfly_app credentials (least-privilege) and
    can only perform operations that the real application can perform:
      - SELECT on granted tables/views
      - EXECUTE on SECURITY DEFINER RPCs

    Use this fixture to test application behavior and verify that the
    security model is correctly enforced.

    Usage:
        def test_app_can_claim_job(admin_db, app_db):
            # Setup: admin seeds a job
            with admin_db.cursor() as cur:
                cur.execute("INSERT INTO ops.job_queue ...")
                admin_db.commit()

            # Action: app claims via RPC (should work)
            with app_db.cursor() as cur:
                cur.execute("SELECT * FROM ops.claim_pending_job(...)")
                job = cur.fetchone()
                assert job is not None
    """
    url = _get_app_db_url()
    if not url:
        pytest.skip("App database URL not configured (SUPABASE_DB_URL)")

    conn = psycopg.connect(url, autocommit=False)
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# PYTEST FIXTURES: SUPABASE CLIENT
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
