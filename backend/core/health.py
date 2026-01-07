"""
backend/core/health.py - Canonical PostgREST Health Module

SINGLE SOURCE OF TRUTH FOR POSTGREST HEALTH STATUS
===================================================

This module provides the authoritative definition of PostgREST health.
All tools (doctor.py, golden_path.py, API health endpoints) should use
this module for consistent health reporting.

Status Definitions:
    HEALTHY     - PostgREST responding correctly to both root and data requests
    STALE_CACHE - PGRST002 error (schema cache needs reload, auto-healing recommended)
    UNAVAILABLE - 503/timeout/connection error (PostgREST is down)

Usage:
    from backend.core.health import check_postgrest_status, HealthStatus

    status = check_postgrest_status(env="dev")
    if status.status == HealthStatus.HEALTHY:
        print("All good!")
    elif status.status == HealthStatus.STALE_CACHE:
        print("Cache stale - triggering reload")
    else:
        print("PostgREST is down!")
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Literal

import httpx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PGRST002_MARKER = "PGRST002"
TIMEOUT_SECONDS = 10.0

# Environment -> Supabase URL mapping (fallback if env vars not loaded)
ENV_URLS = {
    "dev": "https://ejiddanxtqcleyswqvkc.supabase.co",
    "prod": "https://iaketsyhmqbwaabgykux.supabase.co",
}


# ---------------------------------------------------------------------------
# Health Status Enum
# ---------------------------------------------------------------------------


class HealthStatus(str, Enum):
    """
    Canonical PostgREST health status.

    HEALTHY     - PostgREST responding correctly
    STALE_CACHE - PGRST002 (schema cache stale, auto-healing recommended)
    UNAVAILABLE - PostgREST is down or unreachable
    """

    HEALTHY = "healthy"
    STALE_CACHE = "stale_cache"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Data Types
# ---------------------------------------------------------------------------


@dataclass
class EndpointCheckResult:
    """Result of checking a single endpoint."""

    endpoint: str
    status_code: int | None
    is_healthy: bool
    error_code: str | None = None
    message: str = ""


@dataclass
class PostgRESTHealthResult:
    """
    Complete health check result for PostgREST.

    This is the canonical result type used across all health checks.
    """

    status: HealthStatus
    env: str
    root_check: EndpointCheckResult
    data_check: EndpointCheckResult
    message: str = ""

    @property
    def is_healthy(self) -> bool:
        """True only if status is HEALTHY."""
        return self.status == HealthStatus.HEALTHY

    @property
    def is_stale_cache(self) -> bool:
        """True if PGRST002 detected."""
        return self.status == HealthStatus.STALE_CACHE

    @property
    def is_unavailable(self) -> bool:
        """True if PostgREST is completely down."""
        return self.status == HealthStatus.UNAVAILABLE

    def summary(self) -> str:
        """Return a human-readable summary."""
        status_icons = {
            HealthStatus.HEALTHY: "✅ HEALTHY",
            HealthStatus.STALE_CACHE: "⚠️ STALE_CACHE (PGRST002)",
            HealthStatus.UNAVAILABLE: "❌ UNAVAILABLE",
        }
        status_str = status_icons.get(self.status, str(self.status))

        lines = [
            f"PostgREST Health [{self.env.upper()}]: {status_str}",
            f"  Root (/)        : {self._check_status(self.root_check)}",
            f"  Data (judgments): {self._check_status(self.data_check)}",
        ]
        if self.message:
            lines.append(f"  Message: {self.message}")
        return "\n".join(lines)

    @staticmethod
    def _check_status(check: EndpointCheckResult) -> str:
        if check.is_healthy:
            return f"✓ OK (HTTP {check.status_code})"
        if check.error_code:
            return f"✗ {check.error_code}: {check.message}"
        return f"✗ HTTP {check.status_code}: {check.message}"


# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------


def _get_base_url(env: Literal["dev", "prod"]) -> str:
    """Get the Supabase REST base URL for the environment."""
    url = os.getenv("SUPABASE_URL")
    if url:
        return url.rstrip("/")
    return ENV_URLS.get(env, ENV_URLS["dev"])


def _get_service_key() -> str | None:
    """Get the service role key for authenticated requests."""
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY")


def _check_for_pgrst002(response: httpx.Response) -> tuple[bool, str | None]:
    """
    Check if response body contains PGRST002 error.

    Returns:
        (has_error, error_message)
    """
    try:
        body = response.text
        if PGRST002_MARKER in body:
            try:
                data = response.json()
                msg = data.get("message", "Schema cache stale")
                return True, msg
            except Exception:
                return True, "Schema cache stale (PGRST002 detected)"
    except Exception:
        pass
    return False, None


def _check_endpoint(
    url: str,
    headers: dict[str, str] | None = None,
) -> EndpointCheckResult:
    """
    Check a single endpoint for health.

    Logic:
    - 200/401 = HEALTHY (401 means PostgREST is up, just requires auth)
    - 503 = UNAVAILABLE
    - PGRST002 in body = STALE_CACHE
    """
    try:
        response = httpx.get(
            url,
            headers=headers or {},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
        )

        # Check for 503 first
        if response.status_code == 503:
            has_pgrst, msg = _check_for_pgrst002(response)
            return EndpointCheckResult(
                endpoint=url,
                status_code=503,
                is_healthy=False,
                error_code=PGRST002_MARKER if has_pgrst else "HTTP_503",
                message=msg or "Service Unavailable",
            )

        # Check for PGRST002 in body regardless of status
        has_pgrst, msg = _check_for_pgrst002(response)
        if has_pgrst:
            return EndpointCheckResult(
                endpoint=url,
                status_code=response.status_code,
                is_healthy=False,
                error_code=PGRST002_MARKER,
                message=msg or "Schema cache stale",
            )

        # 200 or 401 = healthy
        if response.status_code in (200, 401):
            return EndpointCheckResult(
                endpoint=url,
                status_code=response.status_code,
                is_healthy=True,
                message="OK",
            )

        # Other status codes
        return EndpointCheckResult(
            endpoint=url,
            status_code=response.status_code,
            is_healthy=False,
            message=f"Unexpected status: {response.status_code}",
        )

    except httpx.TimeoutException:
        return EndpointCheckResult(
            endpoint=url,
            status_code=None,
            is_healthy=False,
            error_code="TIMEOUT",
            message=f"Request timed out after {TIMEOUT_SECONDS}s",
        )
    except httpx.ConnectError as e:
        return EndpointCheckResult(
            endpoint=url,
            status_code=None,
            is_healthy=False,
            error_code="CONNECT_ERROR",
            message=str(e)[:100],
        )
    except Exception as e:
        return EndpointCheckResult(
            endpoint=url,
            status_code=None,
            is_healthy=False,
            error_code="UNKNOWN",
            message=str(e)[:100],
        )


def check_postgrest_status(
    env: Literal["dev", "prod"] | None = None,
    verbose: bool = False,
) -> PostgRESTHealthResult:
    """
    Run canonical PostgREST health check.

    Checks BOTH:
    1. Root endpoint (/) - verifies PostgREST is running
    2. Data endpoint (/judgments?limit=1) - verifies schema cache is valid

    Args:
        env: Target environment ('dev' or 'prod'). Defaults to SUPABASE_MODE.
        verbose: Print detailed output

    Returns:
        PostgRESTHealthResult with canonical status
    """
    if env is None:
        env = os.getenv("SUPABASE_MODE", "dev")  # type: ignore[assignment]
        if env not in ("dev", "prod"):
            env = "dev"

    base_url = _get_base_url(env)
    service_key = _get_service_key()

    # Build headers for authenticated requests
    headers: dict[str, str] = {}
    if service_key:
        headers["apikey"] = service_key
        headers["Authorization"] = f"Bearer {service_key}"

    if verbose:
        print(f"Checking PostgREST health for [{env.upper()}]")
        print(f"  Base URL: {base_url}")
        print(f"  Auth: {'configured' if service_key else 'NOT SET'}")
        print()

    # Check 1: Root endpoint
    root_url = f"{base_url}/rest/v1/"
    if verbose:
        print(f"  → GET {root_url}")
    root_check = _check_endpoint(root_url, headers)

    # Check 2: Data endpoint (judgments table)
    data_url = f"{base_url}/rest/v1/judgments?select=id&limit=1"
    if verbose:
        print(f"  → GET {data_url}")
    data_check = _check_endpoint(data_url, headers)

    # Determine overall status
    # Priority: UNAVAILABLE > STALE_CACHE > HEALTHY

    # Check for PGRST002 in either response
    has_pgrst002 = (root_check.error_code == PGRST002_MARKER) or (
        data_check.error_code == PGRST002_MARKER
    )

    # Check for complete unavailability
    root_unavailable = root_check.error_code in ("TIMEOUT", "CONNECT_ERROR", "HTTP_503")
    data_unavailable = data_check.error_code in ("TIMEOUT", "CONNECT_ERROR", "HTTP_503")

    if root_unavailable and data_unavailable:
        status = HealthStatus.UNAVAILABLE
        message = "PostgREST is completely unreachable"
    elif has_pgrst002:
        status = HealthStatus.STALE_CACHE
        message = "Schema cache stale (PGRST002) - auto-healing recommended"
    elif root_check.is_healthy and data_check.is_healthy:
        status = HealthStatus.HEALTHY
        message = "PostgREST is healthy"
    elif root_check.is_healthy or data_check.is_healthy:
        # Partial health - one endpoint works
        if has_pgrst002:
            status = HealthStatus.STALE_CACHE
            message = "Partial health with PGRST002"
        else:
            status = HealthStatus.UNAVAILABLE
            message = "Partial availability - some endpoints failing"
    else:
        status = HealthStatus.UNAVAILABLE
        message = "PostgREST unavailable"

    return PostgRESTHealthResult(
        status=status,
        env=env,
        root_check=root_check,
        data_check=data_check,
        message=message,
    )


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------


def is_postgrest_healthy(env: Literal["dev", "prod"] | None = None) -> bool:
    """Quick check if PostgREST is fully healthy."""
    result = check_postgrest_status(env)
    return result.is_healthy


def get_postgrest_status_for_api(
    env: Literal["dev", "prod"] | None = None,
) -> dict:
    """
    Get PostgREST status as a JSON-serializable dict for API responses.

    Returns:
        Dict with status, env, is_healthy, message, and details
    """
    result = check_postgrest_status(env)
    return {
        "status": result.status.value,
        "env": result.env,
        "is_healthy": result.is_healthy,
        "message": result.message,
        "root_check": {
            "endpoint": result.root_check.endpoint,
            "status_code": result.root_check.status_code,
            "is_healthy": result.root_check.is_healthy,
            "error_code": result.root_check.error_code,
        },
        "data_check": {
            "endpoint": result.data_check.endpoint,
            "status_code": result.data_check.status_code,
            "is_healthy": result.data_check.is_healthy,
            "error_code": result.data_check.error_code,
        },
    }
