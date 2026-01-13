from __future__ import annotations

import importlib
import sys
import types

import pytest
from fastapi import APIRouter, FastAPI

MODULE_UNDER_TEST = "backend.main"
METRICS_MODULE = "backend.api.routers.metrics"


def _reload_backend_main(monkeypatch: pytest.MonkeyPatch):
    """Remove cached backend.main so that import side-effects rerun."""
    monkeypatch.delitem(sys.modules, MODULE_UNDER_TEST, raising=False)
    return importlib.import_module(MODULE_UNDER_TEST)


def test_backend_main_import_survives_missing_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate metrics module missing and ensure backend.main still imports."""

    class _BlockMetricsFinder:
        def find_spec(self, fullname, path=None, target=None):  # type: ignore[override]
            if fullname == METRICS_MODULE:
                raise ModuleNotFoundError("simulated missing metrics module")
            return None

    monkeypatch.delitem(sys.modules, METRICS_MODULE, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_BlockMetricsFinder(), *sys.meta_path])

    module = _reload_backend_main(monkeypatch)

    assert getattr(module, "metrics_router", None) is None


def test_backend_main_includes_metrics_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a dummy metrics router and ensure it is wired into FastAPI."""

    dummy_router = APIRouter()
    dummy_module = types.SimpleNamespace(router=dummy_router)
    monkeypatch.setitem(sys.modules, METRICS_MODULE, dummy_module)

    module = _reload_backend_main(monkeypatch)

    include_calls: list[object] = []
    original_include = FastAPI.include_router

    def spy_include(self, router, *args, **kwargs):  # type: ignore[override]
        include_calls.append(router)
        return original_include(self, router, *args, **kwargs)

    monkeypatch.setattr(FastAPI, "include_router", spy_include)

    module.create_app()

    assert dummy_router in include_calls
