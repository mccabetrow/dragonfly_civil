"""Tests for backend.main startup behavior when .env files are missing."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

MODULES_TO_CLEAR: tuple[str, ...] = (
    "backend.main",
    "backend.config",
    "backend.core.bootstrap",
    "backend.core.config",
    "backend.core.config_guard",
    "src.core_config",
)


def _seed_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide the minimum env vars backend.main expects during import."""

    monkeypatch.setenv("SUPABASE_URL", "https://unit-test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k" * 120)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://dragonfly:pass@localhost:6543/postgres?sslmode=require",
    )
    monkeypatch.setenv("DRAGONFLY_API_KEY", "unit-test-key")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("SUPABASE_MODE", "dev")
    monkeypatch.setenv("DRAGONFLY_ENV", "dev")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.delenv("SUPABASE_MIGRATE_DB_URL", raising=False)
    monkeypatch.delenv("DRAGONFLY_ACTIVE_ENV", raising=False)


def _import_backend_main(monkeypatch: pytest.MonkeyPatch, project_root: Path):
    """Reload backend.main with a patched project root and return the module."""

    for name in MODULES_TO_CLEAR:
        sys.modules.pop(name, None)

    import backend.core.bootstrap as bootstrap

    bootstrap._PROJECT_ROOT = None  # type: ignore[attr-defined]
    monkeypatch.setattr(bootstrap, "_find_project_root", lambda: project_root)
    monkeypatch.delenv("DRAGONFLY_ACTIVE_ENV", raising=False)

    return importlib.import_module("backend.main")


def test_backend_main_tolerates_missing_env_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate /app deployments that lack .env files and ensure import stays safe."""

    _seed_runtime_env(monkeypatch)
    container_root = Path("/app")

    # Scenario 1: default .env.dev lookup under /app should warn, not crash
    monkeypatch.delenv("ENV_FILE", raising=False)
    missing_env_path = container_root / ".env.dev"

    try:
        module = _import_backend_main(monkeypatch, container_root)
    except FileNotFoundError as exc:  # pragma: no cover - explicitly fail with context
        pytest.fail(f"backend.main import should not fail when {missing_env_path} is absent: {exc}")

    assert hasattr(module, "app"), "backend.main should expose FastAPI app even without .env.dev"

    # Scenario 2: explicit ENV_FILE pointing to a nonexistent path still succeeds
    custom_env_file = container_root / "ghost.env"
    monkeypatch.setenv("ENV_FILE", custom_env_file.as_posix())

    module = _import_backend_main(monkeypatch, container_root)
    assert hasattr(module, "app"), "Explicit ENV_FILE pointing to missing file must not crash"
