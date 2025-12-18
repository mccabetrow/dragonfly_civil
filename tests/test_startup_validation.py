"""Tests for startup validation and preflight checks.

Tests single-line error format, effective config printing, and key validation.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from backend.preflight import (
    EX_CONFIG,
    MIN_SERVICE_ROLE_KEY_LENGTH,
    PreflightResult,
    run_preflight_checks,
)
from backend.startup_validator import (
    StartupValidationResult,
    ValidationError,
    validate_startup_config,
)

# ==============================================================================
# ValidationError Tests
# ==============================================================================


class TestValidationError:
    """Tests for the ValidationError dataclass."""

    def test_to_single_line_missing(self):
        """Test single-line format for MISSING errors."""
        error = ValidationError(
            key_name="SUPABASE_SERVICE_ROLE_KEY",
            error_type="MISSING",
            message="Key is not set",
        )
        result = error.to_single_line("api")
        assert result == "api: MISSING - SUPABASE_SERVICE_ROLE_KEY - Key is not set"

    def test_to_single_line_suspicious(self):
        """Test single-line format for SUSPICIOUS errors."""
        error = ValidationError(
            key_name="SUPABASE_SERVICE_ROLE_KEY",
            error_type="SUSPICIOUS",
            message="Key too short (5 chars, expected 100+)",
        )
        result = error.to_single_line("ingest_worker")
        assert (
            result
            == "ingest_worker: SUSPICIOUS - SUPABASE_SERVICE_ROLE_KEY - Key too short (5 chars, expected 100+)"
        )

    def test_to_single_line_no_secrets_in_output(self):
        """Ensure error messages don't contain actual secret values."""
        # Even if someone mistakenly passes a secret as message, format is predictable
        error = ValidationError(
            key_name="API_KEY",
            error_type="INVALID",
            message="Invalid format",
        )
        result = error.to_single_line("service")
        # Should not contain any actual secret patterns
        assert "eyJ" not in result  # JWT prefix
        assert "sk-" not in result  # OpenAI prefix
        assert len(result) < 200  # Reasonable length


# ==============================================================================
# StartupValidationResult Tests
# ==============================================================================


class TestStartupValidationResult:
    """Tests for StartupValidationResult."""

    def test_is_valid_with_no_errors(self):
        """Test that result is valid when no errors."""
        result = StartupValidationResult(
            service_name="test",
            errors=[],
            effective_config={"KEY": "SET"},
        )
        assert result.is_valid is True

    def test_is_valid_with_errors(self):
        """Test that result is invalid when errors present."""
        result = StartupValidationResult(
            service_name="test",
            errors=[ValidationError("KEY", "MISSING", "Not set")],
            effective_config={},
        )
        assert result.is_valid is False

    def test_print_errors_format(self, capsys):
        """Test that print_errors produces single-line format."""
        result = StartupValidationResult(
            service_name="worker",
            errors=[
                ValidationError("KEY1", "MISSING", "Not set"),
                ValidationError("KEY2", "SUSPICIOUS", "Too short"),
            ],
            effective_config={},
        )
        result.print_errors()

        captured = capsys.readouterr()
        # print_errors writes to stderr
        lines = captured.err.strip().split("\n")
        assert len(lines) == 2
        assert "worker: MISSING - KEY1 - Not set" in lines[0]
        assert "worker: SUSPICIOUS - KEY2 - Too short" in lines[1]

    def test_print_effective_config_no_values(self):
        """Test that print_effective_config shows keys but not actual values."""
        result = StartupValidationResult(
            service_name="api",
            errors=[],
            effective_config={
                "SUPABASE_SERVICE_ROLE_KEY": "SET (219 chars)",
                "SUPABASE_URL": "SET (https://example...)",
                "OPENAI_API_KEY": "NOT SET",
            },
        )
        output = StringIO()
        with patch("sys.stdout", output):
            result.print_effective_config()

        text = output.getvalue()
        # Should show key names
        assert "SUPABASE_SERVICE_ROLE_KEY" in text
        assert "SUPABASE_URL" in text
        assert "OPENAI_API_KEY" in text
        # Should show SET/NOT SET status
        assert "SET (219 chars)" in text
        assert "NOT SET" in text
        # Should NOT show actual secret values
        assert "eyJ" not in text  # JWT prefix


# ==============================================================================
# PreflightResult Tests
# ==============================================================================


class TestPreflightResult:
    """Tests for PreflightResult from backend.preflight."""

    def test_get_single_line_errors(self):
        """Test single-line error generation."""
        result = PreflightResult(
            worker_name="test_service",
        )
        result.errors = ["SUPABASE_SERVICE_ROLE_KEY is MISSING"]
        result.effective_config = {"SUPABASE_SERVICE_ROLE_KEY": "NOT SET"}

        lines = result.get_single_line_errors()
        assert len(lines) == 1
        assert "test_service: MISSING - SUPABASE_SERVICE_ROLE_KEY" in lines[0]

    def test_get_single_line_errors_suspicious(self):
        """Test single-line error for suspicious keys."""
        result = PreflightResult(
            worker_name="worker",
        )
        result.errors = ["SUPABASE_SERVICE_ROLE_KEY is SUSPICIOUS (5 chars)"]
        result.effective_config = {"SUPABASE_SERVICE_ROLE_KEY": "SET (5 chars)"}

        lines = result.get_single_line_errors()
        assert len(lines) == 1
        assert "worker: SUSPICIOUS - SUPABASE_SERVICE_ROLE_KEY" in lines[0]


# ==============================================================================
# Integration Tests - validate_startup_config
# ==============================================================================


class TestValidateStartupConfig:
    """Integration tests for validate_startup_config."""

    def test_valid_config(self):
        """Test validation with valid configuration."""
        # Use a realistic JWT-like key (starts with 'ey' and is long enough)
        fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "x" * 150
        with patch.dict(
            os.environ,
            {
                "SUPABASE_SERVICE_ROLE_KEY": fake_jwt,
                "SUPABASE_URL": "https://test.supabase.co",
            },
        ):
            result = validate_startup_config(
                service_name="test",
                exit_on_error=False,
            )
            assert result.is_valid is True
            assert len(result.errors) == 0

    def test_missing_service_role_key(self):
        """Test validation with missing service role key."""
        env = os.environ.copy()
        env.pop("SUPABASE_SERVICE_ROLE_KEY", None)

        with patch.dict(os.environ, env, clear=True):
            # Also need to clear the env var in the patched environ
            os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
            result = validate_startup_config(
                service_name="test",
                exit_on_error=False,
            )
            # Should have at least one error about missing key
            assert result.is_valid is False
            error_keys = [e.key_name for e in result.errors]
            assert "SUPABASE_SERVICE_ROLE_KEY" in error_keys

    def test_suspicious_service_role_key(self):
        """Test validation with too-short service role key."""
        with patch.dict(
            os.environ,
            {
                "SUPABASE_SERVICE_ROLE_KEY": "short",  # Only 5 chars
                "SUPABASE_URL": "https://test.supabase.co",
            },
        ):
            result = validate_startup_config(
                service_name="worker",
                exit_on_error=False,
            )
            assert result.is_valid is False
            # Find the suspicious error
            suspicious_errors = [e for e in result.errors if e.error_type == "SUSPICIOUS"]
            assert len(suspicious_errors) >= 1
            assert any(e.key_name == "SUPABASE_SERVICE_ROLE_KEY" for e in suspicious_errors)


# ==============================================================================
# Integration Tests - run_preflight_checks
# ==============================================================================


class TestRunPreflightChecks:
    """Integration tests for run_preflight_checks."""

    def test_returns_preflight_result(self):
        """Test that run_preflight_checks returns PreflightResult."""
        result = run_preflight_checks("test_service")
        assert isinstance(result, PreflightResult)
        assert hasattr(result, "is_valid")
        assert hasattr(result, "errors")
        assert hasattr(result, "effective_config")

    def test_effective_config_populated(self):
        """Test that effective_config is populated."""
        result = run_preflight_checks("test_service")
        assert isinstance(result.effective_config, dict)
        # Should have some keys tracked
        assert len(result.effective_config) > 0

    def test_effective_config_no_raw_secrets(self):
        """Test that effective_config doesn't contain raw secret values."""
        result = run_preflight_checks("test_service")

        # Check that no raw JWT tokens are in config values
        for key, value in result.effective_config.items():
            if isinstance(value, str):
                assert "eyJ" not in value or "..." in value  # Truncated is OK
                assert len(value) < 100 or "chars)" in value  # Length indicator OK


# ==============================================================================
# CLI Tests
# ==============================================================================


class TestPreflightCLI:
    """Tests for the preflight CLI."""

    @pytest.fixture
    def python_path(self):
        """Get the Python executable path."""
        return sys.executable

    def test_cli_help(self, python_path):
        """Test that CLI --help works."""
        result = subprocess.run(
            [python_path, "-m", "backend.preflight", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--service" in result.stdout
        assert "--print-effective-config" in result.stdout
        assert "--single-line" in result.stdout

    def test_cli_print_effective_config(self, python_path):
        """Test --print-effective-config output."""
        result = subprocess.run(
            [
                python_path,
                "-m",
                "backend.preflight",
                "--service",
                "test",
                "--print-effective-config",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Effective configuration for: test" in result.stdout
        # Should show key names
        assert "SUPABASE" in result.stdout
        # Should not show raw secrets (check for JWT prefix)
        assert result.stdout.count("eyJ") == 0 or "..." in result.stdout


class TestStartupValidatorCLI:
    """Tests for the startup_validator CLI."""

    @pytest.fixture
    def python_path(self):
        """Get the Python executable path."""
        return sys.executable

    def test_cli_help(self, python_path):
        """Test that CLI --help works."""
        result = subprocess.run(
            [python_path, "-m", "backend.startup_validator", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "--service" in result.stdout
        assert "--print-effective-config" in result.stdout

    def test_cli_print_effective_config(self, python_path):
        """Test --print-effective-config output."""
        result = subprocess.run(
            [
                python_path,
                "-m",
                "backend.startup_validator",
                "--service",
                "test",
                "--print-effective-config",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Effective configuration for: test" in result.stdout


# ==============================================================================
# Constants Tests
# ==============================================================================


class TestConstants:
    """Tests for validation constants."""

    def test_ex_config_value(self):
        """Test EX_CONFIG follows BSD sysexits.h convention."""
        assert EX_CONFIG == 78

    def test_min_service_role_key_length(self):
        """Test minimum key length is reasonable."""
        assert MIN_SERVICE_ROLE_KEY_LENGTH == 100
        # Supabase JWT tokens are typically 200+ chars
        assert MIN_SERVICE_ROLE_KEY_LENGTH < 200
