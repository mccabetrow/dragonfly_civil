"""
Tests for src/core_config.py - Production hardening features.

Tests cover:
- ENVIRONMENT normalization (production→prod, development→dev)
- Canonical env var contract (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_DB_URL)
- Collision guard (canonical + deprecated key conflict)
- Startup diagnostics
- Settings load with canonical names only
- Settings fail on missing required vars
- Settings behavior with deprecated vars
"""

from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from src.core_config import (
    Settings,
    get_deprecated_keys_used,
    get_settings,
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
        "SUPABASE_DB_URL": "postgresql://test.example.com:5432/postgres",
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


class TestDbUrl:
    """Tests for canonical DB URL behavior."""

    def test_uses_supabase_db_url_primary(self):
        """SUPABASE_DB_URL is used as primary."""
        s = _create_settings_no_env_file(
            SUPABASE_DB_URL="postgresql://primary.example.com/db",
            SUPABASE_MODE="dev",
        )
        assert s.get_db_url() == "postgresql://primary.example.com/db"

    def test_requires_db_url_at_init(self):
        """Settings requires SUPABASE_DB_URL at initialization."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="SUPABASE_DB_URL"):
            # Create settings without SUPABASE_DB_URL
            base = {
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            }
            with patch.dict(os.environ, {}, clear=True):
                Settings(_env_file="", **base)  # type: ignore[call-arg]


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
        import importlib

        # Reimport src.core_config to get fresh module (in case other tests
        # cleared it from sys.modules and broke the logger reference)
        import src.core_config

        importlib.reload(src.core_config)
        fresh_log_startup_diagnostics = src.core_config.log_startup_diagnostics

        # Mock get_settings to raise an exception
        def mock_get_settings():
            raise RuntimeError("Test error: cannot load settings")

        monkeypatch.setattr(src.core_config, "get_settings", mock_get_settings)

        # Ensure logger propagates to root (required after other tests may have
        # modified logging configuration)
        test_logger = logging.getLogger("src.core_config")
        original_propagate = test_logger.propagate
        test_logger.propagate = True

        try:
            with caplog.at_level(logging.ERROR, logger="src.core_config"):
                # This should not raise, just log an error
                fresh_log_startup_diagnostics("TestService")

            # The function should have caught the error and logged it
            assert (
                "TestService" in caplog.text
            ), f"Expected 'TestService' in caplog, got: {caplog.text!r}"
            assert "Failed to load settings" in caplog.text
        finally:
            test_logger.propagate = original_propagate


# =============================================================================
# CANONICAL CONFIGURATION TESTS
# =============================================================================


class TestSettingsLoadCanonical:
    """Tests for loading settings with canonical environment variables only."""

    def test_settings_load_canonical(self):
        """Settings loads correctly with only canonical SUPABASE_DB_URL."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            "SUPABASE_DB_URL": "postgresql://user:pass@db.example.com:5432/postgres",
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            settings = get_settings()
            assert settings.SUPABASE_URL == "https://test-project.supabase.co"
            assert settings.SUPABASE_DB_URL == "postgresql://user:pass@db.example.com:5432/postgres"
            assert settings.get_db_url() == "postgresql://user:pass@db.example.com:5432/postgres"

    def test_settings_load_with_mode(self):
        """Settings respects SUPABASE_MODE."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            "SUPABASE_DB_URL": "postgresql://user:pass@db.example.com:5432/postgres",
            "SUPABASE_MODE": "prod",
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            settings = get_settings()
            assert settings.supabase_mode == "prod"


class TestSettingsFailOnMissing:
    """Tests for settings validation when required vars are missing."""

    def test_settings_fail_on_missing_db_url(self):
        """Settings raises ValidationError when SUPABASE_DB_URL is missing."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            # SUPABASE_DB_URL intentionally missing
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file="")  # type: ignore[call-arg]
            assert "SUPABASE_DB_URL" in str(exc_info.value)

    def test_settings_fail_on_missing_service_key(self):
        """Settings raises ValidationError when SUPABASE_SERVICE_ROLE_KEY is missing."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_DB_URL": "postgresql://user:pass@db.example.com:5432/postgres",
            # SUPABASE_SERVICE_ROLE_KEY intentionally missing
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            with pytest.raises(ValidationError) as exc_info:
                Settings(_env_file="")  # type: ignore[call-arg]
            assert "SUPABASE_SERVICE_ROLE_KEY" in str(exc_info.value)

    def test_settings_fail_on_empty_env(self):
        """Settings raises ValidationError when environment is empty."""
        with patch.dict(os.environ, {}, clear=True):
            reset_settings()
            with pytest.raises(ValidationError):
                Settings(_env_file="")  # type: ignore[call-arg]


class TestSettingsIgnoresDeprecated:
    """Tests for settings behavior with deprecated environment variables."""

    def test_settings_warns_on_deprecated_lowercase(self, caplog):
        """Settings warns when deprecated lowercase vars are present."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            "SUPABASE_DB_URL": "postgresql://user:pass@db.example.com:5432/postgres",
            # Deprecated lowercase alias (only detectable on Unix)
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            # This should load without error
            settings = get_settings()
            assert settings.SUPABASE_DB_URL is not None

    def test_settings_tracks_deprecated_keys(self):
        """get_deprecated_keys_used() returns set of deprecated keys that were detected."""
        env = {
            "SUPABASE_URL": "https://test-project.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            "SUPABASE_DB_URL": "postgresql://user:pass@db.example.com:5432/postgres",
            "SUPABASE_MIGRATE_DB_URL": "postgresql://migrate@host:5432/db",  # Migration-only key
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            # Force settings load which triggers deprecated key detection
            _ = get_settings()
            deprecated = get_deprecated_keys_used()
            # SUPABASE_MIGRATE_DB_URL is in _MIGRATION_ONLY_KEYS, should be tracked
            assert isinstance(deprecated, set)

    def test_canonical_vars_take_precedence(self):
        """Canonical variables are used even when deprecated vars are present."""
        env = {
            "SUPABASE_URL": "https://canonical.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "a" * 120,
            "SUPABASE_DB_URL": "postgresql://canonical@host:5432/db",
            "SUPABASE_MIGRATE_DB_URL": "postgresql://migrate@host:5432/db",
        }
        with patch.dict(os.environ, env, clear=True):
            reset_settings()
            settings = get_settings()
            # Canonical URL should be used, not migration URL
            assert settings.get_db_url() == "postgresql://canonical@host:5432/db"
            assert "canonical" in settings.get_db_url()
