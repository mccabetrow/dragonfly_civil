from __future__ import annotations

import os

import pytest

from tools import validate_prod_dsn


def _build_url(
    *,
    username: str = "postgres.projectref",
    password: str = "pass",
    host: str = "aws-0-us-east-1.pooler.supabase.com",
    port: int = 6543,
    ssl_clause: str = "sslmode=require",
) -> str:
    return "postgresql" + "://" + f"{username}:{password}@{host}:{port}/postgres?{ssl_clause}"


GOOD_URL = _build_url()


def test_validate_supabase_dsn_happy_path() -> None:
    validate_prod_dsn._validate_supabase_dsn(GOOD_URL)


@pytest.mark.parametrize(
    "url, expected",
    [
        (_build_url(host="db.supabase.co"), "host"),
        (_build_url(port=5432), "port"),
        (_build_url(ssl_clause="sslmode"), "sslmode"),
        (_build_url(username="postgres"), "username"),
    ],
)
def test_validate_supabase_dsn_failures(url: str, expected: str) -> None:
    with pytest.raises(ValueError) as exc:
        validate_prod_dsn._validate_supabase_dsn(url)
    assert expected in str(exc.value)


def test_main_exits_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    with pytest.raises(SystemExit) as exc:
        validate_prod_dsn.main()
    assert exc.value.code == 1


def test_main_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("SUPABASE_DB_URL", GOOD_URL)
    assert validate_prod_dsn.main() == 0
    out = capsys.readouterr().out
    assert "OK" in out
