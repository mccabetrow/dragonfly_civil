"""
Tests for bootstrap resilience - ensuring the application boots
without .env files present (production mode).

This validates the "Optional Dotenv" pattern required for Railway deployments
where configuration comes from system environment variables.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest


def _seed_minimum_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Seed the minimum environment variables needed for boot.

    In production (Railway), these come from platform environment variables.
    For tests, we simulate this by setting them directly.
    """
    # Required for Supabase client initialization
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")

    # Database URL (pooler port for production)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://testuser:testpass@test.pooler.supabase.com:6543/postgres",  # noqa: S105
    )

    # Environment markers
    monkeypatch.setenv("SUPABASE_MODE", "dev")
    monkeypatch.setenv("DRAGONFLY_ENV", "dev")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """
    Fixture that clears env markers and seeds minimum required vars.

    This simulates a fresh Railway boot where no .env file exists
    but platform variables are set.
    """
    # Clear any existing env markers to simulate fresh boot
    monkeypatch.delenv("DRAGONFLY_ACTIVE_ENV", raising=False)

    # Seed minimum required environment variables
    _seed_minimum_env(monkeypatch)

    yield


class TestBootstrapEnvironment:
    """Test bootstrap_environment() resilience."""

    def test_bootstrap_without_env_file(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        Bootstrap should succeed when no .env file exists.

        This simulates Railway production where all config comes from
        platform environment variables, not .env files.
        """
        from backend.core.bootstrap import bootstrap_environment

        # Point to a temp directory that definitely has no .env files
        result = bootstrap_environment(
            cli_override="dev",
            project_root=tmp_path,
            verbose=False,  # Suppress banner for test output
        )

        assert result == "dev"
        assert os.environ.get("DRAGONFLY_ACTIVE_ENV") == "dev"
        assert os.environ.get("SUPABASE_MODE") == "dev"

    def test_bootstrap_prod_without_env_file(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        Bootstrap should succeed in prod mode without .env.prod file.

        This is the exact scenario in Railway production.
        """
        from backend.core.bootstrap import bootstrap_environment

        result = bootstrap_environment(
            cli_override="prod",
            project_root=tmp_path,
            verbose=False,
        )

        assert result == "prod"
        assert os.environ.get("DRAGONFLY_ACTIVE_ENV") == "prod"
        assert os.environ.get("SUPABASE_MODE") == "prod"

    def test_bootstrap_with_existing_env_file(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        Bootstrap should load variables from .env file when it exists.
        """
        from backend.core.bootstrap import bootstrap_environment

        # Create a minimal .env.dev file
        env_file = tmp_path / ".env.dev"
        env_file.write_text("TEST_VAR_FROM_FILE=hello_world\n")

        result = bootstrap_environment(
            cli_override="dev",
            project_root=tmp_path,
            verbose=False,
        )

        assert result == "dev"
        # The file's variable should be loaded
        assert os.environ.get("TEST_VAR_FROM_FILE") == "hello_world"

    def test_environment_variable_prevents_defaulting_to_dev(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ENVIRONMENT=prod takes priority even when .env.prod is missing."""

        from backend.core.bootstrap import bootstrap_environment

        monkeypatch.delenv("DRAGONFLY_ACTIVE_ENV", raising=False)
        monkeypatch.delenv("DRAGONFLY_ENV", raising=False)
        monkeypatch.delenv("SUPABASE_MODE", raising=False)
        monkeypatch.setenv("ENVIRONMENT", "production")

        result = bootstrap_environment(
            project_root=tmp_path,
            verbose=False,
        )

        assert result == "prod"
        assert os.environ.get("DRAGONFLY_ACTIVE_ENV") == "prod"

    def test_bootstrap_cli_override_takes_precedence(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        CLI override should take precedence over system env var.
        """
        from backend.core.bootstrap import bootstrap_environment

        # Set a conflicting system env var
        monkeypatch.setenv("DRAGONFLY_ACTIVE_ENV", "prod")

        result = bootstrap_environment(
            cli_override="dev",  # This should win
            project_root=tmp_path,
            verbose=False,
        )

        assert result == "dev"

    def test_bootstrap_invalid_env_raises_value_error(
        self, clean_env: None, tmp_path: Path
    ) -> None:
        """
        Bootstrap should reject invalid environment names.
        """
        from backend.core.bootstrap import bootstrap_environment

        with pytest.raises(ValueError, match="Invalid environment"):
            bootstrap_environment(
                cli_override="staging",  # Invalid - only dev/prod allowed
                project_root=tmp_path,
                verbose=False,
            )

    def test_bootstrap_never_raises_file_not_found_error(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Bootstrap MUST NEVER raise FileNotFoundError.

        This is the critical production resilience test. In Railway containers,
        .env files don't exist and the working directory might not match
        what the code expects. The bootstrap must handle this gracefully.
        """
        from backend.core.bootstrap import _find_project_root, bootstrap_environment

        # Test with a completely nonexistent path
        nonexistent_path = Path("/nonexistent/container/path")

        # This must NOT raise FileNotFoundError - it should fall back to system vars
        try:
            result = bootstrap_environment(
                cli_override="prod",
                project_root=nonexistent_path,
                verbose=False,
            )
        except FileNotFoundError as exc:
            pytest.fail(
                f"bootstrap_environment raised FileNotFoundError: {exc}. "
                "This breaks Railway production deployments!"
            )

        assert result == "prod"

    def test_find_project_root_handles_filesystem_errors(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        _find_project_root should handle filesystem errors gracefully.

        In containers, Path.cwd() might fail or return unexpected paths.
        The function must never crash.
        """
        import backend.core.bootstrap as bootstrap

        # Reset the cached project root
        bootstrap._PROJECT_ROOT = None

        # Mock Path.cwd() to raise an error (simulates broken container state)
        with patch.object(Path, "cwd", side_effect=OSError("No such directory")):
            # This must NOT raise - it should fall back to /app or similar
            try:
                root = bootstrap._find_project_root()
            except (OSError, FileNotFoundError) as exc:
                pytest.fail(f"_find_project_root raised {type(exc).__name__}: {exc}")

            # Should return some valid fallback path
            assert root is not None


class TestGetGitSha:
    """Test git SHA resolution for boot reports."""

    def test_git_sha_from_railway_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should prefer RAILWAY_GIT_COMMIT_SHA when set."""
        from backend.core.bootstrap import get_git_sha

        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123def456")

        sha = get_git_sha()

        assert sha == "abc123de"  # Truncated to 8 chars

    def test_git_sha_from_github_actions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should use GITHUB_SHA when Railway var not set."""
        from backend.core.bootstrap import get_git_sha

        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
        monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
        monkeypatch.setenv("GITHUB_SHA", "deadbeef12345678")

        sha = get_git_sha()

        assert sha == "deadbeef"

    def test_git_sha_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Should fall back to 'local-dev' when no git info available."""
        from backend.core.bootstrap import get_git_sha

        # Clear all git-related env vars
        for var in [
            "RAILWAY_GIT_COMMIT_SHA",
            "VERCEL_GIT_COMMIT_SHA",
            "GITHUB_SHA",
            "GIT_COMMIT",
            "GIT_SHA",
        ]:
            monkeypatch.delenv(var, raising=False)

        # Mock subprocess to simulate no git available
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")

            sha = get_git_sha()

        assert sha == "local-dev"


class TestCoreConfigOptionalEnvFile:
    """Test that src.core_config loads without .env file."""

    def test_settings_loads_without_env_file(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Settings class should initialize without raising FileNotFoundError.

        This is the critical test for Railway production boot.
        """
        # The fix in core_config.py makes env_file conditional on existence
        # If this import succeeds, the fix is working
        from src.core_config import Settings

        # Should not raise FileNotFoundError
        settings = Settings()

        # Basic sanity check
        assert settings.supabase_url == "https://test.supabase.co"

    def test_settings_with_env_file_override(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        When ENV_FILE points to an existing file, the helper function detects it.

        Note: Due to module-level evaluation of Pydantic's SettingsConfigDict,
        we test the helper function directly rather than the Settings class.
        """
        from src.core_config import _get_optional_env_file

        # Create a test env file
        env_file = tmp_path / "test.env"
        env_file.write_text("SUPABASE_URL=https://from-file.supabase.co\n")

        # When ENV_FILE is set and exists, the helper should return the path
        monkeypatch.setenv("ENV_FILE", str(env_file))

        result = _get_optional_env_file()

        assert result == str(env_file)

    def test_optional_env_file_returns_none_for_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Helper returns None when ENV_FILE points to non-existent file.
        """
        from src.core_config import _get_optional_env_file

        monkeypatch.setenv("ENV_FILE", "/nonexistent/path/.env.fake")

        result = _get_optional_env_file()

        assert result is None


class TestVerifyRuntimeEnv:
    """Test runtime environment verification."""

    def test_verify_runtime_passes_with_pooler(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should pass when using pooler port 6543."""
        from backend.core.bootstrap import verify_runtime_env

        monkeypatch.setenv(
            "SUPABASE_DB_URL",
            "postgresql://testuser:testpass@test.pooler.supabase.com:6543/postgres",  # noqa: S105
        )

        # Should not raise
        verify_runtime_env()

    def test_verify_runtime_blocks_migrate_url_in_prod(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Should raise when migration URL present in production."""
        from backend.core.bootstrap import RuntimeConfigurationError, verify_runtime_env

        monkeypatch.setenv("DRAGONFLY_ENV", "prod")
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv(
            "SUPABASE_MIGRATE_DB_URL",
            "postgresql://testuser:testpass@db.test.supabase.co:5432/postgres",  # noqa: S105
        )

        with pytest.raises(RuntimeConfigurationError, match="Migration URL"):
            verify_runtime_env()
