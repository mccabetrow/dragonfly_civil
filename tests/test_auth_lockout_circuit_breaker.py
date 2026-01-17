"""
Tests for Auth Lockout Circuit Breaker

Validates behavior when Supabase pooler returns server_login_retry
or query_wait_timeout errors, indicating an active lockout.

Requirements:
- server_login_retry OR query_wait_timeout → 15-min+ backoff with jitter
- Workers exit immediately with EXIT_CODE_AUTH_LOCKOUT (78)
- API stays alive in degraded mode, /health returns 200
- Structured log: [DB] READY=false reason=lockout next_retry_in=900s
"""

import pytest

from backend.core.db_state import (
    AUTH_FAILURE_MIN_DELAY_S,
    EXIT_CODE_AUTH_LOCKOUT,
    LOCKOUT_BACKOFF_MAX_S,
    LOCKOUT_BACKOFF_MIN_S,
    LOCKOUT_ERROR_PATTERNS,
    LOCKOUT_JITTER_FACTOR,
    DBReadinessState,
    ProcessRole,
    calculate_backoff_delay,
)
from backend.db import _classify_db_init_error


class DummyError(Exception):
    pass


# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURATION CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════


class TestLockoutConstants:
    """Verify lockout circuit breaker constants are properly defined."""

    def test_lockout_backoff_min_is_15_minutes(self) -> None:
        """Lockout backoff minimum should be 15 minutes (900 seconds)."""
        assert LOCKOUT_BACKOFF_MIN_S == 900

    def test_lockout_backoff_max_is_20_minutes(self) -> None:
        """Lockout backoff maximum should be 20 minutes (1200 seconds)."""
        assert LOCKOUT_BACKOFF_MAX_S == 1200

    def test_lockout_jitter_is_10_percent(self) -> None:
        """Jitter should be ±10%."""
        assert LOCKOUT_JITTER_FACTOR == 0.1

    def test_exit_code_is_distinct(self) -> None:
        """Exit code should be 78 (EX_CONFIG from sysexits)."""
        assert EXIT_CODE_AUTH_LOCKOUT == 78

    def test_lockout_patterns_include_server_login_retry(self) -> None:
        """server_login_retry should be in lockout patterns."""
        assert "server_login_retry" in LOCKOUT_ERROR_PATTERNS

    def test_lockout_patterns_include_query_wait_timeout(self) -> None:
        """query_wait_timeout should be in lockout patterns."""
        assert "query_wait_timeout" in LOCKOUT_ERROR_PATTERNS


# ═══════════════════════════════════════════════════════════════════════════
# ERROR CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════


class TestLockoutErrorClassification:
    """Verify lockout errors are correctly classified."""

    @pytest.mark.parametrize(
        "message",
        [
            "server_login_retry exceeded",
            "FATAL: server_login_retry=3",
            "error: server_login_retry limit reached",
            "query_wait_timeout: no connections available",
            "pool exhausted: query_wait_timeout",
        ],
    )
    def test_lockout_errors_classified_as_lockout(self, message: str) -> None:
        """Lockout-indicating errors should be classified as 'lockout'."""
        err = DummyError(message)
        assert _classify_db_init_error(err) == "lockout"

    def test_server_login_retry_takes_priority_over_fatal(self) -> None:
        """server_login_retry should classify as lockout even with FATAL prefix."""
        err = DummyError("FATAL: server_login_retry lockout")
        # Should be lockout, not auth_failure (even though FATAL is an auth keyword)
        assert _classify_db_init_error(err) == "lockout"


# ═══════════════════════════════════════════════════════════════════════════
# BACKOFF CALCULATION
# ═══════════════════════════════════════════════════════════════════════════


class TestLockoutBackoffCalculation:
    """Verify backoff calculation for lockout errors."""

    def test_lockout_backoff_within_expected_range(self) -> None:
        """Lockout backoff should be 15-20 minutes with jitter."""
        delays = [calculate_backoff_delay(i, "lockout") for i in range(100)]

        # All delays should be within the jittered range
        # Min: 900 - (900 * 0.1) = 810
        # Max: 1200 + (1200 * 0.1) = 1320
        min_expected = LOCKOUT_BACKOFF_MIN_S * (1 - LOCKOUT_JITTER_FACTOR)
        max_expected = LOCKOUT_BACKOFF_MAX_S * (1 + LOCKOUT_JITTER_FACTOR)

        for delay in delays:
            assert delay >= min_expected, f"Delay {delay} below min {min_expected}"
            assert delay <= max_expected, f"Delay {delay} above max {max_expected}"

    def test_lockout_backoff_has_variation(self) -> None:
        """Lockout backoff should have jitter to prevent synchronized retries."""
        delays = set(calculate_backoff_delay(i, "lockout") for i in range(20))
        # Should have multiple unique values due to jitter
        assert len(delays) > 1, "Backoff should have jitter variation"

    def test_lockout_backoff_longer_than_normal_auth_failure(self) -> None:
        """Lockout backoff should be at least as long as auth failure backoff."""
        lockout_delay = calculate_backoff_delay(0, "lockout")
        # AUTH_FAILURE_MIN_DELAY_S is 15 minutes, same as lockout
        assert lockout_delay >= AUTH_FAILURE_MIN_DELAY_S * 0.9  # Allow 10% jitter


# ═══════════════════════════════════════════════════════════════════════════
# DB STATE BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════════


class TestDBStateOnLockout:
    """Verify db_state behavior on lockout errors."""

    def test_mark_failed_with_lockout_sets_error_class(self) -> None:
        """mark_failed with lockout should set error_class correctly."""
        state = DBReadinessState()
        state.mark_failed("server_login_retry error", "lockout", 900)

        assert state.ready is False
        assert state.healthy is False
        assert state.last_error_class == "lockout"
        assert state.consecutive_failures == 1

    def test_next_retry_in_seconds_reflects_lockout_delay(self) -> None:
        """next_retry_in_seconds should reflect the lockout backoff."""
        state = DBReadinessState()
        state.mark_failed("server_login_retry", "lockout", 900)

        retry_in = state.next_retry_in_seconds()
        assert retry_in is not None
        # Allow for small timing differences
        assert 895 <= retry_in <= 905

    def test_operator_status_shows_lockout_reason(self) -> None:
        """operator_status should include lockout reason."""
        state = DBReadinessState()
        state.mark_failed("server_login_retry", "lockout", 900)

        status = state.operator_status()
        assert "[DB] READY=false" in status
        assert "reason=lockout" in status
        assert "next_retry_in=" in status


# ═══════════════════════════════════════════════════════════════════════════
# PROCESS ROLE BEHAVIOR
# ═══════════════════════════════════════════════════════════════════════════


class TestProcessRoleOnLockout:
    """Verify role-dependent behavior for lockout errors."""

    def test_worker_should_exit_on_lockout(self) -> None:
        """Worker role should exit on auth/lockout failures."""
        state = DBReadinessState()
        state.process_role = ProcessRole.WORKER
        assert state.should_exit_on_auth_failure() is True

    def test_api_should_not_exit_on_lockout(self) -> None:
        """API role should NOT exit on auth/lockout failures (degraded mode)."""
        state = DBReadinessState()
        state.process_role = ProcessRole.API
        assert state.should_exit_on_auth_failure() is False

    def test_readiness_metadata_includes_lockout_info(self) -> None:
        """readiness_metadata should include lockout error information."""
        state = DBReadinessState()
        state.mark_failed("server_login_retry", "lockout", 900)

        metadata = state.readiness_metadata()
        assert metadata["ready"] is False
        assert metadata["last_error_class"] == "lockout"
        assert metadata["next_retry_in_seconds"] is not None
        assert metadata["next_retry_in_seconds"] >= 895
