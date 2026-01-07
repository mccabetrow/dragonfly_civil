#!/usr/bin/env python3
"""
Dragonfly Civil - Go-Live Gate

The final gatekeeper script that certifies the production environment
is ready for plaintiff onboarding. Runs the full "Readiness Suite" in
strict order - any failure is FATAL and blocks go-live.

This script orchestrates:
1. Bootstrap & Security Guard (environment safety)
2. Secret Leak Scan (no credentials in codebase)
3. Migration Integrity (no drift, no pending)
4. Tenancy Audit (org_id NOT NULL enforcement)
5. Audit Immutability (court-proof delete blocks)
6. Permission Audit (search_path, RLS enforcement)
7. Security Definer Safety (FATAL: all SECURITY DEFINER must have search_path)
8. Forbidden Env Vars (FATAL: no SUPABASE_MIGRATE_DB_URL in prod)
9. PostgREST Health Check (informational)
10. Golden Path (end-to-end pipeline)
11. Subsystem Smoke Tests (plaintiffs + enforcement)
12. Frontend Security (RAG Safety Policy #1: no OpenAI in frontend)
13. Worker Health (heartbeat freshness - warning only)

Usage:
    python -m tools.go_live_gate --env prod
    python -m tools.go_live_gate --env dev --skip-discord

Exit Codes:
    0 - GO-LIVE CERTIFIED ✅
    1 - GO-LIVE FAILED ❌
    2 - Configuration error (missing env, bad args)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════════════════
# Constants & Configuration
# ═══════════════════════════════════════════════════════════════════════════


class GateStatus(str, Enum):
    """Status of a gate check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    INFO = "info"  # Informational, doesn't affect overall status


@dataclass
class GateResult:
    """Result of a single gate check."""

    name: str
    status: GateStatus
    message: str
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    fatal: bool = True  # If True, failure stops execution

    @property
    def passed(self) -> bool:
        return self.status in (GateStatus.PASSED, GateStatus.INFO, GateStatus.SKIPPED)


@dataclass
class GoLiveReport:
    """Complete go-live certification report."""

    env: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    gates: list[GateResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """All fatal gates must pass."""
        return all(g.passed for g in self.gates if g.fatal)

    @property
    def failed_gate(self) -> GateResult | None:
        """Return the first failed fatal gate."""
        for gate in self.gates:
            if gate.fatal and not gate.passed:
                return gate
        return None

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds() * 1000


# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════


def print_banner(title: str, char: str = "═", width: int = 70) -> None:
    """Print a formatted banner."""
    print()
    print(char * width)
    print(f"  {title}")
    print(char * width)


def print_gate_header(gate_num: int, name: str) -> None:
    """Print gate header."""
    print()
    print(f"[Gate {gate_num}] {name}")
    print("-" * 50)


def format_duration(ms: float) -> str:
    """Format duration for display."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def run_with_timing(func: Callable[[], GateResult]) -> GateResult:
    """Run a function and measure its duration."""
    import time

    start = time.monotonic()
    result = func()
    result.duration_ms = (time.monotonic() - start) * 1000
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Gate 1: Bootstrap & Security Guard
# ═══════════════════════════════════════════════════════════════════════════


def gate_bootstrap_security(env: str) -> GateResult:
    """
    Bootstrap the environment and verify credential safety.

    FATAL: If checks fail, we cannot trust any subsequent operations.
    """
    try:
        from backend.core.bootstrap import bootstrap_environment
        from backend.core.security_guard import verify_safe_environment

        # Bootstrap with explicit environment
        print(f"   Bootstrapping environment: {env}")
        active_env = bootstrap_environment(cli_override=env, verbose=False)

        if active_env != env:
            return GateResult(
                name="Bootstrap & Security Guard",
                status=GateStatus.FAILED,
                message=f"Environment mismatch: requested {env}, got {active_env}",
            )

        # Verify credential safety
        print("   Verifying credential safety...")
        verify_safe_environment(active_env)  # Exits if unsafe!

        print(f"   ✓ Environment: {active_env}")
        print("   ✓ Credentials verified safe")

        return GateResult(
            name="Bootstrap & Security Guard",
            status=GateStatus.PASSED,
            message=f"Environment {env} bootstrapped safely",
            details={"env": active_env},
        )

    except SystemExit as e:
        return GateResult(
            name="Bootstrap & Security Guard",
            status=GateStatus.FAILED,
            message=f"Security guard blocked execution (exit {e.code})",
        )
    except Exception as e:
        return GateResult(
            name="Bootstrap & Security Guard",
            status=GateStatus.FAILED,
            message=f"Bootstrap failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 2: Secret Leak Scan
# ═══════════════════════════════════════════════════════════════════════════


def gate_secret_leak_scan(env: str) -> GateResult:
    """
    Scan codebase for accidentally committed secrets.

    FATAL: Any secrets in codebase = security breach.
    """
    try:
        from pathlib import Path

        from tools.secret_leak_scan import SecretScanner

        print("   Scanning codebase for secrets...")
        project_root = Path(__file__).parent.parent.absolute()
        scanner = SecretScanner(project_root=project_root, strict=True, verbose=False)
        passed = scanner.scan()

        if not passed:
            finding_count = len(scanner.findings)
            critical_count = len([f for f in scanner.findings if f.severity.value == "CRITICAL"])
            high_count = len([f for f in scanner.findings if f.severity.value == "HIGH"])

            print(f"   ❌ Found {finding_count} potential secrets!")
            print(f"      Critical: {critical_count}, High: {high_count}")
            for f in scanner.findings[:3]:
                print(f"      - {f.file_path}:{f.line_number} ({f.pattern_name})")

            return GateResult(
                name="Secret Leak Scan",
                status=GateStatus.FAILED,
                message=f"Found {finding_count} potential secrets in codebase",
                details={
                    "total_findings": finding_count,
                    "critical": critical_count,
                    "high": high_count,
                    "files_scanned": scanner.files_scanned,
                },
            )

        print(f"   ✓ Scanned {scanner.files_scanned} files - no secrets detected")
        return GateResult(
            name="Secret Leak Scan",
            status=GateStatus.PASSED,
            message=f"No secrets detected in {scanner.files_scanned} files",
            details={"files_scanned": scanner.files_scanned},
        )

    except Exception as e:
        return GateResult(
            name="Secret Leak Scan",
            status=GateStatus.FAILED,
            message=f"Secret scan failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 3: Migration Integrity
# ═══════════════════════════════════════════════════════════════════════════


def gate_migration_integrity(env: str) -> GateResult:
    """
    Verify migration integrity: no drift, no pending migrations.

    FATAL: Drift or pending migrations mean schema is not in known state.
    """
    try:
        # Import verification components
        from tools.verify_migrations import (
            VerificationResult,
            fetch_db_migrations,
            get_db_url,
            scan_local_migrations,
        )

        print("   Scanning local migrations...")
        migrations_dir = PROJECT_ROOT / "supabase" / "migrations"
        local = scan_local_migrations(migrations_dir)
        print(f"   Found {len(local)} local migration files")

        print("   Fetching database migration history...")
        db_url = get_db_url(env)
        db_migrations = fetch_db_migrations(db_url)
        print(f"   Found {len(db_migrations)} applied migrations")

        # Compare versions
        local_versions = {m.version for m in local}
        db_versions = {m.version for m in db_migrations}

        pending = [m for m in local if m.version not in db_versions]
        drift = [m for m in db_migrations if m.version not in local_versions]

        if drift:
            print(f"   ❌ DRIFT DETECTED: {len(drift)} migrations in DB but not local!")
            for m in drift[:5]:
                print(f"      - {m.version} ({m.name or 'unknown'})")
            return GateResult(
                name="Migration Integrity",
                status=GateStatus.FAILED,
                message=f"DRIFT: {len(drift)} migrations in DB not found locally",
                details={"drift_count": len(drift)},
            )

        if pending:
            print(f"   ⚠️  {len(pending)} pending migrations not yet applied")
            for m in pending[:5]:
                print(f"      - {m.name}")
            return GateResult(
                name="Migration Integrity",
                status=GateStatus.FAILED,
                message=f"PENDING: {len(pending)} migrations need to be applied",
                details={"pending_count": len(pending)},
            )

        print(f"   ✓ All {len(local)} migrations synced")
        return GateResult(
            name="Migration Integrity",
            status=GateStatus.PASSED,
            message=f"All {len(local)} migrations in sync",
            details={"local_count": len(local), "db_count": len(db_migrations)},
        )

    except Exception as e:
        return GateResult(
            name="Migration Integrity",
            status=GateStatus.FAILED,
            message=f"Migration check failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 4: Tenancy Audit
# ═══════════════════════════════════════════════════════════════════════════


def gate_tenancy_audit(env: str) -> GateResult:
    """
    Audit org_id column constraints for multi-tenant safety.

    FATAL: Nullable org_id columns allow cross-tenant data leaks.
    """
    try:
        from tools.audit_tenancy import run_audit

        print("   Running tenancy audit (org_id NOT NULL enforcement)...")
        result = run_audit(env, strict=True, verbose=False, include_views=False)

        if not result.passed:
            failure_count = len(result.critical_failures)
            print(f"   ❌ {failure_count} tenancy violations found!")
            for msg in result.critical_failures[:5]:
                print(f"      - {msg}")

            return GateResult(
                name="Tenancy Audit",
                status=GateStatus.FAILED,
                message=f"{failure_count} org_id columns allow NULL (tenancy breach)",
                details={
                    "critical_failures": result.critical_failures[:10],
                    "warnings": result.warnings[:10],
                },
            )

        warning_count = len(result.warnings)
        print(f"   ✓ Tenancy audit passed ({warning_count} warnings)")
        return GateResult(
            name="Tenancy Audit",
            status=GateStatus.PASSED,
            message=f"All org_id columns enforce NOT NULL ({warning_count} warnings)",
            details={"warnings": result.warnings},
        )

    except Exception as e:
        return GateResult(
            name="Tenancy Audit",
            status=GateStatus.FAILED,
            message=f"Tenancy audit failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 5: Audit Immutability (Court-Proof)
# ═══════════════════════════════════════════════════════════════════════════


def gate_audit_immutability(env: str) -> GateResult:
    """
    Verify audit tables block DELETE operations (court-proof).

    FATAL: Without delete blocks, audit trails can be tampered with.
    """
    try:
        from tools.verify_court_proof import run_validation

        print("   Running court-proof validation (audit immutability)...")
        result = run_validation(env, verbose=False)

        if not result.passed:
            failure_count = len(result.critical_failures)
            print(f"   ❌ {failure_count} court-proof violations!")
            for msg in result.critical_failures[:5]:
                print(f"      - {msg}")

            return GateResult(
                name="Audit Immutability",
                status=GateStatus.FAILED,
                message=f"{failure_count} audit immutability violations (court-proof broken)",
                details={
                    "critical_failures": result.critical_failures[:10],
                    "tests_run": len(result.tests),
                },
            )

        passed_tests = len([t for t in result.tests if t.passed])
        print(f"   ✓ All {passed_tests} court-proof tests passed")
        return GateResult(
            name="Audit Immutability",
            status=GateStatus.PASSED,
            message=f"Audit tables are court-proof ({passed_tests} tests)",
            details={"tests_passed": passed_tests},
        )

    except Exception as e:
        return GateResult(
            name="Audit Immutability",
            status=GateStatus.FAILED,
            message=f"Court-proof validation failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 6: Permission Audit
# ═══════════════════════════════════════════════════════════════════════════


def gate_permission_audit(env: str) -> GateResult:
    """
    Audit database permissions for security compliance.

    FATAL: Missing search_path or schema access issues = security risk.
    """
    try:
        from tools.audit_permissions import (
            check_function_safety,
            check_rls_status,
            check_schema_access,
            check_view_access,
            connect,
        )

        print("   Connecting to database...")
        conn = connect(env)

        errors = []
        warnings = []

        # Check schema access
        print("   Checking schema access privileges...")
        schema_results = check_schema_access(conn)
        for r in schema_results:
            if not r.passed and r.severity == "error":
                errors.append(r.message)
            elif not r.passed and r.severity == "warning":
                warnings.append(r.message)

        # Check view access
        print("   Checking view access privileges...")
        view_results = check_view_access(conn)
        for r in view_results:
            if not r.passed and r.severity == "error":
                errors.append(r.message)

        # Check SECURITY DEFINER functions have search_path
        print("   Checking function search_path settings...")
        definer_results = check_function_safety(conn)
        for r in definer_results:
            if not r.passed and r.severity == "error":
                errors.append(r.message)
                if r.details:
                    for d in r.details[:3]:
                        print(f"      - {d}")

        # Check RLS status
        print("   Checking RLS enforcement...")
        rls_results = check_rls_status(conn)
        for r in rls_results:
            if not r.passed and r.severity == "error":
                errors.append(r.message)

        conn.close()

        if errors:
            print(f"   ❌ {len(errors)} security violations found")
            return GateResult(
                name="Permission Audit",
                status=GateStatus.FAILED,
                message=f"{len(errors)} security violations detected",
                details={"errors": errors[:5], "warnings": warnings[:5]},
            )

        print(f"   ✓ Permission audit passed ({len(warnings)} warnings)")
        return GateResult(
            name="Permission Audit",
            status=GateStatus.PASSED,
            message=f"Security audit passed ({len(warnings)} warnings)",
            details={"warnings": warnings},
        )

    except Exception as e:
        return GateResult(
            name="Permission Audit",
            status=GateStatus.FAILED,
            message=f"Permission audit failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 7: PostgREST Health (Informational)
# ═══════════════════════════════════════════════════════════════════════════


def gate_postgrest_health(env: str) -> GateResult:
    """
    Check PostgREST health status.

    INFORMATIONAL: We log the status but don't fail on it.
    The system can operate via direct DB fallback.
    """
    try:
        from backend.core.health import HealthStatus, check_postgrest_status

        print("   Checking PostgREST health...")
        status = check_postgrest_status(env=env)

        status_emoji = {
            HealthStatus.HEALTHY: "✓",
            HealthStatus.STALE_CACHE: "⚠️",
            HealthStatus.UNAVAILABLE: "❌",
        }.get(status.status, "?")

        print(f"   {status_emoji} PostgREST: {status.status.value}")
        print(f"     Latency: {status.latency_ms:.0f}ms")
        if status.error:
            print(f"     Error: {status.error}")

        return GateResult(
            name="PostgREST Health",
            status=GateStatus.INFO,  # Informational only
            message=f"PostgREST: {status.status.value} ({status.latency_ms:.0f}ms)",
            details={
                "health_status": status.status.value,
                "latency_ms": status.latency_ms,
                "error": status.error,
            },
            fatal=False,  # Don't fail go-live on PostgREST issues
        )

    except Exception as e:
        return GateResult(
            name="PostgREST Health",
            status=GateStatus.INFO,
            message=f"PostgREST check failed: {type(e).__name__}: {e}",
            fatal=False,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 8: Golden Path
# ═══════════════════════════════════════════════════════════════════════════


def gate_golden_path(env: str) -> GateResult:
    """
    Run the golden path end-to-end validation.

    FATAL: This is the ultimate pipeline integrity test.
    """
    try:
        # Run golden path as subprocess
        print("   Running golden path validation...")
        print("   (This may take 30-60 seconds)")

        # Step 1: Run golden path (creates test data)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.golden_path",
                "--env",
                env,
            ],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=PROJECT_ROOT,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode == 0:
            print("   ✓ Golden path passed")
            # Step 2: Clean up test data
            print("   Cleaning up test data...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.golden_path",
                    "--cleanup",
                ],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=PROJECT_ROOT,
                encoding="utf-8",
                errors="replace",
            )
            print("   ✓ Cleanup complete")
            return GateResult(
                name="Golden Path",
                status=GateStatus.PASSED,
                message="Golden path validation passed",
                details={"output_lines": len(result.stdout.split("\n"))},
            )
        else:
            # Extract error from output
            stderr = result.stderr.strip() or result.stdout.strip()
            last_lines = "\n".join(stderr.split("\n")[-5:])
            print(f"   ❌ Golden path failed (exit {result.returncode})")
            print(f"   Last output: {last_lines[:200]}")
            return GateResult(
                name="Golden Path",
                status=GateStatus.FAILED,
                message=f"Golden path failed (exit {result.returncode})",
                details={"exit_code": result.returncode, "last_output": last_lines[:500]},
            )

    except subprocess.TimeoutExpired:
        return GateResult(
            name="Golden Path",
            status=GateStatus.FAILED,
            message="Golden path timed out after 5 minutes",
        )
    except Exception as e:
        return GateResult(
            name="Golden Path",
            status=GateStatus.FAILED,
            message=f"Golden path error: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 9: Subsystem Smoke Tests
# ═══════════════════════════════════════════════════════════════════════════


def gate_smoke_tests(env: str) -> GateResult:
    """
    Run subsystem smoke tests for plaintiffs and enforcement.

    FATAL: These views are critical for production operations.
    """
    try:
        import psycopg

        from src.supabase_client import get_supabase_db_url

        db_url = get_supabase_db_url(env)

        print("   Running plaintiff smoke tests...")
        plaintiff_counts = {}
        enforcement_counts = {}

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Plaintiff views
                for label, query in [
                    ("plaintiffs", "SELECT count(*) FROM public.plaintiffs"),
                    ("contacts", "SELECT count(*) FROM public.plaintiff_contacts"),
                    ("overview", "SELECT count(*) FROM public.v_plaintiffs_overview"),
                    ("call_queue", "SELECT count(*) FROM public.v_plaintiff_call_queue"),
                ]:
                    try:
                        cur.execute(query)
                        row = cur.fetchone()
                        plaintiff_counts[label] = row[0] if row else 0
                    except Exception as e:
                        return GateResult(
                            name="Subsystem Smoke Tests",
                            status=GateStatus.FAILED,
                            message=f"Plaintiff view {label} failed: {e}",
                        )

                print(f"   ✓ Plaintiffs: {plaintiff_counts}")

                # Enforcement views
                print("   Running enforcement smoke tests...")
                for label, query in [
                    ("overview", "SELECT count(*) FROM public.v_enforcement_overview"),
                    ("recent", "SELECT count(*) FROM public.v_enforcement_recent"),
                    ("pipeline", "SELECT count(*) FROM public.v_judgment_pipeline"),
                ]:
                    try:
                        cur.execute(query)
                        row = cur.fetchone()
                        enforcement_counts[label] = row[0] if row else 0
                    except Exception as e:
                        return GateResult(
                            name="Subsystem Smoke Tests",
                            status=GateStatus.FAILED,
                            message=f"Enforcement view {label} failed: {e}",
                        )

                print(f"   ✓ Enforcement: {enforcement_counts}")

        return GateResult(
            name="Subsystem Smoke Tests",
            status=GateStatus.PASSED,
            message="All subsystem smoke tests passed",
            details={
                "plaintiffs": plaintiff_counts,
                "enforcement": enforcement_counts,
            },
        )

    except Exception as e:
        return GateResult(
            name="Subsystem Smoke Tests",
            status=GateStatus.FAILED,
            message=f"Smoke tests failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 10: Frontend Security (RAG Safety Policy #1)
# ═══════════════════════════════════════════════════════════════════════════


def gate_frontend_security(env: str) -> GateResult:
    """
    Scan frontend for forbidden patterns (OpenAI SDK, API keys).

    RAG Safety Policy #1: "Frontend NEVER talks to OpenAI."
    Any direct OpenAI imports or exposed API keys in the dashboard will
    FAIL THE DEPLOYMENT. All AI calls must flow through the backend.

    FATAL: If OpenAI is detected in frontend, deployment is blocked.
    """
    try:
        from tools.scan_frontend_security import SecurityViolation, find_frontend_dir, scan_frontend

        print("   Scanning frontend for forbidden patterns...")
        print("   Policy: No OpenAI SDK, no API keys, no VITE_OPENAI_API_KEY")

        frontend_dir = find_frontend_dir()
        if frontend_dir is None:
            return GateResult(
                name="Frontend Security",
                status=GateStatus.FAILED,
                message="Frontend directory not found",
            )

        result = scan_frontend(frontend_dir, verbose=False)

        if result.violations:
            # Group violations by type for reporting
            by_type: dict[str, list[SecurityViolation]] = {}
            for v in result.violations:
                by_type.setdefault(v.violation_type, []).append(v)

            print(f"   ❌ FOUND {len(result.violations)} SECURITY VIOLATIONS!")
            for vtype, vlist in by_type.items():
                print(f"      {vtype}: {len(vlist)} occurrences")
                for v in vlist[:3]:
                    print(f"         - {v.file_path}:{v.line_number}")

            return GateResult(
                name="Frontend Security",
                status=GateStatus.FAILED,
                message=f"RAG Safety Policy violated: {len(result.violations)} forbidden patterns detected",
                details={
                    "violation_count": len(result.violations),
                    "violation_types": list(by_type.keys()),
                    "files_scanned": result.files_scanned,
                },
            )

        print(f"   ✓ {result.files_scanned} files scanned")
        print(f"   ✓ {result.env_files_checked} env files checked")
        print("   ✓ No OpenAI imports detected")
        print("   ✓ No API keys exposed")

        return GateResult(
            name="Frontend Security",
            status=GateStatus.PASSED,
            message="Frontend is strictly decoupled from OpenAI",
            details={
                "files_scanned": result.files_scanned,
                "env_files_checked": result.env_files_checked,
            },
        )

    except ImportError as e:
        return GateResult(
            name="Frontend Security",
            status=GateStatus.FAILED,
            message=f"Scanner not available: {e}",
        )
    except Exception as e:
        return GateResult(
            name="Frontend Security",
            status=GateStatus.FAILED,
            message=f"Frontend scan failed: {type(e).__name__}: {e}",
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 11: Worker Health
# ═══════════════════════════════════════════════════════════════════════════


def gate_worker_health(env: str) -> GateResult:
    """
    Check worker fleet health via heartbeat freshness.

    INFORMATIONAL: Stale workers are a warning, not a fatal failure.
    The system can still operate with some workers down.
    """
    try:
        import psycopg

        from src.supabase_client import get_supabase_db_url

        db_url = get_supabase_db_url(env)
        stale_threshold_minutes = 5

        print("   Checking worker heartbeat freshness...")

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Check for stale workers
                cur.execute(
                    """
                    SELECT worker_id, status, last_heartbeat_at,
                           EXTRACT(EPOCH FROM (now() - last_heartbeat_at)) / 60 AS age_minutes
                    FROM workers.heartbeats
                    WHERE last_heartbeat_at < now() - interval '%s minutes'
                    ORDER BY last_heartbeat_at DESC
                """,
                    (stale_threshold_minutes,),
                )
                stale_workers = cur.fetchall()

                # Get total worker count
                cur.execute("SELECT count(*) FROM workers.heartbeats")
                total_row = cur.fetchone()
                total_workers = total_row[0] if total_row else 0

                # Get healthy worker count
                cur.execute(
                    """
                    SELECT count(*) FROM workers.heartbeats
                    WHERE last_heartbeat_at >= now() - interval '%s minutes'
                """,
                    (stale_threshold_minutes,),
                )
                healthy_row = cur.fetchone()
                healthy_workers = healthy_row[0] if healthy_row else 0

        if stale_workers:
            stale_count = len(stale_workers)
            print(f"   ⚠️  {stale_count} stale workers detected (>{stale_threshold_minutes}min)")
            for row in stale_workers[:5]:
                worker_id, status, last_hb, age = row
                print(f"      - {worker_id}: {age:.1f}min ago ({status})")

            return GateResult(
                name="Worker Health",
                status=GateStatus.INFO,  # Warning only, not fatal
                message=f"{stale_count} stale workers, {healthy_workers}/{total_workers} healthy",
                details={
                    "total_workers": total_workers,
                    "healthy_workers": healthy_workers,
                    "stale_workers": stale_count,
                    "stale_threshold_minutes": stale_threshold_minutes,
                },
                fatal=False,  # Don't fail go-live on worker issues
            )

        print(f"   ✓ All {total_workers} workers healthy")
        return GateResult(
            name="Worker Health",
            status=GateStatus.INFO,
            message=f"All {total_workers} workers healthy (heartbeats fresh)",
            details={
                "total_workers": total_workers,
                "healthy_workers": healthy_workers,
            },
            fatal=False,
        )

    except Exception as e:
        # If workers schema doesn't exist or other issue, just warn
        return GateResult(
            name="Worker Health",
            status=GateStatus.INFO,
            message=f"Worker health check skipped: {type(e).__name__}: {e}",
            fatal=False,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 12: Security Definer Safety (FATAL)
# ═══════════════════════════════════════════════════════════════════════════


def gate_security_definer_safety(env: str) -> GateResult:
    """
    Verify ALL SECURITY DEFINER functions have search_path configured.

    FATAL: Missing search_path on SECURITY DEFINER = SQL injection vector.
    Every security definer function MUST lock down its search_path.

    Note: Supabase internal schemas (graphql, storage, vault, etc.) are excluded
    as they are managed by Supabase and outside our control.

    Reference: https://www.postgresql.org/docs/current/sql-createfunction.html
    """
    # Supabase-managed schemas we don't control
    EXCLUDED_SCHEMAS = (
        "pg_catalog",
        "information_schema",
        "graphql",
        "graphql_public",
        "storage",
        "vault",
        "pgsodium",
        "supabase_functions",
        "supabase_migrations",
        "extensions",
        "pgbouncer",
        "realtime",
        "auth",  # Supabase auth - managed by them
    )

    try:
        import psycopg

        from src.supabase_client import get_supabase_db_url

        db_url = get_supabase_db_url(env)

        print("   Scanning SECURITY DEFINER functions for search_path...")
        print("   (excluding Supabase-managed schemas)")

        # Build the exclusion list for SQL
        excluded_list = ", ".join(f"'{s}'" for s in EXCLUDED_SCHEMAS)

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Query all SECURITY DEFINER functions and check proconfig
                # Exclude Supabase-managed schemas
                cur.execute(
                    f"""
                    SELECT 
                        n.nspname || '.' || p.proname AS function_name,
                        p.proconfig
                    FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE p.prosecdef = true
                      AND n.nspname NOT IN ({excluded_list})
                    ORDER BY n.nspname, p.proname
                """
                )
                definer_functions = cur.fetchall()

        offenders = []
        for func_name, proconfig in definer_functions:
            # proconfig is an array like ['search_path=public, pg_temp']
            has_search_path = False
            if proconfig:
                for setting in proconfig:
                    if setting.lower().startswith("search_path"):
                        has_search_path = True
                        break

            if not has_search_path:
                offenders.append(func_name)

        if offenders:
            print(f"   ❌ {len(offenders)} SECURITY DEFINER function(s) missing search_path!")
            print()
            print("   🚨 OFFENDING FUNCTIONS (SQL Injection Risk):")
            for func in offenders[:10]:
                print(f"      - {func}")
            if len(offenders) > 10:
                print(f"      ... and {len(offenders) - 10} more")

            return GateResult(
                name="Security Definer Safety",
                status=GateStatus.FAILED,
                message=f"{len(offenders)} SECURITY DEFINER functions missing search_path",
                details={"offenders": offenders},
                fatal=True,  # HARD BLOCKER
            )

        print(f"   ✓ All {len(definer_functions)} SECURITY DEFINER functions have search_path")
        return GateResult(
            name="Security Definer Safety",
            status=GateStatus.PASSED,
            message=f"All {len(definer_functions)} SECURITY DEFINER functions properly configured",
            details={"total_definer_functions": len(definer_functions)},
        )

    except Exception as e:
        return GateResult(
            name="Security Definer Safety",
            status=GateStatus.FAILED,
            message=f"Security definer check failed: {type(e).__name__}: {e}",
            fatal=True,
        )


# ═══════════════════════════════════════════════════════════════════════════
# Gate 13: Forbidden Environment Variables (FATAL)
# ═══════════════════════════════════════════════════════════════════════════


def gate_forbidden_env_vars(env: str) -> GateResult:
    """
    Verify dangerous environment variables are NOT present in production.

    FATAL: Migration credentials in prod runtime = security catastrophe.
    SUPABASE_MIGRATE_DB_URL bypasses connection pooler and has elevated perms.
    """
    forbidden_in_prod = {
        "SUPABASE_MIGRATE_DB_URL": "Migration credentials bypass pooler and have elevated permissions",
    }

    if env != "prod":
        print(f"   ⏭️  Skipping forbidden env var check (env={env}, only enforced in prod)")
        return GateResult(
            name="Forbidden Environment Variables",
            status=GateStatus.SKIPPED,
            message=f"Skipped: Only enforced in production (current: {env})",
            fatal=False,
        )

    print("   Scanning for forbidden environment variables in PROD...")

    violations = []
    for var_name, risk_description in forbidden_in_prod.items():
        if os.environ.get(var_name):
            violations.append((var_name, risk_description))
            print(f"   🚨 FOUND: {var_name}")

    if violations:
        print()
        print("   ❌ SECURITY RISK: Dangerous credentials in production runtime!")
        for var_name, desc in violations:
            print(f"      - {var_name}: {desc}")

        return GateResult(
            name="Forbidden Environment Variables",
            status=GateStatus.FAILED,
            message=f"Security Risk: {len(violations)} forbidden env var(s) in production",
            details={
                "violations": [v[0] for v in violations],
                "risk": "Migration credentials in runtime bypass connection pooler and have elevated permissions",
            },
            fatal=True,  # HARD BLOCKER
        )

    print("   ✓ No forbidden environment variables detected")
    return GateResult(
        name="Forbidden Environment Variables",
        status=GateStatus.PASSED,
        message="Production runtime clean - no dangerous credentials exposed",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Main Orchestrator
# ═══════════════════════════════════════════════════════════════════════════


def run_go_live_gate(env: Literal["dev", "prod"], skip_discord: bool = False) -> GoLiveReport:
    """
    Execute the full go-live gate in strict order.

    Each gate is executed in sequence. Fatal failures stop execution.
    """
    report = GoLiveReport(env=env)

    gates = [
        (1, "Bootstrap & Security Guard", lambda: gate_bootstrap_security(env)),
        (2, "Secret Leak Scan", lambda: gate_secret_leak_scan(env)),
        (3, "Migration Integrity", lambda: gate_migration_integrity(env)),
        (4, "Tenancy Audit", lambda: gate_tenancy_audit(env)),
        (5, "Audit Immutability", lambda: gate_audit_immutability(env)),
        (6, "Permission Audit", lambda: gate_permission_audit(env)),
        (7, "Security Definer Safety", lambda: gate_security_definer_safety(env)),
        (8, "Forbidden Env Vars", lambda: gate_forbidden_env_vars(env)),
        (9, "PostgREST Health", lambda: gate_postgrest_health(env)),
        (10, "Golden Path", lambda: gate_golden_path(env)),
        (11, "Subsystem Smoke Tests", lambda: gate_smoke_tests(env)),
        (12, "Frontend Security", lambda: gate_frontend_security(env)),
        (13, "Worker Health", lambda: gate_worker_health(env)),
    ]

    for gate_num, gate_name, gate_func in gates:
        print_gate_header(gate_num, gate_name)

        result = run_with_timing(gate_func)
        report.gates.append(result)

        # Print result
        status_emoji = {
            GateStatus.PASSED: "✅",
            GateStatus.FAILED: "❌",
            GateStatus.SKIPPED: "⏭️",
            GateStatus.INFO: "ℹ️",
        }.get(result.status, "?")

        print()
        print(f"   {status_emoji} {result.message} ({format_duration(result.duration_ms)})")

        # Fatal failure stops execution
        if result.fatal and result.status == GateStatus.FAILED:
            print()
            print("   ⛔ FATAL: Stopping execution due to gate failure")
            break

    report.end_time = datetime.now(timezone.utc)

    # Send Discord notification (or console fallback)
    if not skip_discord:
        try:
            from backend.utils.discord import AlertColor, send_alert

            if report.passed:
                send_alert(
                    title="✅ GO-LIVE CERTIFIED",
                    description=f"All {len(report.gates)} gates passed for {env.upper()}",
                    color=AlertColor.SUCCESS,
                    fields={
                        "Environment": env.upper(),
                        "Duration": format_duration(report.duration_ms),
                        "Gates Passed": str(len([g for g in report.gates if g.passed])),
                    },
                )
            else:
                failed = report.failed_gate
                send_alert(
                    title="❌ GO-LIVE FAILED",
                    description=failed.message if failed else "Unknown failure",
                    color=AlertColor.FAILURE,
                    fields={
                        "Environment": env.upper(),
                        "Failed Gate": failed.name if failed else "Unknown",
                        "Duration": format_duration(report.duration_ms),
                    },
                )
        except Exception:
            pass  # Never block on alerting
    else:
        # Console fallback for local mode
        print()
        if report.passed:
            print(
                f"[Local Alert] ✅ GO-LIVE CERTIFIED - All {len(report.gates)} gates passed for {env.upper()}"
            )
        else:
            failed = report.failed_gate
            print(
                f"[Local Alert] ❌ GO-LIVE FAILED - {failed.message if failed else 'Unknown failure'}"
            )

    return report


def print_final_verdict(report: GoLiveReport) -> None:
    """Print the final go-live verdict."""
    if report.passed:
        print()
        print("═" * 70)
        print()
        print("   ██████╗  ██████╗       ██╗     ██╗██╗   ██╗███████╗")
        print("  ██╔════╝ ██╔═══██╗      ██║     ██║██║   ██║██╔════╝")
        print("  ██║  ███╗██║   ██║█████╗██║     ██║██║   ██║█████╗  ")
        print("  ██║   ██║██║   ██║╚════╝██║     ██║╚██╗ ██╔╝██╔══╝  ")
        print("  ╚██████╔╝╚██████╔╝      ███████╗██║ ╚████╔╝ ███████╗")
        print("   ╚═════╝  ╚═════╝       ╚══════╝╚═╝  ╚═══╝  ╚══════╝")
        print()
        print("  ✅ SYSTEM READY FOR PLAINTIFFS")
        print()
        print(f"     Environment: {report.env.upper()}")
        print(
            f"     Gates Passed: {len([g for g in report.gates if g.passed])}/{len(report.gates)}"
        )
        print(f"     Duration: {format_duration(report.duration_ms)}")
        print()
        print("═" * 70)
    else:
        failed = report.failed_gate
        print()
        print("═" * 70)
        print()
        print("  ███████╗ █████╗ ██╗██╗     ███████╗██████╗ ")
        print("  ██╔════╝██╔══██╗██║██║     ██╔════╝██╔══██╗")
        print("  █████╗  ███████║██║██║     █████╗  ██║  ██║")
        print("  ██╔══╝  ██╔══██║██║██║     ██╔══╝  ██║  ██║")
        print("  ██║     ██║  ██║██║███████╗███████╗██████╔╝")
        print("  ╚═╝     ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚═════╝ ")
        print()
        print("  ❌ GO-LIVE BLOCKED")
        print()
        if failed:
            print(f"     Failed Gate: {failed.name}")
            print(f"     Reason: {failed.message}")
        print()
        print("═" * 70)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Go-Live Gate: Certify production readiness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.go_live_gate --env prod
    python -m tools.go_live_gate --env dev --skip-discord

This script must pass before onboarding plaintiff data.
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        required=True,
        help="Target environment to certify",
    )
    parser.add_argument(
        "--skip-discord",
        action="store_true",
        help="Skip Discord notifications",
    )

    args = parser.parse_args()

    # Set environment mode
    os.environ["SUPABASE_MODE"] = args.env

    print_banner(f"DRAGONFLY GO-LIVE GATE ({args.env.upper()})")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")

    if args.skip_discord:
        print("🔕 Discord Alerts Suppressed (Local Mode)")

    # Run the gate
    report = run_go_live_gate(args.env, skip_discord=args.skip_discord)

    # Print verdict
    print_final_verdict(report)

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
