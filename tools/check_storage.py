"""
Dragonfly Storage Bucket Checker - Demo Mode Resilient

Verifies required Supabase storage buckets exist.
Supports --tolerant mode for demo environments where storage
failures should be warnings, not blockers.

Usage:
    python -m tools.check_storage --env prod
    python -m tools.check_storage --env prod --tolerant
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Set

import click

from src.supabase_client import SupabaseEnv, create_supabase_client, get_supabase_env

logger = logging.getLogger(__name__)

# Required storage buckets for enforcement workflows
REQUIRED_BUCKETS: tuple[str, ...] = ("imports", "enforcement_evidence")


@dataclass
class StorageCheckResult:
    """Result of a storage bucket check."""

    status: str  # OK, WARN, FAIL
    message: str
    missing_buckets: List[str]
    found_buckets: List[str]


# =============================================================================
# Transient Error Detection
# =============================================================================


def _is_transient_error(error: Exception) -> bool:
    """Check if an error is transient (rate limit, timeout, etc.)."""
    error_str = str(error).lower()
    transient_patterns = [
        "429",
        "too_many_connections",
        "rate limit",
        "timeout",
        "connection refused",
        "503",
        "service unavailable",
        "circuit breaker",
        "temporarily unavailable",
    ]
    return any(pattern in error_str for pattern in transient_patterns)


def _extract_error_code(error: Exception) -> Optional[int]:
    """Extract HTTP status code from error if present."""
    error_str = str(error)
    if "statusCode" in error_str:
        import re

        match = re.search(r"statusCode.*?(\d{3})", error_str)
        if match:
            return int(match.group(1))
    return None


# =============================================================================
# Storage Check Logic
# =============================================================================


def list_buckets_with_retry(env: SupabaseEnv, max_retries: int = 3) -> Set[str]:
    """
    List storage buckets with jittered retry.

    Args:
        env: Target Supabase environment.
        max_retries: Maximum retry attempts.

    Returns:
        Set of bucket names.

    Raises:
        Exception: If all retries fail.
    """
    import random
    import time

    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            client = create_supabase_client(env)
            buckets = client.storage.list_buckets()
            return {
                getattr(bucket, "name", None) for bucket in buckets if getattr(bucket, "name", None)
            }
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                jitter = random.uniform(0.25, 0.75)
                logger.warning(
                    f"[check_storage] Attempt {attempt}/{max_retries} failed: {e}. "
                    f"Retrying in {jitter:.2f}s..."
                )
                time.sleep(jitter)
            else:
                logger.error(f"[check_storage] All {max_retries} attempts failed: {e}")

    if last_error is not None:
        raise last_error
    raise RuntimeError("Storage check failed with no captured exception")


def check_storage_buckets(
    env: SupabaseEnv,
    tolerant: bool = False,
) -> StorageCheckResult:
    """
    Check that required storage buckets exist.

    Args:
        env: Target Supabase environment.
        tolerant: If True, transient failures become warnings.

    Returns:
        StorageCheckResult with status and details.
    """
    try:
        found_buckets = list_buckets_with_retry(env)
        missing = [name for name in REQUIRED_BUCKETS if name not in found_buckets]

        if missing:
            return StorageCheckResult(
                status="FAIL",
                message=f"Missing buckets: {', '.join(missing)}",
                missing_buckets=missing,
                found_buckets=list(found_buckets),
            )

        return StorageCheckResult(
            status="OK",
            message=f"All required buckets present: {', '.join(REQUIRED_BUCKETS)}",
            missing_buckets=[],
            found_buckets=list(found_buckets),
        )

    except Exception as e:
        error_code = _extract_error_code(e)
        is_transient = _is_transient_error(e)

        if tolerant and is_transient:
            status_msg = f"Rate Limit ({error_code})" if error_code == 429 else "Transient"
            return StorageCheckResult(
                status="WARN",
                message=f"⚠️ Storage check skipped ({status_msg}): {e}",
                missing_buckets=[],
                found_buckets=[],
            )

        return StorageCheckResult(
            status="FAIL",
            message=f"Storage check failed: {e}",
            missing_buckets=list(REQUIRED_BUCKETS),
            found_buckets=[],
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
    help="Downgrade transient failures (429/503) to warnings.",
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
    """Check Supabase storage bucket availability."""
    env = _normalize_env(requested_env)
    os.environ["SUPABASE_MODE"] = env

    # --demo implies --tolerant
    tolerant = tolerant or demo

    if tolerant:
        click.echo(f"[check_storage] Running in TOLERANT mode (env={env})")
    else:
        click.echo(f"[check_storage] env={env}")

    result = check_storage_buckets(env, tolerant=tolerant)

    # Output result
    if result.status == "OK":
        click.echo(f"[check_storage] ✅ {result.message}")
    elif result.status == "WARN":
        click.echo(f"[check_storage] {result.message}")
    else:
        click.echo(f"[check_storage] ❌ {result.message}", err=True)

    # Exit code
    if result.status == "FAIL":
        raise SystemExit(1)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
