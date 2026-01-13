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
    """Valid pooler DSN should return empty violations list."""
    violations = validate_prod_dsn.validate_supabase_dsn(GOOD_URL)
    assert violations == [], f"Expected no violations but got: {violations}"


@pytest.mark.parametrize(
    "url, expected",
    [
        (_build_url(host="db.supabase.co"), "DIRECT connection"),
        (_build_url(port=5432), "5432 is DIRECT"),
        (_build_url(ssl_clause="sslmode"), "sslmode"),
        (_build_url(username="postgres"), "postgres.<project_ref>"),
    ],
)
def test_validate_supabase_dsn_failures(url: str, expected: str) -> None:
    """Invalid DSNs should return violations list with expected text."""
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert len(violations) > 0, f"Expected violations for {url}"
    combined = " ".join(violations)
    assert expected in combined, f"Expected '{expected}' in violations: {violations}"


def test_main_exits_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() should exit 1 with usage message when no env or arg provided."""
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["validate_prod_dsn"])  # No args
    # With no args and no env, main prints usage and exits 1
    result = validate_prod_dsn.main()
    assert result == 1


def test_main_succeeds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """main() should succeed when SUPABASE_DB_URL is set to valid pooler DSN."""
    monkeypatch.setenv("SUPABASE_DB_URL", GOOD_URL)
    monkeypatch.setattr("sys.argv", ["validate_prod_dsn"])  # Use env var
    assert validate_prod_dsn.main() == 0
    out = capsys.readouterr().out
    assert "VALID" in out
