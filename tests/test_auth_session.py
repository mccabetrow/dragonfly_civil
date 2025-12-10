from __future__ import annotations

import os


def test_session_roundtrip(tmp_path, monkeypatch):
    session_path = tmp_path / "sess.json"
    monkeypatch.setenv("SESSION_PATH", str(session_path))
    monkeypatch.setenv("ENCRYPT_SESSIONS", "false")

    from etl.src.auth import (
        ensure_session,
        get_requests_session_with_cookies,
        load_session,
        save_session,
    )

    payload = {"k": "v", "cookies": {"a": "b"}}
    save_session(payload)
    loaded = load_session()
    assert loaded["k"] == "v"

    requests_session = ensure_session()
    assert hasattr(requests_session, "cookies")
    assert requests_session.cookies.get("a") == "b"
