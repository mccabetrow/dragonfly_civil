"""Integration-style tests for WebCivil session lifecycle helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List
from unittest import mock

import pytest

from . import session_manager

SKIP_DESTRUCTIVE = os.environ.get("SKIP_AUTH_DESTRUCTIVE") == "1"


@pytest.fixture()
def isolated_session_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Route session persistence to a temporary path for destructive tests."""

    temp_session_path = tmp_path / "session.json"
    monkeypatch.setenv("ENCRYPT_SESSIONS", "false")
    monkeypatch.delenv("SESSION_KMS_KEY", raising=False)
    monkeypatch.setattr(session_manager, "SESSION_PATH", temp_session_path, raising=False)
    monkeypatch.setattr(session_manager.load_session, "__defaults__", (temp_session_path,))
    monkeypatch.setattr(session_manager.save_session, "__defaults__", (temp_session_path,))
    return temp_session_path


@pytest.mark.skipif(SKIP_DESTRUCTIVE, reason="Skipping destructive auth tests per environment flag")
def test_login_and_persist_session(isolated_session_path: Path) -> None:
    fake_cookies: List[dict] = [
        {"name": "JSESSIONID", "value": "abc123", "domain": "example.com", "path": "/"},
        {"name": "OTHER", "value": "xyz", "domain": "example.com", "path": "/"},
    ]

    with mock.patch("etl.src.auth.login.run_login", return_value=fake_cookies) as run_login_mock:
        cookies = session_manager.ensure_session()

    assert run_login_mock.call_count == 1
    assert isolated_session_path.exists()
    assert any(cookie["name"] == "JSESSIONID" for cookie in cookies)


@pytest.mark.skipif(SKIP_DESTRUCTIVE, reason="Skipping destructive auth tests per environment flag")
def test_reuse_session_fast(isolated_session_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cached_cookies: List[dict] = [
        {"name": "JSESSIONID", "value": "cached", "domain": "example.com", "path": "/"},
    ]

    monkeypatch.setattr(session_manager, "validate_session", lambda cookies: True)

    with mock.patch("etl.src.auth.login.run_login", return_value=cached_cookies) as run_login_mock:
        first = session_manager.ensure_session()
        second = session_manager.ensure_session()

    assert first == cached_cookies
    assert second == cached_cookies
    run_login_mock.assert_called_once()


@pytest.mark.skipif(SKIP_DESTRUCTIVE, reason="Skipping destructive auth tests per environment flag")
def test_validate_session_refresh(
    isolated_session_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_cookies: List[dict] = [
        {"name": "JSESSIONID", "value": "stale", "domain": "example.com", "path": "/"},
    ]
    isolated_session_path.write_text(json.dumps(stale_cookies), encoding="utf-8")
    try:
        isolated_session_path.chmod(0o600)
    except PermissionError:  # pragma: no cover - Windows fallback
        pass

    validation_calls = {"count": 0}

    def fake_validate(cookies: List[dict]) -> bool:
        validation_calls["count"] += 1
        return False

    monkeypatch.setattr(session_manager, "validate_session", fake_validate)

    refreshed_cookies: List[dict] = [
        {"name": "JSESSIONID", "value": "fresh", "domain": "example.com", "path": "/"},
    ]

    with mock.patch(
        "etl.src.auth.login.run_login", return_value=refreshed_cookies
    ) as run_login_mock:
        cookies = session_manager.ensure_session(refresh_if_invalid=True)

    assert cookies == refreshed_cookies
    assert run_login_mock.call_count == 1
    assert validation_calls["count"] == 1
