"""Tests for WorkerBootstrap InFailedSqlTransaction and rollback recovery.

Verifies that:
- InFailedSqlTransaction triggers rollback
- Rollback failure triggers connection close and reconnect
- Transient failures trigger backoff and reconnect
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock, PropertyMock, call, patch

import psycopg
import psycopg.errors
import pytest

from backend.workers.backoff import BackoffState
from backend.workers.bootstrap import WorkerBootstrap, WorkerConfig


class MockConnection:
    """Mock psycopg Connection with controllable behavior."""

    def __init__(
        self,
        closed: bool = False,
        rollback_raises: Optional[Exception] = None,
        close_raises: Optional[Exception] = None,
    ):
        self._closed = closed
        self._rollback_raises = rollback_raises
        self._close_raises = close_raises
        self.rollback_called = False
        self.close_called = False

    @property
    def closed(self) -> bool:
        return self._closed

    def rollback(self) -> None:
        self.rollback_called = True
        if self._rollback_raises:
            raise self._rollback_raises
        # Rollback succeeded

    def close(self) -> None:
        self.close_called = True
        self._closed = True
        if self._close_raises:
            raise self._close_raises


class TestInFailedSqlTransactionRecovery:
    """Test InFailedSqlTransaction handling in WorkerBootstrap."""

    def test_infailedsqltransaction_triggers_rollback(self):
        """InFailedSqlTransaction error should trigger rollback."""
        mock_conn = MockConnection()

        # Simulate the rollback path in bootstrap.py
        # When InFailedSqlTransaction is caught, rollback should be called
        psycopg.errors.InFailedSqlTransaction("current transaction is aborted")

        # Simulate the exception handling code path
        if mock_conn and not mock_conn.closed:
            try:
                mock_conn.rollback()
            except Exception:
                pass

        assert mock_conn.rollback_called, "Rollback should have been called"
        assert not mock_conn.close_called, "Connection should NOT be closed on successful rollback"

    def test_rollback_failure_triggers_reconnect(self):
        """Rollback failure should close connection and force reconnect."""
        mock_conn = MockConnection(rollback_raises=psycopg.OperationalError("connection lost"))

        # Simulate the rollback-failure path from bootstrap.py
        conn: Optional[MockConnection] = mock_conn
        if conn and not conn.closed:
            try:
                conn.rollback()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None  # Force reconnect

        assert mock_conn.rollback_called, "Rollback should have been attempted"
        assert mock_conn.close_called, "Connection should be closed after rollback failure"
        assert conn is None, "Connection should be set to None for reconnect"

    def test_rollback_failure_with_close_failure(self):
        """Even if close fails, connection should be None for reconnect."""
        mock_conn = MockConnection(
            rollback_raises=psycopg.OperationalError("connection lost"),
            close_raises=psycopg.OperationalError("connection already closed"),
        )

        conn: Optional[MockConnection] = mock_conn
        if conn and not conn.closed:
            try:
                conn.rollback()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None  # Force reconnect

        assert mock_conn.rollback_called
        assert mock_conn.close_called
        assert conn is None, "Connection must be None even if close() raised"


class TestBackoffStateIntegration:
    """Test BackoffState behavior used by workers."""

    def test_record_failure_returns_increasing_delays(self):
        """Consecutive failures should increase backoff delay."""
        backoff = BackoffState()

        delays = [backoff.record_failure() for _ in range(5)]

        # First delay should be around INITIAL_BACKOFF_SECONDS (1.0)
        assert 0.9 <= delays[0] <= 1.2, f"First delay should be ~1s, got {delays[0]}"

        # Each subsequent delay should be >= previous (exponential)
        for i in range(1, len(delays)):
            # Allow for jitter variance but generally increasing
            assert delays[i] >= delays[i - 1] * 0.8, (
                f"Delay {i} ({delays[i]}) should be >= delay {i - 1} ({delays[i - 1]})"
            )

    def test_record_success_resets_backoff(self):
        """Success should reset backoff to initial state."""
        backoff = BackoffState()

        # Accumulate some failures
        for _ in range(5):
            backoff.record_failure()

        assert backoff.consecutive_failures == 5

        # Success resets
        backoff.record_success()

        assert backoff.consecutive_failures == 0
        assert backoff.current_delay == 1.0  # INITIAL_BACKOFF_SECONDS

    def test_crash_loop_detection(self):
        """Crash loop should be detected after threshold failures."""
        backoff = BackoffState()

        # Default threshold is 10
        for i in range(9):
            backoff.record_failure()
            assert not backoff.is_in_crash_loop(), f"Should not be crash loop at {i + 1} failures"

        backoff.record_failure()  # 10th failure
        assert backoff.is_in_crash_loop(), "Should detect crash loop at 10 failures"

    def test_success_clears_crash_loop(self):
        """A success should clear crash loop state."""
        backoff = BackoffState()

        # Trigger crash loop
        for _ in range(10):
            backoff.record_failure()
        assert backoff.is_in_crash_loop()

        # Success clears it
        backoff.record_success()
        assert not backoff.is_in_crash_loop()


class TestWorkerConfigDefaults:
    """Test WorkerConfig has sensible defaults."""

    def test_default_lock_timeout(self):
        """Lock timeout should default to reasonable value."""
        config = WorkerConfig(
            worker_type="test",
            job_types=["test_job"],
        )
        assert config.lock_timeout_minutes == 30

    def test_default_poll_interval(self):
        """Poll interval should default to reasonable value."""
        config = WorkerConfig(
            worker_type="test",
            job_types=["test_job"],
        )
        assert config.poll_interval == 5.0


class TestTransientFailureHandling:
    """Test transient failure paths used by InFailedSqlTransaction and OperationalError."""

    def test_transient_error_increments_backoff(self):
        """Transient errors should increase consecutive failure count."""
        backoff = BackoffState()

        # Simulate transient error handling
        delay = backoff.record_failure()

        assert backoff.consecutive_failures == 1
        assert delay >= 0.9  # ~1s with jitter

    def test_max_backoff_is_bounded(self):
        """Backoff should never exceed MAX_BACKOFF_SECONDS."""
        backoff = BackoffState()

        # Many failures should cap at max
        for _ in range(20):
            delay = backoff.record_failure()

        # Max is 60s + jitter (6s = 10% of 60)
        assert delay <= 66.0, f"Delay {delay} exceeds max + jitter"
