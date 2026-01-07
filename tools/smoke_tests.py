#!/usr/bin/env python3
"""
Dragonfly Civil - Lightweight Smoke Tests

Minimal verification that critical subsystems are accessible.
These are fast, read-only checks suitable for health probes.

Usage:
    python -m tools.smoke_tests --env dev
    python -m tools.smoke_tests --env prod

Functions:
    check_plaintiffs() - Verify intake.simplicity_batches is accessible
    check_enforcement() - Verify enforcement.v_metrics_enforcement returns results
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SmokeResult:
    """Result of a smoke test."""

    name: str
    passed: bool
    message: str
    row_count: int | None = None


def check_plaintiffs(env: str | None = None) -> SmokeResult:
    """
    Verify intake.simplicity_batches table exists and is accessible.

    Args:
        env: Target environment (dev/prod). Uses SUPABASE_MODE if not provided.

    Returns:
        SmokeResult with pass/fail status.
    """
    import psycopg

    from src.supabase_client import get_supabase_db_url

    target_env = env or os.environ.get("SUPABASE_MODE", "dev")

    try:
        db_url = get_supabase_db_url(target_env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Check table exists and is queryable
                cur.execute("SELECT count(*) FROM intake.simplicity_batches")
                row = cur.fetchone()
                count = row[0] if row else 0

                return SmokeResult(
                    name="plaintiffs",
                    passed=True,
                    message=f"intake.simplicity_batches accessible ({count} rows)",
                    row_count=count,
                )

    except Exception as e:
        return SmokeResult(
            name="plaintiffs",
            passed=False,
            message=f"intake.simplicity_batches failed: {type(e).__name__}: {e}",
        )


def check_enforcement(env: str | None = None) -> SmokeResult:
    """
    Verify enforcement.v_metrics_enforcement view returns results.

    Args:
        env: Target environment (dev/prod). Uses SUPABASE_MODE if not provided.

    Returns:
        SmokeResult with pass/fail status.
    """
    import psycopg

    from src.supabase_client import get_supabase_db_url

    target_env = env or os.environ.get("SUPABASE_MODE", "dev")

    try:
        db_url = get_supabase_db_url(target_env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Check view exists and returns results (even empty is OK)
                cur.execute("SELECT count(*) FROM enforcement.v_metrics_enforcement")
                row = cur.fetchone()
                count = row[0] if row else 0

                return SmokeResult(
                    name="enforcement",
                    passed=True,
                    message=f"enforcement.v_metrics_enforcement accessible ({count} rows)",
                    row_count=count,
                )

    except Exception as e:
        return SmokeResult(
            name="enforcement",
            passed=False,
            message=f"enforcement.v_metrics_enforcement failed: {type(e).__name__}: {e}",
        )


def run_all(env: str) -> list[SmokeResult]:
    """
    Run all smoke tests.

    Args:
        env: Target environment (dev/prod).

    Returns:
        List of SmokeResult objects.
    """
    return [
        check_plaintiffs(env),
        check_enforcement(env),
    ]


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Lightweight subsystem smoke tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=os.environ.get("SUPABASE_MODE", "dev"),
        help="Target environment (default: from SUPABASE_MODE or 'dev')",
    )

    args = parser.parse_args()
    os.environ["SUPABASE_MODE"] = args.env

    print(f"Running smoke tests against {args.env.upper()}...")
    print("-" * 50)

    results = run_all(args.env)
    all_passed = True

    for result in results:
        status = "✅" if result.passed else "❌"
        print(f"{status} {result.name}: {result.message}")
        if not result.passed:
            all_passed = False

    print("-" * 50)
    if all_passed:
        print("✅ All smoke tests passed")
        return 0
    else:
        print("❌ Some smoke tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
