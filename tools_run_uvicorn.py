#!/usr/bin/env python3
"""
Dragonfly Engine - Uvicorn Launcher Compatibility Shim

This file exists for backwards compatibility with Railway deployments
that may use the underscore format: python -m tools_run_uvicorn

It simply imports and runs the main launcher from tools.run_uvicorn.
"""

from tools.run_uvicorn import main

if __name__ == "__main__":
    main()
