"""
Tests for the maintenance.schema_guard self-healing system.

Tests the backend/maintenance/schema_guard module:
- Drift detection works correctly
- No false positives on healthy schema
- Repair triggers fire appropriately
- Scheduler job is registered

Note: This tests the BACKEND scheduler-based schema guard,
      not the tools/schema_guard.py catalog-based system.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
