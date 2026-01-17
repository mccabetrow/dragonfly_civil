"""Runtime configuration guard regression tests."""

from __future__ import annotations

import importlib
import sys
import types

import pytest

# Module-level reference, set fresh by the reset_execution_mode fixture
config_guard = None  # type: ignore[assignment]


def _get_config_guard():
    """Get a fresh config_guard module, handling cases where it was removed from sys.modules."""
    # If module was removed from sys.modules by another test, reimport it
    if "backend.core.config_guard" not in sys.modules:
        import backend.core.config_guard as cg

        return cg
    else:
        from backend.core import config_guard as cg

        # Reload to get the real implementation (conftest.py mocks it)
        return importlib.reload(cg)


@pytest.fixture(autouse=True)
def reset_execution_mode(monkeypatch):
    """Ensure each test starts with a clean execution-mode cache and env."""
    # Get fresh module (handles case where other tests cleared sys.modules)
    cg = _get_config_guard()
    # Make it available as a module-level binding for tests
    global config_guard
    config_guard = cg

    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]
    monkeypatch.delenv("DRAGONFLY_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("SUPABASE_MIGRATE_DB_URL", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DRAGONFLY_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
    yield
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]


def _set_prod_runtime_env(monkeypatch, db_url: str) -> None:
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SUPABASE_DB_URL", db_url)
    # Production requires API key
    monkeypatch.setenv("DRAGONFLY_API_KEY", "test-api-key-for-testing")


def _valid_pooler_url() -> str:
    """Return a valid Supabase pooler URL that passes all production checks."""
    return (
        "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
    )


def test_runtime_guard_blocks_migrate_url(monkeypatch):
    _set_prod_runtime_env(monkeypatch, _valid_pooler_url())
    monkeypatch.setenv("SUPABASE_MIGRATE_DB_URL", "postgres://direct:5432/postgres")

    with pytest.raises(SystemExit):
        config_guard.validate_runtime_config()


def test_runtime_guard_allows_migrate_url_in_scripts_mode(monkeypatch):
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "script")
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SUPABASE_DB_URL", _valid_pooler_url())
    monkeypatch.setenv("SUPABASE_MIGRATE_DB_URL", "postgres://direct:5432/postgres")

    # Should no-op because scripts mode bypasses runtime guard
    config_guard.validate_runtime_config()


def test_runtime_guard_requires_pooler_port(monkeypatch):
    # Wrong port (5432 instead of 6543) - should fail even with pooler hostname
    bad_url = (
        "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )
    _set_prod_runtime_env(monkeypatch, bad_url)

    with pytest.raises(SystemExit):
        config_guard.validate_runtime_config()


def test_runtime_guard_rejects_direct_connection_port_5432(monkeypatch):
    """Direct connection (db.*.supabase.co:5432) should be rejected."""
    # Port 5432 is direct connection, should fail
    bad_url = "postgresql://user:pass@db.abcdefg.supabase.co:5432/postgres?sslmode=require"
    _set_prod_runtime_env(monkeypatch, bad_url)

    with pytest.raises(SystemExit):
        config_guard.validate_runtime_config()


def test_runtime_guard_accepts_dedicated_pooler(monkeypatch):
    """Dedicated pooler (db.*.supabase.co:6543) should be accepted."""
    # Port 6543 with db.*.supabase.co is the dedicated pooler format
    good_url = "postgresql://user:pass@db.abcdefg.supabase.co:6543/postgres?sslmode=require"
    _set_prod_runtime_env(monkeypatch, good_url)

    # Should NOT raise - dedicated pooler is valid
    config_guard.validate_runtime_config()


def test_runtime_guard_requires_sslmode_require(monkeypatch):
    # URL with correct pooler host and port, but missing sslmode
    bad_url = "postgresql://user:pass@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    _set_prod_runtime_env(monkeypatch, bad_url)

    with pytest.raises(SystemExit):
        config_guard.validate_runtime_config()


def test_runtime_guard_passes_with_valid_configuration(monkeypatch):
    _set_prod_runtime_env(monkeypatch, _valid_pooler_url())
    config_guard.validate_runtime_config()


def test_execution_mode_env_override(monkeypatch):
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "script")
    importlib.reload(config_guard)
    assert config_guard.is_scripts_mode()
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]


def test_execution_mode_runtime_override(monkeypatch):
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]
    monkeypatch.setenv("DRAGONFLY_EXECUTION_MODE", "runtime")
    assert config_guard.is_runtime_mode()


def test_execution_mode_detects_scripts_from_main(monkeypatch):
    fake_main = types.ModuleType("__main__")
    fake_main.__spec__ = types.SimpleNamespace(name="tools.db_push")
    fake_main.__name__ = "__main__"
    monkeypatch.setitem(sys.modules, "__main__", fake_main)
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]
    assert config_guard.is_scripts_mode()


def test_execution_mode_defaults_to_runtime(monkeypatch):
    config_guard._reset_execution_mode_cache()  # type: ignore[attr-defined]
    monkeypatch.delenv("DRAGONFLY_EXECUTION_MODE", raising=False)
    assert config_guard.is_runtime_mode()
