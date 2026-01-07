#!/usr/bin/env python3
"""
PostgREST Health Probe - Truthful PGRST002 Detection.

This probe goes beyond simple pings to detect the specific PGRST002
(Schema Cache Stale) error code in response bodies.

Usage:
    python -m tools.check_postgrest_health --env dev
    python -m tools.check_postgrest_health --env prod --verbose
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
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
# Data Types
# ---------------------------------------------------------------------------


@dataclass
class HealthCheckResult:
    """Result of a single health check."""

    endpoint: str
    status_code: int | None
    is_healthy: bool
    error_code: str | None = None
    message: str = ""


@dataclass
class OverallHealth:
    """Aggregated health status."""

    env: str
    is_healthy: bool
    root_check: HealthCheckResult
    data_check: HealthCheckResult

    def summary(self) -> str:
        """Return a human-readable summary."""
        status = "✅ HEALTHY" if self.is_healthy else "❌ UNHEALTHY"
        lines = [
            f"PostgREST Health [{self.env.upper()}]: {status}",
            f"  Root (/)        : {self._check_status(self.root_check)}",
            f"  Data (judgments): {self._check_status(self.data_check)}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _check_status(check: HealthCheckResult) -> str:
        if check.is_healthy:
            return f"✅ OK (HTTP {check.status_code})"
        if check.error_code:
            return f"❌ FAIL - {check.error_code}: {check.message}"
        return f"❌ FAIL - HTTP {check.status_code}: {check.message}"


# ---------------------------------------------------------------------------
# Core Logic
# ---------------------------------------------------------------------------


def _get_base_url(env: Literal["dev", "prod"]) -> str:
    """Get the Supabase REST base URL for the environment."""
    # Try environment variable first
    url = os.getenv("SUPABASE_URL")
    if url:
        return url.rstrip("/")
    # Fallback to hardcoded
    return ENV_URLS.get(env, ENV_URLS["dev"])


def _check_for_pgrst002(response: httpx.Response) -> tuple[bool, str | None]:
    """
    Check if response body contains PGRST002 error.

    Returns:
        (has_error, error_message)
    """
    try:
        body = response.text
        if PGRST002_MARKER in body:
            # Try to extract the message
            try:
                data = response.json()
                msg = data.get("message", "Schema cache stale")
                return True, msg
            except Exception:
                return True, "Schema cache stale (PGRST002 detected in body)"
    except Exception:
        pass
    return False, None


def check_root_endpoint(
    base_url: str, anon_key: str | None = None, verbose: bool = False
) -> HealthCheckResult:
    """
    Check GET /rest/v1/ for health.

    - 503 or PGRST002 in body -> FAIL
    - 200/401 -> PASS (401 means service is up, just requires auth)
    """
    endpoint = f"{base_url}/rest/v1/"
    headers = {}
    if anon_key:
        headers["apikey"] = anon_key
        headers["Authorization"] = f"Bearer {anon_key}"

    try:
        if verbose:
            print(f"  → GET {endpoint}")
        response = httpx.get(endpoint, headers=headers, timeout=TIMEOUT_SECONDS)

        # Check for 503
        if response.status_code == 503:
            has_pgrst, msg = _check_for_pgrst002(response)
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=503,
                is_healthy=False,
                error_code=PGRST002_MARKER if has_pgrst else "HTTP_503",
                message=msg or "Service Unavailable",
            )

        # Check for PGRST002 in body regardless of status
        has_pgrst, msg = _check_for_pgrst002(response)
        if has_pgrst:
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=response.status_code,
                is_healthy=False,
                error_code=PGRST002_MARKER,
                message=msg or "Schema cache stale",
            )

        # 200 or 401 = healthy (401 means PostgREST is responding, just locked)
        if response.status_code in (200, 401):
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=response.status_code,
                is_healthy=True,
                message="OK",
            )

        # Other status codes are suspicious
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=response.status_code,
            is_healthy=False,
            message=f"Unexpected status: {response.status_code}",
        )

    except httpx.TimeoutException:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="TIMEOUT",
            message=f"Request timed out after {TIMEOUT_SECONDS}s",
        )
    except httpx.ConnectError as e:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="CONNECT_ERROR",
            message=str(e),
        )
    except Exception as e:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="UNKNOWN",
            message=str(e),
        )


def check_data_endpoint(
    base_url: str, anon_key: str | None = None, verbose: bool = False
) -> HealthCheckResult:
    """
    Check GET /rest/v1/judgments?select=id&limit=1 for health.

    - 200/401 -> PASS
    - PGRST002 in body -> FAIL
    """
    endpoint = f"{base_url}/rest/v1/judgments?select=id&limit=1"
    headers = {}
    if anon_key:
        headers["apikey"] = anon_key
        headers["Authorization"] = f"Bearer {anon_key}"

    try:
        if verbose:
            print(f"  → GET {endpoint}")
        response = httpx.get(endpoint, headers=headers, timeout=TIMEOUT_SECONDS)

        # Check for PGRST002 in body
        has_pgrst, msg = _check_for_pgrst002(response)
        if has_pgrst:
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=response.status_code,
                is_healthy=False,
                error_code=PGRST002_MARKER,
                message=msg or "Schema cache stale",
            )

        # 200 or 401 = healthy
        if response.status_code in (200, 401):
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=response.status_code,
                is_healthy=True,
                message="OK",
            )

        # 503 is definitely bad
        if response.status_code == 503:
            return HealthCheckResult(
                endpoint=endpoint,
                status_code=503,
                is_healthy=False,
                error_code="HTTP_503",
                message="Service Unavailable",
            )

        # Other codes - still consider healthy if not PGRST002
        # (e.g., 404 might mean table doesn't exist, but PostgREST is up)
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=response.status_code,
            is_healthy=True,  # PostgREST responded coherently
            message=f"Status {response.status_code} (PostgREST responding)",
        )

    except httpx.TimeoutException:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="TIMEOUT",
            message=f"Request timed out after {TIMEOUT_SECONDS}s",
        )
    except httpx.ConnectError as e:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="CONNECT_ERROR",
            message=str(e),
        )
    except Exception as e:
        return HealthCheckResult(
            endpoint=endpoint,
            status_code=None,
            is_healthy=False,
            error_code="UNKNOWN",
            message=str(e),
        )


def check_health(env: Literal["dev", "prod"], verbose: bool = False) -> OverallHealth:
    """
    Run full PostgREST health check for the given environment.

    Returns OverallHealth with is_healthy=True only if BOTH checks pass.
    """
    base_url = _get_base_url(env)
    anon_key = os.getenv("SUPABASE_ANON_KEY")

    if verbose:
        print(f"Checking PostgREST health for [{env.upper()}]")
        print(f"  Base URL: {base_url}")
        print(f"  Anon Key: {'set' if anon_key else 'NOT SET'}")
        print()

    root_check = check_root_endpoint(base_url, anon_key, verbose)
    data_check = check_data_endpoint(base_url, anon_key, verbose)

    overall_healthy = root_check.is_healthy and data_check.is_healthy

    return OverallHealth(
        env=env,
        is_healthy=overall_healthy,
        root_check=root_check,
        data_check=data_check,
    )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="PostgREST Health Probe with PGRST002 Detection")
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.getenv("SUPABASE_MODE", "dev"),
        help="Target environment (default: SUPABASE_MODE or 'dev')",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    parser.add_argument("--json", action="store_true", help="Output as JSON (for scripting)")
    args = parser.parse_args()

    # Set environment before loading config
    os.environ["SUPABASE_MODE"] = args.env

    result = check_health(args.env, verbose=args.verbose)

    if args.json:
        import json

        output = {
            "env": result.env,
            "is_healthy": result.is_healthy,
            "root_check": {
                "endpoint": result.root_check.endpoint,
                "status_code": result.root_check.status_code,
                "is_healthy": result.root_check.is_healthy,
                "error_code": result.root_check.error_code,
                "message": result.root_check.message,
            },
            "data_check": {
                "endpoint": result.data_check.endpoint,
                "status_code": result.data_check.status_code,
                "is_healthy": result.data_check.is_healthy,
                "error_code": result.data_check.error_code,
                "message": result.data_check.message,
            },
        }
        print(json.dumps(output, indent=2))
    else:
        print(result.summary())

    return 0 if result.is_healthy else 1


if __name__ == "__main__":
    sys.exit(main())
