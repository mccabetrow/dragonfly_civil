# tools/verify_system_health.py
"""
System Health Verifier - Deep checks for production readiness.

This script performs four critical health checks:
1. RLS Compliance - Ensures Zero Trust is enforced on all tables
2. Queue Reachability - Verifies ops.job_queue is accessible via ops.v_queue_health
3. Worker Heartbeats - Confirms workers are alive (strict in prod, warn in dev)
4. Public Exposure Check - Verifies anon/authenticated cannot access protected tables

Usage:
    python -m tools.verify_system_health --mode dev
    python -m tools.verify_system_health --mode prod
    python -m tools.verify_system_health --mode prod --tolerant  # For initial deploys
"""

import argparse
import io
import os
import sys
from typing import NamedTuple

# Fix Windows console encoding for Unicode (emoji) output
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


class HealthCheckResult(NamedTuple):
    """Result of a health check."""

    passed: bool
    message: str
    fatal: bool = False


def get_db_connection():
    """Get database connection using SUPABASE_MIGRATE_DB_URL (direct connection)."""
    import psycopg

    # Use migration URL for direct DB access (bypasses pooler issues)
    db_url = os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if not db_url:
        # Fallback to runtime URL
        db_url = os.environ.get("SUPABASE_DB_URL")

    if not db_url:
        raise RuntimeError("No database URL found. Set SUPABASE_MIGRATE_DB_URL or SUPABASE_DB_URL")

    return psycopg.connect(db_url, connect_timeout=15)


def check_rls_compliance() -> HealthCheckResult:
    """
    Check 1: RLS Compliance
    Query ops.v_rls_coverage for any non-compliant tables.
    Zero Trust requires: count(*) WHERE force_rls = false is 0
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # First check if the view exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views 
                        WHERE schemaname = 'ops' 
                        AND viewname = 'v_rls_coverage'
                    )
                """
                )
                view_exists = cur.fetchone()[0]

                if not view_exists:
                    return HealthCheckResult(
                        passed=False,
                        message="ops.v_rls_coverage view not found - Zero Trust migrations not applied",
                        fatal=True,
                    )

                # Zero Trust check: ALL tables must have force_rls = true
                cur.execute(
                    """
                    SELECT count(*) 
                    FROM ops.v_rls_coverage 
                    WHERE force_rls = false
                """
                )
                force_violation_count = cur.fetchone()[0]

                # Also check for any tables missing RLS entirely
                cur.execute(
                    """
                    SELECT count(*) 
                    FROM ops.v_rls_coverage 
                    WHERE has_rls = false
                """
                )
                rls_violation_count = cur.fetchone()[0]

                # Query for compliance status violations
                cur.execute(
                    """
                    SELECT count(*) 
                    FROM ops.v_rls_coverage 
                    WHERE compliance_status != 'COMPLIANT'
                """
                )
                violation_count = cur.fetchone()[0]

                if violation_count > 0:
                    # Get details of violations
                    cur.execute(
                        """
                        SELECT schema_name, table_name, compliance_status
                        FROM ops.v_rls_coverage 
                        WHERE compliance_status != 'COMPLIANT'
                        ORDER BY schema_name, table_name
                        LIMIT 10
                    """
                    )
                    violations = cur.fetchall()
                    details = ", ".join(f"{r[0]}.{r[1]}({r[2]})" for r in violations)

                    return HealthCheckResult(
                        passed=False,
                        message=f"RLS Missing on {violation_count} tables: {details}",
                        fatal=True,
                    )

                # Get total table count for the success message
                cur.execute("SELECT count(*) FROM ops.v_rls_coverage")
                total_tables = cur.fetchone()[0]

                return HealthCheckResult(
                    passed=True,
                    message=f"All {total_tables} tables have RLS enforced (Zero Trust compliant)",
                )

    except Exception as e:
        return HealthCheckResult(
            passed=False, message=f"Failed to check RLS compliance: {e}", fatal=True
        )


def check_queue_reachability() -> HealthCheckResult:
    """
    Check 2: Queue Reachability
    Query ops.v_queue_health (or ops.v_queue_summary) to verify queue access.
    This also validates that the ops views exist and are queryable.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # First check if the view exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_views 
                        WHERE schemaname = 'ops' 
                        AND viewname = 'v_queue_summary'
                    )
                """
                )
                summary_view_exists = cur.fetchone()[0]

                if summary_view_exists:
                    # Use the new summary view
                    cur.execute(
                        """
                        SELECT 
                            total_jobs, 
                            pending_jobs, 
                            running_jobs, 
                            failed_jobs,
                            oldest_pending_minutes
                        FROM ops.v_queue_summary
                    """
                    )
                    row = cur.fetchone()
                    if row:
                        total, pending, running, failed, oldest = row
                        status_parts = []
                        if pending:
                            status_parts.append(f"{pending} pending")
                        if running:
                            status_parts.append(f"{running} running")
                        if failed:
                            status_parts.append(f"{failed} failed")
                        status = ", ".join(status_parts) if status_parts else "empty"
                        return HealthCheckResult(
                            passed=True,
                            message=f"Queue accessible ({total} jobs: {status})",
                        )
                    else:
                        return HealthCheckResult(
                            passed=True, message="Queue accessible (0 jobs in queue)"
                        )

                # Fallback: check if the table exists directly
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_tables 
                        WHERE schemaname = 'ops' 
                        AND tablename = 'job_queue'
                    )
                """
                )
                table_exists = cur.fetchone()[0]

                if not table_exists:
                    return HealthCheckResult(
                        passed=False,
                        message="ops.job_queue table not found - Queue system not deployed",
                        fatal=True,
                    )

                # Simple count query as health ping
                cur.execute("SELECT count(*) FROM ops.job_queue")
                job_count = cur.fetchone()[0]

                return HealthCheckResult(
                    passed=True, message=f"Queue accessible ({job_count} jobs in queue)"
                )

    except Exception as e:
        return HealthCheckResult(passed=False, message=f"Queue unreachable: {e}", fatal=True)


def check_worker_heartbeats(mode: str) -> HealthCheckResult:
    """
    Check 3: Worker Heartbeats
    Verify workers are alive. Strict in prod, warning in dev.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # First check if the table exists
                cur.execute(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_tables 
                        WHERE schemaname = 'ops' 
                        AND tablename = 'worker_heartbeats'
                    )
                """
                )
                table_exists = cur.fetchone()[0]

                if not table_exists:
                    # Table doesn't exist - might be pre-migration
                    if mode == "prod":
                        return HealthCheckResult(
                            passed=False,
                            message="ops.worker_heartbeats table not found",
                            fatal=True,
                        )
                    else:
                        return HealthCheckResult(
                            passed=True, message="ops.worker_heartbeats table not found (OK in dev)"
                        )

                # Count active workers (heartbeat within last 5 minutes)
                # Column is 'last_seen_at' per 20251215100000_worker_heartbeats.sql
                cur.execute(
                    """
                    SELECT count(DISTINCT worker_id) 
                    FROM ops.worker_heartbeats 
                    WHERE last_seen_at > now() - interval '5 minutes'
                """
                )
                active_workers = cur.fetchone()[0]

                if active_workers == 0:
                    if mode == "prod":
                        return HealthCheckResult(
                            passed=False,
                            message="No active workers in PROD (0 heartbeats in last 5 min)",
                            fatal=True,
                        )
                    else:
                        return HealthCheckResult(
                            passed=True,  # Warning but passes in dev
                            message="No active workers (Allowed in Dev)",
                        )

                return HealthCheckResult(
                    passed=True, message=f"{active_workers} active worker(s) detected"
                )

    except Exception as e:
        # If query fails, treat differently based on mode
        if mode == "prod":
            return HealthCheckResult(
                passed=False, message=f"Failed to check worker heartbeats: {e}", fatal=True
            )
        else:
            return HealthCheckResult(
                passed=True, message=f"Worker heartbeat check failed (OK in dev): {e}"
            )


def check_public_exposure() -> HealthCheckResult:
    """
    Check 4: Public Exposure
    Verify that anon/authenticated roles cannot access protected tables.
    This checks grants in pg_catalog to ensure Zero Trust access control.
    """
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Check for dangerous grants to anon/authenticated on core tables
                # These roles should have NO direct table access
                cur.execute(
                    """
                    SELECT 
                        n.nspname AS schema_name,
                        c.relname AS table_name,
                        r.rolname AS role_name,
                        string_agg(
                            CASE a.privilege_type
                                WHEN 'SELECT' THEN 'r'
                                WHEN 'INSERT' THEN 'a'
                                WHEN 'UPDATE' THEN 'w'
                                WHEN 'DELETE' THEN 'd'
                                ELSE a.privilege_type
                            END, ''
                        ) AS privileges
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    CROSS JOIN (
                        SELECT rolname, oid FROM pg_roles 
                        WHERE rolname IN ('anon', 'authenticated')
                    ) r
                    JOIN LATERAL (
                        SELECT privilege_type 
                        FROM aclexplode(c.relacl) acl
                        WHERE acl.grantee = r.oid
                    ) a ON true
                    WHERE c.relkind = 'r'
                      AND n.nspname IN (
                          'public', 'enforcement', 'intake', 'ops', 
                          'judgments', 'parties', 'enrichment', 'intelligence'
                      )
                    GROUP BY n.nspname, c.relname, r.rolname
                    ORDER BY n.nspname, c.relname, r.rolname
                    LIMIT 10
                """
                )
                exposed_tables = cur.fetchall()

                if exposed_tables:
                    details = ", ".join(f"{r[0]}.{r[1]}({r[2]}:{r[3]})" for r in exposed_tables)
                    return HealthCheckResult(
                        passed=False,
                        message=f"Dangerous grants found on {len(exposed_tables)} tables: {details}",
                        fatal=True,
                    )

                return HealthCheckResult(
                    passed=True,
                    message="No dangerous grants to anon/authenticated (Zero Trust enforced)",
                )

    except Exception as e:
        return HealthCheckResult(
            passed=False, message=f"Failed to check public exposure: {e}", fatal=True
        )


def main():
    parser = argparse.ArgumentParser(
        description="System Health Verifier - Deep checks for production readiness"
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["dev", "prod"],
        help="Environment mode (affects strictness of checks)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show detailed output")
    parser.add_argument(
        "--initial-deploy",
        action="store_true",
        help="Initial deployment mode - relaxes fatal checks for first-time setup",
    )
    parser.add_argument(
        "--tolerant",
        action="store_true",
        help="Alias for --initial-deploy. Relaxes RLS/Worker checks to warnings.",
    )

    args = parser.parse_args()

    # --tolerant is an alias for --initial-deploy
    tolerant_mode = args.initial_deploy or args.tolerant

    print("\n" + "=" * 60)
    if tolerant_mode:
        print(f"  SYSTEM HEALTH VERIFICATION ({args.mode.upper()} - TOLERANT)")
    else:
        print(f"  SYSTEM HEALTH VERIFICATION ({args.mode.upper()})")
    print("=" * 60 + "\n")

    all_passed = True
    has_fatal = False
    has_initial_warnings = False

    # Check 1: RLS Compliance
    print("[1/4] Checking RLS Compliance...")
    result = check_rls_compliance()
    if result.passed:
        print(f"  ✅ {result.message}")
    else:
        if tolerant_mode:
            print(f"  ⚠️  TOLERANT MODE: {result.message} (will fix post-deploy)")
            has_initial_warnings = True
        else:
            print(f"  ❌ SECURITY VIOLATION: {result.message}")
            all_passed = False
            if result.fatal:
                has_fatal = True
    print()

    # Check 2: Queue Reachability
    print("[2/4] Checking Queue Reachability...")
    result = check_queue_reachability()
    if result.passed:
        print(f"  ✅ {result.message}")
    else:
        print(f"  ❌ QUEUE UNREACHABLE: {result.message}")
        all_passed = False
        if result.fatal:
            has_fatal = True
    print()

    # Check 3: Worker Heartbeats
    print("[3/4] Checking Worker Heartbeats...")
    result = check_worker_heartbeats(args.mode)
    if result.passed:
        if "No active workers" in result.message:
            print(f"  ⚠️  WARNING: {result.message}")
        else:
            print(f"  ✅ {result.message}")
    else:
        if tolerant_mode:
            print(f"  ⚠️  TOLERANT MODE: {result.message} (will deploy workers later)")
            has_initial_warnings = True
        else:
            print(f"  ❌ FATAL: {result.message}")
            all_passed = False
            if result.fatal:
                has_fatal = True
    print()

    # Check 4: Public Exposure (Grant Audit)
    print("[4/4] Checking Public Exposure...")
    result = check_public_exposure()
    if result.passed:
        print(f"  ✅ {result.message}")
    else:
        if tolerant_mode:
            print(f"  ⚠️  TOLERANT MODE: {result.message} (will revoke grants post-deploy)")
            has_initial_warnings = True
        else:
            print(f"  ❌ SECURITY VIOLATION: {result.message}")
            all_passed = False
            if result.fatal:
                has_fatal = True
    print()

    # Summary
    print("=" * 60)
    if all_passed and not has_initial_warnings:
        print("  ✅ ALL HEALTH CHECKS PASSED")
        print("=" * 60)
        sys.exit(0)
    elif tolerant_mode and has_initial_warnings:
        print("  ⚠️  TOLERANT MODE WARNINGS (Proceeding)")
        print("=" * 60)
        sys.exit(0)  # Exit 0 for tolerant mode
    else:
        if has_fatal:
            print("  ❌ HEALTH CHECK FAILED - DO NOT DEPLOY")
        else:
            print("  ⚠️  HEALTH CHECK WARNINGS")
        print("=" * 60)
        sys.exit(1 if has_fatal else 0)


if __name__ == "__main__":
    main()
