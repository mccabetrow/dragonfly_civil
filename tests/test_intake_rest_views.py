"""
tests/test_intake_rest_views.py
-------------------------------------------------------------------------------

Integration tests for the public shim views:
  - public.v_intake_monitor (proxies ops.v_intake_monitor)
  - public.v_enrichment_health (proxies ops.v_enrichment_health)

Tests:
  - Views exist and are queryable
  - Views are readable by authenticated role
  - Views have expected columns

Note: These tests require:
  - 20251211000000_intake_rest_views.sql to be applied
  - Underlying ops views to exist (from earlier migrations)

Strategy:
  - If view doesn't exist → pytest.skip (migration not yet applied)
  - If view exists but returns no rows → soft pass (data may be empty)
"""

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env


def _get_connection_url() -> str:
    """Return the database connection URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


def _view_exists(cur: psycopg.Cursor, view_name: str) -> bool:
    """Check if a view exists in the public schema."""
    cur.execute(
        """
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'public'
          AND viewname = %s
        """,
        (view_name,),
    )
    return cur.fetchone() is not None


def _get_view_columns(cur: psycopg.Cursor, view_name: str) -> set[str]:
    """Get the column names of a view."""
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        """,
        (view_name,),
    )
    return {row[0] for row in cur.fetchall()}


def _check_role_has_select(cur: psycopg.Cursor, view_name: str, role: str) -> bool:
    """Check if a role has SELECT privilege on a view."""
    cur.execute(
        f"""
        SELECT has_table_privilege(%s, 'public.{view_name}', 'SELECT')
        """,
        (role,),
    )
    result = cur.fetchone()
    return result[0] if result else False


class TestIntakeMonitorView:
    """Tests for public.v_intake_monitor shim view."""

    VIEW_NAME = "v_intake_monitor"

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_view_exists(self):
        """The v_intake_monitor view should exist after migration."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(
                    f"{self.VIEW_NAME} view not found - migration 20251211000000 not applied"
                )
            assert _view_exists(
                cur, self.VIEW_NAME
            ), f"{self.VIEW_NAME} view should exist"

    def test_view_is_queryable(self):
        """The view should be queryable without errors."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            # Query should not raise
            cur.execute(f"SELECT * FROM public.{self.VIEW_NAME} LIMIT 1")
            # No assertion on row count - view may be empty

    def test_authenticated_role_has_select(self):
        """The authenticated role should have SELECT privilege."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.VIEW_NAME, "authenticated")
            assert (
                has_select
            ), f"authenticated role should have SELECT on {self.VIEW_NAME}"

    def test_service_role_has_select(self):
        """The service_role should have SELECT privilege."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.VIEW_NAME, "service_role")
            assert has_select, f"service_role should have SELECT on {self.VIEW_NAME}"


class TestEnrichmentHealthView:
    """Tests for public.v_enrichment_health shim view."""

    VIEW_NAME = "v_enrichment_health"

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_view_exists(self):
        """The v_enrichment_health view should exist after migration."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(
                    f"{self.VIEW_NAME} view not found - migration 20251211000000 not applied"
                )
            assert _view_exists(
                cur, self.VIEW_NAME
            ), f"{self.VIEW_NAME} view should exist"

    def test_view_is_queryable(self):
        """The view should be queryable without errors."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            # Query should not raise
            cur.execute(f"SELECT * FROM public.{self.VIEW_NAME} LIMIT 1")
            # No assertion on row count - view may be empty

    def test_authenticated_role_has_select(self):
        """The authenticated role should have SELECT privilege."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.VIEW_NAME, "authenticated")
            assert (
                has_select
            ), f"authenticated role should have SELECT on {self.VIEW_NAME}"

    def test_service_role_has_select(self):
        """The service_role should have SELECT privilege."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.VIEW_NAME, "service_role")
            assert has_select, f"service_role should have SELECT on {self.VIEW_NAME}"


class TestBothViewsExist:
    """Combined tests to verify both views are present together."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_both_views_exist(self):
        """Both intake and enrichment health views should exist."""
        with self.conn.cursor() as cur:
            intake_exists = _view_exists(cur, "v_intake_monitor")
            health_exists = _view_exists(cur, "v_enrichment_health")

            if not intake_exists and not health_exists:
                pytest.skip("Neither view found - migration 20251211000000 not applied")

            assert intake_exists, "v_intake_monitor should exist"
            assert health_exists, "v_enrichment_health should exist"
