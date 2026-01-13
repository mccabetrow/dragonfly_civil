"""Regression tests for the production uvicorn launcher."""

from __future__ import annotations

from unittest import mock

import pytest


def test_tools_run_uvicorn_importable() -> None:
    """Fail loudly if the launcher module cannot be imported."""

    import tools.run_uvicorn  # noqa: F401


def test_launcher_uses_env_configuration(monkeypatch: "pytest.MonkeyPatch") -> None:
    """Ensure main() reads env vars and calls uvicorn.run with those values."""

    import importlib

    import tools.run_uvicorn as launcher

    monkeypatch.setenv("HOST", "127.0.0.9")
    monkeypatch.setenv("PORT", "9012")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("UVICORN_APP", "backend.main:app")
    monkeypatch.setenv("LOG_LEVEL", "warning")

    importlib.reload(launcher)

    with mock.patch("uvicorn.run") as mock_run:
        launcher.main()

    mock_run.assert_called_once()
    _, kwargs = mock_run.call_args
    assert kwargs["host"] == "127.0.0.9"
    assert kwargs["port"] == 9012
    assert kwargs["workers"] == 4
    assert kwargs["log_level"] == "warning"
