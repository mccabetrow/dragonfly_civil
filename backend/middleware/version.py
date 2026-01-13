"""
Dragonfly Engine - Version Middleware

Injects Git commit SHA and environment into every HTTP response header
for full traceability of API responses and log correlation.

Headers added:
  - X-Dragonfly-SHA: The Git commit SHA (or "local-dev" for local dev)
  - X-Dragonfly-Env: The environment name (prod/dev/staging)
  - X-Dragonfly-Version: The package version

Usage:
    from backend.middleware.version import VersionMiddleware
    app.add_middleware(VersionMiddleware)
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# SHA resolution order (checked at import time)
_SHA_ENV_VARS = [
    "RAILWAY_GIT_COMMIT_SHA",  # Railway deployment (primary)
    "VERCEL_GIT_COMMIT_SHA",  # Vercel deployment
    "GITHUB_SHA",  # GitHub Actions
    "GIT_COMMIT",  # Jenkins / generic CI
    "GIT_SHA",  # Manual override
]


@dataclass(frozen=True)
class ShaResolution:
    """Result of SHA resolution with provenance tracking."""

    sha_full: str
    sha_short: str
    source: str  # Which env var or "git" or "fallback"


def _find_project_root() -> Path:
    """Find the project root by looking for pyproject.toml."""
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


def _resolve_git_sha() -> ShaResolution:
    """
    Resolve the current git commit SHA from environment or local git.

    Resolution order:
        1. RAILWAY_GIT_COMMIT_SHA (Railway deployment - primary)
        2. VERCEL_GIT_COMMIT_SHA (Vercel deployment)
        3. GITHUB_SHA (GitHub Actions CI)
        4. GIT_COMMIT (Jenkins / generic CI)
        5. GIT_SHA (Manual override)
        6. Local git rev-parse HEAD (local development)
        7. Fallback: "local-dev"

    Returns:
        ShaResolution with full SHA, 8-char short SHA, and source
    """
    # Check environment variables in priority order
    for env_var in _SHA_ENV_VARS:
        value = os.environ.get(env_var, "").strip()
        if value and value.lower() not in ("unknown", "local", ""):
            sha_short = value[:8] if len(value) >= 8 else value
            return ShaResolution(
                sha_full=value,
                sha_short=sha_short,
                source=env_var,
            )

    # Try local git (development mode)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=_find_project_root(),
        )
        if result.returncode == 0 and result.stdout.strip():
            full_sha = result.stdout.strip()
            return ShaResolution(
                sha_full=full_sha,
                sha_short=full_sha[:8],
                source="git",
            )
    except FileNotFoundError:
        pass  # git not available (minimal container)
    except subprocess.TimeoutExpired:
        logger.warning("git rev-parse timed out")
    except Exception:
        pass  # Any other git failure

    # Final fallback
    return ShaResolution(
        sha_full="local-dev",
        sha_short="local-dev",
        source="fallback",
    )


# ============================================================================
# Module-level resolution (cached at import time)
# ============================================================================
_SHA_RESOLUTION: ShaResolution = _resolve_git_sha()
_GIT_SHA: str = _SHA_RESOLUTION.sha_full
_GIT_SHA_SHORT: str = _SHA_RESOLUTION.sha_short
_SHA_SOURCE: str = _SHA_RESOLUTION.source
_ENV_NAME: str = os.environ.get("DRAGONFLY_ACTIVE_ENV", os.environ.get("SUPABASE_MODE", "dev"))

# Try to get version from package
try:
    from backend import __version__ as _VERSION
except ImportError:
    _VERSION = "0.0.0-dev"


def get_version_info() -> dict[str, str]:
    """
    Get version information for logging and debugging.

    Returns:
        Dict with sha, sha_short, env, version, and sha_source
    """
    return {
        "sha": _GIT_SHA,
        "sha_short": _GIT_SHA_SHORT,
        "env": _ENV_NAME,
        "version": _VERSION,
        "sha_source": _SHA_SOURCE,
    }


class VersionMiddleware(BaseHTTPMiddleware):
    """
    Middleware that injects version headers into every HTTP response.

    Headers:
      - X-Dragonfly-SHA: Full Git commit SHA (40 chars) or "local"
      - X-Dragonfly-SHA-Short: Short Git commit SHA (8 chars) for logs
      - X-Dragonfly-Env: Environment name (prod/dev/staging)
      - X-Dragonfly-Version: Package version (e.g., "1.2.3")

    This enables:
      - Tracing any HTTP response back to exact code version
      - Correlating browser errors with deployed commit
      - Verifying correct environment in production
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and add version headers to response."""
        response = await call_next(request)

        # Add version headers to every response
        response.headers["X-Dragonfly-SHA"] = _GIT_SHA
        response.headers["X-Dragonfly-SHA-Short"] = _GIT_SHA_SHORT
        response.headers["X-Dragonfly-Env"] = _ENV_NAME
        response.headers["X-Dragonfly-Version"] = _VERSION

        return response


def add_version_middleware(app) -> None:
    """
    Helper to add version middleware to a FastAPI app.

    Args:
        app: FastAPI application instance
    """
    app.add_middleware(VersionMiddleware)


# Expose version info for structured logging
__all__ = [
    "VersionMiddleware",
    "add_version_middleware",
    "get_version_info",
    # Constants for direct access
    "GIT_SHA",
    "GIT_SHA_SHORT",
    "SHA_SOURCE",
    "ENV_NAME",
    "VERSION",
    # Resolution helpers
    "ShaResolution",
    "resolve_git_sha",
]

# Public constants
GIT_SHA = _GIT_SHA
GIT_SHA_SHORT = _GIT_SHA_SHORT
SHA_SOURCE = _SHA_SOURCE
ENV_NAME = _ENV_NAME
VERSION = _VERSION

# Public function alias
resolve_git_sha = _resolve_git_sha
