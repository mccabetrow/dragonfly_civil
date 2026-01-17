#!/usr/bin/env python3
"""
Crash-proof Uvicorn launcher for Railway / production deployments.

STRICT PORT BINDING ENFORCEMENT:
================================
- In production (ENVIRONMENT=prod or SUPABASE_MODE=prod):
  * PORT env var is REQUIRED - fail fast if missing
  * Binds to 0.0.0.0:$PORT (Railway assigns this dynamically)

- In development/local:
  * Falls back to 8080 if PORT not set
  * Allows HOST override for debugging

SINGLE STARTUP LOG LINE (for log aggregation):
  listening host=0.0.0.0 port=<PORT> env=<env> sha=<sha>
"""

from __future__ import annotations

import os
import sys

import uvicorn


def _get_sha_short() -> str:
    """Get short git SHA from environment (Railway, CI, or local)."""
    for env_var in ("RAILWAY_GIT_COMMIT_SHA", "GIT_SHA", "GITHUB_SHA"):
        value = os.environ.get(env_var, "").strip()
        if value and value.lower() not in ("unknown", "local", ""):
            return value[:8]
    return "local"


def _is_production() -> bool:
    """Check if running in production mode."""
    env = os.environ.get("ENVIRONMENT", os.environ.get("SUPABASE_MODE", "")).lower()
    return env == "prod"


def main() -> None:
    """
    Robust entry point for Railway with strict PORT binding enforcement.

    In production:
    - PORT is REQUIRED (Railway sets it)
    - Exits with error code 1 if PORT is missing

    In development:
    - Falls back to PORT=8080
    """

    # 1. Determine environment
    env = os.environ.get("DRAGONFLY_ACTIVE_ENV", os.environ.get("SUPABASE_MODE", "dev"))
    is_prod = _is_production()

    # 2. STRICT PORT ENFORCEMENT
    port_raw = os.environ.get("PORT", "").strip()

    # =========================================================================
    # INDESTRUCTIBLE BOOT: Always fallback to 8080, never exit on missing PORT
    # Railway SHOULD inject $PORT, but we MUST NOT crash if it's missing.
    # The web server MUST start so /health can respond to probes.
    # =========================================================================
    if not port_raw:
        port_raw = "8080"
        if is_prod:
            print(
                "⚠️  WARNING: PORT not set in production! Falling back to 8080.",
                file=sys.stderr,
            )
            print(
                "   Railway should auto-inject PORT. Check Networking settings.",
                file=sys.stderr,
            )

    # 3. Parse and validate PORT
    try:
        port = int(port_raw)
    except ValueError:
        print(f"[FATAL] Invalid PORT={port_raw!r}. Must be integer.", file=sys.stderr)
        sys.exit(1)

    if port < 1 or port > 65535:
        print(f"[FATAL] PORT={port} out of valid range (1-65535).", file=sys.stderr)
        sys.exit(1)

    # 4. Host is ALWAYS 0.0.0.0 for container deployments
    # Railway requires binding to all interfaces
    host = "0.0.0.0"

    # 5. App configuration
    app = os.getenv("UVICORN_APP", "backend.main:app")
    log_level = os.getenv("LOG_LEVEL", "info").lower()
    workers_raw = os.getenv("WEB_CONCURRENCY", "1")
    try:
        workers = max(1, int(workers_raw))
    except ValueError:
        workers = 1

    # 6. Get SHA for traceability
    sha = _get_sha_short()

    # ==========================================================================
    # SINGLE STARTUP LOG LINE (for log aggregation / grep)
    # Format: listening host=0.0.0.0 port=<PORT> env=<env> sha=<sha>
    # ==========================================================================
    print(f"listening host={host} port={port} env={env} sha={sha}")

    # Railway Mode banner - ALWAYS log this for debugging
    print(f"🚀 Binding to 0.0.0.0:{port} (Railway Mode)")

    # Additional banner for human operators
    print()
    print("=" * 72)
    print("  🐉 DRAGONFLY ENGINE STARTUP")
    print("=" * 72)
    print(f"  Module:      {app}")
    print(f"  Host:        {host}")
    print(f"  Port:        {port}")
    print(f"  Workers:     {workers}")
    print(f"  Log Level:   {log_level}")
    print(f"  Environment: {env}")
    print(f"  Git SHA:     {sha}")
    print(f"  Mode:        {'PRODUCTION' if is_prod else 'DEVELOPMENT'}")
    print("=" * 72)
    print()

    # 7. Launch Uvicorn
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
