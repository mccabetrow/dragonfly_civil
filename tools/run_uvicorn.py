#!/usr/bin/env python3
"""Crash-proof Uvicorn launcher for Railway / production deployments."""

from __future__ import annotations

import os
import sys

import uvicorn


def _parse_port(value: str) -> int:
    """Convert a PORT string to an int or exit with an error message."""

    try:
        return int(value)
    except ValueError:
        print(f"[FATAL] Invalid PORT={value!r}. Must be integer.", file=sys.stderr)
        sys.exit(1)


def _parse_workers(value: str) -> int:
    """Ensure WEB_CONCURRENCY resolves to a positive integer."""

    try:
        return max(1, int(value))
    except ValueError:
        return 1


def main() -> None:
    """Resolve configuration from env vars and boot uvicorn."""

    host = os.getenv("HOST", "0.0.0.0")
    port = _parse_port(os.getenv("PORT", "8080"))
    app = os.getenv("UVICORN_APP", "backend.main:app")
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    workers = _parse_workers(os.getenv("WEB_CONCURRENCY", "1"))

    print(f"🚀 Starting Uvicorn: {app} on {host}:{port} (Workers: {workers})")

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
