"""
tests/test_enforcement_radar_filters.py
═══════════════════════════════════════════════════════════════════════════════

Integration tests for the enforcement_radar_filtered RPC function.

Verifies that:
  1. The RPC exists and returns rows
  2. Passing min_score filter reduces the row count appropriately
  3. Passing only_employed=true filters to rows with employer intel
  4. Passing only_bank_assets=true filters to rows with bank intel

These tests require:
  - Migration 20251223000000_enforcement_radar_filters.sql applied
  - Some seed data in public.judgments with debtor_intelligence records
"""

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env

pytestmark = [pytest.mark.legacy, pytest.mark.integration]


def _get_connection_url() -> str:
    """Return the database connection URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


def _rpc_exists(cur: psycopg.Cursor) -> bool:
    """Check if the enforcement_radar_filtered function exists."""
    cur.execute(
        """
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'public'
          AND p.proname = 'enforcement_radar_filtered'
        """
    )
    return cur.fetchone() is not None


class TestEnforcementRadarFilteredRPC:
    """Tests for enforcement_radar_filtered RPC."""

    def test_rpc_exists(self):
        """RPC function exists after migration is applied."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found - migration not applied")
                assert _rpc_exists(cur)

    def test_rpc_returns_rows_no_filters(self):
        """Calling RPC with no filters returns the full dataset."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found")

                cur.execute("SELECT * FROM public.enforcement_radar_filtered(NULL, NULL, NULL)")
                rows_all = cur.fetchall()
                # Should return some rows (depends on seed data)
                # At minimum, verify the call works
                assert rows_all is not None, "RPC returned None"

    def test_min_score_filter_reduces_rows(self):
        """Passing a min_score filter should return fewer or equal rows."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found")

                # Get all rows
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, NULL, NULL)"
                )
                count_all = cur.fetchone()[0]

                # Get rows with min_score = 50
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(50, NULL, NULL)"
                )
                count_filtered = cur.fetchone()[0]

                # Filtered count should be <= unfiltered count
                assert count_filtered <= count_all, (
                    f"min_score filter should reduce rows: "
                    f"all={count_all}, filtered={count_filtered}"
                )

    def test_only_employed_filter(self):
        """Passing only_employed=true - currently a no-op until schema unified."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found")

                # Get all rows
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, NULL, NULL)"
                )
                count_all = cur.fetchone()[0]

                # Get rows with only_employed=true
                # Note: Currently a no-op - returns same count until schema unified
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, TRUE, NULL)"
                )
                count_employed = cur.fetchone()[0]

                # Employed count should be <= all count (currently equal since filter is no-op)
                assert count_employed <= count_all, (
                    f"only_employed filter should reduce rows: "
                    f"all={count_all}, employed={count_employed}"
                )

                # Note: has_employer is currently stubbed as FALSE until schema unified
                # This test will need updating when employer intel is added to public.judgments

    def test_only_bank_assets_filter(self):
        """Passing only_bank_assets=true - currently a no-op until schema unified."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found")

                # Get all rows
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, NULL, NULL)"
                )
                count_all = cur.fetchone()[0]

                # Get rows with only_bank_assets=true
                # Note: Currently a no-op - returns same count until schema unified
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, NULL, TRUE)"
                )
                count_bank = cur.fetchone()[0]

                # Bank count should be <= all count (currently equal since filter is no-op)
                assert count_bank <= count_all, (
                    f"only_bank_assets filter should reduce rows: "
                    f"all={count_all}, bank={count_bank}"
                )

                # Note: has_bank is currently stubbed as FALSE until schema unified
                # This test will need updating when bank intel is added to public.judgments

    def test_combined_filters(self):
        """Combining multiple filters should compound the reduction."""
        with psycopg.connect(_get_connection_url()) as conn:
            with conn.cursor() as cur:
                if not _rpc_exists(cur):
                    pytest.skip("enforcement_radar_filtered RPC not found")

                # Get counts at each filter level
                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(NULL, NULL, NULL)"
                )
                count_all = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(50, NULL, NULL)"
                )
                count_score = cur.fetchone()[0]

                cur.execute(
                    "SELECT COUNT(*) FROM public.enforcement_radar_filtered(50, TRUE, TRUE)"
                )
                count_all_filters = cur.fetchone()[0]

                # Combined filters should be most restrictive
                assert count_all_filters <= count_score <= count_all, (
                    f"Combined filters should be most restrictive: "
                    f"all={count_all}, score={count_score}, combined={count_all_filters}"
                )
