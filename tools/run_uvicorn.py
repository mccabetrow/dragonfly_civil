#!/usr/bin/env python3
"""
Dragonfly Engine - Uvicorn Launcher

A robust entry point for production deployments that safely handles
environment variables and prevents crashes from misconfiguration.

Usage:
    python -m tools.run_uvicorn

Environment Variables:
    PORT            - Server port (default: 8080)
    HOST            - Server host (default: 0.0.0.0)
    UVICORN_APP     - ASGI app path (default: backend.main:app)
    WEB_CONCURRENCY - Worker count (default: 1, minimum: 1)
    LOG_LEVEL       - Uvicorn log level (default: info)

Author: Dragonfly DevOps
"""

from __future__ import annotations

import os
import sys


def get_int_env(name: str, default: int, minimum: int | None = None) -> int:
    """
    Safely read an integer from environment variable.

    Handles empty strings, non-numeric values, and enforces minimum.
    """
    raw = os.environ.get(name, "").strip()

    if not raw:
        return default

    try:
        value = int(raw)
    except ValueError:
        print(f"WARNING: {name}={raw!r} is not a valid integer, using default={default}")
        return default

    if minimum is not None and value < minimum:
        print(f"WARNING: {name}={value} is below minimum={minimum}, using {minimum}")
        return minimum

    return value


def get_str_env(name: str, default: str) -> str:
    """Safely read a string from environment variable."""
    raw = os.environ.get(name, "").strip()
    return raw if raw else default


def main() -> None:
    """Launch Uvicorn with safe environment variable handling."""
    # Import uvicorn here to fail fast if not installed
    try:
        import uvicorn
    except ImportError:
        print("ERROR: uvicorn is not installed. Run: pip install uvicorn")
        sys.exit(1)

    # Read configuration from environment
    port = get_int_env("PORT", default=8080, minimum=1)
    host = get_str_env("HOST", default="0.0.0.0")
    app = get_str_env("UVICORN_APP", default="backend.main:app")
    workers = get_int_env("WEB_CONCURRENCY", default=1, minimum=1)
    log_level = get_str_env("LOG_LEVEL", default="info").lower()

    # Validate log level
    valid_log_levels = ("critical", "error", "warning", "info", "debug", "trace")
    if log_level not in valid_log_levels:
        print(f"WARNING: LOG_LEVEL={log_level!r} invalid, using 'info'")
        log_level = "info"

    # Print startup banner
    print("=" * 60)
    print("  DRAGONFLY UVICORN LAUNCHER")
    print("=" * 60)
    print(f"  App:     {app}")
    print(f"  Host:    {host}")
    print(f"  Port:    {port}")
    print(f"  Workers: {workers}")
    print(f"  Log:     {log_level}")
    print("=" * 60)

    # Launch uvicorn with Railway/proxy-friendly settings
    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=workers,
        log_level=log_level,
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
