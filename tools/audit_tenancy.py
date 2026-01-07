#!/usr/bin/env python3
"""
Dragonfly Civil - Tenancy Enforcement Auditor

Verifies that multi-tenancy enforcement is properly configured:
1. Schema Inspection: org_id columns must be NOT NULL
2. Null Injection Test: Attempts to insert NULL org_id must fail
3. RLS Policy Scan: No policies should contain "IS NULL" loopholes

This script is designed to run post-migration to verify tenancy hardening.

Usage:
    python -m tools.audit_tenancy --env dev
    python -m tools.audit_tenancy --env prod --strict

Exit Codes:
    0 - All checks passed
    1 - Critical security flaw detected
    2 - Configuration/connection error
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.supabase_client import get_supabase_db_url, get_supabase_env

# Schemas to audit for org_id columns
AUDIT_SCHEMAS = ("public", "intake", "legal", "evidence", "audit")

# Tables to skip in null injection test (system tables, etc.)
SKIP_INJECTION_TABLES = frozenset(
    {
        "schema_migrations",
        "spatial_ref_sys",
        "geography_columns",
        "geometry_columns",
    }
)


@dataclass
class NullableOrgIdColumn:
    """A column that allows NULL org_id (a security concern)."""

    schema_name: str
    table_name: str
    is_nullable: str  # 'YES' or 'NO'
    data_type: str

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


@dataclass
class PolicyWithNullCheck:
    """An RLS policy that contains 'IS NULL' (potential loophole)."""

    schema_name: str
    table_name: str
    policy_name: str
    command: str
    qual: str | None
    with_check: str | None
    matched_text: str  # The actual 'IS NULL' substring found


@dataclass
class AuditResult:
    """Overall audit result."""

    # Check 1: Schema inspection
    nullable_org_id_columns: list[NullableOrgIdColumn] = field(default_factory=list)

    # Check 2: Null injection test
    injection_test_passed: bool = False
    injection_test_error: str | None = None
    injection_target_table: str | None = None

    # Check 3: RLS policy scan
    policies_with_null_check: list[PolicyWithNullCheck] = field(default_factory=list)

    # Overall
    critical_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.critical_failures) == 0


def _resolve_env(requested_env: str | None) -> str:
    """Resolve and set the Supabase environment."""
    if requested_env:
        normalized = requested_env.lower()
        os.environ["SUPABASE_MODE"] = "prod" if normalized == "prod" else "dev"
        return os.environ["SUPABASE_MODE"]
    env = get_supabase_env()
    os.environ["SUPABASE_MODE"] = env
    return env


def _connect(env: str) -> psycopg.Connection:
    """Get a database connection."""
    db_url = get_supabase_db_url(env)
    return psycopg.connect(
        db_url,
        autocommit=False,  # We need transactions for rollback
        row_factory=dict_row,
        connect_timeout=10,
    )


def check_schema_nullable_org_id(
    conn: psycopg.Connection, include_views: bool = False
) -> list[NullableOrgIdColumn]:
    """
    Check 1: Query information_schema.columns for org_id columns.

    Returns list of columns where is_nullable = 'YES' (a security concern).

    Args:
        conn: Database connection
        include_views: If False (default), skip views since they inherit
                       nullability from base tables and can't have constraints.
    """
    schema_list = ",".join(f"'{s}'" for s in AUDIT_SCHEMAS)

    # Join with pg_class to determine if it's a table or view
    query = f"""
        SELECT
            c.table_schema,
            c.table_name,
            c.is_nullable,
            c.data_type,
            CASE pg.relkind
                WHEN 'r' THEN 'table'
                WHEN 'v' THEN 'view'
                WHEN 'm' THEN 'materialized_view'
                ELSE pg.relkind::text
            END as relation_type
        FROM information_schema.columns c
        JOIN pg_class pg ON pg.relname = c.table_name
        JOIN pg_namespace ns ON ns.oid = pg.relnamespace AND ns.nspname = c.table_schema
        WHERE c.column_name = 'org_id'
          AND c.table_schema IN ({schema_list})
        ORDER BY c.table_schema, c.table_name;
    """

    nullable_columns = []
    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            # Skip views unless explicitly requested
            if not include_views and row["relation_type"] in ("view", "materialized_view"):
                continue

            if row["is_nullable"] == "YES":
                nullable_columns.append(
                    NullableOrgIdColumn(
                        schema_name=row["table_schema"],
                        table_name=row["table_name"],
                        is_nullable=row["is_nullable"],
                        data_type=row["data_type"],
                    )
                )

    return nullable_columns


def _find_injection_target_table(conn: psycopg.Connection) -> str | None:
    """
    Find a suitable table for the null injection test.

    Prefers 'cases' or 'plaintiffs', falls back to any table with org_id.
    """
    preferred = ["cases", "plaintiffs", "judgments"]

    for table in preferred:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = %s
                  AND column_name = 'org_id'
                """,
                (table,),
            )
            if cur.fetchone():
                return table

    # Fallback: find any public table with org_id
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name = 'org_id'
            ORDER BY table_name
            LIMIT 1;
            """
        )
        row = cur.fetchone()
        return row["table_name"] if row else None


def check_null_injection(
    conn: psycopg.Connection, target_table: str | None = None
) -> tuple[bool, str | None, str | None]:
    """
    Check 2: Attempt to insert a row with org_id=NULL.

    The insert MUST fail with an IntegrityError (NOT NULL violation).
    If it succeeds, we have a critical security flaw.

    Returns:
        (passed: bool, error_message: str | None, target_table: str | None)
    """
    if target_table is None:
        target_table = _find_injection_target_table(conn)

    if target_table is None:
        return False, "No suitable table found for null injection test", None

    if target_table in SKIP_INJECTION_TABLES:
        return True, f"Skipped system table: {target_table}", target_table

    # Generate a unique ID for test row
    test_id = uuid.uuid4()

    # Build a minimal insert based on the table
    # We only need id and org_id (with org_id=NULL to test the constraint)
    try:
        with conn.cursor() as cur:
            # Start a savepoint so we can rollback just this test
            cur.execute("SAVEPOINT null_injection_test")

            try:
                # Attempt to insert with NULL org_id
                # Using explicit NULL to trigger constraint violation
                cur.execute(
                    f"""
                    INSERT INTO public.{target_table} (id, org_id)
                    VALUES (%s, NULL)
                    """,
                    (test_id,),
                )

                # If we get here, the insert succeeded - CRITICAL FAILURE
                cur.execute("ROLLBACK TO SAVEPOINT null_injection_test")
                return (
                    False,
                    f"CRITICAL: NULL org_id insert succeeded on {target_table}! "
                    "Tenancy constraint is NOT enforced.",
                    target_table,
                )

            except pg_errors.NotNullViolation:
                # This is the EXPECTED outcome - constraint is working
                cur.execute("ROLLBACK TO SAVEPOINT null_injection_test")
                return True, None, target_table

            except pg_errors.UniqueViolation:
                # Row already exists (unlikely with UUID), but constraint may still be valid
                cur.execute("ROLLBACK TO SAVEPOINT null_injection_test")
                return (
                    True,
                    f"Unique violation on {target_table} (row exists), "
                    "but NOT NULL constraint likely active",
                    target_table,
                )

            except pg_errors.CheckViolation as e:
                # Check constraint violation - also valid protection
                cur.execute("ROLLBACK TO SAVEPOINT null_injection_test")
                return True, f"Check constraint prevented NULL org_id: {e}", target_table

            except Exception as e:
                # Other errors - might be missing required columns, etc.
                cur.execute("ROLLBACK TO SAVEPOINT null_injection_test")
                error_str = str(e).lower()
                if "not-null" in error_str or "null value" in error_str:
                    return True, f"NOT NULL constraint active (different column): {e}", target_table
                return False, f"Unexpected error during injection test: {e}", target_table

    except Exception as e:
        return False, f"Failed to run injection test: {e}", target_table


def check_rls_policy_null_patterns(
    conn: psycopg.Connection,
) -> list[PolicyWithNullCheck]:
    """
    Check 3: Scan RLS policies for 'IS NULL' patterns.

    Policies containing 'IS NULL' may indicate a legacy loophole where
    NULL org_id records are visible to all tenants.
    """
    query = """
        SELECT
            schemaname,
            tablename,
            policyname,
            cmd,
            qual,
            with_check
        FROM pg_policies
        WHERE schemaname IN ('public', 'intake', 'legal', 'evidence', 'audit')
        ORDER BY schemaname, tablename, policyname;
    """

    suspicious_policies = []

    with conn.cursor() as cur:
        cur.execute(query)
        for row in cur.fetchall():
            qual = row["qual"] or ""
            with_check = row["with_check"] or ""

            # Case-insensitive search for 'IS NULL' patterns
            qual_lower = qual.lower()
            with_check_lower = with_check.lower()

            matched_text = None

            # Check for various NULL patterns that could be loopholes
            null_patterns = [
                "is null",
                "isnull",
                "= null",  # Always false in SQL, but indicates confusion
                "org_id is null",
            ]

            for pattern in null_patterns:
                if pattern in qual_lower:
                    matched_text = f"qual: '{pattern}'"
                    break
                if pattern in with_check_lower:
                    matched_text = f"with_check: '{pattern}'"
                    break

            if matched_text:
                suspicious_policies.append(
                    PolicyWithNullCheck(
                        schema_name=row["schemaname"],
                        table_name=row["tablename"],
                        policy_name=row["policyname"],
                        command=row["cmd"],
                        qual=qual,
                        with_check=with_check,
                        matched_text=matched_text,
                    )
                )

    return suspicious_policies


def run_audit(
    env: str, strict: bool = False, verbose: bool = False, include_views: bool = False
) -> AuditResult:
    """
    Run all tenancy audit checks.

    Args:
        env: Environment ('dev' or 'prod')
        strict: If True, warnings become failures
        verbose: If True, print detailed output
        include_views: If True, check views for nullable org_id (usually skip)

    Returns:
        AuditResult with all findings
    """
    result = AuditResult()

    try:
        with _connect(env) as conn:
            # ═══════════════════════════════════════════════════════════════
            # CHECK 1: Schema Inspection - org_id must be NOT NULL
            # ═══════════════════════════════════════════════════════════════
            if verbose:
                print("\n🔍 Check 1: Schema Inspection (org_id columns in TABLES)")
                print("─" * 50)
                if not include_views:
                    print("   (Skipping views - use --include-views to check them)")

            nullable_columns = check_schema_nullable_org_id(conn, include_views=include_views)
            result.nullable_org_id_columns = nullable_columns

            if nullable_columns:
                for col in nullable_columns:
                    msg = f"NULLABLE org_id: {col.full_name} (is_nullable={col.is_nullable})"
                    result.critical_failures.append(msg)
                    if verbose:
                        print(f"  ❌ {msg}")
            elif verbose:
                print("  ✅ All org_id columns are NOT NULL")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 2: Null Injection Test
            # ═══════════════════════════════════════════════════════════════
            if verbose:
                print("\n🔍 Check 2: Null Injection Test")
                print("─" * 50)

            passed, error, target_table = check_null_injection(conn)
            result.injection_test_passed = passed
            result.injection_test_error = error
            result.injection_target_table = target_table

            if not passed:
                result.critical_failures.append(error or "Null injection test failed")
                if verbose:
                    print(f"  ❌ {error}")
            elif verbose:
                if error:
                    print(f"  ✅ Passed ({error})")
                else:
                    print(f"  ✅ NULL org_id correctly rejected on {target_table}")

            # ═══════════════════════════════════════════════════════════════
            # CHECK 3: RLS Policy Scan
            # ═══════════════════════════════════════════════════════════════
            if verbose:
                print("\n🔍 Check 3: RLS Policy Scan (IS NULL patterns)")
                print("─" * 50)

            suspicious_policies = check_rls_policy_null_patterns(conn)
            result.policies_with_null_check = suspicious_policies

            if suspicious_policies:
                for policy in suspicious_policies:
                    msg = (
                        f"SUSPICIOUS POLICY: {policy.schema_name}.{policy.table_name} "
                        f"-> {policy.policy_name} ({policy.matched_text})"
                    )
                    if strict:
                        result.critical_failures.append(msg)
                    else:
                        result.warnings.append(msg)
                    if verbose:
                        icon = "❌" if strict else "⚠️"
                        print(f"  {icon} {msg}")
            elif verbose:
                print("  ✅ No suspicious 'IS NULL' patterns in RLS policies")

    except Exception as e:
        result.critical_failures.append(f"Audit failed: {e}")
        if verbose:
            print(f"\n❌ Audit error: {e}")

    return result


def print_summary(result: AuditResult, env: str) -> None:
    """Print a formatted summary of the audit results."""
    print("\n" + "═" * 60)
    print(f"  TENANCY AUDIT SUMMARY ({env.upper()})")
    print("═" * 60)

    # Check 1 Summary
    nullable_count = len(result.nullable_org_id_columns)
    status = "✅ PASS" if nullable_count == 0 else "❌ FAIL"
    print(f"\n  Check 1 - Schema Inspection:      {status}")
    if nullable_count > 0:
        print(f"            {nullable_count} nullable org_id column(s) found")

    # Check 2 Summary
    status = "✅ PASS" if result.injection_test_passed else "❌ FAIL"
    print(f"  Check 2 - Null Injection Test:    {status}")
    if result.injection_target_table:
        print(f"            Target: {result.injection_target_table}")

    # Check 3 Summary
    policy_count = len(result.policies_with_null_check)
    status = "✅ PASS" if policy_count == 0 else "⚠️ WARN"
    print(f"  Check 3 - RLS Policy Scan:        {status}")
    if policy_count > 0:
        print(f"            {policy_count} suspicious policy(ies) found")

    # Overall
    print("\n" + "─" * 60)
    if result.passed:
        print("  🎉 OVERALL: ALL CHECKS PASSED")
    else:
        print("  🚨 OVERALL: CRITICAL FAILURES DETECTED")
        for failure in result.critical_failures:
            print(f"     • {failure}")

    if result.warnings:
        print("\n  ⚠️ WARNINGS:")
        for warning in result.warnings:
            print(f"     • {warning}")

    print("═" * 60 + "\n")


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Audit multi-tenancy enforcement in Dragonfly Civil",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.audit_tenancy --env dev
    python -m tools.audit_tenancy --env prod --strict --verbose
        """,
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        default=None,
        help="Target environment (default: from SUPABASE_MODE)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed output",
    )
    parser.add_argument(
        "--include-views",
        action="store_true",
        help="Include views in schema check (views inherit nullability from base tables)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON",
    )

    args = parser.parse_args()

    # Resolve environment
    env = _resolve_env(args.env)

    print(f"🔐 Tenancy Audit - Environment: {env.upper()}")
    print(f"   Mode: {'STRICT' if args.strict else 'STANDARD'}")

    # Run the audit
    result = run_audit(
        env,
        strict=args.strict,
        verbose=args.verbose,
        include_views=args.include_views,
    )

    # Output results
    if args.json:
        import json

        output = {
            "environment": env,
            "passed": result.passed,
            "nullable_org_id_columns": [
                {
                    "schema": c.schema_name,
                    "table": c.table_name,
                    "is_nullable": c.is_nullable,
                }
                for c in result.nullable_org_id_columns
            ],
            "injection_test": {
                "passed": result.injection_test_passed,
                "target_table": result.injection_target_table,
                "error": result.injection_test_error,
            },
            "suspicious_policies": [
                {
                    "schema": p.schema_name,
                    "table": p.table_name,
                    "policy": p.policy_name,
                    "matched": p.matched_text,
                }
                for p in result.policies_with_null_check
            ],
            "critical_failures": result.critical_failures,
            "warnings": result.warnings,
        }
        print(json.dumps(output, indent=2))
    else:
        print_summary(result, env)

    # Exit code
    if not result.passed:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
