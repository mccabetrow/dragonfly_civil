"""
Dragonfly API Health Checker - Demo Mode Resilient

Verifies PostgREST API availability via Supabase REST endpoint.
Supports --tolerant mode for demo environments where PostgREST
cold-start failures should be warnings, not blockers.

Uses get_resilient_session() from backend.utils.retry for automatic
retry with jittered backoff on 429/502/503/504 errors.

Usage:
    python -m tools.check_api_health --env prod
    python -m tools.check_api_health --env prod --tolerant
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import click

# Add project root to path for backend imports
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.utils.retry import get_resilient_session
from src.supabase_client import SupabaseEnv, get_supabase_env

logger = logging.getLogger(__name__)


@dataclass
class APIHealthResult:
    """Result of an API health check."""

    status: str  # OK, WARN, FAIL
    message: str
    response_time_ms: Optional[float] = None
    http_status: Optional[int] = None


# =============================================================================
# Transient Error Detection
# =============================================================================


def _is_transient_error(
    error: Optional[Exception] = None,
    http_status: Optional[int] = None,
) -> bool:
    """Check if an error or HTTP status is transient."""
    if http_status is not None:
        return http_status in {429, 502, 503, 504}

    if error is not None:
        error_str = str(error).lower()
        transient_patterns = [
            "connection refused",
            "timeout",
            "503",
            "502",
            "429",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
            "temporarily unavailable",
            "waking up",
            "cold start",
        ]
        return any(pattern in error_str for pattern in transient_patterns)

    return False


# =============================================================================
# API Health Check Logic
# =============================================================================


def _get_api_url(env: SupabaseEnv) -> str:
    """Get the Supabase REST API URL for the environment."""
    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise ValueError("SUPABASE_URL not configured")
    return url


def check_postgrest_health(
    env: SupabaseEnv,
    max_retries: int = 3,
    timeout_seconds: float = 10.0,
) -> tuple[bool, Optional[int], Optional[float], Optional[Exception]]:
    """
    Check if PostgREST API is responding.

    Uses get_resilient_session() for automatic retry with jittered backoff.

    Args:
        env: Target Supabase environment.
        max_retries: Maximum retry attempts.
        timeout_seconds: Request timeout.

    Returns:
        Tuple of (success, http_status, response_time_ms, error)
    """
    api_url = _get_api_url(env)
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }

    # Use resilient session with automatic retry on transient errors
    session = get_resilient_session(max_retries=max_retries, timeout=timeout_seconds)

    try:
        start_time = time.time()
        response = session.get(
            f"{api_url}/rest/v1/",
            headers=headers,
            timeout=timeout_seconds,
        )
        elapsed_ms = (time.time() - start_time) * 1000

        if response.status_code in {200, 401}:
            # 200 = OK, 401 = Auth issue but API is up
            return (True, response.status_code, elapsed_ms, None)
        else:
            error = Exception(f"HTTP {response.status_code}: {response.text[:100]}")
            return (False, response.status_code, elapsed_ms, error)

    except Exception as e:
        logger.error(f"[check_api_health] Request failed after retries: {e}")
        return (False, None, None, e)


def check_api_health(
    env: SupabaseEnv,
    tolerant: bool = False,
) -> APIHealthResult:
    """
    Check PostgREST API health.

    Args:
        env: Target Supabase environment.
        tolerant: If True, transient failures become warnings.

    Returns:
        APIHealthResult with status and details.
    """
    try:
        success, http_status, response_time, error = check_postgrest_health(env)

        if success:
            return APIHealthResult(
                status="OK",
                message=f"PostgREST API responding ({response_time:.0f}ms)",
                response_time_ms=response_time,
                http_status=http_status,
            )

        # Check if failure is transient
        is_transient = _is_transient_error(error=error, http_status=http_status)

        if tolerant and is_transient:
            reason = "Likely waking up" if http_status == 503 else "Transient"
            return APIHealthResult(
                status="WARN",
                message=f"⚠️ PostgREST unavailable ({reason}): HTTP {http_status or 'N/A'}",
                response_time_ms=response_time,
                http_status=http_status,
            )

        error_msg = str(error) if error else f"HTTP {http_status}"
        return APIHealthResult(
            status="FAIL",
            message=f"PostgREST API check failed: {error_msg}",
            response_time_ms=response_time,
            http_status=http_status,
        )

    except ValueError as e:
        return APIHealthResult(
            status="FAIL",
            message=f"Configuration error: {e}",
        )
    except Exception as e:
        if tolerant and _is_transient_error(error=e):
            return APIHealthResult(
                status="WARN",
                message=f"⚠️ PostgREST check skipped (Transient): {e}",
            )
        return APIHealthResult(
            status="FAIL",
            message=f"PostgREST API check failed: {e}",
        )


# =============================================================================
# CLI
# =============================================================================


def _normalize_env(value: str | None) -> SupabaseEnv:
    """Normalize environment value to 'dev' or 'prod'."""
    if not value:
        return get_supabase_env()
    return "prod" if value.lower().strip() == "prod" else "dev"


@click.command()
@click.option(
    "--env",
    "requested_env",
    type=click.Choice(["dev", "prod"]),
    default=None,
    help="Target Supabase environment. Defaults to SUPABASE_MODE.",
)
@click.option(
    "--tolerant",
    is_flag=True,
    default=False,
    help="Downgrade transient failures (503/Connection Refused) to warnings.",
)
@click.option(
    "--demo",
    is_flag=True,
    default=False,
    help="Alias for --tolerant (demo mode).",
)
def main(
    requested_env: str | None = None,
    tolerant: bool = False,
    demo: bool = False,
) -> None:
    """Check PostgREST API availability."""
    env = _normalize_env(requested_env)
    os.environ["SUPABASE_MODE"] = env

    # --demo implies --tolerant
    tolerant = tolerant or demo

    if tolerant:
        click.echo(f"[check_api_health] Running in TOLERANT mode (env={env})")
    else:
        click.echo(f"[check_api_health] env={env}")

    result = check_api_health(env, tolerant=tolerant)

    # Output result
    if result.status == "OK":
        click.echo(f"[check_api_health] ✅ {result.message}")
    elif result.status == "WARN":
        click.echo(f"[check_api_health] {result.message}")
    else:
        click.echo(f"[check_api_health] ❌ {result.message}", err=True)

    # Exit code
    if result.status == "FAIL":
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
