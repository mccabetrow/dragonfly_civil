"""Tests for runtime database configuration guard."""

from __future__ import annotations

import importlib
import sys

import pytest


def _get_validate_db_config():
    """Get the REAL validate_db_config function (not the mocked one from conftest)."""
    # Ensure the module is loaded fresh
    if "backend.core.config_guard" not in sys.modules:
        import backend.core.config_guard as cg
    else:
        import backend.core.config_guard as cg

        cg = importlib.reload(cg)
    return cg.validate_db_config


def _get_validate_runtime_config():
    """Get the REAL validate_runtime_config function (strict prod checks)."""
    if "backend.core.config_guard" not in sys.modules:
        import backend.core.config_guard as cg
    else:
        import backend.core.config_guard as cg

        cg = importlib.reload(cg)
    return cg.validate_runtime_config


_DEF_VARS = (
    "ENVIRONMENT",
    "DRAGONFLY_ENV",
    "RAILWAY_ENVIRONMENT",
    "SUPABASE_DB_URL",
    "DATABASE_URL",
    "SUPABASE_MIGRATE_DB_URL",
    "DRAGONFLY_EXECUTION_MODE",
)


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _DEF_VARS:
        monkeypatch.delenv(var, raising=False)


def _set_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("DRAGONFLY_ENV", "prod")
    # Force runtime mode so validate_db_config actually validates
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")


def test_validate_db_config_allows_pooler_in_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws.supabase.co:6543/postgres?sslmode=require",
    )

    validate_db_config = _get_validate_db_config()
    validate_db_config()


def test_validate_db_config_fatal_on_direct_port(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws.supabase.co:5432/postgres?sslmode=require",
    )

    validate_db_config = _get_validate_db_config()
    with pytest.raises(SystemExit):
        validate_db_config()


def test_validate_db_config_warns_when_ssl_missing(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws.supabase.co:6543/postgres",
    )
    caplog.set_level("WARNING")

    validate_db_config = _get_validate_db_config()
    validate_db_config()

    assert any("sslmode" in record.message for record in caplog.records)


def test_validate_db_config_fatal_when_migrate_url_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws.supabase.co:6543/postgres?sslmode=require",
    )
    monkeypatch.setenv(
        "SUPABASE_MIGRATE_DB_URL",
        "postgresql://svc:pass@aws.supabase.co:5432/postgres",
    )

    validate_db_config = _get_validate_db_config()
    with pytest.raises(SystemExit):
        validate_db_config()


# =============================================================================
# Strengthened DSN Contract Tests (host + port + sslmode)
# Uses validate_runtime_config() which has strict prod enforcement
# =============================================================================


def test_validate_runtime_config_fatal_on_non_pooler_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production must use *.pooler.supabase.com host, not db.*.supabase.co."""
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    # Direct connection host (db.* pattern) with correct port/ssl
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@db.abc123.supabase.co:6543/postgres?sslmode=require",
    )

    validate_runtime_config = _get_validate_runtime_config()
    with pytest.raises(SystemExit):
        validate_runtime_config()


def test_validate_runtime_config_fatal_on_missing_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production requires explicit sslmode=require."""
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    # Correct pooler host and port, but missing sslmode
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    )

    validate_runtime_config = _get_validate_runtime_config()
    with pytest.raises(SystemExit):
        validate_runtime_config()


def test_validate_runtime_config_fatal_on_wrong_sslmode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production requires sslmode=require, not prefer or disable."""
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://svc:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=prefer",
    )

    validate_runtime_config = _get_validate_runtime_config()
    with pytest.raises(SystemExit):
        validate_runtime_config()


def test_validate_runtime_config_allows_valid_pooler_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid DSN with pooler host, port 6543, sslmode=require passes."""
    _clear_env(monkeypatch)
    _set_prod_env(monkeypatch)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres.ref:pw@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require",
    )

    validate_runtime_config = _get_validate_runtime_config()
    # Should not raise
    validate_runtime_config()
