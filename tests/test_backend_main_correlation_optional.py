from __future__ import annotations

import importlib
import sys
import types

import pytest
from fastapi import FastAPI

MODULE_UNDER_TEST = "backend.main"
CORRELATION_MODULE = "backend.middleware.correlation"


def _reload_backend_main(monkeypatch: pytest.MonkeyPatch):
    """Force backend.main re-import so module-level side effects rerun."""
    monkeypatch.delitem(sys.modules, MODULE_UNDER_TEST, raising=False)
    return importlib.import_module(MODULE_UNDER_TEST)


def _simulate_missing_correlation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch import machinery so correlation module raises ModuleNotFoundError."""

    class _BlockCorrelationModule:
        def find_spec(self, fullname, path=None, target=None):  # type: ignore[override]
            if fullname == CORRELATION_MODULE:
                raise ModuleNotFoundError("simulated missing correlation middleware")
            return None

    monkeypatch.delitem(sys.modules, CORRELATION_MODULE, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BlockCorrelationModule(), *sys.meta_path])


def test_backend_main_missing_correlation_does_not_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    """If CorrelationMiddleware module is absent, backend.main still boots."""

    _simulate_missing_correlation(monkeypatch)
    module = _reload_backend_main(monkeypatch)

    assert getattr(module, "app", None) is not None
    assert module._CORRELATION_MIDDLEWARE_AVAILABLE is False


def test_backend_main_correlation_loaded_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """When CorrelationMiddleware exists, FastAPI registers it via add_middleware."""

    module = _reload_backend_main(monkeypatch)

    user_middlewares = getattr(module.app, "user_middleware", [])
    middleware_types = {entry.cls for entry in user_middlewares}

    assert module.CorrelationMiddleware in middleware_types
