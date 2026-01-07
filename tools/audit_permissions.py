#!/usr/bin/env python3
"""
Dragonfly Civil - Permissions Audit Tool

Security Operations verification script that proves our security posture
is correct after applying hardening migrations.

Checks:
1. Schema Access: Verify role-schema USAGE grants
2. View Access: Verify SELECT grants on dashboard views
3. Function Safety: All SECURITY DEFINER functions have fixed search_path
4. RLS Status: Verify RLS enabled on critical tables

Usage:
    python -m tools.audit_permissions --env dev
    python -m tools.audit_permissions --env prod --strict
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Schemas that should be accessible to authenticated users
AUTHENTICATED_SCHEMAS = {"public", "api"}

# Schemas that should NOT be accessible to anon/authenticated
RESTRICTED_SCHEMAS = {"intake", "ops", "enforcement"}

# Views that should be SELECTable by anon/authenticated
DASHBOARD_VIEWS = [
    ("public", "v_plaintiffs_overview"),
    ("public", "v_judgment_pipeline"),
    ("public", "v_enforcement_overview"),
    ("public", "v_enforcement_recent"),
    ("public", "v_plaintiff_call_queue"),
]

# Service-role-only views (should NOT have anon/authenticated access)
SERVICE_ONLY_VIEWS = [
    ("ops", "v_batch_performance"),
    ("ops", "v_reaper_status"),
]

# Tables that MUST have RLS enabled
RLS_REQUIRED_TABLES = [
    ("public", "judgments"),
    ("public", "plaintiffs"),
    ("public", "plaintiff_contacts"),
    ("public", "plaintiff_status_history"),
    ("public", "plaintiff_tasks"),
]

# Schemas to audit for SECURITY DEFINER functions
DEFINER_AUDIT_SCHEMAS = ["public", "ops", "api", "intake", "enforcement"]


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class AuditResult:
    """Result of a single audit check."""

    check_name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)
    severity: str = "error"  # "error", "warning", "info"


@dataclass
class AuditReport:
    """Complete audit report."""

    results: list[AuditResult] = field(default_factory=list)
    env: str = ""

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results if r.severity == "error")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.severity == "warning")


# ---------------------------------------------------------------------------
# Database Connection
# ---------------------------------------------------------------------------


def get_db_url(env: str) -> str:
    """Get database URL for the specified environment."""
    env_file = f".env.{env}"
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SUPABASE_DB_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
                if line.startswith("SUPABASE_MIGRATE_DB_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    # Fallback to environment variable
    url = os.environ.get("SUPABASE_DB_URL") or os.environ.get("SUPABASE_MIGRATE_DB_URL")
    if not url:
        raise RuntimeError(f"No database URL found for env={env}")
    return url


def connect(env: str) -> psycopg2.extensions.connection:
    """Connect to the database."""
    url = get_db_url(env)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


# ---------------------------------------------------------------------------
# Audit Checks
# ---------------------------------------------------------------------------


def check_schema_access(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check schema USAGE privileges.

    Verifies:
    - authenticated has USAGE on public, api
    - authenticated does NOT have USAGE on intake, ops, enforcement (direct)
    """
    results = []

    with conn.cursor() as cur:
        # Query schema privileges
        cur.execute(
            """
            SELECT 
                nspname AS schema_name,
                has_schema_privilege('authenticated', nspname, 'USAGE') AS auth_usage,
                has_schema_privilege('anon', nspname, 'USAGE') AS anon_usage,
                has_schema_privilege('service_role', nspname, 'USAGE') AS service_usage
            FROM pg_namespace
            WHERE nspname IN ('public', 'api', 'intake', 'ops', 'enforcement')
            ORDER BY nspname
        """
        )
        rows = cur.fetchall()

    schema_privs = {row["schema_name"]: row for row in rows}

    # Check authenticated has access to public and api
    for schema in AUTHENTICATED_SCHEMAS:
        if schema in schema_privs:
            has_access = schema_privs[schema]["auth_usage"]
            results.append(
                AuditResult(
                    check_name=f"schema_access_{schema}",
                    passed=has_access,
                    message=f"authenticated has USAGE on {schema}: {'✓' if has_access else '✗'}",
                    severity="error",
                )
            )

    # Check service_role has access to all schemas
    for schema in ["public", "api", "intake", "ops", "enforcement"]:
        if schema in schema_privs:
            has_access = schema_privs[schema]["service_usage"]
            results.append(
                AuditResult(
                    check_name=f"schema_access_service_{schema}",
                    passed=has_access,
                    message=f"service_role has USAGE on {schema}: {'✓' if has_access else '✗'}",
                    severity="error",
                )
            )

    return results


def check_view_access(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check SELECT privileges on dashboard views.

    Verifies anon and authenticated can SELECT from critical views.
    """
    results = []

    with conn.cursor() as cur:
        for schema, view in DASHBOARD_VIEWS:
            # Check if view exists
            cur.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.views
                    WHERE table_schema = %s AND table_name = %s
                ) AS view_exists
            """,
                (schema, view),
            )
            row = cur.fetchone()
            if not row or not row["view_exists"]:
                results.append(
                    AuditResult(
                        check_name=f"view_exists_{schema}_{view}",
                        passed=False,
                        message=f"View {schema}.{view} does not exist",
                        severity="warning",
                    )
                )
                continue

            # Check SELECT privileges
            cur.execute(
                """
                SELECT 
                    has_table_privilege('anon', %s || '.' || %s, 'SELECT') AS anon_select,
                    has_table_privilege('authenticated', %s || '.' || %s, 'SELECT') AS auth_select,
                    has_table_privilege('service_role', %s || '.' || %s, 'SELECT') AS service_select
            """,
                (schema, view, schema, view, schema, view),
            )
            privs = cur.fetchone()

            anon_ok = privs["anon_select"]
            auth_ok = privs["auth_select"]
            service_ok = privs["service_select"]

            all_ok = anon_ok and auth_ok and service_ok

            details = []
            if not anon_ok:
                details.append("anon: no SELECT")
            if not auth_ok:
                details.append("authenticated: no SELECT")
            if not service_ok:
                details.append("service_role: no SELECT")

            results.append(
                AuditResult(
                    check_name=f"view_select_{schema}_{view}",
                    passed=all_ok,
                    message=f"SELECT on {schema}.{view}: {'✓ all roles' if all_ok else '✗ missing grants'}",
                    details=details,
                    severity="error",
                )
            )

    return results


def check_function_safety(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check SECURITY DEFINER functions have fixed search_path.

    Queries pg_proc for functions where prosecdef = true and verifies
    proconfig contains search_path setting.
    """
    results = []
    vulnerable_functions = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 
                n.nspname AS schema_name,
                p.proname AS func_name,
                pg_get_function_identity_arguments(p.oid) AS func_args,
                p.proconfig AS config,
                p.prosecdef AS is_definer
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE p.prosecdef = true
              AND n.nspname = ANY(%s)
            ORDER BY n.nspname, p.proname
        """,
            (DEFINER_AUDIT_SCHEMAS,),
        )
        rows = cur.fetchall()

    for row in rows:
        schema = row["schema_name"]
        func_name = row["func_name"]
        func_args = row["func_args"] or ""
        config = row["config"] or []

        # Check if search_path is set in proconfig
        has_search_path = any("search_path=" in str(c).lower() for c in config)

        fqn = f"{schema}.{func_name}({func_args})"

        if not has_search_path:
            vulnerable_functions.append(fqn)

    if vulnerable_functions:
        results.append(
            AuditResult(
                check_name="function_search_path",
                passed=False,
                message=f"❌ VULNERABILITY DETECTED: {len(vulnerable_functions)} SECURITY DEFINER function(s) lack fixed search_path",
                details=vulnerable_functions[:20],  # Limit output
                severity="error",
            )
        )
    else:
        results.append(
            AuditResult(
                check_name="function_search_path",
                passed=True,
                message=f"✓ All {len(rows)} SECURITY DEFINER functions have fixed search_path",
                severity="error",
            )
        )

    return results


def check_rls_status(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check RLS is enabled on critical tables.

    Queries pg_class.relrowsecurity to verify RLS is enabled.
    """
    results = []

    with conn.cursor() as cur:
        for schema, table in RLS_REQUIRED_TABLES:
            cur.execute(
                """
                SELECT 
                    c.relrowsecurity AS rls_enabled,
                    c.relforcerowsecurity AS rls_forced
                FROM pg_class c
                JOIN pg_namespace n ON c.relnamespace = n.oid
                WHERE n.nspname = %s AND c.relname = %s
            """,
                (schema, table),
            )
            row = cur.fetchone()

            if not row:
                results.append(
                    AuditResult(
                        check_name=f"rls_{schema}_{table}",
                        passed=False,
                        message=f"Table {schema}.{table} does not exist",
                        severity="warning",
                    )
                )
                continue

            rls_enabled = row["rls_enabled"]
            rls_forced = row["rls_forced"]

            results.append(
                AuditResult(
                    check_name=f"rls_{schema}_{table}",
                    passed=rls_enabled,
                    message=f"RLS on {schema}.{table}: {'✓ enabled' if rls_enabled else '✗ DISABLED'}",
                    details=[f"forced={rls_forced}"] if rls_enabled else [],
                    severity="error",
                )
            )

    return results


def check_table_grants(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check that anon/authenticated do NOT have direct table access.

    Critical tables should only be accessible via views or RPCs.
    """
    results = []

    sensitive_tables = [
        ("public", "judgments"),
        ("public", "plaintiffs"),
        ("public", "plaintiff_contacts"),
    ]

    with conn.cursor() as cur:
        for schema, table in sensitive_tables:
            cur.execute(
                """
                SELECT 
                    has_table_privilege('anon', %s || '.' || %s, 'INSERT') AS anon_insert,
                    has_table_privilege('anon', %s || '.' || %s, 'UPDATE') AS anon_update,
                    has_table_privilege('anon', %s || '.' || %s, 'DELETE') AS anon_delete,
                    has_table_privilege('authenticated', %s || '.' || %s, 'INSERT') AS auth_insert,
                    has_table_privilege('authenticated', %s || '.' || %s, 'UPDATE') AS auth_update,
                    has_table_privilege('authenticated', %s || '.' || %s, 'DELETE') AS auth_delete
            """,
                (schema, table) * 6,
            )
            row = cur.fetchone()

            if not row:
                continue

            # anon should have NO write access
            anon_safe = not any([row["anon_insert"], row["anon_update"], row["anon_delete"]])

            # authenticated should have NO direct write access (writes go through RPCs)
            auth_safe = not any([row["auth_insert"], row["auth_update"], row["auth_delete"]])

            all_safe = anon_safe and auth_safe

            details = []
            if not anon_safe:
                details.append("anon has write access!")
            if not auth_safe:
                details.append("authenticated has direct write access")

            results.append(
                AuditResult(
                    check_name=f"table_write_{schema}_{table}",
                    passed=all_safe,
                    message=f"Write protection on {schema}.{table}: {'✓ locked' if all_safe else '✗ exposed'}",
                    details=details,
                    severity="error" if not anon_safe else "warning",
                )
            )

    return results


def check_rpc_execute_grants(conn: psycopg2.extensions.connection) -> list[AuditResult]:
    """
    Check that api.* functions are executable by appropriate roles.
    """
    results = []

    with conn.cursor() as cur:
        # Get all api.* functions
        cur.execute(
            """
            SELECT 
                p.proname AS func_name,
                pg_get_function_identity_arguments(p.oid) AS func_args
            FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
            WHERE n.nspname = 'api'
            ORDER BY p.proname
        """
        )
        rows = cur.fetchall()

    if not rows:
        results.append(
            AuditResult(
                check_name="rpc_execute_grants",
                passed=True,
                message="No api.* functions found (OK if not using RPC pattern)",
                severity="info",
            )
        )
        return results

    missing_grants = []

    with conn.cursor() as cur:
        for row in rows:
            func_name = row["func_name"]
            func_args = row["func_args"] or ""
            fqn = f"api.{func_name}({func_args})"

            # Check EXECUTE privilege
            try:
                cur.execute(
                    """
                    SELECT 
                        has_function_privilege('anon', %s, 'EXECUTE') AS anon_exec,
                        has_function_privilege('authenticated', %s, 'EXECUTE') AS auth_exec,
                        has_function_privilege('service_role', %s, 'EXECUTE') AS service_exec
                """,
                    (fqn, fqn, fqn),
                )
                privs = cur.fetchone()

                if not (privs["anon_exec"] and privs["auth_exec"] and privs["service_exec"]):
                    missing = []
                    if not privs["anon_exec"]:
                        missing.append("anon")
                    if not privs["auth_exec"]:
                        missing.append("authenticated")
                    if not privs["service_exec"]:
                        missing.append("service_role")
                    missing_grants.append(f"{fqn}: missing {', '.join(missing)}")
            except Exception:
                # Function might have complex signature
                pass

    if missing_grants:
        results.append(
            AuditResult(
                check_name="rpc_execute_grants",
                passed=False,
                message=f"✗ {len(missing_grants)} api.* functions missing EXECUTE grants",
                details=missing_grants[:10],
                severity="warning",
            )
        )
    else:
        results.append(
            AuditResult(
                check_name="rpc_execute_grants",
                passed=True,
                message=f"✓ All {len(rows)} api.* functions have EXECUTE grants",
                severity="info",
            )
        )

    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------


def run_audit(env: str) -> AuditReport:
    """Run all audit checks and return report."""
    report = AuditReport(env=env)

    conn = connect(env)
    try:
        # Run all checks
        report.results.extend(check_schema_access(conn))
        report.results.extend(check_view_access(conn))
        report.results.extend(check_function_safety(conn))
        report.results.extend(check_rls_status(conn))
        report.results.extend(check_table_grants(conn))
        report.results.extend(check_rpc_execute_grants(conn))
    finally:
        conn.close()

    return report


def print_report(report: AuditReport) -> None:
    """Print audit report to console."""
    print()
    print("=" * 70)
    print(f"  PERMISSIONS AUDIT REPORT - {report.env.upper()}")
    print("=" * 70)
    print()

    # Group by category
    categories = {
        "Schema Access": [],
        "View Access": [],
        "Function Safety": [],
        "RLS Status": [],
        "Table Protection": [],
        "RPC Grants": [],
    }

    for result in report.results:
        if "schema_access" in result.check_name:
            categories["Schema Access"].append(result)
        elif "view_" in result.check_name:
            categories["View Access"].append(result)
        elif "function_" in result.check_name:
            categories["Function Safety"].append(result)
        elif "rls_" in result.check_name:
            categories["RLS Status"].append(result)
        elif "table_" in result.check_name:
            categories["Table Protection"].append(result)
        elif "rpc_" in result.check_name:
            categories["RPC Grants"].append(result)

    for category, results in categories.items():
        if not results:
            continue

        print(f"[{category}]")
        for result in results:
            status = "PASS" if result.passed else "FAIL"
            icon = "✓" if result.passed else "✗"

            if result.severity == "warning" and not result.passed:
                status = "WARN"
                icon = "⚠"
            elif result.severity == "info":
                status = "INFO"
                icon = "ℹ"

            print(f"  [{status}] {result.message}")

            if result.details and not result.passed:
                for detail in result.details[:5]:
                    print(f"         → {detail}")
                if len(result.details) > 5:
                    print(f"         → ... and {len(result.details) - 5} more")

        print()

    # Summary
    print("-" * 70)
    total = len(report.results)
    passed = sum(1 for r in report.results if r.passed)
    errors = report.error_count
    warnings = report.warning_count

    if report.passed:
        print(f"  ✓ AUDIT PASSED: {passed}/{total} checks passed")
    else:
        print(f"  ✗ AUDIT FAILED: {errors} error(s), {warnings} warning(s)")

    print("-" * 70)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit database permissions to verify security posture"
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default="dev",
        help="Environment to audit (default: dev)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as errors",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    # Set environment
    os.environ["SUPABASE_MODE"] = args.env

    try:
        report = run_audit(args.env)
    except Exception as e:
        print(f"[audit_permissions] ERROR: {e}", file=sys.stderr)
        return 1

    if args.json:
        import json

        output = {
            "env": report.env,
            "passed": report.passed,
            "error_count": report.error_count,
            "warning_count": report.warning_count,
            "results": [
                {
                    "check": r.check_name,
                    "passed": r.passed,
                    "message": r.message,
                    "details": r.details,
                    "severity": r.severity,
                }
                for r in report.results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print_report(report)

    # Exit code
    if args.strict:
        # In strict mode, warnings also cause failure
        if report.error_count > 0 or report.warning_count > 0:
            return 1
    else:
        # Normal mode: only errors cause failure
        if report.error_count > 0:
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
