"""
Tests for src/core_config.py - Production hardening features.

Tests cover:
- ENVIRONMENT normalization (production→prod, development→dev)
- DB URL fallback (SUPABASE_DB_URL_DEV)
- Collision guard (canonical + deprecated key conflict)
- Startup diagnostics
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

from src.core_config import (
    Settings,
    get_deprecated_keys_used,
    log_startup_diagnostics,
    reset_settings,
)


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Reset the settings cache before and after each test."""
    reset_settings()
    yield
    reset_settings()


def _minimal_env() -> dict[str, str]:
    """Minimal valid environment for Settings instantiation."""
    return {
        "SUPABASE_URL": "https://test.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,  # Must be 100+ chars
    }


def _create_settings_no_env_file(**overrides):
    """Create Settings without loading .env file, isolated from current env."""
    base = _minimal_env()
    all_values = base | overrides
    # Use _env_file="" to explicitly disable .env loading
    # Also clear env temporarily to avoid picking up real env vars
    with patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file="", **all_values)  # type: ignore[call-arg]


class TestEnvironmentNormalization:
    """Tests for ENVIRONMENT value normalization."""

    def test_accepts_dev(self):
        """dev is accepted as-is."""
        s = _create_settings_no_env_file(ENVIRONMENT="dev")
        assert s.ENVIRONMENT == "dev"

    def test_accepts_staging(self):
        """staging is accepted as-is."""
        s = _create_settings_no_env_file(ENVIRONMENT="staging")
        assert s.ENVIRONMENT == "staging"

    def test_accepts_prod(self):
        """prod is accepted as-is."""
        s = _create_settings_no_env_file(ENVIRONMENT="prod")
        assert s.ENVIRONMENT == "prod"

    def test_normalizes_production_to_prod(self, caplog):
        """production is normalized to prod with a warning."""
        with caplog.at_level(logging.WARNING):
            s = _create_settings_no_env_file(ENVIRONMENT="production")
        assert s.ENVIRONMENT == "prod"
        assert "production" in caplog.text
        assert "deprecated" in caplog.text.lower()

    def test_normalizes_development_to_dev(self, caplog):
        """development is normalized to dev with a warning."""
        with caplog.at_level(logging.WARNING):
            s = _create_settings_no_env_file(ENVIRONMENT="development")
        assert s.ENVIRONMENT == "dev"
        assert "development" in caplog.text
        assert "deprecated" in caplog.text.lower()

    def test_rejects_unknown_environment(self):
        """Unknown environment values are rejected."""
        with pytest.raises(ValueError, match="ENVIRONMENT='test' is invalid"):
            _create_settings_no_env_file(ENVIRONMENT="test")


class TestDbUrlFallback:
    """Tests for DB URL fallback logic."""

    def test_uses_supabase_db_url_primary(self):
        """SUPABASE_DB_URL is used as primary."""
        s = _create_settings_no_env_file(
            SUPABASE_DB_URL="postgresql://primary.example.com/db",
            SUPABASE_MODE="dev",
        )
        assert s.get_db_url() == "postgresql://primary.example.com/db"

    def test_falls_back_to_dev_url(self, caplog):
        """When SUPABASE_DB_URL missing and mode=dev, falls back to SUPABASE_DB_URL_DEV."""
        s = _create_settings_no_env_file(
            SUPABASE_DB_URL_DEV="postgresql://dev.example.com/db",
            SUPABASE_MODE="dev",
        )
        with caplog.at_level(logging.INFO):
            url = s.get_db_url()
        assert url == "postgresql://dev.example.com/db"
        assert "SUPABASE_DB_URL_DEV" in caplog.text

    def test_prod_mode_uses_prod_url(self):
        """In prod mode, SUPABASE_DB_URL_PROD is used."""
        s = _create_settings_no_env_file(
            SUPABASE_DB_URL_PROD="postgresql://prod.example.com/db",
            SUPABASE_MODE="prod",
        )
        assert s.get_db_url() == "postgresql://prod.example.com/db"

    def test_prod_prefers_direct_url(self):
        """In prod mode, SUPABASE_DB_URL_DIRECT_PROD is preferred."""
        s = _create_settings_no_env_file(
            SUPABASE_DB_URL_PROD="postgresql://pooler.example.com/db",
            SUPABASE_DB_URL_DIRECT_PROD="postgresql://direct.example.com/db",
            SUPABASE_MODE="prod",
        )
        assert s.get_db_url() == "postgresql://direct.example.com/db"

    def test_raises_if_no_db_url(self):
        """Raises RuntimeError if no DB URL is available."""
        s = _create_settings_no_env_file(SUPABASE_MODE="dev")
        with pytest.raises(RuntimeError, match="Missing database URL"):
            s.get_db_url()


class TestCollisionGuard:
    """Tests for collision detection between canonical and deprecated keys.

    Note: On Windows, environment variables are case-insensitive, so LOG_LEVEL
    and log_level are the same variable. These tests only apply on Unix systems.
    """

    def test_allows_only_canonical(self):
        """No error when only canonical key is set."""
        s = _create_settings_no_env_file(LOG_LEVEL="DEBUG")
        assert s.LOG_LEVEL == "DEBUG"

    def test_allows_same_value_in_env(self):
        """No error when canonical and deprecated have the same value in env."""
        # Need to use actual env vars for collision detection
        env = _minimal_env() | {"LOG_LEVEL": "DEBUG", "log_level": "DEBUG"}
        with patch.dict(os.environ, env, clear=True):
            s = Settings(_env_file=None)  # type: ignore[call-arg]
            assert s.LOG_LEVEL == "DEBUG"

    @pytest.mark.skipif(
        os.name == "nt", reason="Windows env vars are case-insensitive; collision impossible"
    )
    def test_detects_collision_with_different_values_in_env(self):
        """Raises ValueError when canonical and deprecated have different values in env."""
        env = _minimal_env() | {"LOG_LEVEL": "DEBUG", "log_level": "INFO"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="Configuration collision detected"):
                Settings(_env_file=None)  # type: ignore[call-arg]

    @pytest.mark.skipif(
        os.name == "nt", reason="Windows env vars are case-insensitive; collision impossible"
    )
    def test_collision_message_includes_both_values(self):
        """The error message lists both conflicting values."""
        env = _minimal_env() | {"SUPABASE_MODE": "prod", "supabase_mode": "dev"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError) as exc_info:
                Settings(_env_file=None)  # type: ignore[call-arg]
            msg = str(exc_info.value)
            assert "SUPABASE_MODE" in msg
            assert "supabase_mode" in msg
            assert "prod" in msg
            assert "dev" in msg


class TestStartupDiagnostics:
    """Tests for log_startup_diagnostics function."""

    def test_logs_service_name(self, caplog):
        """Service name is logged."""
        env = _minimal_env() | {"SUPABASE_MODE": "dev"}
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with caplog.at_level(logging.INFO):
                log_startup_diagnostics("TestService")
            assert "TestService" in caplog.text

    def test_logs_environment(self, caplog):
        """Environment is logged."""
        env = _minimal_env() | {"ENVIRONMENT": "staging"}
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with caplog.at_level(logging.INFO):
                log_startup_diagnostics("TestService")
            assert "staging" in caplog.text

    def test_logs_db_url_status(self, caplog):
        """DB URL configured status is logged."""
        env = _minimal_env() | {"SUPABASE_DB_URL": "postgresql://test/db"}
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with caplog.at_level(logging.INFO):
                log_startup_diagnostics("TestService")
            assert "DB URL Set" in caplog.text
            assert "✓" in caplog.text

    def test_logs_service_key_status(self, caplog):
        """Service key validity is logged."""
        env = _minimal_env()  # Has valid 120-char key
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with caplog.at_level(logging.INFO):
                log_startup_diagnostics("TestService")
            assert "Service Key OK" in caplog.text
            assert "✓" in caplog.text

    def test_handles_invalid_settings_gracefully(self, caplog, monkeypatch):
        """Doesn't crash if settings fail to load."""

        # Mock get_settings to raise an exception
        def mock_get_settings():
            raise RuntimeError("Test error: cannot load settings")

        import src.core_config

        monkeypatch.setattr(src.core_config, "get_settings", mock_get_settings)

        with caplog.at_level(logging.ERROR):
            # This should not raise, just log an error
            log_startup_diagnostics("TestService")

        # The function should have caught the error and logged it
        assert "TestService" in caplog.text
        assert "Failed to load settings" in caplog.text
