"""Smoke tests for the uvicorn launcher modules.

These tests ensure the modules import cleanly and expose a callable
``main`` entrypoint, without actually starting a server.
"""

import importlib


def test_tools_run_uvicorn_imports() -> None:
    module = importlib.import_module("tools.run_uvicorn")
    assert hasattr(module, "main")
    assert callable(module.main)


def test_tools_run_uvicorn_shim_imports() -> None:
    module = importlib.import_module("tools_run_uvicorn")
    assert hasattr(module, "main")
    assert callable(module.main)
