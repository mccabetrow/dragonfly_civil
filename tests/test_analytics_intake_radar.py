"""
tests/test_analytics_intake_radar.py
-------------------------------------------------------------------------------

Unit and integration tests for the Intake Radar analytics feature (v2).

Tests:
  1. Unit: IntakeRadarMetrics Pydantic model serialization
  2. Integration: View exists, RPC callable, grants correct
  3. Integration: Seed data and verify metrics match

Requires:
  - Migration 20251209220000_analytics_intake_radar_v2.sql to be applied
  - Underlying tables: public.judgments, ops.ingest_batches, ops.job_queue

Strategy:
  - If view doesn't exist → pytest.skip (migration not yet applied)
  - If DB unavailable → pytest.skip (no connection)

DUAL-CONNECTION PATTERN (Zero Trust):
  - admin_db: Used for test setup (INSERT seed data) and verification
  - app_db: Used for testing application-level queries (view/RPC access)

NOTE: Marked as integration because these tests require analytics schema
      with grants applied - may not be fully deployed to prod.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

# Mark entire module as integration - requires analytics schema with grants
pytestmark = pytest.mark.integration

# =============================================================================
# Helper Functions
# =============================================================================


def _view_exists(cur: psycopg.Cursor, schema: str, view_name: str) -> bool:
    """Check if a view exists in the specified schema."""
    cur.execute(
        """
        SELECT 1
        FROM pg_views
        WHERE schemaname = %s
          AND viewname = %s
        """,
        (schema, view_name),
    )
    return cur.fetchone() is not None


def _function_exists(cur: psycopg.Cursor, schema: str, func_name: str) -> bool:
    """Check if a function exists in the specified schema."""
    cur.execute(
        """
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = %s
          AND p.proname = %s
        """,
        (schema, func_name),
    )
    return cur.fetchone() is not None


def _get_view_columns(cur: psycopg.Cursor, schema: str, view_name: str) -> set[str]:
    """Get the column names of a view."""
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        (schema, view_name),
    )
    return {row[0] for row in cur.fetchall()}


def _check_role_has_select(cur: psycopg.Cursor, schema: str, view_name: str, role: str) -> bool:
    """Check if a role has SELECT privilege on a view."""
    cur.execute(
        f"""
        SELECT has_table_privilege(%s, '{schema}.{view_name}', 'SELECT')
        """,
        (role,),
    )
    result = cur.fetchone()
    return result[0] if result else False


def _check_role_has_execute(cur: psycopg.Cursor, schema: str, func_name: str, role: str) -> bool:
    """Check if a role has EXECUTE privilege on a function."""
    cur.execute(
        f"""
        SELECT has_function_privilege(%s, '{schema}.{func_name}()', 'EXECUTE')
        """,
        (role,),
    )
    result = cur.fetchone()
    return result[0] if result else False


# =============================================================================
# UNIT TESTS: Pydantic Model Serialization
# =============================================================================

# Define a local copy of the model for unit testing to avoid import chain issues
# with backend.db dependencies (psycopg_pool, etc.)
from pydantic import BaseModel


class IntakeRadarMetricsLocal(BaseModel):
    """Local copy of IntakeRadarMetrics for unit testing."""

    judgments_ingested_24h: int
    judgments_ingested_7d: int
    new_aum_24h: float
    validity_rate_24h: float
    queue_depth_pending: int
    critical_failures_24h: int
    avg_processing_time_seconds: float


class TestIntakeRadarMetricsModel:
    """Unit tests for IntakeRadarMetrics Pydantic model."""

    def test_model_serialization_default_values(self) -> None:
        """Test that the model serializes with default/zero values."""
        metrics = IntakeRadarMetricsLocal(
            judgments_ingested_24h=0,
            judgments_ingested_7d=0,
            new_aum_24h=0.0,
            validity_rate_24h=100.0,
            queue_depth_pending=0,
            critical_failures_24h=0,
            avg_processing_time_seconds=0.0,
        )

        # Serialize to dict
        data = metrics.model_dump()

        assert data["judgments_ingested_24h"] == 0
        assert data["judgments_ingested_7d"] == 0
        assert data["new_aum_24h"] == 0.0
        assert data["validity_rate_24h"] == 100.0
        assert data["queue_depth_pending"] == 0
        assert data["critical_failures_24h"] == 0
        assert data["avg_processing_time_seconds"] == 0.0

    def test_model_serialization_with_real_values(self) -> None:
        """Test model serializes correctly with realistic values."""
        metrics = IntakeRadarMetricsLocal(
            judgments_ingested_24h=42,
            judgments_ingested_7d=187,
            new_aum_24h=1_234_567.89,
            validity_rate_24h=98.5,
            queue_depth_pending=5,
            critical_failures_24h=2,
            avg_processing_time_seconds=12.34,
        )

        data = metrics.model_dump()

        assert data["judgments_ingested_24h"] == 42
        assert data["judgments_ingested_7d"] == 187
        assert data["new_aum_24h"] == 1_234_567.89
        assert data["validity_rate_24h"] == 98.5
        assert data["queue_depth_pending"] == 5
        assert data["critical_failures_24h"] == 2
        assert data["avg_processing_time_seconds"] == 12.34

    def test_model_json_serialization(self) -> None:
        """Test model serializes to JSON correctly."""
        metrics = IntakeRadarMetricsLocal(
            judgments_ingested_24h=10,
            judgments_ingested_7d=50,
            new_aum_24h=99999.99,
            validity_rate_24h=95.0,
            queue_depth_pending=3,
            critical_failures_24h=1,
            avg_processing_time_seconds=5.5,
        )

        json_str = metrics.model_dump_json()

        assert '"judgments_ingested_24h":10' in json_str
        assert '"judgments_ingested_7d":50' in json_str
        assert '"new_aum_24h":99999.99' in json_str
        assert '"validity_rate_24h":95.0' in json_str

    def test_model_required_fields(self) -> None:
        """Test that all fields are required (no Optional)."""
        # Missing required field should raise ValidationError
        with pytest.raises(Exception):  # Pydantic ValidationError
            IntakeRadarMetricsLocal(
                judgments_ingested_24h=10,
                # Missing other fields
            )  # type: ignore[call-arg]


# =============================================================================
# INTEGRATION TESTS: View and RPC Existence
# =============================================================================


class TestIntakeRadarViewExists:
    """Integration tests for analytics.v_intake_radar view existence."""

    def test_view_exists(self, admin_db: psycopg.Connection) -> None:
        """Test that analytics.v_intake_radar view exists."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View analytics.v_intake_radar not found - migration not applied")
            # View exists - test passes
            assert True

    def test_view_has_expected_columns(self, admin_db: psycopg.Connection) -> None:
        """Test that view has all expected columns from v2 spec."""
        expected_columns = {
            "judgments_ingested_24h",
            "judgments_ingested_7d",
            "new_aum_24h",
            "validity_rate_24h",
            "queue_depth_pending",
            "critical_failures_24h",
            "avg_processing_time_seconds",
        }

        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found - migration not applied")

            actual_columns = _get_view_columns(cur, "analytics", "v_intake_radar")

            # Check all expected columns exist
            missing = expected_columns - actual_columns
            assert not missing, f"Missing columns: {missing}"

    def test_rpc_function_exists(self, admin_db: psycopg.Connection) -> None:
        """Test that intake_radar_metrics_v2 RPC function exists."""
        with admin_db.cursor() as cur:
            if not _function_exists(cur, "public", "intake_radar_metrics_v2"):
                pytest.skip("Function intake_radar_metrics_v2 not found")
            assert True


class TestIntakeRadarGrants:
    """Integration tests for view and RPC grants."""

    def test_view_grants_authenticated(self, admin_db: psycopg.Connection) -> None:
        """Test that authenticated role has SELECT on view."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found")

            has_select = _check_role_has_select(cur, "analytics", "v_intake_radar", "authenticated")
            assert has_select, "authenticated role should have SELECT on analytics.v_intake_radar"

    def test_view_grants_service_role(self, admin_db: psycopg.Connection) -> None:
        """Test that service_role has SELECT on view."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found")

            has_select = _check_role_has_select(cur, "analytics", "v_intake_radar", "service_role")
            assert has_select, "service_role should have SELECT on analytics.v_intake_radar"

    def test_rpc_grants_authenticated(self, admin_db: psycopg.Connection) -> None:
        """Test that authenticated role has EXECUTE on RPC function."""
        with admin_db.cursor() as cur:
            if not _function_exists(cur, "public", "intake_radar_metrics_v2"):
                pytest.skip("Function not found")

            has_exec = _check_role_has_execute(
                cur, "public", "intake_radar_metrics_v2", "authenticated"
            )
            assert has_exec, "authenticated should have EXECUTE on intake_radar_metrics_v2"


# =============================================================================
# INTEGRATION TESTS: View Query and Data Validation
# =============================================================================


class TestIntakeRadarViewQuery:
    """Integration tests for querying the view."""

    def test_view_returns_exactly_one_row(self, admin_db: psycopg.Connection) -> None:
        """Test that view returns exactly one row (aggregated)."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found")

            cur.execute("SELECT * FROM analytics.v_intake_radar")
            rows = cur.fetchall()

            assert len(rows) == 1, f"Expected exactly 1 row, got {len(rows)}"

    def test_view_returns_no_nulls(self, admin_db: psycopg.Connection) -> None:
        """Test that all columns have COALESCE'd values (no NULLs)."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found")

            cur.execute(
                """
                SELECT
                    judgments_ingested_24h IS NULL AS n1,
                    judgments_ingested_7d IS NULL AS n2,
                    new_aum_24h IS NULL AS n3,
                    validity_rate_24h IS NULL AS n4,
                    queue_depth_pending IS NULL AS n5,
                    critical_failures_24h IS NULL AS n6,
                    avg_processing_time_seconds IS NULL AS n7
                FROM analytics.v_intake_radar
            """
            )
            row = cur.fetchone()

            assert row is not None, "View returned no rows"
            nulls = [i for i, is_null in enumerate(row) if is_null]
            assert not nulls, f"Columns at positions {nulls} have NULL values"

    def test_rpc_returns_same_as_view(self, admin_db: psycopg.Connection) -> None:
        """Test that RPC function returns same data as direct view query."""
        with admin_db.cursor() as cur:
            if not _view_exists(cur, "analytics", "v_intake_radar"):
                pytest.skip("View not found")
            if not _function_exists(cur, "public", "intake_radar_metrics_v2"):
                pytest.skip("Function not found")

            # Query view directly
            cur.execute("SELECT * FROM analytics.v_intake_radar")
            view_row = cur.fetchone()

            # Query via RPC
            cur.execute("SELECT * FROM public.intake_radar_metrics_v2()")
            rpc_row = cur.fetchone()

            assert view_row == rpc_row, "RPC should return same data as view"


# =============================================================================
# INTEGRATION TESTS: Seeded Data Validation
# =============================================================================


class TestIntakeRadarWithSeededData:
    """
    Integration tests that seed test data and verify metrics.

    These tests use admin_db fixture for INSERT operations (seeding),
    then query the view to verify metrics. Uses savepoints to rollback
    and avoid polluting the database.

    Zero Trust Pattern:
      - admin_db: Superuser connection for INSERT/UPDATE/DELETE
      - Savepoints ensure cleanup even on test failure
    """

    def test_judgments_24h_count_matches_seeded_data(self, admin_db: psycopg.Connection) -> None:
        """
        Seed judgments in last 24h and verify count matches.

        Strategy:
          1. Start savepoint (will rollback)
          2. Insert N judgments with created_at = now() (within 24h)
          3. Insert M judgments with created_at = 2 days ago (outside 24h)
          4. Query view and assert judgments_ingested_24h >= N
          5. Rollback savepoint
        """
        cur = admin_db.cursor()

        if not _view_exists(cur, "analytics", "v_intake_radar"):
            pytest.skip("View analytics.v_intake_radar not found")

        # Get baseline count
        cur.execute("SELECT judgments_ingested_24h FROM analytics.v_intake_radar")
        baseline_row = cur.fetchone()
        baseline_count = baseline_row[0] if baseline_row else 0

        # Start savepoint for rollback
        cur.execute("SAVEPOINT test_seed")

        try:
            # Insert 5 judgments within 24h
            test_case_prefix = f"TEST-INTAKE-{uuid4().hex[:8]}"
            for i in range(5):
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number, judgment_amount, status, created_at
                    ) VALUES (
                        %s, %s, 'active', NOW()
                    )
                    """,
                    (f"{test_case_prefix}-{i}", 1000.00 + i),
                )

            # Insert 3 judgments outside 24h (2 days ago)
            for i in range(3):
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number, judgment_amount, status, created_at
                    ) VALUES (
                        %s, %s, 'active', NOW() - INTERVAL '2 days'
                    )
                    """,
                    (f"{test_case_prefix}-OLD-{i}", 2000.00 + i),
                )

            # Query view
            cur.execute("SELECT judgments_ingested_24h FROM analytics.v_intake_radar")
            result_row = cur.fetchone()
            new_count = result_row[0] if result_row else 0

            # Assert at least 5 more than baseline
            assert (
                new_count >= baseline_count + 5
            ), f"Expected at least {baseline_count + 5} judgments_24h, got {new_count}"

        finally:
            # Rollback to avoid polluting database
            cur.execute("ROLLBACK TO SAVEPOINT test_seed")

    def test_new_aum_24h_sums_correctly(self, admin_db: psycopg.Connection) -> None:
        """
        Seed judgments with known amounts and verify new_aum_24h sum.
        """
        cur = admin_db.cursor()

        if not _view_exists(cur, "analytics", "v_intake_radar"):
            pytest.skip("View analytics.v_intake_radar not found")

        # Get baseline AUM
        cur.execute("SELECT new_aum_24h FROM analytics.v_intake_radar")
        baseline_row = cur.fetchone()
        baseline_aum = float(baseline_row[0]) if baseline_row else 0.0

        cur.execute("SAVEPOINT test_aum")

        try:
            # Insert judgments with known amounts
            test_amounts = [10000.00, 25000.50, 5000.25]
            test_case_prefix = f"TEST-AUM-{uuid4().hex[:8]}"

            for i, amount in enumerate(test_amounts):
                cur.execute(
                    """
                    INSERT INTO public.judgments (
                        case_number, judgment_amount, status, created_at
                    ) VALUES (
                        %s, %s, 'active', NOW()
                    )
                    """,
                    (f"{test_case_prefix}-{i}", amount),
                )

            expected_sum = sum(test_amounts)

            # Query view
            cur.execute("SELECT new_aum_24h FROM analytics.v_intake_radar")
            result_row = cur.fetchone()
            new_aum = float(result_row[0]) if result_row else 0.0

            # Assert AUM increased by at least our seeded amount
            delta = new_aum - baseline_aum
            assert (
                delta >= expected_sum - 0.01
            ), f"Expected AUM increase of at least {expected_sum}, got {delta}"

        finally:
            cur.execute("ROLLBACK TO SAVEPOINT test_aum")
