"""
Tests for degraded mode and DB readiness gating.

These tests verify:
1. API boots without DB env (DB_READY false, /health 200, /readyz 503)
2. API does not sys.exit on auth failure patterns (degraded mode)
3. Worker still exits on auth failure (kill-switch semantics)
4. Background DB supervisor respects polite backoff
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.db_state import (
    DBReadinessState,
    DBSupervisor,
    ProcessRole,
    calculate_backoff_delay,
    db_state,
    detect_process_role,
)


class TestProcessRoleDetection:
    """Test process role detection from env and entrypoint."""

    def test_explicit_api_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PROCESS_ROLE=api should return API role."""
        monkeypatch.setenv("PROCESS_ROLE", "api")
        assert detect_process_role() == ProcessRole.API

    def test_explicit_worker_role(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PROCESS_ROLE=worker should return WORKER role."""
        monkeypatch.setenv("PROCESS_ROLE", "worker")
        assert detect_process_role() == ProcessRole.WORKER

    def test_legacy_worker_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WORKER_MODE=true should return WORKER role."""
        monkeypatch.delenv("PROCESS_ROLE", raising=False)
        monkeypatch.setenv("WORKER_MODE", "true")
        assert detect_process_role() == ProcessRole.WORKER

    def test_entrypoint_heuristic_worker(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Script name containing 'worker' should return WORKER role."""
        monkeypatch.delenv("PROCESS_ROLE", raising=False)
        monkeypatch.delenv("WORKER_MODE", raising=False)
        monkeypatch.setattr(sys, "argv", ["ingest_worker.py"])
        assert detect_process_role() == ProcessRole.WORKER

    def test_default_is_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default (no env, no worker script) should return API role."""
        monkeypatch.delenv("PROCESS_ROLE", raising=False)
        monkeypatch.delenv("WORKER_MODE", raising=False)
        monkeypatch.setattr(sys, "argv", ["uvicorn", "backend.main:app"])
        assert detect_process_role() == ProcessRole.API


class TestDBReadinessState:
    """Test DBReadinessState tracking."""

    def test_initial_state_not_ready(self) -> None:
        """Initial state should be not ready."""
        state = DBReadinessState()
        assert state.ready is False
        assert state.healthy is False
        assert state.initialized is False

    def test_mark_connected(self) -> None:
        """mark_connected should set ready=True."""
        state = DBReadinessState()
        state.mark_connected(init_duration_ms=150.0)
        assert state.ready is True
        assert state.healthy is True
        assert state.initialized is True
        assert state.last_error is None
        assert state.consecutive_failures == 0
        assert state.init_duration_ms == 150.0

    def test_mark_failed(self) -> None:
        """mark_failed should set ready=False with metadata."""
        state = DBReadinessState()
        state.mark_failed("Connection refused", "network", 30.0)
        assert state.ready is False
        assert state.healthy is False
        assert state.last_error == "Connection refused"
        assert state.last_error_class == "network"
        assert state.consecutive_failures == 1
        assert state.next_retry_ts is not None

    def test_consecutive_failures_increment(self) -> None:
        """Multiple failures should increment consecutive_failures."""
        state = DBReadinessState()
        state.mark_failed("Error 1", "network", 5.0)
        state.mark_failed("Error 2", "network", 10.0)
        state.mark_failed("Error 3", "network", 15.0)
        assert state.consecutive_failures == 3

    def test_mark_connected_resets_failures(self) -> None:
        """mark_connected should reset consecutive_failures."""
        state = DBReadinessState()
        state.mark_failed("Error", "network", 5.0)
        state.mark_failed("Error", "network", 10.0)
        assert state.consecutive_failures == 2
        state.mark_connected(100.0)
        assert state.consecutive_failures == 0

    def test_operator_status_ready(self) -> None:
        """operator_status should return clean format when ready."""
        state = DBReadinessState()
        state.mark_connected(100.0)
        assert state.operator_status() == "[DB] READY=true"

    def test_operator_status_not_ready(self) -> None:
        """operator_status should include reason and retry when not ready."""
        state = DBReadinessState()
        state.mark_failed("Auth error", "auth_failure", 900.0)
        status = state.operator_status()
        assert "[DB] READY=false" in status
        assert "reason=auth_failure" in status
        assert "next_retry_in=" in status

    def test_readiness_metadata(self) -> None:
        """readiness_metadata should return dict for /readyz response."""
        state = DBReadinessState()
        state.mark_failed("Timeout", "network", 60.0)
        metadata = state.readiness_metadata()
        assert metadata["ready"] is False
        assert metadata["last_error"] == "Timeout"
        assert metadata["last_error_class"] == "network"
        assert metadata["consecutive_failures"] == 1


class TestBackoffCalculation:
    """Test backoff delay calculation."""

    def test_auth_failure_polite_backoff(self) -> None:
        """Auth failures should use 15-30 minute backoff."""
        delay = calculate_backoff_delay(0, "auth_failure")
        assert 15 * 60 <= delay <= 30 * 60  # 15-30 minutes

    def test_network_failure_exponential_backoff(self) -> None:
        """Network failures should use exponential backoff."""
        # First failure: ~2s
        delay0 = calculate_backoff_delay(0, "network")
        assert 1.0 <= delay0 <= 4.0  # Base with jitter

        # After 3 failures: ~16s
        delay3 = calculate_backoff_delay(3, "network")
        assert 8.0 <= delay3 <= 32.0  # Exponential with jitter

    def test_backoff_caps_at_60s(self) -> None:
        """Backoff should cap at 60 seconds for network failures."""
        delay = calculate_backoff_delay(10, "network")
        assert delay <= 72.0  # 60s + 20% jitter


class TestProcessRoleExitBehavior:
    """Test sys.exit behavior based on process role."""

    def test_api_role_should_not_exit_on_auth_failure(self) -> None:
        """API role should NOT exit on auth failure."""
        state = DBReadinessState()
        state.process_role = ProcessRole.API
        assert state.should_exit_on_auth_failure() is False

    def test_worker_role_should_exit_on_auth_failure(self) -> None:
        """WORKER role SHOULD exit on auth failure."""
        state = DBReadinessState()
        state.process_role = ProcessRole.WORKER
        assert state.should_exit_on_auth_failure() is True


class TestDBSupervisor:
    """Test background DB supervisor."""

    @pytest.mark.asyncio
    async def test_supervisor_starts_and_stops(self) -> None:
        """Supervisor should start and stop cleanly."""
        state = DBReadinessState()
        connect_fn = AsyncMock(side_effect=Exception("Test error"))
        supervisor = DBSupervisor(state, connect_fn)

        await supervisor.start()
        assert state.supervisor_running is True

        await supervisor.stop()
        assert state.supervisor_running is False

    @pytest.mark.asyncio
    async def test_supervisor_does_not_double_start(self) -> None:
        """Calling start() twice should be idempotent."""
        state = DBReadinessState()
        connect_fn = AsyncMock()
        supervisor = DBSupervisor(state, connect_fn)

        await supervisor.start()
        await supervisor.start()  # Should not error
        assert state.supervisor_running is True

        await supervisor.stop()


class TestHealthEndpointDegradedMode:
    """Test /health and /readyz behavior in degraded mode."""

    @pytest.mark.asyncio
    async def test_health_returns_200_when_db_unavailable(self) -> None:
        """
        /health should return 200 even when DB is not ready.
        This is the liveness probe - process is alive.
        """
        from backend.api.routers.health import root_health_check

        # Simulate DB not ready
        with patch.object(db_state, "ready", False):
            response = await root_health_check()
            assert response.status == "ok"

    @pytest.mark.asyncio
    async def test_readyz_returns_503_when_db_not_ready(self) -> None:
        """
        /readyz should return 503 when db_state.ready is False.
        """
        from backend.api.routers.health import root_readiness_check

        # Save original state
        original_ready = db_state.ready
        original_error_class = db_state.last_error_class
        original_failures = db_state.consecutive_failures

        try:
            # Simulate DB not ready
            db_state.ready = False
            db_state.last_error_class = "auth_failure"
            db_state.consecutive_failures = 3

            response = await root_readiness_check()
            assert response.status_code == 503

            # Verify response includes metadata
            import json

            content = json.loads(response.body)
            assert content["status"] == "not_ready"
            assert content["reason"] == "Database unavailable"
            assert content["consecutive_failures"] == 3

        finally:
            # Restore original state
            db_state.ready = original_ready
            db_state.last_error_class = original_error_class
            db_state.consecutive_failures = original_failures


class TestAPIDoesNotExitOnAuthFailure:
    """Test that API process role prevents sys.exit on auth failures."""

    def test_api_mode_prevents_exit_path(self) -> None:
        """
        When process_role is API, should_exit_on_auth_failure returns False,
        preventing the sys.exit(1) path in init_db_pool.
        """
        state = DBReadinessState()
        state.process_role = ProcessRole.API

        # This is the check that gates sys.exit in db.py
        assert state.should_exit_on_auth_failure() is False

    def test_worker_mode_allows_exit_path(self) -> None:
        """
        When process_role is WORKER, should_exit_on_auth_failure returns True,
        allowing the sys.exit(1) path in init_db_pool.
        """
        state = DBReadinessState()
        state.process_role = ProcessRole.WORKER

        assert state.should_exit_on_auth_failure() is True
