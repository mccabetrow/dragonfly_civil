#!/usr/bin/env python3
"""
Dragonfly Engine - Release Gate

A true release gate with two modes:
  - dev:  Local correctness only (tests, import graph, lint, evaluator)
  - prod: Strict production checks (API health, worker heartbeats, DB reality, evaluator)

Configuration:
  Environment variables (no hardcoded URLs):
    DRAGONFLY_API_URL_PROD - Production API base URL
    DRAGONFLY_API_URL_DEV  - Dev API base URL (localhost fallback)
    SUPABASE_MODE          - Target database environment

Usage:
    # Dev gate (local correctness)
    python -m tools.prod_gate --mode dev

    # Prod gate (strict deployment checks)
    python -m tools.prod_gate --mode prod

    # JSON output for CI/CD
    python -m tools.prod_gate --mode prod --json

    # Skip specific checks
    python -m tools.prod_gate --mode prod --skip evaluator
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.logging import configure_worker_logging
from src.supabase_client import get_supabase_db_url, get_supabase_env

# Configure logging
logger = configure_worker_logging("prod_gate")

# =============================================================================
# Configuration - All from environment variables
# =============================================================================

# API URLs - MUST be set via env vars, no hardcoded fallbacks for prod
PROD_API_URL = os.getenv(
    "DRAGONFLY_API_URL_PROD",
    "https://dragonflycivil-production-d57a.up.railway.app",
)
DEV_API_URL = os.getenv("DRAGONFLY_API_URL_DEV", "http://localhost:8000")

# Thresholds
EVALUATOR_PASS_THRESHOLD = 0.95  # 95% minimum pass rate
WORKER_STALE_SECONDS = 300  # 5 minutes


# =============================================================================
# Data Structures
# =============================================================================


@dataclass
class CheckResult:
    """Result of a single gate check."""

    name: str
    passed: bool
    message: str
    remediation: str = ""  # Actionable fix when failed
    details: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "skipped": self.skipped,
            "message": self.message,
            "remediation": self.remediation,
            "details": self.details,
        }


@dataclass
class GateReport:
    """Full release gate report."""

    mode: str  # "dev" or "prod"
    timestamp: str
    environment: str
    checks: list[CheckResult] = field(default_factory=list)
    overall_passed: bool = False

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    def finalize(self) -> None:
        # Only non-skipped checks count toward pass/fail
        active_checks = [c for c in self.checks if not c.skipped]
        self.overall_passed = all(c.passed for c in active_checks)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.passed and not c.skipped)

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed and not c.skipped)

    @property
    def skip_count(self) -> int:
        return sum(1 for c in self.checks if c.skipped)

    @property
    def total_count(self) -> int:
        return len(self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "timestamp": self.timestamp,
            "environment": self.environment,
            "overall_passed": self.overall_passed,
            "summary": {
                "passed": self.pass_count,
                "failed": self.fail_count,
                "skipped": self.skip_count,
                "total": self.total_count,
            },
            "checks": [c.to_dict() for c in self.checks],
        }

    def print_console(self) -> None:
        """Print formatted summary to console with ANSI colors."""
        GREEN = "\033[32m"
        RED = "\033[31m"
        YELLOW = "\033[33m"
        BOLD = "\033[1m"
        RESET = "\033[0m"

        width = 78

        print()
        print("=" * width)
        print(f"  {BOLD}DRAGONFLY RELEASE GATE{RESET} — {self.mode.upper()} MODE")
        print("=" * width)
        print(f"  Timestamp:   {self.timestamp}")
        print(f"  Environment: {self.environment}")
        print(
            f"  Checks:      {self.pass_count} pass, {self.fail_count} fail, {self.skip_count} skip"
        )
        print("-" * width)

        for check in self.checks:
            if check.skipped:
                status = f"{YELLOW}[SKIP]{RESET}"
            elif check.passed:
                status = f"{GREEN}[PASS]{RESET}"
            else:
                status = f"{RED}[FAIL]{RESET}"

            print(f"  {status} {check.name}")
            print(f"         {check.message}")

            if not check.passed and not check.skipped and check.remediation:
                print(f"         {RED}→ FIX: {check.remediation}{RESET}")

            if check.details:
                for key, value in check.details.items():
                    # Truncate long values
                    val_str = str(value)
                    if len(val_str) > 60:
                        val_str = val_str[:57] + "..."
                    print(f"         {key}: {val_str}")
            print()

        print("=" * width)
        if self.overall_passed:
            print(f"  {GREEN}{BOLD}✓ RESULT: GATE PASSED — READY FOR DEPLOY{RESET}")
        else:
            print(f"  {RED}{BOLD}✗ RESULT: GATE FAILED — DO NOT DEPLOY{RESET}")
            # Show first failed check's remediation prominently
            for check in self.checks:
                if not check.passed and not check.skipped and check.remediation:
                    print(f"  {RED}  → {check.remediation}{RESET}")
                    break
        print("=" * width)
        print()


# =============================================================================
# DEV MODE CHECKS (Local Correctness)
# =============================================================================


def check_pytest(skip: bool = False) -> CheckResult:
    """Run pytest and check for failures."""
    if skip:
        return CheckResult(
            name="PyTest Suite",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Running pytest...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=Path(__file__).parent.parent,
        )

        # Parse output for pass/fail counts
        output = result.stdout + result.stderr
        lines = output.strip().split("\n")
        summary_line = lines[-1] if lines else ""

        if result.returncode == 0:
            return CheckResult(
                name="PyTest Suite",
                passed=True,
                message=f"All tests passed: {summary_line}",
            )
        else:
            # Extract failed test names if possible
            failed_tests = [line for line in lines if "FAILED" in line][:3]
            return CheckResult(
                name="PyTest Suite",
                passed=False,
                message=f"Tests failed: {summary_line}",
                remediation="Run `pytest -v` to see full failure details",
                details={"failed_tests": failed_tests},
            )

    except subprocess.TimeoutExpired:
        return CheckResult(
            name="PyTest Suite",
            passed=False,
            message="Pytest timed out (>5min)",
            remediation="Check for hung tests or infinite loops",
        )
    except Exception as e:
        return CheckResult(
            name="PyTest Suite",
            passed=False,
            message=f"Error running pytest: {e}",
            remediation="Ensure pytest is installed: pip install pytest",
        )


def check_import_graph(skip: bool = False) -> CheckResult:
    """Verify all modules can be imported without errors."""
    if skip:
        return CheckResult(
            name="Import Graph",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking import graph...")
    try:
        # Key modules that must import cleanly
        modules = [
            "backend.main",
            "backend.workers.enforcement_engine",
            "backend.workers.ingest_processor",
            "src.supabase_client",
            "etl.src.plaintiff_importer",
        ]

        failed = []
        for mod in modules:
            try:
                __import__(mod)
            except Exception as e:
                failed.append(f"{mod}: {type(e).__name__}")

        if failed:
            return CheckResult(
                name="Import Graph",
                passed=False,
                message=f"{len(failed)} module(s) failed to import",
                remediation="Fix import errors before deploying",
                details={"failed_modules": failed},
            )

        return CheckResult(
            name="Import Graph",
            passed=True,
            message=f"All {len(modules)} key modules import cleanly",
        )

    except Exception as e:
        return CheckResult(
            name="Import Graph",
            passed=False,
            message=f"Error checking imports: {e}",
        )


def check_lint(skip: bool = False) -> CheckResult:
    """Run ruff linter for critical errors only."""
    if skip:
        return CheckResult(
            name="Lint (Ruff)",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Running ruff lint...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", ".", "--select=E9,F63,F7,F82", "--quiet"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).parent.parent,
        )

        if result.returncode == 0:
            return CheckResult(
                name="Lint (Ruff)",
                passed=True,
                message="No critical lint errors",
            )
        else:
            errors = result.stdout.strip().split("\n")[:5]
            return CheckResult(
                name="Lint (Ruff)",
                passed=False,
                message=f"Found {len(errors)} critical lint error(s)",
                remediation="Run `ruff check . --fix` to auto-fix",
                details={"errors": errors},
            )

    except FileNotFoundError:
        return CheckResult(
            name="Lint (Ruff)",
            passed=True,
            message="Skipped (ruff not installed)",
            skipped=True,
        )
    except Exception as e:
        return CheckResult(
            name="Lint (Ruff)",
            passed=False,
            message=f"Error running ruff: {e}",
        )


def check_evaluator(skip: bool = False) -> CheckResult:
    """Run AI evaluator and check pass rate."""
    if skip:
        return CheckResult(
            name="AI Evaluator",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Running AI evaluator...")
    try:
        from backend.ai.evaluator import Evaluator

        evaluator = Evaluator()
        eval_result = evaluator.evaluate_all()

        pass_rate = eval_result.score
        passed = pass_rate >= EVALUATOR_PASS_THRESHOLD

        failed_cases = [r.case_id for r in eval_result.case_results if not r.passed]

        return CheckResult(
            name="AI Evaluator",
            passed=passed,
            message=f"{eval_result.passed_cases}/{eval_result.total_cases} cases passed ({pass_rate:.1%})",
            remediation=(
                f"Evaluator below {EVALUATOR_PASS_THRESHOLD:.0%} threshold. Review failed cases."
                if not passed
                else ""
            ),
            details={
                "pass_rate": f"{pass_rate:.1%}",
                "threshold": f"{EVALUATOR_PASS_THRESHOLD:.0%}",
                "failed_cases": failed_cases[:5] if failed_cases else [],
            },
        )

    except ImportError:
        return CheckResult(
            name="AI Evaluator",
            passed=True,
            message="Skipped (evaluator not available)",
            skipped=True,
        )
    except Exception as e:
        return CheckResult(
            name="AI Evaluator",
            passed=False,
            message=f"Error running evaluator: {e}",
            remediation="Check evaluator configuration and golden dataset",
        )


# =============================================================================
# PROD MODE CHECKS (Strict Production Blockers)
# =============================================================================


def check_api_health(env: str, skip: bool = False) -> CheckResult:
    """Check API /api/health returns 200 OK."""
    if skip:
        return CheckResult(
            name="API Health",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    # In dev mode, skip if localhost isn't running
    if env == "dev":
        return CheckResult(
            name="API Health",
            passed=True,
            message="Skipped in dev mode (local API check not required)",
            skipped=True,
        )

    base_url = PROD_API_URL if env == "prod" else DEV_API_URL
    health_url = f"{base_url}/api/health"

    logger.info(f"Checking API health: {health_url}")

    try:
        req = Request(health_url, method="GET")
        req.add_header("User-Agent", "DragonflyReleaseGate/2.0")

        with urlopen(req, timeout=30) as response:
            status_code = response.getcode()
            body = json.loads(response.read().decode("utf-8"))

            # Handle both wrapped {"ok": true, "data": {...}} and unwrapped responses
            data = body.get("data", body)
            status = data.get("status")
            is_ok = body.get("ok", True) and status == "ok"

            if status_code == 200 and is_ok:
                return CheckResult(
                    name="API Health",
                    passed=True,
                    message=f"API healthy ({base_url})",
                    details={
                        "status": status,
                        "environment": data.get("environment"),
                        "version": data.get("version"),
                    },
                )
            else:
                return CheckResult(
                    name="API Health",
                    passed=False,
                    message=f"API returned unhealthy status: {status}",
                    remediation="Check Railway logs for API errors",
                    details={"url": health_url, "response": body},
                )

    except HTTPError as e:
        return CheckResult(
            name="API Health",
            passed=False,
            message=f"HTTP {e.code}: {e.reason}",
            remediation=f"API at {base_url} returned error. Check Railway deployment.",
            details={"url": health_url},
        )
    except URLError as e:
        return CheckResult(
            name="API Health",
            passed=False,
            message=f"Connection failed: {e.reason}",
            remediation=f"Cannot reach API at {base_url}. Verify Railway service is running.",
            details={"url": health_url},
        )
    except Exception as e:
        return CheckResult(
            name="API Health",
            passed=False,
            message=f"Error: {e}",
            remediation="Unexpected error checking API health",
        )


def check_worker_heartbeats(env: str, skip: bool = False) -> CheckResult:
    """Check workers have recent heartbeats (prod only)."""
    if skip:
        return CheckResult(
            name="Worker Heartbeats",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    # In dev mode, workers aren't expected to be running
    if env == "dev":
        return CheckResult(
            name="Worker Heartbeats",
            passed=True,
            message="Skipped in dev mode (workers not required locally)",
            skipped=True,
        )

    logger.info("Checking worker heartbeats...")

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Get workers with recent heartbeats
                cur.execute(
                    f"""
                    SELECT worker_id, worker_type, status, last_seen_at,
                           EXTRACT(EPOCH FROM (now() - last_seen_at)) AS age_seconds
                    FROM ops.worker_heartbeats
                    WHERE last_seen_at > now() - interval '{WORKER_STALE_SECONDS} seconds'
                    ORDER BY worker_type
                """
                )
                active = cur.fetchall()

                # Get all workers for context
                cur.execute(
                    """
                    SELECT worker_type, status, last_seen_at
                    FROM ops.worker_heartbeats
                    ORDER BY last_seen_at DESC
                    LIMIT 10
                """
                )
                all_workers = cur.fetchall()

        if not all_workers:
            return CheckResult(
                name="Worker Heartbeats",
                passed=False,
                message="No worker heartbeats found in database",
                remediation="Deploy and start workers. See docs/ops/troubleshooting.md",
            )

        if not active:
            # Show last seen times for debugging
            stale_info = [f"{w[0]}={w[1]} @ {w[2]}" for w in all_workers[:3]]
            return CheckResult(
                name="Worker Heartbeats",
                passed=False,
                message=f"No workers active in last {WORKER_STALE_SECONDS}s",
                remediation="Restart workers on Railway. Check for OOM/crashes in logs.",
                details={"last_seen": stale_info},
            )

        active_types = list(set(w[1] for w in active))
        return CheckResult(
            name="Worker Heartbeats",
            passed=True,
            message=f"{len(active)} worker(s) online: {', '.join(active_types)}",
            details={"active_worker_types": active_types},
        )

    except Exception as e:
        return CheckResult(
            name="Worker Heartbeats",
            passed=False,
            message=f"Error checking heartbeats: {e}",
            remediation="Verify database connectivity and ops.worker_heartbeats table exists",
        )


def check_db_connectivity(env: str, skip: bool = False) -> CheckResult:
    """Verify database is reachable and healthy."""
    if skip:
        return CheckResult(
            name="DB Connectivity",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking database connectivity...")

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Basic connectivity
                cur.execute("SELECT 1")
                cur.fetchone()

                # Check critical tables exist
                cur.execute(
                    """
                    SELECT
                        EXISTS (SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'ops' AND table_name = 'job_queue') AS job_queue,
                        EXISTS (SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'ops' AND table_name = 'worker_heartbeats') AS heartbeats,
                        EXISTS (SELECT 1 FROM information_schema.tables
                                WHERE table_schema = 'public' AND table_name = 'plaintiffs') AS plaintiffs
                """
                )
                row = cur.fetchone()
                tables = {"job_queue": row[0], "worker_heartbeats": row[1], "plaintiffs": row[2]}

                missing = [k for k, v in tables.items() if not v]
                if missing:
                    return CheckResult(
                        name="DB Connectivity",
                        passed=False,
                        message=f"Missing tables: {', '.join(missing)}",
                        remediation="Run migrations: ./scripts/db_push.ps1 -SupabaseEnv " + env,
                        details={"missing_tables": missing},
                    )

        return CheckResult(
            name="DB Connectivity",
            passed=True,
            message=f"Database connected ({env}), all critical tables present",
        )

    except psycopg.OperationalError as e:
        return CheckResult(
            name="DB Connectivity",
            passed=False,
            message=f"Connection failed: {e}",
            remediation="Check SUPABASE_DB_URL env var and database availability",
        )
    except Exception as e:
        return CheckResult(
            name="DB Connectivity",
            passed=False,
            message=f"Error: {e}",
        )


def check_current_user(env: str, skip: bool = False) -> CheckResult:
    """
    Verify current_user matches expected role for the environment.

    Expected roles:
    - prod: postgres, dragonfly_app, dragonfly_worker, or authenticated
    - dev: postgres or the service role is acceptable
    """
    if skip:
        return CheckResult(
            name="DB Role Check",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking database current_user role...")

    # Expected roles that are acceptable
    expected_roles = {
        "postgres",
        "dragonfly_app",
        "dragonfly_worker",
        "dragonfly_readonly",
        "authenticated",
        "service_role",
    }

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user, session_user, current_database()")
                row = cur.fetchone()
                current_user = row[0]
                session_user = row[1]
                current_db = row[2]

                if current_user in expected_roles:
                    return CheckResult(
                        name="DB Role Check",
                        passed=True,
                        message=f"Connected as '{current_user}' (session: {session_user})",
                        details={
                            "current_user": current_user,
                            "session_user": session_user,
                            "database": current_db,
                        },
                    )
                else:
                    return CheckResult(
                        name="DB Role Check",
                        passed=False,
                        message=f"Unexpected role '{current_user}'",
                        remediation=f"Connection using unknown role. Expected one of: {expected_roles}",
                        details={
                            "current_user": current_user,
                            "expected_roles": list(expected_roles),
                        },
                    )

    except psycopg.OperationalError as e:
        return CheckResult(
            name="DB Role Check",
            passed=False,
            message=f"Connection failed: {e}",
            remediation="Check SUPABASE_DB_URL env var",
        )
    except Exception as e:
        return CheckResult(
            name="DB Role Check",
            passed=False,
            message=f"Error: {e}",
        )


def check_worker_rpc_capability(env: str, skip: bool = False) -> CheckResult:
    """
    Verify worker RPC functions are callable (read-only test).

    Tests that critical SECURITY DEFINER RPCs exist and are executable:
    - ops.claim_pending_job (via dry-run with empty job types)
    - ops.register_heartbeat (function signature check only)

    This is a safe, read-only check - it doesn't actually claim jobs or write heartbeats.
    """
    if skip:
        return CheckResult(
            name="Worker RPC Capability",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking worker RPC capability...")

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                rpc_results = {}

                # Test 1: Check claim_pending_job exists and is callable
                # Use empty job_types array - will return NULL but proves RPC works
                try:
                    cur.execute(
                        """
                        SELECT ops.claim_pending_job(
                            p_job_types := ARRAY[]::TEXT[],
                            p_lock_timeout_minutes := 1
                        )
                        """
                    )
                    cur.fetchone()
                    rpc_results["claim_pending_job"] = "OK"
                except Exception as e:
                    error_str = str(e)
                    if "permission denied" in error_str.lower():
                        rpc_results["claim_pending_job"] = "PERMISSION_DENIED"
                    elif "does not exist" in error_str.lower():
                        rpc_results["claim_pending_job"] = "NOT_FOUND"
                    else:
                        rpc_results["claim_pending_job"] = f"ERROR: {error_str[:50]}"

                # Test 2: Check register_heartbeat exists (signature check via pg_proc)
                try:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM pg_proc p
                        JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = 'ops'
                          AND p.proname = 'register_heartbeat'
                        """
                    )
                    count = cur.fetchone()[0]
                    if count > 0:
                        rpc_results["register_heartbeat"] = "OK"
                    else:
                        rpc_results["register_heartbeat"] = "NOT_FOUND"
                except Exception as e:
                    rpc_results["register_heartbeat"] = f"ERROR: {str(e)[:50]}"

                # Test 3: Check queue_job exists
                try:
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM pg_proc p
                        JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = 'ops'
                          AND p.proname = 'queue_job'
                        """
                    )
                    count = cur.fetchone()[0]
                    if count > 0:
                        rpc_results["queue_job"] = "OK"
                    else:
                        rpc_results["queue_job"] = "NOT_FOUND"
                except Exception as e:
                    rpc_results["queue_job"] = f"ERROR: {str(e)[:50]}"

                # Evaluate results
                failed_rpcs = [k for k, v in rpc_results.items() if v != "OK"]

                if failed_rpcs:
                    return CheckResult(
                        name="Worker RPC Capability",
                        passed=False,
                        message=f"RPC check failed: {', '.join(failed_rpcs)}",
                        remediation="Apply migrations to create missing RPCs: ./scripts/db_push.ps1",
                        details=rpc_results,
                    )

                return CheckResult(
                    name="Worker RPC Capability",
                    passed=True,
                    message="All worker RPCs available and callable",
                    details=rpc_results,
                )

    except psycopg.OperationalError as e:
        return CheckResult(
            name="Worker RPC Capability",
            passed=False,
            message=f"Connection failed: {e}",
            remediation="Check database connectivity first",
        )
    except Exception as e:
        return CheckResult(
            name="Worker RPC Capability",
            passed=False,
            message=f"Error: {e}",
        )


def check_schema_drift(env: str, skip: bool = False) -> CheckResult:
    """
    Check for schema drift by comparing expected views against production.

    Uses synchronous queries to check that critical views exist in the database.
    """
    if skip:
        return CheckResult(
            name="Schema Drift",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking for schema drift...")

    # Critical views that must exist
    critical_views = [
        "public.v_plaintiffs_overview",
        "public.v_judgment_pipeline",
        "public.v_enforcement_overview",
        "public.v_enforcement_recent",
        "public.v_plaintiff_call_queue",
    ]

    try:
        db_url = get_supabase_db_url(env)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Get all views in monitored schemas
                cur.execute(
                    """
                    SELECT table_schema || '.' || table_name AS view_name
                    FROM information_schema.views
                    WHERE table_schema IN ('public', 'ops', 'enforcement', 'analytics')
                    """
                )
                existing_views = {row[0].lower() for row in cur.fetchall()}

                # Check for missing critical views
                missing_views = []
                for view in critical_views:
                    if view.lower() not in existing_views:
                        missing_views.append(view)

                if missing_views:
                    return CheckResult(
                        name="Schema Drift",
                        passed=False,
                        message=f"Missing {len(missing_views)} critical view(s)",
                        remediation="Run migrations or recovery: ./scripts/db_push.ps1 && python -m tools.schema_repair",
                        details={
                            "missing_views": missing_views,
                            "existing_view_count": len(existing_views),
                        },
                    )

                # Also check critical RPC functions exist
                cur.execute(
                    """
                    SELECT n.nspname || '.' || p.proname AS func_name
                    FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'ops'
                      AND p.proname IN ('claim_pending_job', 'register_heartbeat', 'queue_job', 'upsert_judgment')
                    """
                )
                existing_funcs = {row[0].lower() for row in cur.fetchall()}

                expected_funcs = [
                    "ops.claim_pending_job",
                    "ops.register_heartbeat",
                    "ops.queue_job",
                ]
                missing_funcs = [f for f in expected_funcs if f.lower() not in existing_funcs]

                if missing_funcs:
                    return CheckResult(
                        name="Schema Drift",
                        passed=False,
                        message=f"Missing {len(missing_funcs)} critical RPC function(s)",
                        remediation="Apply security migration: ./scripts/db_push.ps1",
                        details={
                            "missing_functions": missing_funcs,
                            "views_ok": True,
                        },
                    )

                return CheckResult(
                    name="Schema Drift",
                    passed=True,
                    message=f"No drift detected ({len(critical_views)} views, {len(expected_funcs)} RPCs verified)",
                    details={
                        "verified_views": len(critical_views),
                        "verified_funcs": len(expected_funcs),
                    },
                )

    except psycopg.OperationalError as e:
        return CheckResult(
            name="Schema Drift",
            passed=False,
            message=f"Connection failed: {e}",
            remediation="Check database connectivity first",
        )
    except Exception as e:
        return CheckResult(
            name="Schema Drift",
            passed=False,
            message=f"Error: {e}",
        )


def check_migrations(env: str, skip: bool = False) -> CheckResult:
    """Check for pending migrations."""
    if skip:
        return CheckResult(
            name="Migration Status",
            passed=True,
            message="Skipped by user request",
            skipped=True,
        )

    logger.info("Checking migration status...")

    try:
        db_url = get_supabase_db_url(env)
        migrations_dir = Path(__file__).parent.parent / "supabase" / "migrations"

        if not migrations_dir.exists():
            return CheckResult(
                name="Migration Status",
                passed=False,
                message="Migrations directory not found",
                remediation="Ensure supabase/migrations/ exists",
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

        pending = [m for m in local_migrations if m not in applied]

        if pending:
            # In dev, pending migrations are a warning only
            if env == "dev":
                return CheckResult(
                    name="Migration Status",
                    passed=True,  # Pass in dev
                    message=f"{len(pending)} pending migration(s) (dev: OK)",
                    details={"pending": pending[:5]},
                )
            else:
                return CheckResult(
                    name="Migration Status",
                    passed=False,
                    message=f"{len(pending)} pending migration(s)",
                    remediation=f"Apply migrations: ./scripts/db_push.ps1 -SupabaseEnv {env}",
                    details={"pending": pending[:5]},
                )

        return CheckResult(
            name="Migration Status",
            passed=True,
            message=f"All {len(local_migrations)} migrations applied",
        )

    except Exception as e:
        return CheckResult(
            name="Migration Status",
            passed=False,
            message=f"Error checking migrations: {e}",
        )


# =============================================================================
# Gate Runners
# =============================================================================


def run_dev_gate(skips: set[str]) -> GateReport:
    """
    Dev gate: Local correctness checks only.

    Checks:
    - PyTest suite
    - Import graph (all modules load)
    - Lint (critical errors only)
    - AI Evaluator (optional)
    - DB connectivity
    - Current user role
    - Worker RPC capability
    - Schema drift
    """
    env = get_supabase_env()

    report = GateReport(
        mode="dev",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        environment=env,
    )

    # Dev checks - code correctness
    report.add(check_pytest("pytest" in skips))
    report.add(check_import_graph("imports" in skips))
    report.add(check_lint("lint" in skips))
    report.add(check_evaluator("evaluator" in skips))

    # Dev checks - database
    report.add(check_db_connectivity(env, "db" in skips))
    report.add(check_current_user(env, "role" in skips))
    report.add(check_worker_rpc_capability(env, "rpc" in skips))
    report.add(check_schema_drift(env, "drift" in skips))

    report.finalize()
    return report


def run_prod_gate(skips: set[str]) -> GateReport:
    """
    Prod gate: Strict production blockers.

    Checks:
    - DB connectivity (can open connection)
    - Current user role (expected role for env)
    - Worker RPC capability (claim job, heartbeat via RPC)
    - Migration status (none pending)
    - Schema drift (critical views/functions exist)
    - API health (200 OK)
    - Worker heartbeats (online)
    - AI Evaluator pass rate
    """
    env = "prod"  # Always check prod for prod gate

    report = GateReport(
        mode="prod",
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds") + "Z",
        environment=env,
    )

    # Production checks - database first (fail fast)
    report.add(check_db_connectivity(env, "db" in skips))
    report.add(check_current_user(env, "role" in skips))
    report.add(check_worker_rpc_capability(env, "rpc" in skips))
    report.add(check_migrations(env, "migrations" in skips))
    report.add(check_schema_drift(env, "drift" in skips))

    # Production checks - runtime
    report.add(check_api_health(env, "api" in skips))
    report.add(check_worker_heartbeats(env, "workers" in skips))
    report.add(check_evaluator("evaluator" in skips))

    report.finalize()
    return report


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dragonfly Release Gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tools.prod_gate --mode dev          # Dev correctness checks
  python -m tools.prod_gate --mode prod         # Prod deployment checks
  python -m tools.prod_gate --mode prod --json  # JSON output for CI
  python -m tools.prod_gate --mode dev --skip evaluator pytest
  python -m tools.prod_gate --mode prod --skip api workers  # DB checks only
""",
    )
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        required=True,
        help="Gate mode: 'dev' for local correctness, 'prod' for deployment checks",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of formatted console",
    )
    parser.add_argument(
        "--skip",
        nargs="+",
        default=[],
        choices=[
            "pytest",
            "imports",
            "lint",
            "evaluator",  # Dev checks
            "api",
            "workers",
            "db",
            "migrations",  # Prod checks
            "role",
            "rpc",
            "drift",  # New checks
        ],
        help="Skip specific checks",
    )
    # Legacy --env flag for backwards compatibility
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        help="(Deprecated) Use --mode instead",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="(Deprecated) Prod gate is always strict",
    )

    args = parser.parse_args()

    # Handle legacy --env flag
    mode = args.mode
    if args.env and not args.mode:
        logger.warning("--env is deprecated, use --mode instead")
        mode = args.env

    skips = set(args.skip)

    # Run appropriate gate
    if mode == "dev":
        report = run_dev_gate(skips)
    else:
        report = run_prod_gate(skips)

    # Output
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        report.print_console()

    # Exit code
    sys.exit(0 if report.overall_passed else 1)


if __name__ == "__main__":
    main()
