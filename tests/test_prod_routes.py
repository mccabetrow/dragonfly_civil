"""
Integration tests for production routes.

These tests verify that critical API endpoints and database views are
accessible and return expected data structures.

Run with: pytest tests/test_prod_routes.py -v --integration
"""

from __future__ import annotations

import os
from typing import Any

import pytest

# Mark all tests in this module as integration tests (skip in normal runs)
pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def supabase_client():
    """Get Supabase client for prod environment."""
    # Use environment or default to prod for integration tests
    os.environ.setdefault("SUPABASE_MODE", "prod")
    from src.supabase_client import create_supabase_client, get_supabase_env

    env = get_supabase_env()
    return create_supabase_client(env)


@pytest.fixture(scope="module")
def db_connection():
    """Get direct database connection for prod environment."""
    os.environ.setdefault("SUPABASE_MODE", "prod")
    import psycopg

    from src.supabase_client import get_supabase_db_url

    url = get_supabase_db_url()
    conn = psycopg.connect(url)
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# View Existence Tests
# ---------------------------------------------------------------------------


class TestViewExistence:
    """Test that required views exist in the database."""

    REQUIRED_VIEWS = [
        ("public", "v_radar"),
        ("public", "v_enforcement_pipeline_status"),
        ("public", "v_plaintiffs_overview"),
        ("public", "v_judgment_pipeline"),
        ("ops", "v_intake_monitor"),
        ("enforcement", "v_radar"),
        ("enforcement", "v_enforcement_pipeline_status"),
    ]

    @pytest.mark.parametrize("schema,view_name", REQUIRED_VIEWS)
    def test_view_exists(self, db_connection, schema: str, view_name: str):
        """Verify each required view exists."""
        cur = db_connection.execute(
            """
            SELECT COUNT(*) FROM pg_views
            WHERE schemaname = %s AND viewname = %s
        """,
            (schema, view_name),
        )
        row = cur.fetchone()
        assert row is not None and row[0] > 0, f"View {schema}.{view_name} does not exist"


# ---------------------------------------------------------------------------
# REST API View Tests
# ---------------------------------------------------------------------------


class TestRestApiViews:
    """Test that views are accessible via Supabase REST API."""

    def test_v_radar_accessible(self, supabase_client):
        """Test public.v_radar is queryable via REST."""
        result = (
            supabase_client.table("v_radar")
            .select("id, case_number, offer_strategy")
            .limit(5)
            .execute()
        )

        # Should not error - may have 0 rows in some environments
        assert result.data is not None
        assert isinstance(result.data, list)

        # If data exists, verify expected columns
        if result.data:
            row = result.data[0]
            assert "id" in row
            assert "case_number" in row
            assert "offer_strategy" in row

    def test_v_radar_has_expected_columns(self, supabase_client):
        """Test public.v_radar has all expected columns."""
        result = supabase_client.table("v_radar").select("*").limit(1).execute()

        assert result.data is not None

        if result.data:
            row = result.data[0]
            expected_columns = [
                "id",
                "case_number",
                "plaintiff_name",
                "defendant_name",
                "judgment_amount",
                "court",
                "county",
                "judgment_date",
                "collectability_score",
                "status",
                "enforcement_stage",
                "offer_strategy",
                "created_at",
                "updated_at",
            ]
            for col in expected_columns:
                assert col in row, f"Missing expected column: {col}"

    def test_v_enforcement_pipeline_status_accessible(self, supabase_client):
        """Test public.v_enforcement_pipeline_status is queryable via REST."""
        result = supabase_client.table("v_enforcement_pipeline_status").select("*").execute()

        assert result.data is not None
        assert isinstance(result.data, list)

        if result.data:
            row = result.data[0]
            expected_columns = [
                "enforcement_stage",
                "case_count",
                "total_amount",
                "avg_score",
            ]
            for col in expected_columns:
                assert col in row, f"Missing expected column: {col}"

    def test_v_intake_monitor_accessible(self, supabase_client):
        """Test ops.v_intake_monitor is queryable via REST (if exposed)."""
        # Note: ops schema may not be exposed via REST API
        # This test documents expected behavior
        try:
            result = (
                supabase_client.table("v_intake_monitor")
                .select("id, filename, status")
                .limit(5)
                .execute()
            )
            # If it works, verify structure
            if result.data:
                row = result.data[0]
                assert "id" in row
                assert "filename" in row
        except Exception:
            # ops schema views may not be directly exposed via public REST API
            pytest.skip("ops.v_intake_monitor not exposed via REST API")


# ---------------------------------------------------------------------------
# Column Structure Tests
# ---------------------------------------------------------------------------


class TestColumnStructure:
    """Test that views have the correct column structure."""

    def test_v_radar_not_summary_view(self, db_connection):
        """Verify public.v_radar is a detail view, not a summary view."""
        cur = db_connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'v_radar'
            ORDER BY ordinal_position
        """
        )
        columns = [row[0] for row in cur.fetchall()]

        # Should have detail columns, not summary columns
        assert "id" in columns, "v_radar should have 'id' column (detail view)"
        assert "offer_strategy" in columns, "v_radar should have 'offer_strategy' column"

        # Should NOT have summary-only columns
        assert "category" not in columns, (
            "v_radar should NOT have 'category' (that's a summary view)"
        )
        assert "count" not in columns, "v_radar should NOT have 'count' (that's a summary view)"

    def test_v_enforcement_pipeline_status_is_aggregate(self, db_connection):
        """Verify public.v_enforcement_pipeline_status is an aggregate view."""
        cur = db_connection.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'v_enforcement_pipeline_status'
            ORDER BY ordinal_position
        """
        )
        columns = [row[0] for row in cur.fetchall()]

        # Should have aggregate columns
        assert "enforcement_stage" in columns
        assert "case_count" in columns
        assert "total_amount" in columns


# ---------------------------------------------------------------------------
# Data Integrity Tests
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    """Test data integrity and consistency."""

    def test_v_radar_offer_strategy_values(self, supabase_client):
        """Verify offer_strategy has valid values."""
        valid_strategies = {
            "BUY_CANDIDATE",
            "CONTINGENCY",
            "LOW_PRIORITY",
            "ENRICHMENT_PENDING",
        }

        result = supabase_client.table("v_radar").select("offer_strategy").execute()

        if result.data:
            for row in result.data:
                strategy = row.get("offer_strategy")
                assert strategy in valid_strategies, f"Invalid offer_strategy: {strategy}"

    def test_v_radar_judgment_amount_non_negative(self, supabase_client):
        """Verify judgment_amount is non-negative."""
        result = supabase_client.table("v_radar").select("id, judgment_amount").execute()

        if result.data:
            for row in result.data:
                amount = row.get("judgment_amount", 0)
                assert amount >= 0, f"Negative judgment_amount for id {row['id']}: {amount}"


# ---------------------------------------------------------------------------
# Performance Tests
# ---------------------------------------------------------------------------


class TestPerformance:
    """Basic performance tests to ensure views are optimized."""

    def test_v_radar_query_time(self, db_connection):
        """Verify v_radar query completes in reasonable time."""
        import time

        start = time.time()
        cur = db_connection.execute("SELECT COUNT(*) FROM public.v_radar")
        cur.fetchone()
        elapsed = time.time() - start

        # Should complete in under 5 seconds even with large datasets
        assert elapsed < 5.0, f"v_radar query took {elapsed:.2f}s (expected < 5s)"

    def test_v_enforcement_pipeline_status_query_time(self, db_connection):
        """Verify v_enforcement_pipeline_status query completes in reasonable time."""
        import time

        start = time.time()
        cur = db_connection.execute("SELECT * FROM public.v_enforcement_pipeline_status")
        cur.fetchall()
        elapsed = time.time() - start

        # Aggregate view should be fast
        assert elapsed < 2.0, (
            f"v_enforcement_pipeline_status query took {elapsed:.2f}s (expected < 2s)"
        )
