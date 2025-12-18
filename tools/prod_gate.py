#!/usr/bin/env python3
"""
Dragonfly Engine - Production Gate

"Perfect" Production Gate: All checks must pass before deploy.

Requirements:
1. Migration safety (no pending migrations)
2. DB reality check (ops.worker_heartbeats exists + upsert works)
3. Evaluator >= 95% pass rate (real data grounded)
4. API readiness 200 OK
5. Worker status endpoint shows workers online

Usage:
    python -m tools.prod_gate --env prod
    python -m tools.prod_gate --env prod --strict  # Exit 1 on any failure
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logging import configure_worker_logging
from src.supabase_client import get_supabase_db_url, get_supabase_env

# Configure logging
logger = configure_worker_logging("prod_gate")

# Constants
# API URLs - allow override via environment variables
PROD_API_URL = os.getenv("API_BASE_URL_PROD", "https://dragonfly-api-production.up.railway.app")
DEV_API_URL = os.getenv("API_BASE_URL_DEV", "http://localhost:8000")
EVALUATOR_PASS_THRESHOLD = 0.95  # 95% minimum pass rate


@dataclass
class GateResult:
    """Result of a single gate check."""

    name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateReport:
    """Full production gate report."""

    timestamp: str
    environment: str
    results: list[GateResult] = field(default_factory=list)
    overall_passed: bool = False

    def add(self, result: GateResult) -> None:
        self.results.append(result)

    def finalize(self) -> None:
        self.overall_passed = all(r.passed for r in self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def total_count(self) -> int:
        return len(self.results)

    def print_summary(self) -> None:
        """Print formatted summary to console."""
        print()
        print("=" * 70)
        print("  PRODUCTION GATE REPORT")
        print("=" * 70)
        print(f"  Timestamp:   {self.timestamp}")
        print(f"  Environment: {self.environment}")
        print(f"  Checks:      {self.pass_count}/{self.total_count} passed")
        print()

        for result in self.results:
            status = "[PASS]" if result.passed else "[FAIL]"
            color = "\033[32m" if result.passed else "\033[31m"
            reset = "\033[0m"
            print(f"  {color}{status}{reset} {result.name}")
            print(f"         {result.message}")
            if result.details:
                for key, value in result.details.items():
                    print(f"         {key}: {value}")
            print()

        print("=" * 70)
        if self.overall_passed:
            print("  \033[32mRESULT: ALL GATES PASSED - READY FOR DEPLOY\033[0m")
        else:
            print("  \033[31mRESULT: GATE FAILED - DO NOT DEPLOY\033[0m")
        print("=" * 70)
        print()


# =============================================================================
# Gate Checks
# =============================================================================


def check_migration_safety(env: str) -> GateResult:
    """
    Gate 1: Migration safety - no pending migrations.

    Checks if all migrations in supabase/migrations/ have been applied.
    """
    logger.info("Checking migration safety...")

    try:
        db_url = get_supabase_db_url(env)
        migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"

        if not migrations_dir.exists():
            return GateResult(
                name="Migration Safety",
                passed=False,
                message="Migrations directory not found",
                details={"path": str(migrations_dir)},
            )

        # Get local migration files
        local_migrations = sorted(
            [f.stem for f in migrations_dir.glob("*.sql") if f.stem[0].isdigit()]
        )

        # Get applied migrations from database
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT version FROM supabase_migrations.schema_migrations
                    ORDER BY version
                """
                )
                applied = [row[0] for row in cur.fetchall()]

        # Find pending migrations
        pending = [m for m in local_migrations if m not in applied]

        if pending:
            # In dev, pending migrations are a warning, not a failure
            is_dev = env == "dev"
            return GateResult(
                name="Migration Safety",
                passed=is_dev,  # Pass in dev (warning only), fail in prod
                message=f"{len(pending)} pending migration(s)"
                + (" (dev: warning only)" if is_dev else ""),
                details={
                    "pending": pending[:5],  # Show first 5
                    "total_pending": len(pending),
                },
            )

        return GateResult(
            name="Migration Safety",
            passed=True,
            message=f"All {len(local_migrations)} migrations applied",
            details={"applied_count": len(applied)},
        )

    except Exception as e:
        return GateResult(
            name="Migration Safety",
            passed=False,
            message=f"Error checking migrations: {e}",
        )


def check_db_reality(env: str) -> GateResult:
    """
    Gate 2: DB reality check - ops.worker_heartbeats exists and upsert works.

    Verifies the heartbeat infrastructure is operational.
    """
    logger.info("Checking DB reality (heartbeat table)...")

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Check table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables
                        WHERE table_schema = 'ops'
                        AND table_name = 'worker_heartbeats'
                    )
                """
                )
                exists = cur.fetchone()[0]

                if not exists:
                    return GateResult(
                        name="DB Reality Check",
                        passed=False,
                        message="ops.worker_heartbeats table does not exist",
                        details={"table": "ops.worker_heartbeats"},
                    )

                # Test upsert capability (using actual schema: worker_id, worker_type, last_seen_at)
                # Status must be running|stopped|error per check constraint
                test_worker_id = "prod_gate_test_instance"
                test_worker_type = "prod_gate"
                cur.execute(
                    """
                    INSERT INTO ops.worker_heartbeats (worker_id, worker_type, last_seen_at, status)
                    VALUES (%s, %s, now(), 'running')
                    ON CONFLICT (worker_id) DO UPDATE SET
                        last_seen_at = now(),
                        status = 'running'
                    RETURNING worker_id
                """,
                    (test_worker_id, test_worker_type),
                )
                conn.commit()

                # Clean up test row
                cur.execute(
                    "DELETE FROM ops.worker_heartbeats WHERE worker_id = %s",
                    (test_worker_id,),
                )
                conn.commit()

                # Get current heartbeat count
                cur.execute("SELECT COUNT(*) FROM ops.worker_heartbeats")
                count = cur.fetchone()[0]

        return GateResult(
            name="DB Reality Check",
            passed=True,
            message="ops.worker_heartbeats exists and upsert works",
            details={"current_heartbeat_rows": count},
        )

    except Exception as e:
        return GateResult(
            name="DB Reality Check",
            passed=False,
            message=f"Error: {e}",
        )


def check_evaluator_pass_rate() -> GateResult:
    """
    Gate 3: Evaluator >= 95% pass rate on real data.

    Runs the AI evaluator and checks the pass rate.
    """
    logger.info("Running AI evaluator...")

    try:
        # Import evaluator components
        from backend.ai.evaluator import Evaluator, GoldenDataset

        # Run evaluator
        evaluator = Evaluator()
        eval_result = evaluator.evaluate_all()

        pass_rate = eval_result.score
        passed_gate = pass_rate >= EVALUATOR_PASS_THRESHOLD

        failed_cases = [r.case_id for r in eval_result.case_results if not r.passed]

        return GateResult(
            name="Evaluator Pass Rate",
            passed=passed_gate,
            message=f"{eval_result.passed_cases}/{eval_result.total_cases} cases passed ({pass_rate:.1%})",
            details={
                "pass_rate": f"{pass_rate:.1%}",
                "threshold": f"{EVALUATOR_PASS_THRESHOLD:.0%}",
                "failed_cases": failed_cases[:5] if failed_cases else [],
            },
        )

    except Exception as e:
        return GateResult(
            name="Evaluator Pass Rate",
            passed=False,
            message=f"Error running evaluator: {e}",
        )


def check_api_readiness(env: str) -> GateResult:
    """
    Gate 4: API readiness - /api/health returns 200 OK.

    In prod, checks the Railway production API.
    In dev, checks localhost (skips if not running).
    """
    logger.info("Checking API readiness...")

    base_url = PROD_API_URL if env == "prod" else DEV_API_URL
    health_url = f"{base_url}/api/health"

    try:
        req = Request(health_url, method="GET")
        req.add_header("User-Agent", "DragonflyProdGate/1.0")

        with urlopen(req, timeout=30) as response:
            status_code = response.getcode()
            body = json.loads(response.read().decode("utf-8"))

            # Handle both wrapped and unwrapped response formats
            # Wrapped: {"ok": true, "data": {"status": "ok", ...}}
            # Unwrapped: {"status": "ok", ...}
            data = body.get("data", body)
            status = data.get("status")
            is_ok = body.get("ok", True) and status == "ok"

            if status_code == 200 and is_ok:
                return GateResult(
                    name="API Readiness",
                    passed=True,
                    message="API health check passed",
                    details={
                        "status": status,
                        "environment": data.get("environment"),
                        "version": data.get("version"),
                    },
                )
            else:
                return GateResult(
                    name="API Readiness",
                    passed=False,
                    message=f"API returned status: {status}",
                    details={"response": body},
                )

    except HTTPError as e:
        return GateResult(
            name="API Readiness",
            passed=False,
            message=f"HTTP {e.code}: {e.reason}",
            details={"url": health_url},
        )
    except URLError as e:
        # In dev, connection refused is expected if local server isn't running
        if env == "dev":
            return GateResult(
                name="API Readiness",
                passed=True,
                message="Skipped (dev: local API not running)",
                details={"url": health_url, "hint": "Start with: uvicorn backend.main:app"},
            )
        return GateResult(
            name="API Readiness",
            passed=False,
            message=f"Connection failed: {e.reason}",
            details={"url": health_url},
        )
    except Exception as e:
        return GateResult(
            name="API Readiness",
            passed=False,
            message=f"Error: {e}",
        )


def check_worker_status(env: str, skip_in_dev: bool = True) -> GateResult:
    """
    Gate 5: Worker status - workers show recent heartbeats.

    Checks ops.worker_heartbeats for workers that have checked in recently.
    In dev mode, skips by default (workers not typically running locally).
    """
    logger.info("Checking worker status...")

    # Skip in dev mode unless explicitly enabled
    if env == "dev" and skip_in_dev:
        return GateResult(
            name="Worker Status",
            passed=True,
            message="Skipped (dev: workers not running locally)",
            details={"hint": "Run workers locally to enable this check"},
        )

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Get workers with heartbeats in last 5 minutes
                # Get workers with heartbeats in last 5 minutes
                # Schema: worker_id, worker_type, last_seen_at, status
                cur.execute(
                    """
                    SELECT worker_id, worker_type, status, last_seen_at
                    FROM ops.worker_heartbeats
                    WHERE last_seen_at > now() - interval '5 minutes'
                    ORDER BY worker_type
                """
                )
                active_workers = cur.fetchall()

                # Get all workers regardless of age
                cur.execute(
                    """
                    SELECT worker_id, worker_type, status, last_seen_at
                    FROM ops.worker_heartbeats
                    ORDER BY last_seen_at DESC
                """
                )
                all_workers = cur.fetchall()

        if not all_workers:
            return GateResult(
                name="Worker Status",
                passed=False,
                message="No worker heartbeats found",
                details={"hint": "Workers may not have started yet"},
            )

        # Format: (worker_id, worker_type, status, last_seen_at)
        active_types = list(set(w[1] for w in active_workers))

        if active_workers:
            return GateResult(
                name="Worker Status",
                passed=True,
                message=f"{len(active_workers)} worker(s) online",
                details={
                    "active_worker_types": active_types,
                    "total_registered": len(all_workers),
                },
            )
        else:
            # Show last seen times for debugging
            last_seen = {f"{w[1]}:{w[0][:8]}": str(w[3]) for w in all_workers[:3]}
            return GateResult(
                name="Worker Status",
                passed=False,
                message="No workers active in last 5 minutes",
                details={
                    "last_seen": last_seen,
                    "total_registered": len(all_workers),
                },
            )

    except Exception as e:
        return GateResult(
            name="Worker Status",
            passed=False,
            message=f"Error: {e}",
        )


# =============================================================================
# Main Entry Point
# =============================================================================


def run_production_gate(env: str, strict: bool = False) -> int:
    """
    Run all production gate checks.

    Args:
        env: Target environment (dev/prod)
        strict: If True, exit 1 on any failure

    Returns:
        Exit code (0 = all passed, 1 = failures)
    """
    report = GateReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        environment=env,
    )

    # Run all gates
    report.add(check_migration_safety(env))
    report.add(check_db_reality(env))
    report.add(check_evaluator_pass_rate())
    report.add(check_api_readiness(env))
    report.add(check_worker_status(env))

    report.finalize()
    report.print_summary()

    if strict and not report.overall_passed:
        return 1

    return 0 if report.overall_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Production Gate - All checks must pass before deploy"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="prod",
        help="Target environment (default: prod)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any failure",
    )

    args = parser.parse_args()

    exit_code = run_production_gate(args.env, args.strict)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
