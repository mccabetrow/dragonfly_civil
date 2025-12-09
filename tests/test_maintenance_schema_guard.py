"""
Tests for the maintenance.schema_guard self-healing system.

Tests the backend/maintenance/schema_guard module:
- Drift detection works correctly
- No false positives on healthy schema
- Repair triggers fire appropriately
- Scheduler job is registered

Additionally, contains DATA CONTRACT tests for critical tables and views:
- enforcement.enforcement_plans (id, judgment_id, status)
- ops.ingest_batches (id, status, row_count_valid)
- ops.v_intake_monitor (view existence)
- finance.v_portfolio_stats (view existence)

Note: This tests the BACKEND scheduler-based schema guard,
      not the tools/schema_guard.py catalog-based system.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
import pytest

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Check if backend.maintenance is importable (requires psycopg_pool which may not be installed locally)
try:
    from backend.maintenance import SchemaGuard  # noqa: F401

    BACKEND_MAINTENANCE_AVAILABLE = True
except ImportError:
    BACKEND_MAINTENANCE_AVAILABLE = False

# Skip decorator for tests that require backend.maintenance
requires_backend_maintenance = pytest.mark.skipif(
    not BACKEND_MAINTENANCE_AVAILABLE,
    reason="backend.maintenance requires psycopg_pool (Railway dependencies)",
)


@requires_backend_maintenance
class TestMaintenanceSchemaGuard:
    """Test the backend maintenance SchemaGuard class."""

    @pytest.fixture
    def mock_settings(self):
        """Mock settings for testing."""
        settings = MagicMock()
        settings.discord_webhook_url = "https://discord.com/test"
        return settings

    @pytest.fixture
    def mock_connection(self):
        """Mock database connection."""

        async def async_gen():
            conn = AsyncMock()
            yield conn

        return async_gen

    @pytest.mark.asyncio
    async def test_schema_guard_imports(self, mock_settings):
        """Test that SchemaGuard can be imported."""
        with patch("backend.maintenance.schema_guard.get_settings", return_value=mock_settings):
            from backend.maintenance.schema_guard import SchemaGuard

            guard = SchemaGuard()
            assert guard is not None

    @pytest.mark.asyncio
    async def test_check_and_repair_returns_dict(self, mock_settings, mock_connection):
        """Test that check_and_repair returns properly structured dict."""
        with (
            patch("backend.maintenance.schema_guard.get_settings", return_value=mock_settings),
            patch(
                "backend.maintenance.schema_guard.get_connection",
                return_value=mock_connection(),
            ),
        ):
            from backend.maintenance.schema_guard import SchemaGuard

            guard = SchemaGuard()

            # Mock to return no drift
            guard.check_schema_drift = AsyncMock(return_value=False)

            result = await guard.check_and_repair()

            # Should return a dict with expected keys
            assert isinstance(result, dict)
            assert "drift_detected" in result
            assert "repair_triggered" in result
            assert "checked_at" in result

    @pytest.mark.asyncio
    async def test_repair_triggers_on_drift(self, mock_settings, mock_connection):
        """Test that repair is triggered when drift is detected."""
        with (
            patch("backend.maintenance.schema_guard.get_settings", return_value=mock_settings),
            patch(
                "backend.maintenance.schema_guard.get_connection",
                return_value=mock_connection(),
            ),
        ):
            from backend.maintenance.schema_guard import SchemaGuard

            guard = SchemaGuard()

            # Mock check_schema_drift to return True (drift detected)
            guard.check_schema_drift = AsyncMock(return_value=True)
            guard.get_detailed_drift = AsyncMock(return_value="Mock drift details")
            guard._execute_repair = AsyncMock(
                return_value={"success": True, "files_executed": ["test.sql"]}
            )
            guard._send_alert = AsyncMock()

            result = await guard.check_and_repair()

            assert result["drift_detected"] is True
            assert result["repair_triggered"] is True
            guard._execute_repair.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_repair_when_no_drift(self, mock_settings, mock_connection):
        """Test that repair is NOT triggered when no drift detected."""
        with (
            patch("backend.maintenance.schema_guard.get_settings", return_value=mock_settings),
            patch(
                "backend.maintenance.schema_guard.get_connection",
                return_value=mock_connection(),
            ),
        ):
            from backend.maintenance.schema_guard import SchemaGuard

            guard = SchemaGuard()

            # Mock no drift
            guard.check_schema_drift = AsyncMock(return_value=False)
            guard._execute_repair = AsyncMock()

            result = await guard.check_and_repair()

            assert result["drift_detected"] is False
            assert result["repair_triggered"] is False
            guard._execute_repair.assert_not_called()


class TestSchemaRepairRunner:
    """Test the run_schema_repair module."""

    def test_repair_files_exist(self):
        """Test that repair SQL files exist in the recovery directory."""
        from pathlib import Path

        recovery_dir = Path(__file__).parent.parent / "supabase" / "recovery"

        expected_files = [
            "core_schema_repair.sql",
            "ops_intake_schema_repair.sql",
            "enforcement_schema_repair.sql",
        ]

        for filename in expected_files:
            file_path = recovery_dir / filename
            assert file_path.exists(), f"Recovery file missing: {filename}"

    def test_repair_module_imports(self):
        """Test that run_schema_repair module can be imported."""
        from tools import run_schema_repair

        assert hasattr(run_schema_repair, "run_repair")
        assert hasattr(run_schema_repair, "execute_sql_file")


@requires_backend_maintenance
class TestSchedulerSchemaGuardJob:
    """Test scheduler integration of schema_guard job."""

    def test_schema_guard_job_function_exists(self):
        """Test that the schema_guard_job function exists in scheduler."""
        from backend.scheduler import schema_guard_job

        assert callable(schema_guard_job)

    @pytest.mark.asyncio
    async def test_schema_guard_job_handles_errors_gracefully(self):
        """Test that the job doesn't crash on errors."""
        with patch(
            "backend.maintenance.check_and_repair",
            new=AsyncMock(side_effect=Exception("Test error")),
        ):
            from backend.scheduler import schema_guard_job

            # Should NOT raise - job should catch and log errors
            await schema_guard_job()

    @pytest.mark.asyncio
    async def test_schema_guard_job_runs_successfully(self):
        """Test that the job runs when check_and_repair succeeds."""
        mock_result: dict[str, Any] = {
            "drift_detected": False,
            "repair_triggered": False,
            "repair_result": None,
            "error": None,
        }

        with patch(
            "backend.maintenance.check_and_repair",
            new=AsyncMock(return_value=mock_result),
        ):
            from backend.scheduler import schema_guard_job

            # Should run without error
            await schema_guard_job()

    def test_register_jobs_includes_schema_guard(self):
        """Test that _register_jobs includes schema_guard job."""
        import inspect

        from backend.scheduler import _register_jobs

        source = inspect.getsource(_register_jobs)

        assert "schema_guard_job" in source
        assert 'id="schema_guard"' in source
        assert "IntervalTrigger(minutes=15)" in source


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CONTRACT TESTS
# ═══════════════════════════════════════════════════════════════════════════════
#
# These tests enforce strict schema contracts to prevent Dev/Prod drift.
# If any column or view is missing, CI fails loudly.
# ═══════════════════════════════════════════════════════════════════════════════


def _get_connection_url() -> str:
    """Return the database connection URL for the current environment."""
    env = get_supabase_env()
    return get_supabase_db_url(env)


def _table_exists(cur: psycopg.Cursor, schema: str, table_name: str) -> bool:
    """Check if a table exists in the given schema."""
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = %s
          AND table_type = 'BASE TABLE'
        """,
        (schema, table_name),
    )
    return cur.fetchone() is not None


def _view_exists(cur: psycopg.Cursor, schema: str, view_name: str) -> bool:
    """Check if a view exists in the given schema."""
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


def _get_table_columns(cur: psycopg.Cursor, schema: str, table_name: str) -> set[str]:
    """Return the set of column names for a table."""
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        (schema, table_name),
    )
    return {row[0] for row in cur.fetchall()}


@pytest.mark.integration
class TestSchemaDataContracts:
    """
    Hard schema contract tests.

    These tests verify that critical tables and views exist with the
    expected columns. Failures here indicate Dev/Prod schema drift
    that must be fixed before deployment.
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Table: enforcement.enforcement_plans
    # ─────────────────────────────────────────────────────────────────────────

    def test_enforcement_plans_table_exists(self):
        """Verify enforcement.enforcement_plans table exists."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                exists = _table_exists(cur, "enforcement", "enforcement_plans")
                assert exists, (
                    "Table enforcement.enforcement_plans does not exist. "
                    "Run migrations to create it."
                )

    def test_enforcement_plans_required_columns(self):
        """Verify enforcement.enforcement_plans has required columns."""
        # Canonical columns per 20251209_promote_enforcement_to_prod.sql
        required_columns = {"id", "case_id", "plan_status"}

        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                actual_columns = _get_table_columns(cur, "enforcement", "enforcement_plans")

        missing = required_columns - actual_columns
        assert not missing, (
            f"enforcement.enforcement_plans missing required columns: {missing}. "
            "Schema contract violation - check migrations."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Table: ops.ingest_batches
    # ─────────────────────────────────────────────────────────────────────────

    def test_ops_ingest_batches_table_exists(self):
        """Verify ops.ingest_batches table exists."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                exists = _table_exists(cur, "ops", "ingest_batches")
                assert exists, (
                    "Table ops.ingest_batches does not exist. " "Run migrations to create it."
                )

    def test_ops_ingest_batches_required_columns(self):
        """Verify ops.ingest_batches has required columns."""
        required_columns = {"id", "status", "row_count_valid"}

        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                actual_columns = _get_table_columns(cur, "ops", "ingest_batches")

        missing = required_columns - actual_columns
        assert not missing, (
            f"ops.ingest_batches missing required columns: {missing}. "
            "Schema contract violation - check migrations."
        )

    # ─────────────────────────────────────────────────────────────────────────
    # View: ops.v_intake_monitor
    # ─────────────────────────────────────────────────────────────────────────

    def test_ops_v_intake_monitor_exists(self):
        """Verify ops.v_intake_monitor view exists."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                exists = _view_exists(cur, "ops", "v_intake_monitor")
                assert exists, (
                    "View ops.v_intake_monitor does not exist. " "Run migrations to create it."
                )

    # ─────────────────────────────────────────────────────────────────────────
    # View: finance.v_portfolio_stats
    # ─────────────────────────────────────────────────────────────────────────

    def test_finance_v_portfolio_stats_exists(self):
        """Verify finance.v_portfolio_stats view exists."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                exists = _view_exists(cur, "finance", "v_portfolio_stats")
                assert exists, (
                    "View finance.v_portfolio_stats does not exist. " "Run migrations to create it."
                )

    def test_finance_v_portfolio_stats_queryable(self):
        """Verify finance.v_portfolio_stats can be queried without error."""
        url = _get_connection_url()
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                # This will raise if the view is broken or has missing deps
                cur.execute("SELECT COUNT(*) FROM finance.v_portfolio_stats")
                row = cur.fetchone()
                assert row is not None, "Query returned no rows"
                # Count can be zero - that's fine, view just needs to be queryable
