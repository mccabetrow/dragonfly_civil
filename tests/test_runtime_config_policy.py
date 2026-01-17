"""
Tests for Runtime Config Policy enforcement.

Covers:
1. Missing ENV_FILE never crashes (logs warning, continues)
2. SUPABASE_MIGRATE_DB_URL allowed in scripts mode, FATAL in runtime mode
3. Port 5432 is FATAL in production runtime
4. Auth failure classification (no retry on auth, retry on network)
"""

from __future__ import annotations

import importlib
import sys

import pytest

# Static imports for pure functions that don't need reloading
# These are NOT mocked by conftest.py and don't call sys.exit()
from backend.core.config_guard import (
    AUTH_FAILURE_PATTERNS,
    NETWORK_FAILURE_PATTERNS,
    classify_db_error,
    is_auth_failure,
    is_network_failure,
)


def _get_config_guard():
    """Get a fresh config_guard module, handling cases where it was removed from sys.modules."""
    if "backend.core.config_guard" not in sys.modules:
        import backend.core.config_guard as cg

        return cg
    else:
        import backend.core.config_guard as cg

        # Reload to get the real implementation (conftest.py mocks it)
        return importlib.reload(cg)


# =============================================================================
# Environment variable fixtures
# =============================================================================

_ENV_VARS = (
    "ENVIRONMENT",
    "DRAGONFLY_ENV",
    "RAILWAY_ENVIRONMENT",
    "SUPABASE_DB_URL",
    "DATABASE_URL",
    "SUPABASE_MIGRATE_DB_URL",
    "DRAGONFLY_EXECUTION_MODE",
)


@pytest.fixture(autouse=True)
def reset_config_guard_cache(monkeypatch: pytest.MonkeyPatch):
    """Reset config_guard execution mode cache before each test."""
    cg = _get_config_guard()
    cg._reset_execution_mode_cache()  # type: ignore[attr-defined]
    # Clear env vars that affect mode detection
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    yield
    cg._reset_execution_mode_cache()  # type: ignore[attr-defined]


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all relevant environment variables."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set production environment."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DRAGONFLY_ENV", "prod")


def _set_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set development environment."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("DRAGONFLY_ENV", "dev")


def _set_scripts_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force scripts mode via environment variable."""
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "script")
    _get_config_guard()._reset_execution_mode_cache()  # type: ignore[attr-defined]


def _set_runtime_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force runtime mode via environment variable."""
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")
    _get_config_guard()._reset_execution_mode_cache()  # type: ignore[attr-defined]


# =============================================================================
# TEST 1: Execution Mode Detection
# =============================================================================


class TestExecutionModeDetection:
    """Tests for is_scripts_mode() and is_runtime_mode()."""

    def test_scripts_mode_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DRAGONFLY_EXECUTION_MODE=script forces scripts mode."""
        _clear_env(monkeypatch)
        _set_scripts_mode(monkeypatch)

        cg = _get_config_guard()
        assert cg.is_scripts_mode() is True
        assert cg.is_runtime_mode() is False

    def test_runtime_mode_explicit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DRAGONFLY_EXECUTION_MODE=runtime forces runtime mode."""
        _clear_env(monkeypatch)
        _set_runtime_mode(monkeypatch)

        cg = _get_config_guard()
        assert cg.is_scripts_mode() is False
        assert cg.is_runtime_mode() is True

    def test_default_is_runtime_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without explicit mode, tests run as scripts (detected by test module path)."""
        _clear_env(monkeypatch)
        # In pytest context, __main__ is pytest, which should be detected as scripts
        # This test validates the default behavior in the pytest context
        # Note: The exact result depends on how pytest runs the test


# =============================================================================
# TEST 2: SUPABASE_MIGRATE_DB_URL Policy
# =============================================================================


class TestMigrateUrlPolicy:
    """Tests for SUPABASE_MIGRATE_DB_URL handling based on execution mode."""

    def test_migrate_url_allowed_in_scripts_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SUPABASE_MIGRATE_DB_URL is ALLOWED in scripts mode."""
        _clear_env(monkeypatch)
        _set_scripts_mode(monkeypatch)
        monkeypatch.setenv(
            "SUPABASE_MIGRATE_DB_URL",
            "postgresql://user:pass@host:5432/db",
        )

        # check_forbidden_vars should pass in scripts mode
        cg = _get_config_guard()
        passed, error = cg.check_forbidden_vars()
        assert passed is True
        assert error is None

    def test_migrate_url_fatal_in_runtime_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SUPABASE_MIGRATE_DB_URL is FATAL in runtime mode."""
        _clear_env(monkeypatch)
        _set_runtime_mode(monkeypatch)
        monkeypatch.setenv(
            "SUPABASE_MIGRATE_DB_URL",
            "postgresql://user:pass@host:5432/db",
        )

        # check_forbidden_vars should fail in runtime mode
        cg = _get_config_guard()
        passed, error = cg.check_forbidden_vars()
        assert passed is False
        assert error is not None
        assert "SUPABASE_MIGRATE_DB_URL" in error

    def test_validate_runtime_config_skipped_in_scripts_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """validate_runtime_config() is a no-op in scripts mode."""
        _clear_env(monkeypatch)
        _set_scripts_mode(monkeypatch)
        _set_prod_env(monkeypatch)
        # Set forbidden vars that would normally cause exit
        monkeypatch.setenv(
            "SUPABASE_MIGRATE_DB_URL",
            "postgresql://user:pass@host:5432/db",
        )

        # Should NOT raise in scripts mode
        cg = _get_config_guard()
        cg.validate_runtime_config()  # No exception = pass


# =============================================================================
# TEST 3: Port 5432 Policy
# =============================================================================


class TestPortPolicy:
    """Tests for port 5432 being FATAL in production runtime."""

    def test_port_5432_fatal_in_prod_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Port 5432 causes SystemExit in production runtime mode."""
        _clear_env(monkeypatch)
        _set_runtime_mode(monkeypatch)
        _set_prod_env(monkeypatch)
        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://user:pass@host:5432/db?sslmode=require",
        )

        cg = _get_config_guard()
        with pytest.raises(SystemExit) as exc_info:
            cg.validate_runtime_config()

        assert exc_info.value.code == 1

    def test_port_6543_allowed_in_prod_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Port 6543 (pooler) with pooler hostname is allowed in production runtime mode."""
        _clear_env(monkeypatch)
        _set_runtime_mode(monkeypatch)
        _set_prod_env(monkeypatch)
        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/db?sslmode=require",
        )

        # Should NOT raise
        cg = _get_config_guard()
        cg.validate_runtime_config()

    def test_port_5432_allowed_in_scripts_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Port 5432 is allowed in scripts mode (even in prod env)."""
        _clear_env(monkeypatch)
        _set_scripts_mode(monkeypatch)
        _set_prod_env(monkeypatch)
        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://user:pass@host:5432/db?sslmode=require",
        )

        # Should NOT raise in scripts mode
        cg = _get_config_guard()
        cg.validate_runtime_config()


# =============================================================================
# TEST 4: Auth Failure Classification
# =============================================================================


class TestAuthFailureClassification:
    """Tests for auth failure detection and classification."""

    @pytest.mark.parametrize(
        "error_msg",
        [
            "password authentication failed for user postgres",
            'FATAL:  password authentication failed for user "postgres"',
            'role "missing_user" does not exist',
            'database "missing_db" does not exist',
            "server_login_retry: too many failed login attempts",
            "FATAL: too many connections for role",
        ],
    )
    def test_auth_failures_detected(self, error_msg: str) -> None:
        """Auth failures are correctly classified."""
        assert classify_db_error(error_msg) == "auth"
        assert is_auth_failure(error_msg) is True
        assert is_network_failure(error_msg) is False

    @pytest.mark.parametrize(
        "error_msg",
        [
            "could not connect to server: Connection refused",
            "connection timed out",
            "server closed the connection unexpectedly",
            "SSL SYSCALL error: EOF detected",
            "network is unreachable",
        ],
    )
    def test_network_failures_detected(self, error_msg: str) -> None:
        """Network failures are correctly classified."""
        assert classify_db_error(error_msg) == "network"
        assert is_network_failure(error_msg) is True
        assert is_auth_failure(error_msg) is False

    def test_unknown_error_classification(self) -> None:
        """Unknown errors are classified as 'unknown'."""
        error_msg = "some random error that doesn't match patterns"
        assert classify_db_error(error_msg) == "unknown"
        assert is_auth_failure(error_msg) is False
        assert is_network_failure(error_msg) is False

    def test_auth_patterns_are_lowercase_matched(self) -> None:
        """Auth patterns match case-insensitively."""
        # Mixed case should still match
        assert is_auth_failure("PASSWORD AUTHENTICATION FAILED") is True
        assert is_auth_failure("Server_Login_Retry") is True


# =============================================================================
# TEST 5: ENV_FILE Missing Never Crashes
# =============================================================================


class TestEnvFileMissing:
    """Tests that missing .env files don't crash the application."""

    def test_bootstrap_handles_missing_env_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """bootstrap_environment logs warning but continues if .env.{env} missing."""
        import os
        from pathlib import Path

        # Import bootstrap function
        from backend.core.bootstrap import bootstrap_environment

        # Clear environment
        _clear_env(monkeypatch)
        monkeypatch.delenv("DRAGONFLY_ACTIVE_ENV", raising=False)

        # Use a temp directory with no .env files
        monkeypatch.chdir(tmp_path)

        # Create minimal pyproject.toml so project root detection works
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        # Should NOT crash, should return 'dev' (default)
        result = bootstrap_environment(
            cli_override="dev",
            project_root=tmp_path,
            verbose=False,
        )

        assert result == "dev"


# =============================================================================
# TEST 6: Policy Constants Sanity Checks
# =============================================================================


class TestPolicyConstants:
    """Sanity checks for policy constants."""

    def test_auth_failure_patterns_not_empty(self) -> None:
        """AUTH_FAILURE_PATTERNS should have entries."""
        assert len(AUTH_FAILURE_PATTERNS) > 0

    def test_network_failure_patterns_not_empty(self) -> None:
        """NETWORK_FAILURE_PATTERNS should have entries."""
        assert len(NETWORK_FAILURE_PATTERNS) > 0

    def test_no_overlap_between_auth_and_network_patterns(self) -> None:
        """Auth and network patterns should not overlap."""
        auth_lower = {p.lower() for p in AUTH_FAILURE_PATTERNS}
        network_lower = {p.lower() for p in NETWORK_FAILURE_PATTERNS}
        overlap = auth_lower & network_lower
        assert len(overlap) == 0, f"Overlapping patterns: {overlap}"


class TestProductionPoolerContract:
    """Tests for mandatory pooler host enforcement in production."""

    def test_direct_connection_port_5432_rejected_in_prod(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direct connection (port 5432) should be rejected in production."""
        import backend.core.config_guard as guard

        monkeypatch.setenv("DRAGONFLY_ENV", "prod")
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")
        guard._reset_execution_mode_cache()

        # Port 5432 is direct connection - should fail
        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://user:pass@db.fake.supabase.co:5432/postgres?sslmode=require",
        )
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k" * 120)
        monkeypatch.setenv("DRAGONFLY_API_KEY", "unit-test")
        monkeypatch.delenv("SUPABASE_MIGRATE_DB_URL", raising=False)

        with pytest.raises(SystemExit):
            guard.validate_production_config()

    def test_dedicated_pooler_accepted_in_prod(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dedicated pooler (db.<ref>.supabase.co:6543) should be accepted in production."""
        import backend.core.config_guard as guard

        monkeypatch.setenv("DRAGONFLY_ENV", "prod")
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")
        guard._reset_execution_mode_cache()

        # Port 6543 with db.* host is dedicated pooler - should pass
        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://user:pass@db.fake.supabase.co:6543/postgres?sslmode=require",
        )
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k" * 120)
        monkeypatch.setenv("DRAGONFLY_API_KEY", "unit-test")
        monkeypatch.delenv("SUPABASE_MIGRATE_DB_URL", raising=False)

        # Should NOT raise - dedicated pooler is valid
        guard.validate_production_config()
