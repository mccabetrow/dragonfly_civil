"""
Tests for strict PORT binding enforcement in run_uvicorn.py.

These tests verify:
1. Production mode requires PORT env var (fail fast if missing)
2. Development mode falls back to PORT=8080
3. Single startup log line format is correct
4. Invalid PORT values are rejected
"""

from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestPortBindingProduction:
    """Tests for production PORT enforcement."""

    def test_production_fails_without_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        In production, missing PORT must cause immediate exit with code 1.

        This is fail-fast behavior to prevent silent binding failures.
        """
        # Set up production environment WITHOUT PORT
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("SUPABASE_MODE", "prod")
        monkeypatch.delenv("PORT", raising=False)

        from tools import run_uvicorn

        # Should exit with code 1
        with pytest.raises(SystemExit) as exc_info:
            run_uvicorn.main()

        assert exc_info.value.code == 1

    def test_production_succeeds_with_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        In production, PORT set correctly should proceed to uvicorn.run.
        """
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("SUPABASE_MODE", "prod")
        monkeypatch.setenv("PORT", "8080")

        from tools import run_uvicorn

        # Mock uvicorn.run to prevent actual server start
        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            # Verify uvicorn.run was called with correct port
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 8080
            assert call_kwargs["host"] == "0.0.0.0"

    def test_production_uses_railway_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Production should use Railway-assigned PORT (often dynamic like 3000, 5000, etc).
        """
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("PORT", "3000")  # Railway-assigned

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 3000


class TestPortBindingDevelopment:
    """Tests for development PORT fallback behavior."""

    def test_development_falls_back_to_8080(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        In development, missing PORT should fall back to 8080.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("SUPABASE_MODE", "dev")
        monkeypatch.delenv("PORT", raising=False)

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 8080

    def test_development_respects_port_if_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Development should still use PORT if explicitly set.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "9000")

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 9000


class TestStartupLogLine:
    """Tests for the single startup log line format."""

    def test_startup_log_format(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """
        Startup must emit a single log line with format:
        listening host=0.0.0.0 port=<PORT> env=<env> sha=<sha>
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv("DRAGONFLY_ACTIVE_ENV", "dev")
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc12345def67890")

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run"):
            run_uvicorn.main()

        captured = capsys.readouterr()

        # Check for the single startup log line
        assert "listening host=0.0.0.0 port=8080 env=dev sha=abc12345" in captured.out

    def test_startup_log_includes_sha(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """
        SHA should be included in startup log for traceability.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv("GIT_SHA", "fedcba98")

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run"):
            run_uvicorn.main()

        captured = capsys.readouterr()
        assert "sha=fedcba98" in captured.out

    def test_startup_log_sha_fallback_local(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """
        If no git SHA env var, should use 'local'.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
        monkeypatch.delenv("GIT_SHA", raising=False)
        monkeypatch.delenv("GITHUB_SHA", raising=False)

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run"):
            run_uvicorn.main()

        captured = capsys.readouterr()
        assert "sha=local" in captured.out


class TestPortValidation:
    """Tests for PORT value validation."""

    def test_invalid_port_string_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Non-numeric PORT should fail with exit code 1.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "not-a-number")

        from tools import run_uvicorn

        with pytest.raises(SystemExit) as exc_info:
            run_uvicorn.main()

        assert exc_info.value.code == 1

    def test_port_zero_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        PORT=0 should fail (out of valid range).
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "0")

        from tools import run_uvicorn

        with pytest.raises(SystemExit) as exc_info:
            run_uvicorn.main()

        assert exc_info.value.code == 1

    def test_port_negative_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Negative PORT should fail.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "-1")

        from tools import run_uvicorn

        with pytest.raises(SystemExit) as exc_info:
            run_uvicorn.main()

        assert exc_info.value.code == 1

    def test_port_too_high_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        PORT > 65535 should fail.
        """
        monkeypatch.setenv("ENVIRONMENT", "dev")
        monkeypatch.setenv("PORT", "70000")

        from tools import run_uvicorn

        with pytest.raises(SystemExit) as exc_info:
            run_uvicorn.main()

        assert exc_info.value.code == 1


class TestHostBinding:
    """Tests for host binding behavior."""

    def test_always_binds_to_all_interfaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Must always bind to 0.0.0.0 for container networking.
        """
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("PORT", "8080")

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["host"] == "0.0.0.0"

    def test_ignores_host_env_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        HOST env var should be ignored - always use 0.0.0.0.
        (Railway requires binding to all interfaces)
        """
        monkeypatch.setenv("ENVIRONMENT", "prod")
        monkeypatch.setenv("PORT", "8080")
        monkeypatch.setenv("HOST", "127.0.0.1")  # Should be ignored

        from tools import run_uvicorn

        with patch.object(run_uvicorn.uvicorn, "run") as mock_run:
            run_uvicorn.main()

            call_kwargs = mock_run.call_args[1]
            # Must be 0.0.0.0, not 127.0.0.1
            assert call_kwargs["host"] == "0.0.0.0"
