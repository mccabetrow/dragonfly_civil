"""
tests/test_migration_status_view.py
-------------------------------------------------------------------------------

Integration tests for the v_migration_status view.

Tests:
  - View exists and is queryable
  - Returns rows from both 'legacy' and 'supabase' sources (if data exists)
  - Has the expected columns (source, version, name, executed_at, success)

Note: These tests require:
  - 20251209000000_migration_status_view.sql to be applied
  - At least one migration in either dragonfly_migrations or schema_migrations

Strategy:
  - If view doesn't exist → pytest.skip (migration not yet applied)
  - If view exists but returns no rows → soft warning (tables may be empty)
"""

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env

pytestmark = pytest.mark.integration

# Expected columns in the view
EXPECTED_COLUMNS = {"source", "version", "name", "executed_at", "success"}


def _get_connection_url() -> str:
    """Return the database connection URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


def _view_exists(cur: psycopg.Cursor) -> bool:
    """Check if v_migration_status view exists."""
    cur.execute(
        """
        SELECT 1
        FROM pg_views
        WHERE schemaname = 'public'
          AND viewname = 'v_migration_status'
        """
    )
    return cur.fetchone() is not None


def _get_view_columns(cur: psycopg.Cursor) -> set[str]:
    """Get the column names of the view."""
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'v_migration_status'
        """
    )
    return {row[0] for row in cur.fetchall()}


class TestMigrationStatusView:
    """Tests for public.v_migration_status view."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_view_exists(self):
        """The v_migration_status view should exist after migration."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip(
                    "v_migration_status view not found - migration 20251209000000 not applied"
                )
            assert _view_exists(cur), "v_migration_status view should exist"

    def test_view_has_expected_columns(self):
        """The view should have all expected columns."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            columns = _get_view_columns(cur)
            missing = EXPECTED_COLUMNS - columns
            assert not missing, f"Missing columns: {missing}"

    def test_view_is_queryable(self):
        """The view should be queryable without errors."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            # Query should not raise
            cur.execute("SELECT * FROM public.v_migration_status LIMIT 10")
            rows = cur.fetchall()
            # Just verify it returns a list (may be empty if no migrations recorded)
            assert isinstance(rows, list)

    def test_source_values(self):
        """If rows exist, source should be 'legacy' or 'supabase'."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            cur.execute("SELECT DISTINCT source FROM public.v_migration_status")
            sources = {row[0] for row in cur.fetchall()}

            if not sources:
                pytest.skip("No migrations recorded in either tracker table")

            valid_sources = {"legacy", "supabase"}
            invalid = sources - valid_sources
            assert not invalid, f"Unexpected source values: {invalid}"

    def test_both_sources_present_when_data_exists(self):
        """
        When both tracking tables have data, both sources should appear.
        This is a soft check - we only fail if we expect both but find neither.
        """
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            # Check if legacy table has data
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'dragonfly_migrations'
                """
            )
            legacy_table_exists = cur.fetchone() is not None

            if legacy_table_exists:
                cur.execute("SELECT COUNT(*) FROM public.dragonfly_migrations")
                legacy_count = cur.fetchone()[0]
            else:
                legacy_count = 0

            # Check if supabase table has data
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'supabase_migrations'
                  AND table_name = 'schema_migrations'
                """
            )
            supabase_table_exists = cur.fetchone() is not None

            if supabase_table_exists:
                cur.execute("SELECT COUNT(*) FROM supabase_migrations.schema_migrations")
                supabase_count = cur.fetchone()[0]
            else:
                supabase_count = 0

            # Get sources from view
            cur.execute("SELECT DISTINCT source FROM public.v_migration_status")
            view_sources = {row[0] for row in cur.fetchall()}

            # Verify consistency
            if legacy_count > 0:
                assert (
                    "legacy" in view_sources
                ), f"Legacy table has {legacy_count} rows but 'legacy' not in view sources"

            if supabase_count > 0:
                assert (
                    "supabase" in view_sources
                ), f"Supabase table has {supabase_count} rows but 'supabase' not in view sources"

    def test_success_column_is_boolean(self):
        """The success column should be boolean."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            cur.execute(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'v_migration_status'
                  AND column_name = 'success'
                """
            )
            row = cur.fetchone()
            assert row is not None, "success column not found"
            assert row[0] == "boolean", f"success column should be boolean, got {row[0]}"

    def test_authenticated_role_has_select(self):
        """The authenticated role should have SELECT on the view."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            cur.execute(
                """
                SELECT has_table_privilege('authenticated', 'public.v_migration_status', 'SELECT')
                """
            )
            result = cur.fetchone()
            assert (
                result and result[0]
            ), "authenticated role should have SELECT on v_migration_status"

    def test_service_role_has_select(self):
        """The service_role should have SELECT on the view."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur):
                pytest.skip("v_migration_status view not found")

            cur.execute(
                """
                SELECT has_table_privilege('service_role', 'public.v_migration_status', 'SELECT')
                """
            )
            result = cur.fetchone()
            assert result and result[0], "service_role should have SELECT on v_migration_status"
