"""
Import Integrity Test Suite

Validates boot safety guarantees for backend.main:
1. All referenced middleware/router modules exist in the package
2. backend.main imports successfully in a minimal environment (no .env, no optional modules)
3. Optional modules degrade gracefully without crashing

This suite simulates a minimal container layout to catch packaging failures in CI.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# =============================================================================
# EXPECTED MODULE MANIFEST
# =============================================================================

# Required middleware - MUST exist for production boot
REQUIRED_MIDDLEWARE_MODULES = [
    "backend.middleware.correlation",
    "backend.middleware.metrics",
    "backend.middleware.version",
    "backend.core.middleware",
    "backend.core.trace_middleware",
]

# Required router modules - MUST exist for production boot
REQUIRED_ROUTER_MODULES = [
    "backend.api.routers.health",
    "backend.api.routers.dashboard",
    "backend.api.routers.cases",
    "backend.api.routers.enforcement",
    "backend.api.routers.intake",
    "backend.api.routers.ingest",
    "backend.api.routers.analytics",
]

# Optional modules - should degrade gracefully if missing
OPTIONAL_MODULES = [
    "backend.api.routers.metrics",
]


class TestModuleManifestExists:
    """Verify all declared modules exist in the package (packaging guarantee)."""

    @pytest.mark.parametrize("module_path", REQUIRED_MIDDLEWARE_MODULES)
    def test_required_middleware_exists(self, module_path: str) -> None:
        """Required middleware modules must exist in the built package."""
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Required middleware module not found: {module_path}"

    @pytest.mark.parametrize("module_path", REQUIRED_ROUTER_MODULES)
    def test_required_router_exists(self, module_path: str) -> None:
        """Required router modules must exist in the built package."""
        spec = importlib.util.find_spec(module_path)
        assert spec is not None, f"Required router module not found: {module_path}"


class TestBootSafeImport:
    """Verify backend.main imports in a minimal environment."""

    def test_backend_main_imports_in_minimal_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """backend.main must import even with minimal env vars."""
        # Clear potentially problematic env vars to simulate container startup
        for var in [
            "DRAGONFLY_CORS_ORIGINS",
            "RAILWAY_GIT_COMMIT_SHA",
            "VERCEL_GIT_COMMIT_SHA",
        ]:
            monkeypatch.delenv(var, raising=False)

        # Force reimport
        monkeypatch.delitem(sys.modules, "backend.main", raising=False)

        # Import must succeed
        module = importlib.import_module("backend.main")

        # App object must exist
        assert hasattr(module, "app"), "backend.main must expose 'app' object"

    def test_backend_main_survives_missing_optional_router(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """backend.main boots even if optional routers are missing."""

        class BlockOptionalModules:
            """Meta path finder that blocks optional modules."""

            def find_spec(self, fullname, path=None, target=None):
                if fullname in OPTIONAL_MODULES:
                    raise ModuleNotFoundError(f"Simulated missing: {fullname}")
                return None

        # Remove cached optional modules
        for mod in OPTIONAL_MODULES:
            monkeypatch.delitem(sys.modules, mod, raising=False)

        # Insert blocker before other finders
        monkeypatch.setattr(sys, "meta_path", [BlockOptionalModules(), *sys.meta_path])

        # Force reimport
        monkeypatch.delitem(sys.modules, "backend.main", raising=False)

        # Import must succeed
        module = importlib.import_module("backend.main")
        assert hasattr(module, "app"), "App must exist even with missing optional modules"


class TestMiddlewareGracefulDegradation:
    """Verify middleware imports degrade gracefully."""

    def test_correlation_middleware_degradation_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Missing CorrelationMiddleware logs CRITICAL but doesn't crash."""

        class BlockCorrelation:
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "backend.middleware.correlation":
                    raise ModuleNotFoundError("Simulated missing correlation")
                return None

        monkeypatch.delitem(sys.modules, "backend.middleware.correlation", raising=False)
        monkeypatch.setattr(sys, "meta_path", [BlockCorrelation(), *sys.meta_path])
        monkeypatch.delitem(sys.modules, "backend.main", raising=False)

        with caplog.at_level("CRITICAL"):
            module = importlib.import_module("backend.main")

        assert module._CORRELATION_MIDDLEWARE_AVAILABLE is False
        assert any(
            "CorrelationMiddleware missing" in record.message
            for record in caplog.records
            if record.levelname == "CRITICAL"
        )


class TestContainerLayoutSimulation:
    """Simulate container /app layout to catch path issues."""

    def test_relative_imports_resolve_correctly(self) -> None:
        """All relative imports in backend.main must resolve."""
        # This test catches the actual production failure mode:
        # ModuleNotFoundError: No module named 'backend.middleware.correlation'

        backend_main_path = Path(__file__).parent.parent / "backend" / "main.py"
        assert backend_main_path.exists(), "backend/main.py must exist"

        # Read the file and extract all relative imports
        content = backend_main_path.read_text(encoding="utf-8")
        import re

        # Pattern for relative imports: from .something import ...
        relative_imports = re.findall(r"from \.([\w.]+) import", content)

        for rel_import in relative_imports:
            full_module = f"backend.{rel_import}"
            spec = importlib.util.find_spec(full_module)
            assert spec is not None, (
                f"Relative import '.{rel_import}' resolves to '{full_module}' "
                f"which does not exist. This will crash in production container."
            )
