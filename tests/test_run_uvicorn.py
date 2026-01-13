from __future__ import annotations

import importlib
from unittest import mock

import pytest

import tools.run_uvicorn as run_uvicorn


def test_run_uvicorn_importable() -> None:
    module = importlib.reload(run_uvicorn)
    assert hasattr(module, "main")


def test_run_uvicorn_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("UVICORN_APP", "backend.main:app")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")

    with mock.patch("uvicorn.run") as mock_run:
        run_uvicorn.main()

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == "backend.main:app"
    assert kwargs["port"] == 8123
    assert kwargs["workers"] == 3
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["log_level"] == "warning"
    assert kwargs["proxy_headers"] is True
    assert kwargs["forwarded_allow_ips"] == "*"
