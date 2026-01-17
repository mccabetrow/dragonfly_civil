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


def test_validate_supabase_dsn_valid_different_region() -> None:
    """Different region pooler DSN is valid."""
    url = _build_url(host="aws-0-eu-west-1.pooler.supabase.com")
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert violations == []


def test_validate_supabase_dsn_sslmode_uppercase() -> None:
    """sslmode=REQUIRE (uppercase) should be accepted."""
    url = _build_url(ssl_clause="sslmode=REQUIRE")
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert violations == []


@pytest.mark.parametrize(
    "url, expected",
    [
        # Direct connection (port 5432) should fail
        (_build_url(host="db.abc123.supabase.co", port=5432), "5432"),
        # Random host should fail
        (_build_url(host="some-random-host.com"), "pooler"),
        # Port 5432 on any host should fail
        (_build_url(port=5432), "5432"),
        # Non-standard port should fail
        (_build_url(port=5433), "6543"),
        # Missing sslmode should fail
        (_build_url(ssl_clause=""), "sslmode"),
        # Wrong sslmode should fail
        (_build_url(ssl_clause="sslmode=disable"), "sslmode"),
        (_build_url(ssl_clause="sslmode=prefer"), "sslmode"),
    ],
)
def test_validate_supabase_dsn_failures(url: str, expected: str) -> None:
    """Invalid DSNs should return violations list with expected text."""
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert len(violations) > 0, f"Expected violations for {url}"
    combined = " ".join(violations)
    assert expected in combined, f"Expected '{expected}' in violations: {violations}"


def test_validate_supabase_dsn_dedicated_pooler_valid() -> None:
    """Dedicated pooler (db.<ref>.supabase.co:6543) should be valid."""
    url = _build_url(host="db.abc123.supabase.co", port=6543)
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert violations == [], f"Expected no violations but got: {violations}"


def test_validate_supabase_dsn_multiple_violations() -> None:
    """DSN with multiple violations returns all errors."""
    url = "postgresql://user:pass@some-random-host.com:5432/postgres"
    violations = validate_prod_dsn.validate_supabase_dsn(url)
    assert len(violations) >= 2, f"Expected at least 2 violations but got: {violations}"


def test_validate_supabase_dsn_empty_url() -> None:
    """Empty URL returns violation."""
    violations = validate_prod_dsn.validate_supabase_dsn("")
    assert len(violations) >= 1
    assert any("empty" in v.lower() or "not set" in v.lower() for v in violations)


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


def test_main_fails_on_invalid_dsn(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """main() should exit 1 and print violations for invalid DSN."""
    bad_url = _build_url(host="db.xyz.supabase.co", port=5432, ssl_clause="")
    monkeypatch.setenv("SUPABASE_DB_URL", bad_url)
    monkeypatch.setattr("sys.argv", ["validate_prod_dsn"])
    result = validate_prod_dsn.main()
    assert result == 1
    out = capsys.readouterr().out
    assert "VIOLATION" in out or "✗" in out
