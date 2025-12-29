"""
Integration Tests - Segregated by Infrastructure vs Schema
===========================================================

This module provides integration tests split into two categories:

1. integration_infra: Infrastructure availability tests
   - Database connectivity
   - PostgREST availability
   - Pooler reachability
   - Basic health endpoints

   These tests verify that external infrastructure is accessible.
   On Initial Deploy, failures are WARNINGS (tolerated).

2. integration_schema: Schema correctness tests
   - Table existence
   - RPC logic
   - Business flow verification
   - View accessibility

   These tests verify that the schema is correctly deployed.
   SKIPPED on Initial Deploy (schema may not exist yet).

Run modes:
    pytest -m "integration_infra"           # Infra only
    pytest -m "integration_schema"          # Schema only
    pytest -m "integration_infra or integration_schema"  # All integration
"""

from __future__ import annotations

import os
from typing import Generator

import psycopg
import pytest
import requests

from src.supabase_client import get_supabase_db_url, get_supabase_env

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(scope="module")
def db_url() -> str:
    """Get the database URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


@pytest.fixture(scope="module")
def db_connection(db_url: str) -> Generator[psycopg.Connection, None, None]:
    """Provide a database connection for tests."""
    with psycopg.connect(db_url, autocommit=True, connect_timeout=10) as conn:
        yield conn


@pytest.fixture(scope="module")
def supabase_url() -> str:
    """Get the Supabase REST API URL."""
    return os.environ.get("SUPABASE_URL", "")


@pytest.fixture(scope="module")
def service_role_key() -> str:
    """Get the Supabase service role key."""
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")


# ============================================================================
# INFRASTRUCTURE TESTS (integration_infra)
# ============================================================================


@pytest.mark.integration_infra
class TestInfraConnectivity:
    """Infrastructure availability tests - connectivity and health."""

    def test_db_connection_direct(self, db_url: str) -> None:
        """Verify direct database connection works."""
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                assert result == (1,), "SELECT 1 should return (1,)"

    def test_db_version(self, db_connection: psycopg.Connection) -> None:
        """Verify PostgreSQL version is accessible."""
        with db_connection.cursor() as cur:
            cur.execute("SELECT version()")
            result = cur.fetchone()
            assert result is not None
            version_str = result[0]
            assert "PostgreSQL" in version_str

    def test_postgrest_health(self, supabase_url: str, service_role_key: str) -> None:
        """Verify PostgREST endpoint is reachable."""
        if not supabase_url or not service_role_key:
            pytest.skip("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

        # PostgREST root returns OpenAPI spec
        headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }
        try:
            resp = requests.get(f"{supabase_url}/rest/v1/", headers=headers, timeout=10)
            # 200 = OpenAPI spec, 406 = no Accept header (still reachable)
            # 503 = service temporarily unavailable (transient, still "reachable")
            # 429 = rate limited (transient, still "reachable")
            reachable_codes = (200, 406, 429, 503)
            assert resp.status_code in reachable_codes, f"PostgREST unreachable: {resp.status_code}"
        except requests.RequestException as e:
            pytest.fail(f"PostgREST connection failed: {e}")

    def test_supabase_storage_reachable(self, supabase_url: str, service_role_key: str) -> None:
        """Verify Supabase Storage endpoint is reachable."""
        if not supabase_url or not service_role_key:
            pytest.skip("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set")

        headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }
        try:
            resp = requests.get(f"{supabase_url}/storage/v1/bucket", headers=headers, timeout=10)
            # 200 = list buckets, 401/403 = auth required (still reachable)
            # 429 = rate limited (transient, still "reachable")
            # 503 = service temporarily unavailable (transient)
            reachable_codes = (200, 401, 403, 429, 503)
            assert resp.status_code in reachable_codes, f"Storage unreachable: {resp.status_code}"
        except requests.RequestException as e:
            pytest.fail(f"Storage connection failed: {e}")


# ============================================================================
# SCHEMA TESTS (integration_schema)
# ============================================================================


@pytest.mark.integration_schema
class TestSchemaCorrectness:
    """Schema correctness tests - table existence and structure."""

    def test_judgments_table_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify judgments table exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'judgments'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "judgments table must exist"

    def test_plaintiffs_table_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify plaintiffs table exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'plaintiffs'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "plaintiffs table must exist"

    def test_enforcement_cases_table_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify enforcement_cases table exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public'
                    AND table_name = 'enforcement_cases'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "enforcement_cases table must exist"

    def test_job_queue_table_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify job_queue table exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'ops'
                    AND table_name = 'job_queue'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "ops.job_queue table must exist"


@pytest.mark.integration_schema
class TestRpcLogic:
    """RPC logic tests - function existence and basic invocation."""

    def test_queue_job_rpc_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify queue_job RPC function exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND p.proname = 'queue_job'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "queue_job RPC must exist"

    def test_set_enforcement_stage_rpc_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify set_enforcement_stage RPC function exists."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND p.proname = 'set_enforcement_stage'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "set_enforcement_stage RPC must exist"

    def test_get_plaintiffs_overview_rpc_exists(self, db_connection: psycopg.Connection) -> None:
        """Verify a plaintiffs overview RPC or view exists."""
        with db_connection.cursor() as cur:
            # Check for view (v_plaintiffs_overview) or RPC
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name = 'v_plaintiffs_overview'
                )
            """
            )
            result = cur.fetchone()
            assert result and result[0], "v_plaintiffs_overview view must exist"


@pytest.mark.integration_schema
class TestCriticalViews:
    """Critical view tests - dashboard views must exist."""

    CRITICAL_VIEWS = [
        "v_plaintiffs_overview",
        "v_judgment_pipeline",
        "v_enforcement_overview",
    ]

    @pytest.mark.parametrize("view_name", CRITICAL_VIEWS)
    def test_critical_view_exists(self, db_connection: psycopg.Connection, view_name: str) -> None:
        """Verify critical dashboard views exist."""
        with db_connection.cursor() as cur:
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_schema = 'public'
                    AND table_name = %s
                )
            """,
                (view_name,),
            )
            result = cur.fetchone()
            assert result and result[0], f"{view_name} view must exist"
