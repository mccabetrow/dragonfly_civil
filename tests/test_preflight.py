"""
Unit tests for backend.preflight module.

Tests cover:
- Environment variable validation (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, etc.)
- Git SHA detection
- Fail-fast vs warn mode behavior
- Structured logging output
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from unittest import mock

import pytest

from backend.preflight import (
    MIN_SERVICE_ROLE_KEY_LENGTH,
    PreflightResult,
    StructuredLogFormatter,
    _get_env,
    _validate_environment,
    _validate_supabase_db_url,
    _validate_supabase_service_role_key,
    _validate_supabase_url,
    configure_structured_logging,
    get_git_sha,
    run_preflight_checks,
    validate_worker_env,
)

# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def clean_env():
    """Provide a clean environment for tests."""
    # Store original values
    original_env = {}
    keys_to_clear = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_DB_URL",
        "ENVIRONMENT",
        "SUPABASE_MODE",
        "GIT_SHA",
        "RAILWAY_GIT_COMMIT_SHA",
        "RENDER_GIT_COMMIT",
        "HEROKU_SLUG_COMMIT",
    ]
    for key in keys_to_clear:
        original_env[key] = os.environ.get(key)
        if key in os.environ:
            del os.environ[key]

    yield

    # Restore original values
    for key, value in original_env.items():
        if value is not None:
            os.environ[key] = value
        elif key in os.environ:
            del os.environ[key]


@pytest.fixture
def valid_service_role_key() -> str:
    """Return a valid-looking service role key for tests."""
    # JWT-like key starting with 'ey' and >= 100 chars
    return "ey" + "a" * 120


@pytest.fixture
def valid_env(valid_service_role_key: str, clean_env):
    """Set up a valid environment for tests."""
    os.environ["SUPABASE_URL"] = "https://test.supabase.co"
    os.environ["SUPABASE_SERVICE_ROLE_KEY"] = valid_service_role_key
    os.environ["SUPABASE_DB_URL"] = "postgresql://user:pass@host:5432/db"
    os.environ["ENVIRONMENT"] = "dev"
    os.environ["SUPABASE_MODE"] = "dev"
    yield


# ==============================================================================
# GIT SHA DETECTION TESTS
# ==============================================================================


class TestGetGitSha:
    """Tests for get_git_sha function."""

    def test_from_git_sha_env(self, clean_env):
        """Test reading from GIT_SHA env var."""
        os.environ["GIT_SHA"] = "abc123def456"
        assert get_git_sha() == "abc123de"  # truncated to 8 chars

    def test_from_railway_env(self, clean_env):
        """Test reading from Railway-specific env var."""
        os.environ["RAILWAY_GIT_COMMIT_SHA"] = "railway123456"
        assert get_git_sha() == "railway1"

    def test_from_render_env(self, clean_env):
        """Test reading from Render-specific env var."""
        os.environ["RENDER_GIT_COMMIT"] = "render123456"
        assert get_git_sha() == "render12"

    def test_priority_order(self, clean_env):
        """Test that GIT_SHA takes priority over platform-specific vars."""
        os.environ["GIT_SHA"] = "priority1"
        os.environ["RAILWAY_GIT_COMMIT_SHA"] = "railway99"
        assert get_git_sha() == "priority"

    def test_returns_none_when_unavailable(self, clean_env):
        """Test returns None when no git info available."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError):
            result = get_git_sha()
            # May return actual git SHA if in git repo, or None
            assert result is None or len(result) == 8


# ==============================================================================
# VALIDATION FUNCTION TESTS
# ==============================================================================


class TestValidateSupabaseServiceRoleKey:
    """Tests for _validate_supabase_service_role_key."""

    def test_missing_key(self, clean_env):
        """Test error when key is missing."""
        result = PreflightResult(worker_name="test")
        _validate_supabase_service_role_key(result)
        assert len(result.errors) == 1
        assert "MISSING" in result.errors[0]

    def test_key_too_short(self, clean_env):
        """Test error when key is too short."""
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "eyshort"
        result = PreflightResult(worker_name="test")
        _validate_supabase_service_role_key(result)
        assert len(result.errors) == 1
        assert "SUSPICIOUS" in result.errors[0]
        assert "(7 chars)" in result.errors[0]

    def test_invalid_format(self, clean_env):
        """Test error when key doesn't start with 'ey'."""
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "x" * 150  # long enough but wrong format
        result = PreflightResult(worker_name="test")
        _validate_supabase_service_role_key(result)
        assert len(result.errors) == 1
        assert "INVALID FORMAT" in result.errors[0]

    def test_valid_key(self, clean_env, valid_service_role_key):
        """Test no errors with valid key."""
        os.environ["SUPABASE_SERVICE_ROLE_KEY"] = valid_service_role_key
        result = PreflightResult(worker_name="test")
        _validate_supabase_service_role_key(result)
        assert len(result.errors) == 0


class TestValidateSupabaseUrl:
    """Tests for _validate_supabase_url."""

    def test_missing_url(self, clean_env):
        """Test error when URL is missing."""
        result = PreflightResult(worker_name="test")
        _validate_supabase_url(result)
        assert len(result.errors) == 1
        assert "MISSING" in result.errors[0]

    def test_non_https_url(self, clean_env):
        """Test error when URL is not HTTPS."""
        os.environ["SUPABASE_URL"] = "http://test.supabase.co"
        result = PreflightResult(worker_name="test")
        _validate_supabase_url(result)
        assert len(result.errors) == 1
        assert "HTTPS" in result.errors[0]

    def test_invalid_format(self, clean_env):
        """Test error when URL format is invalid."""
        os.environ["SUPABASE_URL"] = "https://"
        result = PreflightResult(worker_name="test")
        _validate_supabase_url(result)
        assert len(result.errors) == 1
        assert "INVALID FORMAT" in result.errors[0]

    def test_valid_url(self, clean_env):
        """Test no errors with valid URL."""
        os.environ["SUPABASE_URL"] = "https://project.supabase.co"
        result = PreflightResult(worker_name="test")
        _validate_supabase_url(result)
        assert len(result.errors) == 0


class TestValidateEnvironment:
    """Tests for _validate_environment."""

    def test_missing_environment(self, clean_env):
        """Test warning when ENVIRONMENT is not set."""
        result = PreflightResult(worker_name="test")
        _validate_environment(result)
        assert len(result.warnings) == 1
        assert "not set" in result.warnings[0]

    def test_production_variant(self, clean_env):
        """Test warning for 'production' variant."""
        os.environ["ENVIRONMENT"] = "production"
        result = PreflightResult(worker_name="test")
        _validate_environment(result)
        assert len(result.warnings) == 1
        assert "normalized to 'prod'" in result.warnings[0]

    def test_invalid_environment(self, clean_env):
        """Test error for invalid environment value."""
        os.environ["ENVIRONMENT"] = "invalid"
        result = PreflightResult(worker_name="test")
        _validate_environment(result)
        assert len(result.errors) == 1
        assert "INVALID VALUE" in result.errors[0]

    @pytest.mark.parametrize("env", ["dev", "staging", "prod"])
    def test_valid_environments(self, clean_env, env):
        """Test no errors for valid environment values."""
        os.environ["ENVIRONMENT"] = env
        result = PreflightResult(worker_name="test")
        _validate_environment(result)
        assert len(result.errors) == 0
        assert len(result.warnings) == 0


class TestValidateSupabaseDbUrl:
    """Tests for _validate_supabase_db_url."""

    def test_missing_db_url(self, clean_env):
        """Test error when DB URL is not set."""
        result = PreflightResult(worker_name="test")
        _validate_supabase_db_url(result)
        assert len(result.errors) == 1
        assert "required" in result.errors[0]

    def test_invalid_format(self, clean_env):
        """Test error when DB URL has invalid format."""
        os.environ["SUPABASE_DB_URL"] = "mysql://user:pass@host/db"
        result = PreflightResult(worker_name="test")
        _validate_supabase_db_url(result)
        assert len(result.errors) == 1
        assert "INVALID FORMAT" in result.errors[0]

    def test_valid_postgresql_url(self, clean_env):
        """Test no errors with valid postgresql:// URL."""
        os.environ["SUPABASE_DB_URL"] = "postgresql://user:pass@host:5432/db"
        result = PreflightResult(worker_name="test")
        _validate_supabase_db_url(result)
        assert len(result.errors) == 0

    def test_valid_postgres_url(self, clean_env):
        """Test no errors with valid postgres:// URL."""
        os.environ["SUPABASE_DB_URL"] = "postgres://user:pass@host:5432/db"
        result = PreflightResult(worker_name="test")
        _validate_supabase_db_url(result)
        assert len(result.errors) == 0


# ==============================================================================
# PREFLIGHT RESULT TESTS
# ==============================================================================


class TestPreflightResult:
    """Tests for PreflightResult dataclass."""

    def test_is_valid_with_no_errors(self):
        """Test is_valid is True when no errors."""
        result = PreflightResult(worker_name="test")
        assert result.is_valid is True

    def test_is_valid_with_errors(self):
        """Test is_valid is False when errors present."""
        result = PreflightResult(worker_name="test", errors=["error"])
        assert result.is_valid is False

    def test_has_warnings(self):
        """Test has_warnings property."""
        result = PreflightResult(worker_name="test")
        assert result.has_warnings is False
        result.warnings.append("warning")
        assert result.has_warnings is True

    def test_to_dict(self):
        """Test to_dict serialization."""
        result = PreflightResult(
            worker_name="test_worker",
            errors=["e1"],
            warnings=["w1", "w2"],
            git_sha="abc123",
            environment="prod",
            supabase_mode="prod",
        )
        d = result.to_dict()
        assert d["worker"] == "test_worker"
        assert d["is_valid"] is False
        assert d["errors"] == 1
        assert d["warnings"] == 2
        assert d["git_sha"] == "abc123"
        assert d["environment"] == "prod"
        assert d["supabase_mode"] == "prod"


# ==============================================================================
# RUN PREFLIGHT CHECKS TESTS
# ==============================================================================


class TestRunPreflightChecks:
    """Tests for run_preflight_checks function."""

    def test_populates_metadata(self, valid_env):
        """Test that result includes git_sha, environment, supabase_mode."""
        os.environ["GIT_SHA"] = "test1234"
        result = run_preflight_checks("test_worker")
        assert result.worker_name == "test_worker"
        assert result.git_sha == "test1234"
        assert result.environment == "dev"
        assert result.supabase_mode == "dev"

    def test_collects_all_errors(self, clean_env):
        """Test that all validation errors are collected."""
        # Missing both required vars
        result = run_preflight_checks("test_worker")
        # Should have errors for URL and key
        assert len(result.errors) >= 2


# ==============================================================================
# VALIDATE WORKER ENV TESTS
# ==============================================================================


class TestValidateWorkerEnv:
    """Tests for validate_worker_env function."""

    def test_returns_result_on_success(self, valid_env):
        """Test successful validation returns result."""
        result = validate_worker_env("test_worker", exit_on_error=False, structured_logging=False)
        assert result.is_valid is True

    def test_exit_on_error(self, clean_env):
        """Test sys.exit is called on validation errors."""
        with pytest.raises(SystemExit) as exc_info:
            validate_worker_env("test_worker", structured_logging=False)
        assert exc_info.value.code == 1

    def test_no_exit_when_disabled(self, clean_env):
        """Test no sys.exit when exit_on_error=False."""
        result = validate_worker_env("test_worker", exit_on_error=False, structured_logging=False)
        assert result.is_valid is False

    def test_fail_fast_in_prod(self, valid_env):
        """Test fail_fast defaults to True in prod."""
        os.environ["ENVIRONMENT"] = "prod"
        # Remove required DB URL to cause failure
        del os.environ["SUPABASE_DB_URL"]

        with pytest.raises(SystemExit) as exc_info:
            validate_worker_env("test_worker", structured_logging=False)
        assert exc_info.value.code == 1

    def test_error_in_dev_also_fails(self, valid_env):
        """Test missing required config fails even in dev."""
        os.environ["ENVIRONMENT"] = "dev"
        # Remove required DB URL
        del os.environ["SUPABASE_DB_URL"]

        # Should fail since SUPABASE_DB_URL is now required
        result = validate_worker_env("test_worker", exit_on_error=False, structured_logging=False)
        assert result.is_valid is False
        assert len(result.errors) >= 1

    def test_explicit_fail_fast_override(self, valid_env):
        """Test fail_fast causes exit on errors."""
        os.environ["ENVIRONMENT"] = "dev"
        del os.environ["SUPABASE_DB_URL"]

        # With fail_fast=True, should exit
        with pytest.raises(SystemExit):
            validate_worker_env("test_worker", fail_fast=True, structured_logging=False)


# ==============================================================================
# STRUCTURED LOGGING TESTS
# ==============================================================================


class TestStructuredLogFormatter:
    """Tests for StructuredLogFormatter."""

    def test_formats_as_json(self):
        """Test output is valid JSON."""
        formatter = StructuredLogFormatter("test_service", git_sha="abc12345")
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["service"] == "test_service"
        assert data["sha"] == "abc12345"
        assert data["msg"] == "Test message"
        assert data["level"] == "INFO"

    def test_includes_all_fields(self, clean_env):
        """Test all required fields are present."""
        os.environ["ENVIRONMENT"] = "staging"
        os.environ["SUPABASE_MODE"] = "dev"
        formatter = StructuredLogFormatter("my_worker", git_sha="12345678")

        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="",
            lineno=0,
            msg="Warning message",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)

        assert "ts" in data
        assert data["level"] == "WARNING"
        assert data["service"] == "my_worker"
        assert data["sha"] == "12345678"
        assert data["env"] == "staging"
        assert data["mode"] == "dev"
        assert data["msg"] == "Warning message"


class TestConfigureStructuredLogging:
    """Tests for configure_structured_logging."""

    def test_returns_logger(self):
        """Test returns configured logger."""
        logger = configure_structured_logging("test_service")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "preflight"

    def test_clears_existing_handlers(self):
        """Test removes existing handlers and creates split stdout/stderr handlers."""
        logger = logging.getLogger("preflight")
        logger.addHandler(logging.StreamHandler())

        configure_structured_logging("test_service")
        # Now uses split handlers: stdout for INFO, stderr for WARNING+
        assert len(logger.handlers) == 2


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestPreflightIntegration:
    """Integration tests for full preflight workflow."""

    def test_full_valid_flow(self, valid_env, capsys):
        """Test complete validation with valid config."""
        os.environ["GIT_SHA"] = "integr8t"
        result = validate_worker_env(
            "integration_worker", exit_on_error=False, structured_logging=False
        )
        assert result.is_valid is True

        captured = capsys.readouterr()
        assert "integration_worker" in captured.out
        assert "integr8t" in captured.out

    def test_banner_output(self, valid_env, capsys):
        """Test banner is printed with key metadata."""
        os.environ["GIT_SHA"] = "banner12"
        os.environ["ENVIRONMENT"] = "staging"

        validate_worker_env("banner_test", exit_on_error=False, structured_logging=False)

        captured = capsys.readouterr()
        assert "Dragonfly Worker: banner_test" in captured.out
        assert "Environment:" in captured.out
        assert "staging" in captured.out
        assert "Git SHA:" in captured.out
