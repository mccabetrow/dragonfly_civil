#!/usr/bin/env python3
"""Compatibility shim so `python -m tools_run_uvicorn` keeps working."""

from tools.run_uvicorn import main

if __name__ == "__main__":
    main()
