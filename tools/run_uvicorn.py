#!/usr/bin/env python3
"""Crash-proof Uvicorn launcher for Railway / production deployments."""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> None:
    """Robust entry point for Railway with defensive env handling."""

    # 1. Host Defaults
    host = os.getenv("HOST", "0.0.0.0")

    # 2. Port Safety (The Fix for 'str is not int')
    port_raw = os.getenv("PORT", "8080")
    try:
        port = int(port_raw)
    except ValueError:
        print(f"[FATAL] Invalid PORT={port_raw!r}. Must be integer.", file=sys.stderr)
        sys.exit(1)

    # 3. App Import Path
    app = os.getenv("UVICORN_APP", "backend.main:app")

    # 4. Worker Configuration
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    workers_raw = os.getenv("WEB_CONCURRENCY", "1")
    try:
        workers = max(1, int(workers_raw))
    except ValueError:
        workers = 1

    print(f"🚀 Starting Uvicorn: {app} on {host}:{port} (Workers: {workers})")

    # 5. Launch
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level,
        workers=workers,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
