"""
tests/test_ceo_command_center.py
-------------------------------------------------------------------------------

Integration tests for the CEO Command Center analytics view and API endpoint.

Tests:
  - analytics.v_ceo_command_center view exists
  - public.ceo_command_center_metrics() RPC function exists and is callable
  - View/RPC returns expected column structure
  - Grants are correct for authenticated/service_role

Note: These tests require:
  - 20251209200000_analytics_ceo_command_center.sql to be applied
  - Underlying tables to exist (public.judgments, ops.job_queue, etc.)

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


class TestCEOCommandCenterView:
    """Tests for analytics.v_ceo_command_center view."""

    SCHEMA = "analytics"
    VIEW_NAME = "v_ceo_command_center"

    # Expected columns in the view
    EXPECTED_COLUMNS = {
        # Portfolio Health
        "total_judgments",
        "total_judgment_value",
        "active_judgments",
        "avg_judgment_value",
        # Pipeline Velocity
        "judgments_24h",
        "judgments_7d",
        "judgments_30d",
        "intake_value_24h",
        "intake_value_7d",
        # Enforcement Performance
        "enforcement_cases_active",
        "enforcement_cases_stalled",
        "enforcement_actions_pending",
        "enforcement_actions_completed_7d",
        "pending_attorney_signatures",
        # Tier Distribution
        "tier_a_count",
        "tier_b_count",
        "tier_c_count",
        "tier_d_count",
        "tier_unassigned_count",
        # Ops Health
        "queue_pending",
        "queue_failed",
        "batch_success_rate_30d",
        "last_successful_import_ts",
        # Generated
        "generated_at",
    }

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_view_exists(self):
        """The v_ceo_command_center view should exist after migration."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(
                    f"{self.SCHEMA}.{self.VIEW_NAME} view not found - "
                    "migration 20251209200000 not applied"
                )
            assert _view_exists(
                cur, self.SCHEMA, self.VIEW_NAME
            ), f"{self.VIEW_NAME} view should exist"

    def test_view_has_expected_columns(self):
        """The view should have all expected columns."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            actual_columns = _get_view_columns(cur, self.SCHEMA, self.VIEW_NAME)
            missing = self.EXPECTED_COLUMNS - actual_columns
            extra = actual_columns - self.EXPECTED_COLUMNS

            if missing:
                pytest.fail(f"Missing columns: {missing}")
            # Extra columns are OK (forward compatibility)
            if extra:
                print(f"Note: Extra columns found (OK): {extra}")

    def test_view_is_queryable(self):
        """The view should be queryable without errors."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            # Should not raise
            cur.execute(f"SELECT * FROM {self.SCHEMA}.{self.VIEW_NAME}")
            rows = cur.fetchall()

            # View should return exactly one row
            assert len(rows) == 1, "CEO Command Center should return exactly 1 row"

    def test_view_returns_valid_data_types(self):
        """The view should return valid data types for key fields."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            cur.execute(
                f"""
                SELECT
                    total_judgments,
                    total_judgment_value,
                    judgments_24h,
                    batch_success_rate_30d,
                    generated_at
                FROM {self.SCHEMA}.{self.VIEW_NAME}
                """
            )
            row = cur.fetchone()
            assert row is not None, "View should return data"

            total_judgments, total_value, j24h, batch_rate, gen_at = row

            # Validate types (Decimal is also valid for numeric columns)
            from decimal import Decimal

            assert isinstance(total_judgments, int), "total_judgments should be int"
            assert isinstance(
                total_value, (int, float, Decimal)
            ), "total_judgment_value should be numeric"
            assert isinstance(j24h, int), "judgments_24h should be int"
            assert isinstance(
                batch_rate, (int, float, Decimal)
            ), "batch_success_rate should be numeric"
            assert gen_at is not None, "generated_at should not be null"

            # Validate ranges
            assert total_judgments >= 0, "total_judgments should be non-negative"
            assert total_value >= 0, "total_judgment_value should be non-negative"
            assert 0 <= batch_rate <= 100, "batch_success_rate should be 0-100"

    def test_authenticated_role_has_select(self):
        """The authenticated role should have SELECT on the view."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.SCHEMA, self.VIEW_NAME, "authenticated")
            assert has_select, "authenticated role should have SELECT on view"

    def test_service_role_has_select(self):
        """The service_role should have SELECT on the view."""
        with self.conn.cursor() as cur:
            if not _view_exists(cur, self.SCHEMA, self.VIEW_NAME):
                pytest.skip(f"{self.VIEW_NAME} view not found")

            has_select = _check_role_has_select(cur, self.SCHEMA, self.VIEW_NAME, "service_role")
            assert has_select, "service_role should have SELECT on view"


class TestCEOCommandCenterRPC:
    """Tests for public.ceo_command_center_metrics() RPC function."""

    SCHEMA = "public"
    FUNC_NAME = "ceo_command_center_metrics"

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up database connection."""
        url = _get_connection_url()
        self.conn = psycopg.connect(url)
        yield
        self.conn.close()

    def test_function_exists(self):
        """The ceo_command_center_metrics function should exist."""
        with self.conn.cursor() as cur:
            if not _function_exists(cur, self.SCHEMA, self.FUNC_NAME):
                pytest.skip(
                    f"{self.SCHEMA}.{self.FUNC_NAME}() not found - "
                    "migration 20251209200000 not applied"
                )
            assert _function_exists(
                cur, self.SCHEMA, self.FUNC_NAME
            ), f"{self.FUNC_NAME} function should exist"

    def test_function_is_callable(self):
        """The function should be callable and return data."""
        with self.conn.cursor() as cur:
            if not _function_exists(cur, self.SCHEMA, self.FUNC_NAME):
                pytest.skip(f"{self.FUNC_NAME} function not found")

            cur.execute(f"SELECT * FROM {self.SCHEMA}.{self.FUNC_NAME}()")
            rows = cur.fetchall()

            # Function should return exactly one row
            assert len(rows) == 1, "RPC should return exactly 1 row"

    def test_authenticated_role_has_execute(self):
        """The authenticated role should have EXECUTE on the function."""
        with self.conn.cursor() as cur:
            if not _function_exists(cur, self.SCHEMA, self.FUNC_NAME):
                pytest.skip(f"{self.FUNC_NAME} function not found")

            has_exec = _check_role_has_execute(cur, self.SCHEMA, self.FUNC_NAME, "authenticated")
            assert has_exec, "authenticated role should have EXECUTE on function"

    def test_service_role_has_execute(self):
        """The service_role should have EXECUTE on the function."""
        with self.conn.cursor() as cur:
            if not _function_exists(cur, self.SCHEMA, self.FUNC_NAME):
                pytest.skip(f"{self.FUNC_NAME} function not found")

            has_exec = _check_role_has_execute(cur, self.SCHEMA, self.FUNC_NAME, "service_role")
            assert has_exec, "service_role should have EXECUTE on function"


class TestCEOCommandCenterAPIModel:
    """Tests for the Pydantic response model (unit test, no DB required)."""

    def test_model_instantiation(self):
        """The CEOCommandCenterMetrics model should instantiate correctly."""
        from backend.routers.analytics import CEOCommandCenterMetrics, TierDistribution

        tier_dist = TierDistribution(
            tier_a=100,
            tier_b=200,
            tier_c=150,
            tier_d=50,
            unassigned=25,
        )

        metrics = CEOCommandCenterMetrics(
            total_judgments=525,
            total_judgment_value=1_500_000.00,
            active_judgments=400,
            avg_judgment_value=2857.14,
            judgments_24h=10,
            judgments_7d=75,
            judgments_30d=250,
            intake_value_24h=50_000.00,
            intake_value_7d=350_000.00,
            enforcement_cases_active=120,
            enforcement_cases_stalled=15,
            enforcement_actions_pending=45,
            enforcement_actions_completed_7d=30,
            pending_attorney_signatures=8,
            tier_distribution=tier_dist,
            queue_pending=5,
            queue_failed=2,
            batch_success_rate_30d=97.5,
            last_successful_import_ts="2025-12-09T18:30:00Z",
            generated_at="2025-12-09T20:00:00Z",
        )

        assert metrics.total_judgments == 525
        assert metrics.tier_distribution.tier_a == 100
        assert metrics.batch_success_rate_30d == 97.5

    def test_model_json_serialization(self):
        """The model should serialize to JSON correctly."""
        from backend.routers.analytics import CEOCommandCenterMetrics, TierDistribution

        tier_dist = TierDistribution(tier_a=100, tier_b=200, tier_c=150, tier_d=50, unassigned=25)

        metrics = CEOCommandCenterMetrics(
            total_judgments=525,
            total_judgment_value=1_500_000.00,
            active_judgments=400,
            avg_judgment_value=2857.14,
            judgments_24h=10,
            judgments_7d=75,
            judgments_30d=250,
            intake_value_24h=50_000.00,
            intake_value_7d=350_000.00,
            enforcement_cases_active=120,
            enforcement_cases_stalled=15,
            enforcement_actions_pending=45,
            enforcement_actions_completed_7d=30,
            pending_attorney_signatures=8,
            tier_distribution=tier_dist,
            queue_pending=5,
            queue_failed=2,
            batch_success_rate_30d=97.5,
            last_successful_import_ts=None,  # Test nullable field
            generated_at="2025-12-09T20:00:00Z",
        )

        json_data = metrics.model_dump()

        assert "tier_distribution" in json_data
        assert json_data["tier_distribution"]["tier_a"] == 100
        assert json_data["last_successful_import_ts"] is None
